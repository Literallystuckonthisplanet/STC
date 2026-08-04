#!/usr/bin/env python3
"""Deterministic, offline weekly audit of the STC capability contract.

The audit reads repository and local evidence only.  It writes generated
reports under the configured memory root; it never applies deployment changes,
starts services, or invokes launchctl.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


DEFAULT_MEMORY_ROOT = Path("/Users/xtoshin/Work/memory")
DEFAULT_CORPUS_ROOT = Path("/Users/xtoshin/Work/transcripts")
DEFAULT_OLLAMA_ENDPOINT = os.environ.get(
    "STC_OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/chat"
)
DEFAULT_MODEL = os.environ.get("STC_LOCAL_MODEL", "qwen3:4b")
STATUSES = frozenset({"PASS", "WARN", "FAIL", "NO_SAMPLE", "UNVERIFIED"})

OLLAMA_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "highlights", "next_steps"],
    "additionalProperties": False,
}

SECRET_PATTERNS = (
    re.compile(r"\b(?:ntn|sk|ghp|re)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"(?i)\b(?:api[_ -]?key|token|password|secret|private[_ -]?key|authorization|bearer)"
        r"\s*[:=]\s*['\"]?[^\s'\"]{12,}"
    ),
)


# Keep the catalog explicit and ordered.  The order is part of the human
# report contract and makes two runs comparable without sorting prose later.
CAPABILITY_CATALOG = (
    ("DEP-01", "deploy", "Проверяет render/check/deploy-контракты STC без применения изменений."),
    ("CTX-01", "always/profile", "Проверяет always-context, профиль и базовые правила доставки."),
    ("HOOK-01", "hooks contracts", "Проверяет наличие и форму hook-контрактов STC."),
    ("PEV-01", "PEV/delegation/model/caveman/isolation", "Проверяет планирование, делегацию, модели, сжатие и изоляцию."),
    ("MCP-01", "skills/commands/MCP", "Проверяет каталог skills/commands и MCP-конфигурацию."),
    ("SEC-01", "security/AgentShield", "Проверяет детерминированные security evidence и результаты AgentShield."),
    ("MEM-01", "memory/transcripts/ingest", "Проверяет read-only corpus SQLite и offline ingest."),
    ("GRAPH-01", "snapshots/Graphify", "Проверяет snapshot и локальные Graphify-артефакты."),
    ("DS-01", "DS", "Проверяет design-system процесс и шаблон токенов."),
    ("TDD-01", "TDD/docs-first/buy-vs-build", "Проверяет TDD, docs-first и buy-vs-build контракт."),
    ("QA-01", "review/QA/security/E2E", "Проверяет review, QA, security и E2E роли."),
    ("TOK-01", "token budget", "Проверяет правила token budget и учёт расходов агентов."),
    ("LD-01", "launchd", "Проверяет weekly launchd schedule и wake-safe guard."),
    ("DOC-01", "docs/retired/upstream", "Проверяет карту документации, retired-коды и upstream references."),
    ("BKP-01", "backup", "Проверяет контракт резервных копий deploy-артефактов."),
    ("H22-H11", "H22/H11", "Проверяет prompt-lens и output-hygiene guard-контракты."),
    ("USE-01", "usage matrix", "Проверяет task-to-model/mode usage matrix."),
)

SOURCE_REQUIREMENTS = {
    "always/profile": (
        "core/rules/behavior.md",
        "core/rules/pev.md",
        "core/rules/session.md",
        "core/rules/project_docs.md",
        "user/profile.md",
    ),
    "hooks contracts": (
        "core/hooks/session-start-context.sh",
        "core/hooks/block-dangerous-git.sh",
        "core/hooks/secret-read-guard.sh",
        "core/hooks/output-hygiene-guard.sh",
        "core/hooks/README.md",
    ),
    "PEV/delegation/model/caveman/isolation": (
        "core/rules/pev.md",
        "core/agents/builder.md",
        "core/agents/registry.yaml",
        "core/skills/caveman/SKILL.md",
        "core/skills/worktree/SKILL.md",
        "stc.yaml",
    ),
    "skills/commands/MCP": (
        "core/skills/docs/SKILL.md",
        "core/commands/install-mcp.md",
        "adapters/claude/adapter.yaml",
        "adapters/codex/adapter.yaml",
        "stc.yaml",
    ),
    "snapshots/Graphify": (
        "core/memory/SNAPSHOT.md",
        "core/scripts/infra_graph.py",
        "core/scripts/graphify_maintenance.py",
        "core/skills/code-graph/SKILL.md",
    ),
    "DS": (
        "core/templates/design-system/process.md",
        "core/templates/design-system/DESIGN.template.md",
    ),
    "TDD/docs-first/buy-vs-build": (
        "core/skills/tdd/SKILL.md",
        "core/hooks/integration-docs-gate.sh",
        "core/hooks/buy-vs-build-reminder.sh",
        "core/memory/skills_triggers.md",
    ),
    "review/QA/security/E2E": (
        "core/agents/code-reviewer.md",
        "core/agents/qa.md",
        "core/agents/security-arch.md",
        "core/agents/security-deps.md",
        "core/agents/e2e.md",
        "core/agents/registry.yaml",
    ),
    "token budget": (
        "core/scripts/agent_cost.py",
        "core/rules/behavior.md",
        "core/rules/pev.md",
    ),
    "launchd": (
        "deploy/launchd/com.xtoshin.stc-weekly-audit.plist",
        "core/scripts/weekly_audit.py",
    ),
    "docs/retired/upstream": (
        "README.md",
        "core/memory/MEMORY.md",
        "core/memory/reference_retired_codes.md",
        "core/skills/tdd/SKILL.md",
    ),
    "backup": (
        "deploy/checks.py",
        "deploy/README.md",
    ),
    "H22/H11": (
        "core/hooks/prompt-lens.sh",
        "core/hooks/output-hygiene-guard.sh",
        "deploy/tests/test_hook_behavior.py",
        "deploy/tests/test_hook_contracts.py",
    ),
    "usage matrix": (
        "core/agents/registry.yaml",
        "core/rules/pev.md",
        "stc.yaml",
        "README.md",
    ),
}


def _coerce_date(value: date | datetime | str | None) -> date:
    if value is None:
        return datetime.now().astimezone().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def iso_week(value: date | datetime | str | None = None) -> str:
    """Return the stable ISO week label used by the guard and report names."""
    current = _coerce_date(value)
    year, week, _ = current.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _metric(status: str, *, eligible: int, invoked: int, completed: int, violations: int) -> dict[str, int]:
    if status not in STATUSES:
        raise ValueError(f"unknown capability status: {status}")
    return {
        "eligible": int(eligible),
        "invoked": int(invoked),
        "completed": int(completed),
        "violations": int(violations),
    }


def _capability(code: str, name: str, description: str) -> dict[str, Any]:
    status = "NO_SAMPLE"
    return {
        "code": code,
        "name": name,
        "description": description,
        "status": status,
        "details": ["Доказательство ещё не подключено."],
        "evidence": [],
        **_metric(status, eligible=0, invoked=0, completed=0, violations=0),
    }


def _catalog() -> list[dict[str, Any]]:
    return [_capability(*item) for item in CAPABILITY_CATALOG]


def collect_source_contract(capability_name: str, repo: Path | str) -> dict[str, Any]:
    """Check source-backed contract files without executing or mutating them."""
    required = SOURCE_REQUIREMENTS.get(capability_name, ())
    if not required:
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "violations": 0,
            "details": ["source contract not applicable"],
            "evidence": [],
        }
    repo = Path(repo).expanduser().resolve()
    missing = [path for path in required if not (repo / path).is_file()]
    status = "FAIL" if missing else "PASS"
    details = [f"missing={path}" for path in missing] or [f"files={len(required)}"]
    return {
        "status": status,
        "invoked": 1,
        "completed": 1,
        "violations": len(missing),
        "details": details,
        "evidence": [str(repo / path) for path in required if (repo / path).is_file()],
    }


def _apply_source_contracts(capabilities: list[dict[str, Any]], repo: Path | str) -> None:
    for item in capabilities:
        if item["name"] in {"deploy", "security/AgentShield", "memory/transcripts/ingest"}:
            continue
        evidence = collect_source_contract(item["name"], repo)
        _set_capability(
            item,
            status=evidence["status"],
            details=evidence.get("details") or [],
            evidence=evidence.get("evidence") or [],
            eligible=1 if evidence["status"] != "NO_SAMPLE" else 0,
            invoked=int(evidence.get("invoked", 0)),
            completed=int(evidence.get("completed", 0)),
            violations=int(evidence.get("violations", 0)),
        )


def redact_secrets(value: str) -> str:
    """Remove obvious credential-shaped values before report rendering."""
    redacted = str(value)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("<REDACTED_SECRET>", redacted)
    return redacted


def _valid_ollama_endpoint(endpoint: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _model_prompt(report: dict[str, Any]) -> str:
    findings = []
    for item in report.get("capabilities") or []:
        if item.get("status") in {"FAIL", "WARN", "UNVERIFIED", "NO_SAMPLE"}:
            findings.append({
                "code": item.get("code"),
                "name": item.get("name"),
                "status": item.get("status"),
                "details": [redact_secrets(str(detail)) for detail in item.get("details") or []],
            })
    return (
        "Составь краткое advisory-резюме weekly STC audit. Не меняй статусы, "
        "не скрывай FAIL/WARN/UNVERIFIED/NO_SAMPLE, не выдумывай факты и не "
        "включай секреты. Верни только JSON по заданной схеме.\n\n"
        + json.dumps({"iso_week": report.get("iso_week"), "findings": findings},
                     ensure_ascii=False, sort_keys=True)
    )


def _parse_model_content(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or set(raw) != {"summary", "highlights", "next_steps"}:
        raise ValueError("model response violates JSON schema")
    if not isinstance(raw["summary"], str):
        raise ValueError("model summary must be a string")
    if not isinstance(raw["highlights"], list) or not isinstance(raw["next_steps"], list):
        raise ValueError("model highlights/next_steps must be arrays")
    if not all(isinstance(value, str) for value in raw["highlights"]):
        raise ValueError("model highlights must be strings")
    if not all(isinstance(value, str) for value in raw["next_steps"]):
        raise ValueError("model next_steps must be strings")
    return {
        "summary": redact_secrets(raw["summary"][:2000]),
        "highlights": [redact_secrets(value[:500]) for value in raw["highlights"][:10]],
        "next_steps": [redact_secrets(value[:500]) for value in raw["next_steps"][:10]],
    }


def summarize_with_ollama(
    report: dict[str, Any],
    *,
    endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    model: str = DEFAULT_MODEL,
    timeout: int = 45,
    attempts: int = 2,
    opener: Any | None = None,
) -> dict[str, Any]:
    """Ask loopback Qwen for advisory prose; deterministic findings stay authoritative."""
    if not _valid_ollama_endpoint(endpoint):
        return {
            "status": "unavailable",
            "model": model,
            "attempts": 0,
            "degraded": True,
            "summary": "",
            "highlights": [],
            "next_steps": [],
        }
    opener = opener or urllib.request.urlopen
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _model_prompt(report)}],
        "stream": False,
        "format": OLLAMA_SCHEMA,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 384},
    }
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error = "unavailable"
    max_attempts = max(1, min(int(attempts), 2))
    used_attempts = 0
    for _ in range(max_attempts):
        used_attempts += 1
        request = urllib.request.Request(
            endpoint,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = ((payload.get("message") or {}).get("content") if isinstance(payload, dict) else None)
            parsed = _parse_model_content(content)
            return {
                "status": "ok",
                "model": model,
                "attempts": used_attempts,
                "degraded": False,
                **parsed,
            }
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            last_error = "unavailable"
            del exc
        except (ValueError, TypeError, json.JSONDecodeError):
            last_error = "malformed"
    return {
        "status": last_error,
        "model": model,
        "attempts": used_attempts,
        "degraded": True,
        "summary": "",
        "highlights": [],
        "next_steps": [],
    }


def _sanitise(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {str(key): _sanitise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitise(item) for item in value]
    return value


def _status(value: Any, default: str = "UNVERIFIED") -> str:
    candidate = str(value or "").upper()
    return candidate if candidate in STATUSES else default


def _set_capability(
    item: dict[str, Any],
    *,
    status: str,
    details: Iterable[Any],
    evidence: Iterable[str] = (),
    eligible: int,
    invoked: int,
    completed: int,
    violations: int,
) -> None:
    item["status"] = _status(status)
    item["details"] = [redact_secrets(str(detail)) for detail in details]
    item["evidence"] = sorted({redact_secrets(str(value)) for value in evidence})
    item.update(_metric(
        item["status"], eligible=eligible, invoked=invoked,
        completed=completed, violations=violations,
    ))


def collect_infra_audit(repo: Path | str) -> dict[str, Any]:
    """Read the existing deterministic audit through its public subprocess CLI."""
    repo = Path(repo).expanduser().resolve()
    script = repo / "core" / "scripts" / "infra_audit_local.py"
    if not script.is_file():
        return {"status": "NO_SAMPLE", "invoked": 0, "completed": 0, "checks": [], "details": [
            "infra_audit_local.py отсутствует",
        ]}
    try:
        process = subprocess.run(
            [sys.executable, str(script), "--repo", str(repo)],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "checks": [],
            "details": [redact_secrets(str(exc))],
        }
    try:
        payload = json.loads(process.stdout or "")
    except (TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "checks": [],
            "details": ["infra_audit_local вернул невалидный JSON", redact_secrets(str(exc))],
        }
    checks = payload.get("checks") if isinstance(payload, dict) else None
    if not isinstance(checks, list):
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "checks": [],
            "details": ["infra_audit_local JSON не содержит checks"],
        }
    normalised = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        normalised.append({
            "name": redact_secrets(str(check.get("name") or "unknown")),
            "status": _status(check.get("status")),
            "details": _sanitise(check.get("details") or []),
        })
    verdict = _status(payload.get("verdict"), "PASS" if process.returncode == 0 else "WARN")
    return {
        "status": verdict,
        "invoked": 1,
        "completed": 1,
        "checks": normalised,
        "details": [
            f"checks={len(normalised)}",
            f"returncode={process.returncode}",
        ],
    }


def _apply_infra_evidence(capabilities: list[dict[str, Any]], repo: Path | str) -> None:
    evidence = collect_infra_audit(repo)
    deploy = next(item for item in capabilities if item["name"] == "deploy")
    checks = evidence.get("checks") or []
    deploy_check = next((check for check in checks if check["name"] == "deploy-precheck"), None)
    if deploy_check is not None:
        details = list(deploy_check.get("details") or [])
        details.extend(evidence.get("details") or [])
        failed_checks = [check["name"] for check in checks if check.get("status") == "FAIL"]
        details.extend(f"failed-check={name}" for name in failed_checks if name != "deploy-precheck")
        violations = len(failed_checks)
        status = deploy_check["status"]
        if status == "PASS" and evidence.get("status") == "FAIL":
            status = "FAIL"
        _set_capability(
            deploy,
            status=status,
            details=details,
            evidence=("infra_audit_local", "deploy-precheck"),
            eligible=1,
            invoked=int(evidence.get("invoked", 0)),
            completed=int(evidence.get("completed", 0)),
            violations=violations,
        )
        return
    _set_capability(
        deploy,
        status=evidence.get("status", "UNVERIFIED"),
        details=evidence.get("details") or ["deploy-precheck evidence отсутствует"],
        evidence=("infra_audit_local",),
        eligible=1 if evidence.get("status") != "NO_SAMPLE" else 0,
        invoked=int(evidence.get("invoked", 0)),
        completed=int(evidence.get("completed", 0)),
        violations=1 if evidence.get("status") == "FAIL" else 0,
    )


def collect_transcript_evidence(corpus_root: Path | str, repo: Path | str) -> dict[str, Any]:
    """Inspect the corpus index through SQLite's read-only URI mode."""
    corpus_root = Path(corpus_root).expanduser().resolve()
    database = corpus_root / "sessions.sqlite"
    ingest = Path(repo).expanduser().resolve() / "core" / "scripts" / "memory_ingest.py"
    corpus = Path(repo).expanduser().resolve() / "core" / "scripts" / "transcript_corpus.py"
    if not database.is_file():
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["sessions.sqlite отсутствует"],
            "evidence": [],
        }
    if not ingest.is_file() or not corpus.is_file():
        return {
            "status": "WARN",
            "invoked": 1,
            "completed": 1,
            "details": ["offline ingest/corpus script отсутствует"],
            "evidence": [str(database)],
        }
    connection = None
    try:
        uri = f"file:{quote(str(database), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only = ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
        ).fetchone()
        if table is None:
            return {
                "status": "UNVERIFIED",
                "invoked": 1,
                "completed": 0,
                "details": ["sessions.sqlite не содержит таблицу events"],
                "evidence": [str(database)],
            }
        events = int(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0])
        return {
            "status": "PASS",
            "invoked": 1,
            "completed": 1,
            "details": [f"events={events}"],
            "evidence": [str(database), str(ingest), str(corpus)],
        }
    except (OSError, sqlite3.Error) as exc:
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "details": [redact_secrets(str(exc))],
            "evidence": [str(database)],
        }
    finally:
        if connection is not None:
            connection.close()


