#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-harness transcript corpus.

The harnesses remain the owners of their live session stores. This tool imports
their JSONL transcripts into a local, harness-neutral corpus:

    raw/          immutable, content-addressed source copies
    sessions.sqlite normalized events + searchable metadata/indexes

Import is idempotent. The source hash and event lineage are retained so every
normalized record can be traced back to a harness file and line number.

Examples:
    python3 core/scripts/transcript_corpus.py inventory
    python3 core/scripts/transcript_corpus.py import
    python3 core/scripts/transcript_corpus.py rebuild-index
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
import tempfile
import time
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

SEARCH_INDEX_FILENAME = "sessions.fts5.sqlite"
SEARCH_INDEX_STATE_FILENAME = "sessions.fts5.state.json"
SEARCH_INDEX_SCHEMA_VERSION = 1
INGEST_CYCLE_SECONDS = 24 * 60 * 60
MAX_SEARCH_LIMIT = 100


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


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open a SQLite database without giving the connection write access."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _search_index_path(root: Path) -> Path:
    return root / SEARCH_INDEX_FILENAME


def _search_index_state_path(root: Path) -> Path:
    return root / SEARCH_INDEX_STATE_FILENAME


def _read_search_index_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    os.chmod(path, 0o600)


def _source_shape(connection: sqlite3.Connection, database: Path) -> dict[str, Any]:
    stat = database.stat()
    row = connection.execute(
        "SELECT COUNT(*) AS event_count, COALESCE(MAX(rowid), 0) AS max_rowid FROM events"
    ).fetchone()
    return {
        "database_mtime_ns": stat.st_mtime_ns,
        "database_size": stat.st_size,
        "event_count": int(row["event_count"]),
        "max_rowid": int(row["max_rowid"]),
    }


def _fingerprint_row(digest: Any, row: sqlite3.Row) -> None:
    values = [
        row["event_key"], row["session_key"], row["harness"], row["session_id"],
        row["event_id"], row["sequence"], row["timestamp"], row["cwd"],
        row["role"], row["text"], row["searchable"], row["source_id"],
        row["source_line"], row["raw_ref"], row["content_hash"],
    ]
    digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\n")


