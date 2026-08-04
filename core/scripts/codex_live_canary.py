#!/usr/bin/env python3
"""Monthly live check that Codex can actually see the deployed STC contract.

Static audits prove that files exist.  This canary spends one bounded Luna Max
call per month and asks the real Codex runtime to report facts that are present
only in the startup rules/profile.  It is read-only, ephemeral, schema-bound,
and writes its result to the Obsidian-backed STC report tree.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MODEL = "gpt-5.6-luna"
PROMPT = """This is an STC startup-context live canary. Do not use tools and do
not infer from this prompt. Based only on the user/profile and behavioral rules
loaded before this message, return the requested JSON fields:
- timezone: the user's configured IANA timezone;
- main_model: the default main model and effort name;
- medium_file_range: the M-task file-count range, using ASCII digits and '-';
- large_file_minimum: the minimum file count for an L task;
- caveman_scope: the exact categories where Caveman compression is allowed;
- session_end_memory_required: whether session-end memory rotation is required.
If a value is absent from startup context, use "unknown" (or -1 for the number)
rather than guessing.
"""

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "timezone",
        "main_model",
        "medium_file_range",
        "large_file_minimum",
        "caveman_scope",
        "session_end_memory_required",
    ],
    "properties": {
        "timezone": {"type": "string"},
        "main_model": {"type": "string"},
        "medium_file_range": {"type": "string"},
        "large_file_minimum": {"type": "integer"},
        "caveman_scope": {"type": "string"},
        "session_end_memory_required": {"type": "boolean"},
    },
}


def build_command(
    codex_bin: Path,
    repo: Path,
    schema_path: Path,
    answer_path: Path,
) -> list[str]:
    """Build the bounded real-runtime invocation used by the canary."""
    return [
        str(codex_bin),
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--enable",
        "hooks",
        "--dangerously-bypass-hook-trust",
        "--model",
        MODEL,
        "-c",
        'model_reasoning_effort="max"',
        "--cd",
        str(repo),
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(answer_path),
        PROMPT,
    ]


def _check(name: str, passed: bool, observed) -> dict:
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "observed": observed,
    }


def evaluate(answer: dict) -> tuple[str, list[dict]]:
    """Evaluate facts without trusting the model's own pass/fail judgment."""
    main_model = str(answer.get("main_model", "")).strip().lower()
    medium = str(answer.get("medium_file_range", "")).replace("–", "-").replace("—", "-")
    caveman = str(answer.get("caveman_scope", "")).strip().lower().replace("_", "-")
    caveman_words = ("read-only", "exploration", "research", "docs", "status")
    checks = [
        _check("user-profile-timezone", answer.get("timezone") == "Asia/Yerevan", answer.get("timezone")),
        _check("luna-max-main-routing", "luna" in main_model and "max" in main_model, answer.get("main_model")),
        _check("pev-medium-file-threshold", medium.replace(" ", "") == "2-5", answer.get("medium_file_range")),
        _check("pev-large-file-threshold", answer.get("large_file_minimum") == 6, answer.get("large_file_minimum")),
        _check("caveman-read-only-scope", all(word in caveman for word in caveman_words), answer.get("caveman_scope")),
        _check(
            "retired-session-end-memory",
            answer.get("session_end_memory_required") is False,
            answer.get("session_end_memory_required"),
        ),
    ]
    return ("pass" if all(item["status"] == "pass" for item in checks) else "fail", checks)


def is_due(state_path: Path, month: str) -> bool:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return True
    return state.get("attempted_month") != month


def record_attempt(state_path: Path, month: str, verdict: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "attempted_month": month,
        "verdict": verdict,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_markdown(report: dict) -> str:
    lines = [
        "# Codex live canary",
        "",
        f"- Запуск: `{report['run_at']}`",
        f"- Модель: `{report['model']} / max`",
        f"- Итог: **{report['verdict'].upper()}**",
        "- Назначение: реальная проверка, что Codex видит профиль и компактные правила STC.",
        "",
        "## Проверки",
        "",
    ]
    for item in report.get("checks", []):
        icon = "✅" if item["status"] == "pass" else "❌"
        lines.append(f"- {icon} `{item['name']}` — получено: `{item.get('observed')}`")
    if report.get("error"):
        lines.extend(["", "## Ошибка запуска", "", f"```text\n{report['error']}\n```"])
    lines.extend([
        "",
        "## Что делать",
        "",
        "- PASS: отдельная сессия не нужна.",
        "- FAIL: открыть отдельную сессию STC и приложить этот отчёт.",
        "",
    ])
    return "\n".join(lines)


def run_canary(repo: Path, codex_bin: Path, timeout_seconds: int = 240) -> dict:
    report = {
        "schema_version": 1,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "verdict": "fail",
        "checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="stc-codex-canary-") as tmp:
        tmpdir = Path(tmp)
        schema_path = tmpdir / "schema.json"
        answer_path = tmpdir / "answer.json"
        schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")
        command = build_command(codex_bin, repo, schema_path, answer_path)
        try:
            proc = subprocess.run(
                command,
                cwd=str(repo),
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            report["error"] = str(exc)
            return report
        if proc.returncode != 0:
            report["error"] = (proc.stderr or proc.stdout or f"codex exited {proc.returncode}")[-4000:]
            return report
        try:
            answer = json.loads(answer_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            report["error"] = f"invalid structured answer: {exc}"
            return report
        verdict, checks = evaluate(answer)
        report.update({"verdict": verdict, "checks": checks, "answer": answer})
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--reports-root", default="~/Work/memory/reports/stc")
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_CLI", "~/.local/bin/codex"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    reports_root = Path(args.reports_root).expanduser().resolve()
    month = datetime.now().strftime("%Y-%m")
    state_path = reports_root / ".state" / "codex-live-canary.json"
    if not args.force and not is_due(state_path, month):
        print(f"SKIP: Codex live canary already attempted for {month}")
        return 0

    report = run_canary(repo, Path(args.codex_bin).expanduser(), args.timeout_seconds)
    month_dir = reports_root / month
    month_dir.mkdir(parents=True, exist_ok=True)
    (month_dir / "codex-live-canary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (month_dir / "codex-live-canary.md").write_text(_render_markdown(report), encoding="utf-8")
    record_attempt(state_path, month, report["verdict"])
    print(f"{report['verdict'].upper()}: {month_dir / 'codex-live-canary.md'}")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