def _apply_transcript_evidence(
    capabilities: list[dict[str, Any]], corpus_root: Path | str, repo: Path | str
) -> None:
    item = next(item for item in capabilities if item["name"] == "memory/transcripts/ingest")
    evidence = collect_transcript_evidence(corpus_root, repo)
    _set_capability(
        item,
        status=evidence["status"],
        details=evidence.get("details") or [],
        evidence=evidence.get("evidence") or [],
        eligible=1 if evidence["status"] != "NO_SAMPLE" else 0,
        invoked=int(evidence.get("invoked", 0)),
        completed=int(evidence.get("completed", 0)),
        violations=1 if evidence["status"] == "FAIL" else 0,
    )


def _agentshield_files(root: Path | str | None) -> list[Path]:
    if root is None:
        return []
    path = Path(root).expanduser().resolve()
    if path.is_file():
        return [path] if path.suffix.lower() == ".json" else []
    if not path.is_dir():
        return []
    # The scanner wrapper publishes one redacted canonical result. State and
    # baseline JSON files are metadata inputs, not scan evidence; selecting the
    # first recursive JSON used to make `.state.json` hide all real findings.
    canonical = path / "agentshield-result.json"
    if canonical.is_file():
        return [canonical]
    candidates = [
        candidate
        for candidate in path.rglob("*.json")
        if candidate.is_file()
        and not candidate.name.startswith(".")
        and "baselines" not in candidate.relative_to(path).parts
    ]
    return sorted(candidates)[:20]