def _build_search_index(source_database: Path, temporary_index: Path) -> dict[str, Any]:
    started = time.perf_counter()
    source = _readonly_connection(source_database)
    index = sqlite3.connect(temporary_index)
    try:
        index.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE events_fts USING fts5(
                event_key UNINDEXED,
                session_key UNINDEXED,
                harness UNINDEXED,
                session_id UNINDEXED,
                timestamp UNINDEXED,
                cwd UNINDEXED,
                role UNINDEXED,
                text,
                raw_ref UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            );
        """)
        source_shape_before = _source_shape(source, source_database)
        digest = hashlib.sha256()
        source_event_count = 0
        indexed_event_count = 0
        max_rowid = 0
        batch: list[tuple[Any, ...]] = []
        rows = source.execute("""
            SELECT rowid, event_key, session_key, harness, session_id, event_id,
                   sequence, timestamp, cwd, role, text, searchable, source_id,
                   source_line, raw_ref, content_hash
            FROM events ORDER BY rowid
        """)
        for row in rows:
            max_rowid = max(max_rowid, int(row["rowid"]))
            source_event_count += 1
            _fingerprint_row(digest, row)
            if int(row["searchable"] or 0):
                batch.append((
                    row["event_key"], row["session_key"], row["harness"], row["session_id"],
                    row["timestamp"], row["cwd"], row["role"], row["text"], row["raw_ref"],
                ))
                indexed_event_count += 1
            if len(batch) >= 500:
                index.executemany(
                    "INSERT INTO events_fts(event_key,session_key,harness,session_id,timestamp,cwd,role,text,raw_ref) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            index.executemany(
                "INSERT INTO events_fts(event_key,session_key,harness,session_id,timestamp,cwd,role,text,raw_ref) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                batch,
            )

        source_shape_after = _source_shape(source, source_database)
        if source_shape_before != source_shape_after:
            raise RuntimeError("source database changed during search-index build")
        source_watermark = {
            **source_shape_after,
            "fingerprint": digest.hexdigest(),
        }
        built_at_epoch = time.time()
        metadata = {
            "schema_version": SEARCH_INDEX_SCHEMA_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "built_at_epoch": built_at_epoch,
            "build_duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "source_watermark": source_watermark,
            "index_watermark": {
                "source_event_count": source_event_count,
                "indexed_event_count": indexed_event_count,
                "max_rowid": max_rowid,
                "fingerprint": source_watermark["fingerprint"],
            },
        }
        index.executemany(
            "INSERT INTO metadata(key,value) VALUES(?,?)",
            [(key, json.dumps(value, ensure_ascii=False, sort_keys=True))
             for key, value in metadata.items()],
        )
        index.commit()
        integrity = index.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"search index integrity check failed: {integrity}")
        return metadata
    finally:
        index.close()
        source.close()


def _record_search_index_failure(root: Path, error: BaseException) -> None:
    state_path = _search_index_state_path(root)
    state = _read_search_index_state(state_path)
    state["schema_version"] = SEARCH_INDEX_SCHEMA_VERSION
    state["attempts"] = int(state.get("attempts", 0)) + 1
    state["failed_rebuilds"] = int(state.get("failed_rebuilds", 0)) + 1
    state["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
    state["last_status"] = "failed"
    state["last_failure"] = {
        "type": type(error).__name__,
        "at": state["last_attempt_at"],
    }
    try:
        _write_json_atomically(state_path, state)
    except OSError:
        # The original rebuild error is authoritative; a status-file failure
        # must not hide it or make the primary corpus unusable.
        pass


def rebuild_search_index(root: Path | str) -> dict[str, Any]:
    """Build and atomically publish the copied-text FTS5 sidecar."""
    root = Path(root).expanduser().resolve()
    source_database = root / "sessions.sqlite"
    index_path = _search_index_path(root)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    temporary_name: str | None = None
    published = False
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{index_path.name}.", suffix=".tmp", dir=root
        )
        os.close(fd)
        os.chmod(temporary_name, 0o600)
        metadata = _build_search_index(source_database, Path(temporary_name))
        os.replace(temporary_name, index_path)
        published = True
        os.chmod(index_path, 0o600)
        state_path = _search_index_state_path(root)
        state = _read_search_index_state(state_path)
        state.update({
            "schema_version": SEARCH_INDEX_SCHEMA_VERSION,
            "attempts": int(state.get("attempts", 0)) + 1,
            "last_status": "ok",
            "last_successful_build_at": metadata["built_at"],
            "built_at_epoch": metadata["built_at_epoch"],
            "build_duration_ms": metadata["build_duration_ms"],
            "last_failure": None,
            "source_watermark": metadata["source_watermark"],
            "index_watermark": metadata["index_watermark"],
        })
        _write_json_atomically(state_path, state)
        return {
            "status": "ok",
            "index_status": "fresh",
            "path": str(index_path),
            **metadata,
            "failed_rebuilds": int(state.get("failed_rebuilds", 0)),
        }
    except BaseException as error:
        if not published:
            _record_search_index_failure(root, error)
        raise
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _load_search_index_metadata(index_path: Path) -> dict[str, Any]:
    connection = _readonly_connection(index_path)
    try:
        table_names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        if not {"metadata", "events_fts"}.issubset(table_names):
            raise sqlite3.DatabaseError("search index schema is incomplete")
        return {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key,value FROM metadata")
        }
    finally:
        connection.close()


def search_index_status(root: Path | str) -> dict[str, Any]:
    """Return freshness and rebuild telemetry without modifying the corpus."""
    root = Path(root).expanduser().resolve()
    index_path = _search_index_path(root)
    state = _read_search_index_state(_search_index_state_path(root))
    result: dict[str, Any] = {
        "path": str(index_path),
        "attempts": int(state.get("attempts", 0)),
        "failed_rebuilds": int(state.get("failed_rebuilds", 0)),
        "last_successful_build_at": state.get("last_successful_build_at"),
        "last_failure": state.get("last_failure"),
    }
    if not index_path.exists():
        result["index_status"] = "missing"
        return result
    stored = state.get("source_watermark")
    source_database = root / "sessions.sqlite"
    if isinstance(stored, dict):
        try:
            source_stat = source_database.stat()
            if (
                stored.get("database_mtime_ns") == source_stat.st_mtime_ns
                and stored.get("database_size") == source_stat.st_size
                and state.get("index_watermark")
            ):
                result.update({
                    "source_watermark": stored,
                    "index_watermark": state["index_watermark"],
                    "built_at": state.get("last_successful_build_at"),
                    "build_duration_ms": state.get("build_duration_ms"),
                    "index_status": "fresh",
                    "lag_seconds": 0,
                })
                return result
        except OSError:
            pass
    try:
        metadata = _load_search_index_metadata(index_path)
        source = _readonly_connection(source_database)
        try:
            current = _source_shape(source, source_database)
        finally:
            source.close()
        stored = metadata["source_watermark"]
        same_source = all(
            stored.get(key) == current.get(key)
            for key in ("database_mtime_ns", "database_size", "event_count", "max_rowid")
        )
        result.update({
            "source_watermark": current,
            "index_watermark": metadata.get("index_watermark"),
            "built_at": metadata.get("built_at"),
            "build_duration_ms": metadata.get("build_duration_ms"),
        })
        if same_source:
            result["index_status"] = "fresh"
            result["lag_seconds"] = 0
            return result
        built_at_epoch = float(metadata.get("built_at_epoch") or 0)
        lag_seconds = max(0, round(time.time() - built_at_epoch, 3)) if built_at_epoch else None
        result["lag_seconds"] = lag_seconds
        result["index_status"] = (
            "lagging" if lag_seconds is not None and lag_seconds > INGEST_CYCLE_SECONDS else "stale"
        )
        return result
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError) as error:
        result.update({"index_status": "corrupt", "error_type": type(error).__name__})
        return result


def _fts_match_query(query: str) -> str | None:
    words = [word for word in query.split() if word]
    if not words or any(not word.isalnum() for word in words):
        return None
    return " AND ".join(f'"{word.replace(chr(34), chr(34) * 2)}"*' for word in words)


def _bounded_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    return limit


def _cli_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer") from error
    try:
        return _bounded_limit(limit)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _escape_like(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _project_scope(column: str, project: str | None) -> tuple[str, list[str]] | None:
    """Build a path-component scope without treating user text as LIKE syntax."""
    if project is None:
        return None
    cleaned = project.strip()
    if not cleaned:
        return None
    if cleaned.startswith("/"):
        base = "/" + cleaned.strip("/")
        if base == "/":
            return f"{column} LIKE ? ESCAPE '!'", ["/%"]
        escaped = _escape_like(base)
        return f"({column} = ? OR {column} LIKE ? ESCAPE '!')", [base, f"{escaped}/%"]
    base = cleaned.strip("/")
    escaped = _escape_like(base)
    return (
        f"({column} = ? OR {column} LIKE ? ESCAPE '!' OR {column} LIKE ? ESCAPE '!')",
        [cleaned, f"%/{escaped}", f"%/{escaped}/%"],
    )


def _search_fts(root: Path, query: str, project: str | None,
                harness: str | None, limit: int) -> list[dict[str, Any]]:
    match = _fts_match_query(query)
    if match is None:
        return []
    connection = _readonly_connection(_search_index_path(root))
    connection.row_factory = sqlite3.Row
    try:
        clauses = ["events_fts MATCH ?"]
        params: list[Any] = [match]
        project_filter = _project_scope("COALESCE(cwd, '')", project)
        if project_filter:
            clause, values = project_filter
            clauses.append(clause)
            params.extend(values)
        if harness:
            clauses.append("harness = ?")
            params.append(harness)
        params.append(limit)
        rows = connection.execute(f"""
            SELECT event_key, session_key, harness, session_id,
                   timestamp, cwd, role, substr(text, 1, 600) AS text,
                   raw_ref, bm25(events_fts) AS score
            FROM events_fts
            WHERE {' AND '.join(clauses)}
            ORDER BY score ASC, timestamp DESC LIMIT ?
        """, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


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


def _search_baseline(root: Path, query: str, project: str | None = None,
                     harness: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    db = _readonly_connection(root / "sessions.sqlite")
    db.row_factory = sqlite3.Row
    try:
        words = [w for w in query.split() if w]
        clauses = ["e.text LIKE ?" for _ in words]
        params: list[Any] = [f"%{w}%" for w in words]
        project_filter = _project_scope("COALESCE(e.cwd, '')", project)
        if project_filter:
            clause, values = project_filter
            clauses.append(clause)
            params.extend(values)
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


def search_with_status(root: Path | str, query: str, project: str | None = None,
                       harness: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Search the fresh FTS sidecar, or report its state and use the baseline."""
    limit = _bounded_limit(limit)
    root = Path(root).expanduser().resolve()
    status = search_index_status(root)
    if _fts_match_query(query) is None:
        return {
            **status,
            "used_fallback": True,
            "fallback_reason": "empty-or-punctuation-query",
            "results": _search_baseline(root, query, project, harness, limit),
        }
    if status["index_status"] == "fresh":
        try:
            return {
                **status,
                "used_fallback": False,
                "fallback_reason": None,
                "results": _search_fts(root, query, project, harness, limit),
            }
        except (OSError, sqlite3.Error, ValueError) as error:
            status = {
                **status,
                "index_status": "corrupt",
                "error_type": type(error).__name__,
            }
    return {
        **status,
        "used_fallback": True,
        "fallback_reason": status.get("index_status"),
        "results": _search_baseline(root, query, project, harness, limit),
    }


