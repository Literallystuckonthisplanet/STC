#!/usr/bin/env python3
"""Offline transcript ingest for the shared STC memory/Wiki.

The transcript corpus is the source of truth.  This script performs the cheap,
deterministic part first and writes only staging candidates plus a monthly
Obsidian report.  A local Ollama model is optional and is never allowed to
write canonical memory, rules, hooks, or always-context directly.

Typical invocation from launchd::

    python3 core/scripts/memory_ingest.py run --config stc.yaml

The process is intentionally silent apart from a compact JSON status line.  A
human-facing view is the generated note under ``reports/stc/YYYY-MM/``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MEMORY_ROOT = Path(os.environ.get("STC_MEMORY_ROOT", "~/Work/memory")).expanduser()
DEFAULT_CORPUS_ROOT = Path(os.environ.get("STC_TRANSCRIPTS_ROOT", "~/Work/transcripts")).expanduser()
DEFAULT_MODEL = os.environ.get("STC_LOCAL_MODEL", "qwen3:4b")
DEFAULT_OLLAMA_ENDPOINT = os.environ.get(
    "STC_OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/chat"
)

# This is deliberately stricter than a bare 📌.  The user profile already uses
# 📌 for "remembered" information; requiring a durable-memory word prevents
# ordinary pinning/annotation from entering the memory pipeline accidentally.
EXPLICIT_MEMORY_RE = re.compile(
    r"(?im)^\s*📌\s*(?:memory|запомнил(?:а|о)?|запомнить|помни(?:\s+это)?)"
    r"\s*(?::\s*(?P<claim>\S.*))?$"
)

SECRET_PATTERNS = (
    re.compile(r"\b(?:ntn|sk|ghp|re)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|token|password|secret|private[_ -]?key)\b"
        r"\s*[:=]\s*['\"]?[^\s'\"]{12,}"
    ),
)

OLLAMA_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "fact", "decision", "preference",
                            "instinct_candidate", "rule_proposal",
                        ],
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "project", "session"],
                    },
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["text", "type", "scope", "confidence", "reason"],
            },
        }
    },
    "required": ["claims"],
}


def _month(value: str | None = None) -> str:
    if value:
        return value[:7]
    return datetime.now().astimezone().strftime("%Y-%m")


def _expand_path(value: Path | str) -> Path:
    raw = os.path.expandvars(str(value))
    # launchd does not promise that HOME is present in the job environment.
    raw = raw.replace("${HOME}", str(Path.home()))
    return Path(raw).expanduser().resolve()


def _normalise_claim(value: str) -> str:
    return " ".join(value.strip().split())


def redact_secrets(value: str) -> str:
    """Redact obvious credential-shaped values before local-model calls."""
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    return redacted


def _scope_for(cwd: str | None) -> tuple[str, str | None]:
    if not cwd:
        return "global", None
    path = Path(cwd)
    project = path.name or None
    return ("project", project) if project else ("global", None)


def extract_marked_claims(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract only explicit durable-memory markers from normalized events."""
    claims: list[dict[str, Any]] = []
    for event in events:
        text = str(event.get("text") or "")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = EXPLICIT_MEMORY_RE.match(line)
            if not match:
                continue
            raw_claims = []
            if match.group("claim"):
                raw_claims.append(match.group("claim"))
            else:
                # A block marker is used by the session protocol: metadata
                # first, then one or more decision/fact bullets.  Stop at the
                # blank line so the following prose cannot leak into memory.
                for following in lines[index + 1:]:
                    stripped = following.strip()
                    if not stripped or stripped.startswith(("📌", "##", "---", "```")):
                        break
                    if re.match(r"(?i)^(тип|type|область|scope|источник|source|статус|status)\s*:", stripped):
                        continue
                    stripped = re.sub(r"^[-*]\s*", "", stripped)
                    stripped = re.sub(r"(?i)^(решение|decision|факт|fact)\s*:\s*", "", stripped)
                    if stripped:
                        raw_claims.append(stripped)
            for raw_claim in raw_claims:
                claim = _normalise_claim(raw_claim)
                if not claim:
                    continue
                claims.append({
                    "kind": "explicit_memory",
                    "text": claim,
                    "source": {
                        "event_key": event.get("event_key"),
                        "session_key": event.get("session_key"),
                        "harness": event.get("harness"),
                        "session_id": event.get("session_id"),
                        "line": event.get("line"),
                        "timestamp": event.get("timestamp"),
                        "raw_ref": event.get("raw_ref"),
                        "role": event.get("role"),
                        "cwd": event.get("cwd"),
                    },
                    "evidence": redact_secrets(text[:1000]),
                })
    return claims