def _default_agentshield_root(memory_root: Path, repo: Path | str) -> Path:
    repo = Path(repo).expanduser().resolve()
    candidates = (
        memory_root / "agentshield",
        memory_root / "security",
        repo / "agentshield-results",
        repo / ".agentshield",
    )
    for candidate in candidates:
        if _agentshield_files(candidate):
            return candidate
    return candidates[0]


def collect_agentshield_evidence(root: Path | str | None) -> dict[str, Any]:
    """Read bounded AgentShield JSON results without copying their contents."""
    files = _agentshield_files(root)
    if not files:
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["AgentShield result file отсутствует"],
            "evidence": [],
        }
    path = files[0]
    try:
        if path.stat().st_size > 256 * 1024:
            raise ValueError("AgentShield result file exceeds safe read limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "details": [redact_secrets(str(exc))],
            "evidence": [str(path)],
        }
    if not isinstance(payload, dict):
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "details": ["AgentShield result JSON должен быть объектом"],
            "evidence": [str(path)],
        }
    raw_findings = payload.get("findings") or payload.get("violations") or []
    findings = raw_findings if isinstance(raw_findings, list) else []
    severe = sum(
        1 for finding in findings
        if isinstance(finding, dict)
        and str(finding.get("severity") or "").lower() in {"critical", "high"}
    )
    verdict = str(payload.get("verdict") or payload.get("status") or "").upper()
    if verdict in {"FAIL", "CRITICAL", "BLOCK", "ERROR"} or severe:
        status = "FAIL"
    elif findings or verdict in {"WARN", "WARNING", "PARTIAL"}:
        status = "WARN"
    elif verdict in {"PASS", "OK", "CLEAN", "SUCCESS"}:
        status = "PASS"
    else:
        status = "UNVERIFIED"
    return {
        "status": status,
        "invoked": 1,
        "completed": 1,
        "details": [
            f"verdict={redact_secrets(verdict or 'missing')}",
            f"findings={len(findings)}",
            f"high_or_critical={severe}",
        ],
        "evidence": [str(path)],
        "findings_count": len(findings),
    }