def search(root: Path, query: str, project: str | None = None,
           harness: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Backward-compatible result-only search API."""
    return search_with_status(root, query, project, harness, limit)["results"]


def show(root: Path, session_key: str, limit: int = 100) -> list[dict[str, Any]]:
    limit = _bounded_limit(limit)
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
    sub.add_parser("rebuild-index", help="build and atomically publish the FTS5 sidecar")
    sub.add_parser("index-status", help="show sidecar freshness and rebuild telemetry")
    srch = sub.add_parser("search", help="search normalized transcript events")
    srch.add_argument("query")
    srch.add_argument("--project")
    srch.add_argument("--harness", choices=("claude", "codex", "zcode"))
    srch.add_argument("--limit", type=_cli_limit, default=20)
    sh = sub.add_parser("show", help="show a normalized session")
    sh.add_argument("session_key")
    sh.add_argument("--limit", type=_cli_limit, default=100)
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
    if args.command == "rebuild-index":
        print(json.dumps(rebuild_search_index(args.root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "index-status":
        print(json.dumps(search_index_status(args.root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "search":
        print(json.dumps(search_with_status(args.root.expanduser().resolve(), args.query, args.project,
                                            args.harness, args.limit), ensure_ascii=False, indent=2,
                         sort_keys=True))
        return 0
    if args.command == "show":
        print(json.dumps(show(args.root.expanduser().resolve(), args.session_key, args.limit),
                         ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