def make_candidate(
    event: dict[str, Any],
    claim: str,
    *,
    model: dict[str, Any] | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    """Build a stable staging record tied to one transcript event."""
    claim = _normalise_claim(claim)
    model = model or {}
    source = {
        "event_key": event.get("event_key"),
        "session_key": event.get("session_key"),
        "harness": event.get("harness"),
        "session_id": event.get("session_id"),
        "line": event.get("line"),
        "timestamp": event.get("timestamp"),
        "raw_ref": event.get("raw_ref"),
        "role": event.get("role"),
        "cwd": event.get("cwd"),
    }
    scope, project = _scope_for(event.get("cwd"))
    scope = str(model.get("scope") or scope)
    identity = "\0".join([
        str(source.get("event_key") or ""), claim, str(model.get("type") or "explicit_memory")
    ])
    candidate_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "status": "new",
        "kind": "model_candidate" if model else "explicit_memory",
        "text": claim,
        "type": str(model.get("type") or "fact"),
        "scope": scope if scope in {"global", "project", "session"} else "project",
        "project": project,
        "confidence": float(model.get("confidence", 1.0)),
        "reason": str(model.get("reason") or "Явно отмечено пользователем/моделью."),
        "source": source,
        "evidence": redact_secrets(evidence if evidence is not None else str(event.get("text") or "")[:1000]),
    }


def _candidate_path(root: Path, month: str) -> Path:
    return root / "candidates" / f"{month}.jsonl"