def _apply_agentshield_evidence(
    capabilities: list[dict[str, Any]], root: Path | str | None
) -> None:
    item = next(item for item in capabilities if item["name"] == "security/AgentShield")
    evidence = collect_agentshield_evidence(root)
    _set_capability(
        item,
        status=evidence["status"],
        details=evidence.get("details") or [],
        evidence=evidence.get("evidence") or [],
        eligible=1 if evidence["status"] != "NO_SAMPLE" else 0,
        invoked=int(evidence.get("invoked", 0)),
        completed=int(evidence.get("completed", 0)),
        violations=int(evidence.get("findings_count", 0))
        if evidence["status"] in {"FAIL", "WARN"}
        else 0,
    )


def collect_launchd_evidence(root: Path | str | None, week: str) -> dict[str, Any]:
    """Summarise launchd state/log files without invoking launchctl or echoing logs."""
    if root is None:
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["launchd state/log root не задан"],
            "evidence": [],
            "log_errors": 0,
        }
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["launchd state/log root отсутствует"],
            "evidence": [],
            "log_errors": 0,
        }
    scan_roots = [root]
    for name in ("weekly-audit", "infra-audit", "offline-ingest", "graphify-maintenance", "project-snapshot"):
        child = root / name
        if child.is_dir():
            scan_roots.append(child)
    preferred_state_paths = [root / "weekly-audit" / "state.json", root / "state.json"]
    state_paths = preferred_state_paths + [
        candidate / "state.json"
        for candidate in scan_roots
        if candidate not in {root, root / "weekly-audit"}
    ]
    state_path = next((candidate for candidate in state_paths if candidate.is_file()), root / "state.json")
    state: dict[str, Any] = {}
    state_error = ""
    if state_path.is_file():
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(state_payload, dict):
                state = state_payload
            else:
                state_error = "state.json должен быть объектом"
        except (OSError, json.JSONDecodeError) as exc:
            state_error = redact_secrets(str(exc))
    log_files = sorted({
        path for scan_root in scan_roots
        for path in scan_root.glob("*.log")
        if path.is_file()
    })
    log_errors = 0
    for path in log_files[:10]:
        try:
            if path.stat().st_size > 128 * 1024:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        log_errors += len(re.findall(r"(?im)\b(?:error|failed|failure|exception|traceback)\b", text))
    if not state_path.is_file() and not log_files:
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["launchd state/log files отсутствуют"],
            "evidence": [],
            "log_errors": 0,
        }
    last_week = redact_secrets(str(state.get("last_successful_week") or "missing"))
    details = [
        f"last_successful_week={last_week}",
        f"logs={len(log_files)}",
        f"log_errors={log_errors}",
    ]
    if state_error:
        details.append(state_error)
    status = "UNVERIFIED" if state_error else (
        "WARN" if log_errors or not state_path.is_file() else "PASS"
    )
    return {
        "status": status,
        "invoked": 1,
        "completed": 1 if not state_error else 0,
        "details": details,
        "evidence": [str(state_path)] + [str(path) for path in log_files[:10]],
        "log_errors": log_errors,
        "week_matches": state.get("last_successful_week") == week,
    }


