#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-harness transcript corpus.

The harnesses remain the owners of their live session stores. This tool imports
their JSONL transcripts into a local, harness-neutral corpus:

    raw/          immutable, content-addressed source copies
    sessions.db   normalized events + searchable metadata/indexes

Import is idempotent. The source hash and event lineage are retained so every
normalized record can be traced back to a harness file and line number.

Examples:
    python3 core/scripts/transcript_corpus.py inventory
    python3 core/scripts/transcript_corpus.py import
    python3 core/scripts/transcript_corpus.py search "payment" --project Work
    python3 core/scripts/transcript_corpus.py show <session-key>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


DEFAULT_ROOT = Path(os.environ.get("STC_TRANSCRIPTS_ROOT", "~/Work/transcripts")).expanduser()

# Keep envelopes in raw/normalized storage for auditability, but exclude
# obvious harness-injected noise from the default human history search.
NON_SEARCHABLE_PREFIXES = (
    "<app-context>",
    "<recommended_plugins>",
    "<system-reminder>",
    "<command-name>",
    "<local-command",
    "<bash-input>",
    "<bash-stdout>",
    "tool_result",
)


@dataclass(frozen=True)
class Source:
    harness: str
    path: Path


def discover_sources(home: Path | None = None) -> list[Source]:
    """Discover raw transcript files without reading or modifying them."""
    home = (home or Path.home()).expanduser()
    patterns = (
        ("claude", home / ".claude" / "projects", "**/*.jsonl"),
        ("codex", home / ".codex" / "archived_sessions", "*.jsonl"),
        ("codex", home / ".codex" / "sessions", "**/*.jsonl"),
        ("zcode", home / ".zcode" / "cli" / "agents", "**/transcript.jsonl"),
    )
    found: dict[tuple[str, str], Source] = {}
    for harness, root, pattern in patterns:
        if not root.exists():
            continue
        for path in root.glob(pattern):
            if path.is_file():
                key = (harness, str(path.resolve()))
                found[key] = Source(harness, path.resolve())
    return sorted(found.values(), key=lambda s: (s.harness, str(s.path)))


def file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "value"):
                    if isinstance(item.get(key), str):
                        parts.append(item[key])
                        break
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("content") or value.get("message"))
    return ""


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Codex turn timestamps are sometimes epoch milliseconds.
        if value > 10_000_000_000:
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return str(value)


def _event(
    *, harness: str, session_id: str, event_id: str, line: int,
    timestamp: Any, cwd: str | None, role: str, text: str,
) -> dict[str, Any] | None:
    text = text.strip()
    if not text or role not in {"user", "assistant", "system", "tool"}:
        return None
    return {
        "harness": harness,
        "session_id": session_id,
        "event_id": event_id,
        "line": line,
        "timestamp": _timestamp(timestamp),
        "cwd": cwd or None,
        "role": role,
        "text": text,
    }


def parse_claude(obj: dict[str, Any], line: int) -> dict[str, Any] | None:
    if obj.get("type") not in {"user", "assistant"}:
        return None
    message = obj.get("message") or {}
    if not isinstance(message, dict):
        return None
    role = message.get("role") or obj.get("type")
    return _event(
        harness="claude",
        session_id=str(obj.get("sessionId") or "unknown"),
        event_id=str(obj.get("uuid") or f"line-{line}"),
        line=line,
        timestamp=obj.get("timestamp"),
        cwd=obj.get("cwd"),
        role=str(role),
        text=_text(message.get("content")),
    )


def parse_codex(obj: dict[str, Any], state: dict[str, Any], line: int) -> dict[str, Any] | None:
    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    if obj.get("type") == "session_meta":
        state.update({
            "session_id": payload.get("session_id") or state.get("session_id"),
            "cwd": payload.get("cwd") or state.get("cwd"),
        })
        return None
    ptype = payload.get("type")
    if ptype not in {"message", "agent_message", "user_message"}:
        return None
    role = payload.get("role")
    if role not in {"user", "assistant", "system", "tool"}:
        role = "user" if ptype == "user_message" else "assistant"
    event_id = payload.get("id") or obj.get("id") or f"line-{line}"
    return _event(
        harness="codex",
        session_id=str(state.get("session_id") or "unknown"),
        event_id=str(event_id),
        line=line,
        timestamp=obj.get("timestamp"),
        cwd=payload.get("cwd") or state.get("cwd"),
        role=role,
        text=_text(payload.get("content") or payload.get("message") or payload.get("text")),
    )


def parse_zcode(obj: dict[str, Any], line: int) -> dict[str, Any] | None:
    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    obj_type = obj.get("type")
    if obj_type == "turn_started":
        role, value = "user", payload.get("input")
    elif obj_type == "model_complete":
        role, value = "assistant", payload.get("content")
    else:
        return None
    return _event(
        harness="zcode",
        session_id=str(obj.get("sessionId") or "unknown"),
        event_id=str(obj.get("id") or f"line-{line}"),
        line=line,
        timestamp=obj.get("timestamp"),
        cwd=payload.get("cwd"),
        role=role,
        text=_text(value),
    )