def store_candidates(root: Path | str, candidates: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Append new candidates once; the JSONL store is staging, not canonical memory."""
    root = Path(root).expanduser().resolve()
    candidates = list(candidates)
    if not candidates:
        return {"added": 0, "duplicates": 0}
    by_month: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        timestamp = (candidate.get("source") or {}).get("timestamp")
        by_month.setdefault(_month(timestamp), []).append(candidate)
    added = duplicates = 0
    for month, items in by_month.items():
        path = _candidate_path(root, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        existing = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    if row.get("candidate_id"):
                        existing.add(row["candidate_id"])
                except json.JSONDecodeError:
                    continue
        with path.open("a", encoding="utf-8") as fh:
            for item in items:
                if item["candidate_id"] in existing:
                    duplicates += 1
                    continue
                fh.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
                existing.add(item["candidate_id"])
                added += 1
        os.chmod(path, 0o600)
    return {"added": added, "duplicates": duplicates}


def load_candidates(root: Path | str, month: str) -> list[dict[str, Any]]:
    path = _candidate_path(Path(root).expanduser().resolve(), month)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def render_monthly_report(
    root: Path | str,
    month: str,
    candidates: Iterable[dict[str, Any]],
    run_info: dict[str, Any],
    report_root: Path | str | None = None,
) -> Path:
    """Write the Obsidian note for one month and return its path."""
    root = Path(root).expanduser().resolve()
    candidates = list(candidates)
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = _normalise_claim(str(candidate.get("text") or "")).casefold()
        if key not in grouped:
            grouped[key] = {**candidate, "source_refs": []}
        source = candidate.get("source") or {}
        ref = source.get("raw_ref") or source.get("event_key")
        if ref and ref not in grouped[key]["source_refs"]:
            grouped[key]["source_refs"].append(ref)
    candidates = list(grouped.values())
    if report_root is None:
        report = root / "reports" / "stc" / month / "memory-review.md"
    else:
        report = _expand_path(report_root) / month / "memory-review.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(report.parent, 0o700)
    status = "pending-review" if candidates else "no-candidates"
    lines = [
        "---",
        "type: stc-memory-review",
        f"month: {month}",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        f"status: {status}",
        f"candidate_count: {len(candidates)}",
        "---",
        "",
        f"# STC — разбор памяти за {month}",
        "",
        "> Это staging-отчёт из транскриптов. Он не меняет canonical memory, профиль, правила или hooks.",
        "",
        "## Состояние ingest",
        "",
        f"```json\n{json.dumps(run_info, ensure_ascii=False, indent=2, sort_keys=True)}\n```",
        "",
        "## Кандидаты",
        "",
    ]
    if not candidates:
        lines.append("Новых кандидатов для согласования нет.")
    else:
        for index, candidate in enumerate(candidates, 1):
            source = candidate.get("source") or {}
            lines.extend([
                f"### {index}. {candidate.get('text', '').strip()}",
                "",
                f"- Статус: `{candidate.get('status', 'new')}`",
                f"- Тип: `{candidate.get('type', 'fact')}`",
                f"- Область: `{candidate.get('scope', 'project')}`",
                f"- Уверенность модели: `{candidate.get('confidence', 1.0)}`",
                f"- Обоснование: {candidate.get('reason', '')}",
                f"- Источник: `{source.get('raw_ref') or source.get('event_key')}`",
                f"- Сессия: `{source.get('session_key')}` / `{source.get('harness')}`",
                "",
                "> Доказательство: " + str(candidate.get("evidence", "")).replace("\n", " "),
                "",
                "Решение: `принять` / `отложить` / `отклонить` / `сделать proposal`",
                "",
            ])
            extra_refs = [ref for ref in candidate.get("source_refs", []) if ref != source.get("raw_ref")]
            if extra_refs:
                lines.insert(-3, "- Дополнительные источники: " + ", ".join(f"`{ref}`" for ref in extra_refs))
    lines.extend([
        "## Правило monthly review",
        "",
        "- подтверждённый обычный факт → canonical Wiki с источником;",
        "- preference/Instinct → остаётся кандидатом до согласования;",
        "- изменение правила или процесса → отдельный proposal, не auto-apply;",
        "- конфликт → не разрешать молча, вынести на разбор.",
        "",
    ])
    report.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(report, 0o600)
    return report


def claim_daily_run(state_path: Path | str, day: str) -> bool:
    """Claim one successful run per local day, used by RunAtLoad + calendar launchd."""
    state_path = Path(state_path).expanduser().resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(state_path.parent, 0o700)
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    if state.get("last_successful_day") == day:
        return False
    state["last_successful_day"] = day
    fd, tmp_name = tempfile.mkstemp(prefix="state-", suffix=".json", dir=state_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, state_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    os.chmod(state_path, 0o600)
    return True


def daily_run_exists(state_path: Path | str, day: str) -> bool:
    """Read the launch guard without changing it."""
    state_path = Path(state_path).expanduser().resolve()
    if not state_path.exists():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return state.get("last_successful_day") == day


def iter_db_events(root: Path | str, *, since: datetime | None = None) -> list[dict[str, Any]]:
    db_path = Path(root).expanduser().resolve() / "sessions.sqlite"
    if not db_path.exists():
        return []
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        params: list[Any] = []
        where = "e.searchable=1"
        if since:
            where += " AND e.timestamp >= ?"
            params.append(since.astimezone(timezone.utc).isoformat())
        rows = db.execute(
            f"""SELECT e.event_key, e.session_key, e.harness, e.session_id,
                       e.source_line AS line, e.timestamp, e.cwd, e.role, e.text,
                       e.raw_ref
                FROM events e WHERE {where}
                ORDER BY e.timestamp, e.sequence""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        db.close()


def _ollama_claims(event: dict[str, Any], endpoint: str, model: str, timeout: int) -> list[dict[str, Any]]:
    prompt = (
        "Извлеки только потенциально долговечные факты из одного сообщения. "
        "Не выдумывай и не превращай обычный текст в память. Не включай секреты. "
        "Невысказанные предпочтения, повторяющиеся паттерны и предложения правил "
        "помечай соответствующим type; результат всегда должен быть JSON по схеме.\n\n"
        f"Сообщение:\n{redact_secrets(str(event.get('text') or '')[:1600])}"
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": OLLAMA_SCHEMA,
        "think": False,
        "keep_alive": "60s",
        "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 256},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = ((payload.get("message") or {}).get("content") or "")
    parsed = json.loads(content) if isinstance(content, str) else content
    claims = parsed.get("claims", []) if isinstance(parsed, dict) else []
    return [claim for claim in claims if isinstance(claim, dict) and str(claim.get("text") or "").strip()]


def local_candidates(
    events: Iterable[dict[str, Any]], *, endpoint: str, model: str, timeout: int = 30,
    max_events: int = 120,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the optional local extractor; a missing runtime is a clean fallback."""
    candidates: list[dict[str, Any]] = []
    attempted = 0
    malformed = 0
    selected = []
    for event in events:
        # The deterministic marker pass already examines every event. The
        # model pass is deliberately bounded and focuses on user-authored
        # prose where implicit preferences/decisions are most informative.
        text = str(event.get("text") or "")
        if event.get("role") != "user" or not 80 <= len(text) <= 4000:
            continue
        selected.append(event)
    if max_events > 0:
        selected = selected[-max_events:]
    for event in selected:
        attempted += 1
        try:
            claims = _ollama_claims(event, endpoint, model, timeout)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            return candidates, {
                "status": "unavailable",
                "model": model,
                "attempted_events": attempted,
                "error": str(exc),
            }
        except (ValueError, json.JSONDecodeError):
            # A small local model can occasionally violate the JSON contract.
            # One malformed response must not discard valid claims from other
            # events or make the deterministic ingest fail.
            malformed += 1
            continue
        for claim in claims:
            confidence = float(claim.get("confidence", 0) or 0)
            if confidence < 0.65:
                continue
            candidates.append(make_candidate(event, str(claim["text"]), model=claim, evidence=str(claim["text"])))
    return candidates, {
        "status": "partial" if malformed else "ok",
        "model": model,
        "attempted_events": attempted,
        "selected_events": len(selected),
        "max_events": max_events,
        "malformed_responses": malformed,
        "claims": len(candidates),
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        return {}
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def run_pipeline(
    *,
    memory_root: Path | str = DEFAULT_MEMORY_ROOT,
    corpus_root: Path | str = DEFAULT_CORPUS_ROOT,
    config_path: Path | str | None = None,
    force: bool = False,
    no_model: bool = False,
    home: Path | None = None,
) -> dict[str, Any]:
    memory_root = Path(memory_root).expanduser().resolve()
    corpus_root = Path(corpus_root).expanduser().resolve()
    now = datetime.now().astimezone()
    day = now.strftime("%Y-%m-%d")
    state_path = memory_root / "offline-ingest" / "state.json"
    if not force and daily_run_exists(state_path, day):
        return {"status": "skipped", "reason": "already-ran-today", "day": day}

    from transcript_corpus import discover_sources, import_sources

    sources = discover_sources(home)
    imported = import_sources(sources, corpus_root)
    all_events = iter_db_events(corpus_root)
    explicit = extract_marked_claims(all_events)
    explicit_candidates = [
        make_candidate(
            {
                **claim["source"],
                "text": claim["evidence"],
                "raw_ref": claim["source"].get("raw_ref"),
            },
            claim["text"],
            evidence=claim["text"],
        )
        for claim in explicit
    ]

    pipeline_config = _load_yaml(Path(config_path).expanduser()) if config_path else {}
    model_config = (pipeline_config.get("memory_pipeline") or {}).get("local_model") or {}
    model_info: dict[str, Any] = {"status": "disabled"}
    model_candidates: list[dict[str, Any]] = []
    if not no_model and model_config.get("enabled", True):
        cutoff = now - timedelta(hours=int((pipeline_config.get("memory_pipeline") or {}).get("lookback_hours", 36)))
        recent_events = iter_db_events(corpus_root, since=cutoff)
        model_candidates, model_info = local_candidates(
            recent_events,
            endpoint=str(model_config.get("endpoint") or DEFAULT_OLLAMA_ENDPOINT),
            model=str(model_config.get("model") or DEFAULT_MODEL),
            timeout=int(model_config.get("timeout_seconds", 30)),
            max_events=int(model_config.get("max_events", 120)),
        )

    candidates = explicit_candidates + model_candidates
    stored = store_candidates(memory_root, candidates)
    month = _month()
    monthly = load_candidates(memory_root, month)
    run_info = {
        "run_at": now.isoformat(),
        "imported": imported,
        "explicit_markers": len(explicit_candidates),
        "stored": stored,
        "local_model": model_info,
        "corpus_root": str(corpus_root),
    }
    configured_report_root = (pipeline_config.get("memory_pipeline") or {}).get("report_root")
    report = render_monthly_report(
        memory_root,
        month,
        monthly,
        run_info,
        report_root=configured_report_root,
    )
    # Claim the day only after all durable outputs are complete.
    claim_daily_run(state_path, day)
    return {"status": "ok", "report": str(report), **run_info}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("run", nargs="?", choices=("run",), default="run")
    parser.add_argument("--memory-root", default=str(DEFAULT_MEMORY_ROOT))
    parser.add_argument("--corpus-root", default=str(DEFAULT_CORPUS_ROOT))
    parser.add_argument("--config", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    args = parser.parse_args(argv)
    result = run_pipeline(
        memory_root=args.memory_root,
        corpus_root=args.corpus_root,
        config_path=args.config or None,
        force=args.force,
        no_model=args.no_model,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