def _apply_launchd_evidence(
    capabilities: list[dict[str, Any]], root: Path | str | None, week: str
) -> None:
    item = next(item for item in capabilities if item["name"] == "launchd")
    evidence = collect_launchd_evidence(root, week)
    if evidence["status"] == "NO_SAMPLE":
        item["details"].append("live launchd sample: NO_SAMPLE")
        return
    static_status = item["status"]
    status = static_status if static_status == "FAIL" else evidence["status"]
    _set_capability(
        item,
        status=status,
        details=list(item.get("details") or []) + list(evidence.get("details") or []),
        evidence=list(item.get("evidence") or []) + list(evidence.get("evidence") or []),
        eligible=1,
        invoked=1,
        completed=int(evidence.get("completed", 0)),
        violations=int(item.get("violations", 0)) + int(evidence.get("log_errors", 0)),
    )


def collect_graphify_evidence(repo: Path | str) -> dict[str, Any]:
    """Read the derived graph file without refreshing or rebuilding it."""
    graph = Path(repo).expanduser().resolve() / "graphify-out" / "graph.json"
    if not graph.is_file():
        return {
            "status": "NO_SAMPLE",
            "invoked": 0,
            "completed": 0,
            "details": ["graphify-out/graph.json отсутствует"],
            "evidence": [],
            "nodes": 0,
            "links": 0,
        }
    try:
        if graph.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("graph.json exceeds safe read limit")
        payload = json.loads(graph.read_text(encoding="utf-8"))
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        links = payload.get("links") if isinstance(payload, dict) else None
        if not isinstance(nodes, list) or not isinstance(links, list):
            raise ValueError("graph.json lacks nodes/links arrays")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "UNVERIFIED",
            "invoked": 1,
            "completed": 0,
            "details": [redact_secrets(str(exc))],
            "evidence": [str(graph)],
            "nodes": 0,
            "links": 0,
        }
    return {
        "status": "PASS",
        "invoked": 1,
        "completed": 1,
        "details": [f"nodes={len(nodes)}", f"links={len(links)}"],
        "evidence": [str(graph)],
        "nodes": len(nodes),
        "links": len(links),
    }