def iter_events(source: Source) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {}
    with source.path.open(encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if source.harness == "claude":
                event = parse_claude(obj, line_no)
            elif source.harness == "codex":
                event = parse_codex(obj, state, line_no)
            else:
                event = parse_zcode(obj, line_no)
            if event:
                yield event


def source_id(source: Source) -> str:
    return hashlib.sha256(f"{source.harness}\0{source.path}".encode()).hexdigest()[:32]


def event_key(event: dict[str, Any]) -> str:
    body = "\0".join([
        event["harness"], event["session_id"], event["event_id"],
        event["role"], hashlib.sha256(event["text"].encode()).hexdigest(),
    ])
    return hashlib.sha256(body.encode()).hexdigest()


def is_searchable(text: str) -> bool:
    """Whether an event belongs in an ordinary human history search."""
    return not text.lstrip().startswith(NON_SEARCHABLE_PREFIXES)


def init_db(db: sqlite3.Connection) -> None:
    db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS sources (
            source_id TEXT PRIMARY KEY,
            harness TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            raw_path TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            source_mtime REAL NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_key TEXT PRIMARY KEY,
            harness TEXT NOT NULL,
            session_id TEXT NOT NULL,
            cwd TEXT,
            started_at TEXT,
            ended_at TEXT,
            event_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            event_key TEXT PRIMARY KEY,
            session_key TEXT NOT NULL,
            harness TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            timestamp TEXT,
            cwd TEXT,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            searchable INTEGER NOT NULL DEFAULT 1,
            source_id TEXT NOT NULL,
            source_line INTEGER NOT NULL,
            raw_ref TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS events_session_idx ON events(session_key, sequence);
        CREATE INDEX IF NOT EXISTS events_harness_idx ON events(harness, timestamp);
        CREATE INDEX IF NOT EXISTS events_content_idx ON events(content_hash);
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
    if "searchable" not in columns:
        db.execute("ALTER TABLE events ADD COLUMN searchable INTEGER NOT NULL DEFAULT 1")
    db.execute(
        "UPDATE events SET searchable=0 WHERE ltrim(text) LIKE '<app-context>%' "
        "OR ltrim(text) LIKE '<recommended_plugins>%' "
        "OR ltrim(text) LIKE '<system-reminder>%' "
        "OR ltrim(text) LIKE '<command-name>%' "
        "OR ltrim(text) LIKE '<local-command%' "
        "OR ltrim(text) LIKE '<bash-input>%' "
        "OR ltrim(text) LIKE '<bash-stdout>%' "
        "OR ltrim(text) LIKE 'tool_result%'"
    )
    db.execute("CREATE INDEX IF NOT EXISTS events_searchable_idx ON events(searchable, timestamp)")


def import_sources(sources: Iterable[Source], root: Path) -> dict[str, int]:
    root = root.expanduser().resolve()
    raw_root = root / "raw"
    root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    os.chmod(raw_root, 0o700)
    db_path = root / "sessions.sqlite"
    db = sqlite3.connect(db_path)
    try:
        init_db(db)
        stats = {"sources": 0, "events_added": 0, "duplicates": 0, "sessions": 0}
        now = datetime.now(timezone.utc).isoformat()
        for source in sources:
            try:
                digest, size = file_digest(source.path)
                mtime = source.path.stat().st_mtime
            except OSError:
                continue
            sid = source_id(source)
            raw_dir = raw_root / source.harness
            raw_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(raw_dir, 0o700)
            raw_path = raw_dir / f"{digest}.jsonl"
            if not raw_path.exists():
                tmp = raw_path.with_suffix(".tmp")
                shutil.copyfile(source.path, tmp)
                os.chmod(tmp, 0o600)
                os.replace(tmp, raw_path)
            db.execute("""
                INSERT INTO sources(source_id,harness,source_path,source_hash,raw_path,byte_size,source_mtime,imported_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_hash=excluded.source_hash, raw_path=excluded.raw_path,
                    byte_size=excluded.byte_size, source_mtime=excluded.source_mtime,
                    imported_at=excluded.imported_at
            """, (sid, source.harness, str(source.path), digest, str(raw_path), size, mtime, now))
            stats["sources"] += 1
            sequences: dict[str, int] = {}
            touched: set[str] = set()
            for event in iter_events(source):
                session_key = hashlib.sha256(
                    f"{event['harness']}\0{event['session_id']}".encode()
                ).hexdigest()[:32]
                sequences[session_key] = sequences.get(session_key, 0) + 1
                sequence = sequences[session_key]
                ekey = event_key(event)
                content_hash = hashlib.sha256(event["text"].encode()).hexdigest()
                cur = db.execute("""
                    INSERT OR IGNORE INTO events(
                        event_key,session_key,harness,session_id,event_id,sequence,
                        timestamp,cwd,role,text,searchable,source_id,source_line,raw_ref,content_hash
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (ekey, session_key, event["harness"], event["session_id"],
                       event["event_id"], sequence, event["timestamp"], event["cwd"],
                       event["role"], event["text"], int(is_searchable(event["text"])), sid, event["line"],
                       f"{sid}:{event['line']}", content_hash))
                if cur.rowcount == 1:
                    stats["events_added"] += 1
                else:
                    stats["duplicates"] += 1
                touched.add(session_key)
                db.execute("""
                    INSERT INTO sessions(session_key,harness,session_id,cwd,started_at,ended_at,event_count)
                    VALUES(?,?,?,?,?,?,0)
                    ON CONFLICT(session_key) DO NOTHING
                """, (session_key, event["harness"], event["session_id"], event["cwd"],
                       event["timestamp"], event["timestamp"]))
            for session_key in touched:
                db.execute("""
                    UPDATE sessions SET
                        event_count=(SELECT COUNT(*) FROM events WHERE session_key=?),
                        cwd=COALESCE((SELECT cwd FROM events WHERE session_key=? AND cwd IS NOT NULL LIMIT 1), cwd),
                        started_at=(SELECT MIN(timestamp) FROM events WHERE session_key=? AND timestamp IS NOT NULL),
                        ended_at=(SELECT MAX(timestamp) FROM events WHERE session_key=? AND timestamp IS NOT NULL)
                    WHERE session_key=?
                """, (session_key, session_key, session_key, session_key, session_key))
            stats["sessions"] += len(touched)
        db.commit()
        os.chmod(db_path, 0o600)
        return stats
    finally:
        db.close()


def inventory(sources: Iterable[Source]) -> dict[str, Any]:
    result: dict[str, Any] = {"sources": [], "totals": {"files": 0, "bytes": 0}}
    by_harness: dict[str, dict[str, int]] = {}
    for source in sources:
        try:
            size = source.path.stat().st_size
        except OSError:
            continue
        item = by_harness.setdefault(source.harness, {"files": 0, "bytes": 0})
        item["files"] += 1
        item["bytes"] += size
        result["totals"]["files"] += 1
        result["totals"]["bytes"] += size
    result["sources"] = [dict(harness=k, **v) for k, v in sorted(by_harness.items())]
    return result


def search(root: Path, query: str, project: str | None = None,
           harness: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    db = sqlite3.connect(root / "sessions.sqlite")
    db.row_factory = sqlite3.Row
    try:
        words = [w for w in query.split() if w]
        clauses = ["e.text LIKE ?" for _ in words]
        params: list[Any] = [f"%{w}%" for w in words]
        if project:
            clauses.append("COALESCE(e.cwd, '') LIKE ?")
            params.append(f"%{project}%")
        if harness:
            clauses.append("e.harness = ?")
            params.append(harness)
        clauses.insert(0, "e.searchable=1")
        where = " AND ".join(clauses)
        params.append(limit)
        rows = db.execute(f"""
            SELECT e.event_key, e.session_key, e.harness, e.session_id,
                   e.timestamp, e.cwd, e.role, substr(e.text, 1, 600) AS text
            FROM events e WHERE {where}
            ORDER BY e.timestamp DESC LIMIT ?
        """, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def show(root: Path, session_key: str, limit: int = 100) -> list[dict[str, Any]]:
    db = sqlite3.connect(root / "sessions.sqlite")
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("""
            SELECT event_key, harness, session_id, sequence, timestamp, cwd,
                   role, text, raw_ref
            FROM events WHERE session_key=? ORDER BY sequence LIMIT ?
        """, (session_key, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="canonical corpus root (default: ~/Work/transcripts)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="inspect harness transcript sources; no writes")
    imp = sub.add_parser("import", help="copy raw sources and build/update the index")
    imp.add_argument("--harness", choices=("claude", "codex", "zcode"), action="append")
    srch = sub.add_parser("search", help="search normalized transcript events")
    srch.add_argument("query")
    srch.add_argument("--project")
    srch.add_argument("--harness", choices=("claude", "codex", "zcode"))
    srch.add_argument("--limit", type=int, default=20)
    sh = sub.add_parser("show", help="show a normalized session")
    sh.add_argument("session_key")
    sh.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    sources = discover_sources()
    if args.command == "inventory":
        print(json.dumps(inventory(sources), ensure_ascii=False, indent=2))
        return 0
    if args.command == "import":
        if args.harness:
            sources = [s for s in sources if s.harness in args.harness]
        stats = import_sources(sources, args.root)
        print(json.dumps({"root": str(args.root.expanduser().resolve()), **stats}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "search":
        print(json.dumps(search(args.root.expanduser().resolve(), args.query, args.project,
                                args.harness, args.limit), ensure_ascii=False, indent=2))
        return 0
    if args.command == "show":
        print(json.dumps(show(args.root.expanduser().resolve(), args.session_key, args.limit),
                         ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