def _apply_graphify_evidence(capabilities: list[dict[str, Any]], repo: Path | str) -> None:
    item = next(item for item in capabilities if item["name"] == "snapshots/Graphify")
    evidence = collect_graphify_evidence(repo)
    if evidence["status"] == "NO_SAMPLE":
        if item["status"] != "FAIL":
            _set_capability(
                item,
                status="NO_SAMPLE",
                details=list(item.get("details") or []) + list(evidence["details"]),
                evidence=item.get("evidence") or [],
                eligible=0,
                invoked=0,
                completed=0,
                violations=0,
            )
        return
    status = item["status"] if item["status"] == "FAIL" else evidence["status"]
    _set_capability(
        item,
        status=status,
        details=list(item.get("details") or []) + list(evidence.get("details") or []),
        evidence=list(item.get("evidence") or []) + list(evidence.get("evidence") or []),
        eligible=1,
        invoked=int(evidence.get("invoked", 0)),
        completed=int(evidence.get("completed", 0)),
        violations=int(item.get("violations", 0)) + (1 if status == "FAIL" else 0),
    )


def _sum_metrics(capabilities: Iterable[dict[str, Any]]) -> dict[str, int]:
    fields = ("eligible", "invoked", "completed", "violations")
    return {field: sum(int(item.get(field, 0)) for item in capabilities) for field in fields}


def _status_counts(capabilities: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in sorted(STATUSES)}
    for item in capabilities:
        status = str(item.get("status") or "UNVERIFIED")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _report_paths(memory_root: Path, current_date: date) -> dict[str, Path]:
    folder = memory_root / "reports" / "stc" / current_date.strftime("%Y-%m")
    week = iso_week(current_date)
    return {
        "report": folder / f"weekly-{week}.md",
        "latest_report": folder / "latest.md",
        "json_report": folder / f"weekly-{week}.json",
        "latest_json": folder / "latest.json",
    }


def _weekly_state_path(memory_root: Path) -> Path:
    return memory_root / "weekly-audit" / "state.json"


def _read_week_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _guard_result(paths: dict[str, Path], week: str, reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": reason,
        "iso_week": week,
        **{key: str(value) for key, value in paths.items()},
    }


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def render_json(report: dict[str, Any]) -> str:
    """Render a stable JSON representation for files and machine consumers."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the human report without embedding untrusted raw machine logs."""
    lines = [
        "# STC weekly offline audit",
        "",
        f"- ISO week: `{report['iso_week']}`",
        f"- Month: `{report['month']}`",
        f"- Verdict: `{report['verdict']}`",
        f"- Model degraded: `{str(report.get('model_degraded', False)).lower()}`",
        "",
        "## Counts",
        "",
        "```json",
        json.dumps(report["counts"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Capabilities",
        "",
    ]
    for item in report["capabilities"]:
        lines.extend([
            f"### {item['code']} — {item['name']}",
            "",
            item["description"],
            "",
            f"- Status: `{item['status']}`",
            f"- Evidence: {', '.join(f'`{value}`' for value in item.get('evidence', [])) or 'нет'}",
        ])
        for detail in item.get("details", []):
            lines.append(f"- Деталь: {detail}")
        lines.append("")
    model = report.get("model") or {}
    if model.get("summary"):
        lines.extend(["## Optional local model summary", "", model["summary"], ""])
        if model.get("highlights"):
            lines.extend(["### Model highlights", ""])
            lines.extend(f"- {redact_secrets(str(value))}" for value in model["highlights"])
            lines.append("")
        if model.get("next_steps"):
            lines.extend(["### Model next steps", ""])
            lines.extend(f"- {redact_secrets(str(value))}" for value in model["next_steps"])
            lines.append("")
    return "\n".join(lines)


def build_report(
    *,
    repo: Path | str,
    as_of: date | datetime | str | None = None,
    capabilities: list[dict[str, Any]] | None = None,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic report object from already collected evidence."""
    current_date = _coerce_date(as_of)
    items = list(capabilities if capabilities is not None else _catalog())
    catalog_order = {name: index for index, (_, name, _) in enumerate(CAPABILITY_CATALOG)}
    items.sort(key=lambda item: (catalog_order.get(str(item.get("name")), len(catalog_order)),
                                 str(item.get("code"))))
    counts = _sum_metrics(items)
    report = {
        "schema_version": 1,
        "iso_week": iso_week(current_date),
        "month": current_date.strftime("%Y-%m"),
        "repo": str(Path(repo).expanduser().resolve()),
        "verdict": "FAIL" if any(item["status"] == "FAIL" for item in items) else (
            "WARN" if any(item["status"] in {"WARN", "UNVERIFIED", "NO_SAMPLE"} for item in items)
            else "PASS"
        ),
        "status_counts": _status_counts(items),
        "counts": counts,
        "capabilities": items,
        "model_degraded": bool((model or {}).get("degraded", False)),
        "model": model or {"status": "disabled", "degraded": False},
    }
    return report


def run_audit(
    *,
    repo: Path | str,
    memory_root: Path | str = DEFAULT_MEMORY_ROOT,
    corpus_root: Path | str = DEFAULT_CORPUS_ROOT,
    agentshield_root: Path | str | None = None,
    launchd_root: Path | str | None = None,
    as_of: date | datetime | str | None = None,
    force: bool = False,
    no_model: bool = False,
    model_endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
    model_name: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Run the weekly audit and write the four canonical report artifacts."""
    current_date = _coerce_date(as_of)
    root = Path(memory_root).expanduser().resolve()
    paths = _report_paths(root, current_date)
    week = iso_week(current_date)
    state_path = _weekly_state_path(root)
    if not force and _read_week_state(state_path).get("last_successful_week") == week:
        return _guard_result(paths, week, "already-ran-this-iso-week")
    capabilities = _catalog()
    _apply_source_contracts(capabilities, repo)
    _apply_infra_evidence(capabilities, repo)
    _apply_transcript_evidence(capabilities, corpus_root, repo)
    shield_root = agentshield_root or os.environ.get("STC_AGENTSHIELD_ROOT")
    _apply_agentshield_evidence(
        capabilities,
        shield_root or _default_agentshield_root(root, repo),
    )
    _apply_launchd_evidence(capabilities, launchd_root or root, week)
    _apply_graphify_evidence(capabilities, repo)
    deterministic_report = build_report(
        repo=repo,
        as_of=current_date,
        capabilities=capabilities,
        model={"status": "disabled", "degraded": False},
    )
    model_info = (
        {"status": "disabled", "model": model_name, "attempts": 0, "degraded": False,
         "summary": "", "highlights": [], "next_steps": []}
        if no_model
        else summarize_with_ollama(
            deterministic_report,
            endpoint=model_endpoint,
            model=model_name,
        )
    )
    report = build_report(
        repo=repo,
        as_of=current_date,
        capabilities=capabilities,
        model=model_info,
    )
    rendered_json = render_json(report)
    rendered_markdown = render_markdown(report)
    for key in ("json_report", "latest_json"):
        _atomic_write(paths[key], rendered_json)
    for key in ("report", "latest_report"):
        _atomic_write(paths[key], rendered_markdown)
    _atomic_write(state_path, render_json({
        "schema_version": 1,
        "last_successful_week": week,
        "report": str(paths["report"]),
    }))
    return {
        "status": "ok",
        "report": str(paths["report"]),
        "latest_report": str(paths["latest_report"]),
        "json_report": str(paths["json_report"]),
        "latest_json": str(paths["latest_json"]),
        "iso_week": report["iso_week"],
        "verdict": report["verdict"],
        "model_degraded": report["model_degraded"],
        "counts": report["counts"],
        "status_counts": report["status_counts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--memory-root", default=str(DEFAULT_MEMORY_ROOT))
    parser.add_argument("--corpus-root", default=str(DEFAULT_CORPUS_ROOT))
    parser.add_argument("--as-of", default=None, help="local date YYYY-MM-DD; useful for tests")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--agentshield-root", default=None)
    parser.add_argument("--launchd-root", default=None)
    parser.add_argument("--model-endpoint", default=DEFAULT_OLLAMA_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="json")
    args = parser.parse_args(argv)
    result = run_audit(
        repo=args.repo,
        memory_root=args.memory_root,
        corpus_root=args.corpus_root,
        agentshield_root=args.agentshield_root,
        launchd_root=args.launchd_root,
        as_of=args.as_of,
        force=args.force,
        no_model=args.no_model,
        model_endpoint=args.model_endpoint,
        model_name=args.model,
    )
    if result.get("status") == "ok":
        if args.format in {"markdown", "both"}:
            print(Path(result["report"]).read_text(encoding="utf-8"), end="")
        if args.format in {"json", "both"}:
            print(Path(result["json_report"]).read_text(encoding="utf-8"), end="")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.get("verdict") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
