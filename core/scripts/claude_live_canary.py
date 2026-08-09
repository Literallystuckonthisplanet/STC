#!/usr/bin/env python3
"""Monthly live check that Claude Code can actually see the deployed STC contract.

Static audits prove that files exist.  This canary spends one bounded headless
Claude Code call per month and asks the real runtime to report facts that are
present only in the startup rules/profile injected by the session-start hook.

Two deliberate differences from the Codex canary:

* Claude Code has no ``--output-schema``, so the answer is requested as one raw
  JSON object and parsed from the first assistant message.
* The run is cut off after that first message.  Stop hooks would otherwise keep
  the session going and replace the answer with unrelated hook follow-up, and a
  single turn is also the cheapest bound on the call.

The canary is read-only: every file/exec tool is denied, MCP is disabled, only
user-scope settings are loaded, and the process runs in a throwaway directory so
no project ``CLAUDE.md`` can contaminate the result.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


MODEL = "sonnet"
DENIED_TOOLS = (
    "Bash Read Glob Grep WebFetch WebSearch Task Edit Write NotebookEdit"
)
PROMPT = """This is an STC startup-context live canary. Do not use tools and do
not infer from this prompt. Based only on the user profile and behavioral rules
loaded before this message, reply with ONE raw JSON object and nothing else (no
prose, no code fences), with exactly these keys:
- timezone: the user's configured IANA timezone;
- main_model: the default main model and effort name;
- medium_file_range: the M-task file-count range, using ASCII digits and '-';
- large_file_minimum: the minimum file count for an L task, as an integer;
- caveman_scope: the exact categories where Caveman compression is allowed;
- session_end_memory_required: whether session-end memory rotation is required.
If a value is absent from startup context, use "unknown" (or -1 for the number)
rather than guessing.
"""

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def build_command(claude_bin: Path, model: str = MODEL) -> list[str]:
    """Build the bounded read-only headless invocation used by the canary."""
    return [
        str(claude_bin),
        "-p",
        PROMPT,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--strict-mcp-config",
        "--setting-sources",
        "user",
        "--disallowed-tools",
        DENIED_TOOLS,
    ]


def first_assistant_text(lines: Iterable[str]) -> str | None:
    """Return the first non-empty assistant text block from a stream-json feed."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                return block["text"].strip()
    return None


def extract_payload(text: str) -> dict:
    """Parse the answer object, tolerating a fenced code block around it."""
    stripped = FENCE_RE.sub("", text).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("canary answer must be a JSON object")
    return payload


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
    session_end = answer.get("session_end_memory_required")
    # The requirement is retired: absent from context ("unknown") is the same
    # good outcome as an explicit False.  Only a positive claim is a regression.
    session_end_ok = session_end is False or (
        isinstance(session_end, str) and session_end.strip().lower() == "unknown"
    )
    large = answer.get("large_file_minimum")
    try:
        large_ok = int(large) == 6
    except (TypeError, ValueError):
        large_ok = False
    checks = [
        _check("user-profile-timezone", answer.get("timezone") == "Asia/Yerevan", answer.get("timezone")),
        _check("luna-max-main-routing", "luna" in main_model and "max" in main_model, answer.get("main_model")),
        _check("pev-medium-file-threshold", medium.replace(" ", "") == "2-5", answer.get("medium_file_range")),
        _check("pev-large-file-threshold", large_ok, large),
        _check("caveman-read-only-scope", all(word in caveman for word in caveman_words), answer.get("caveman_scope")),
        _check("retired-session-end-memory", session_end_ok, session_end),
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
        "# Claude live canary",
        "",
        f"- Запуск: `{report['run_at']}`",
        f"- Модель: `{report['model']}`",
        f"- Итог: **{report['verdict'].upper()}**",
        "- Назначение: реальная проверка, что Claude Code видит профиль и компактные правила STC.",
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


def _read_first_text(proc: subprocess.Popen, timeout_seconds: int) -> str | None:
    """Read stream-json until the first assistant text, then stop the process."""
    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
    try:
        while True:
            remaining = deadline - datetime.now(timezone.utc).timestamp()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
            if not ready:
                if proc.poll() is not None:
                    return None
                continue
            line = proc.stdout.readline()
            if not line:
                return None
            text = first_assistant_text([line])
            if text is not None:
                return text
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                proc.kill()


def run_canary(claude_bin: Path, model: str = MODEL, timeout_seconds: int = 240) -> dict:
    report = {
        "schema_version": 1,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "verdict": "fail",
        "checks": [],
    }
    command = build_command(claude_bin, model)
    with tempfile.TemporaryDirectory(prefix="stc-claude-canary-") as workdir:
        try:
            proc = subprocess.Popen(
                command,
                cwd=workdir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
            )
        except OSError as exc:
            report["error"] = str(exc)
            return report
        text = _read_first_text(proc, timeout_seconds)
        if text is None:
            stderr = (proc.stderr.read() if proc.stderr else "") or ""
            report["error"] = (stderr or "no assistant message before timeout")[-4000:]
            return report
    try:
        answer = extract_payload(text)
    except (json.JSONDecodeError, ValueError) as exc:
        report["error"] = f"invalid structured answer: {exc}"
        report["raw_answer"] = text[:4000]
        return report
    verdict, checks = evaluate(answer)
    report.update({"verdict": verdict, "checks": checks, "answer": answer})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-root", default="~/Work/memory/reports/stc")
    parser.add_argument("--claude-bin", default=os.environ.get("CLAUDE_CLI", "~/.local/bin/claude"))
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    # Accepted for interface parity with the Codex canary; the Claude canary is
    # deliberately repo-independent and runs in a throwaway directory.
    parser.add_argument("--repo", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    reports_root = Path(args.reports_root).expanduser().resolve()
    month = datetime.now().strftime("%Y-%m")
    state_path = reports_root / ".state" / "claude-live-canary.json"
    if not args.force and not is_due(state_path, month):
        print(f"SKIP: Claude live canary already attempted for {month}")
        return 0

    report = run_canary(Path(args.claude_bin).expanduser(), args.model, args.timeout_seconds)
    month_dir = reports_root / month
    month_dir.mkdir(parents=True, exist_ok=True)
    (month_dir / "claude-live-canary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (month_dir / "claude-live-canary.md").write_text(_render_markdown(report), encoding="utf-8")
    record_attempt(state_path, month, report["verdict"])
    print(f"{report['verdict'].upper()}: {month_dir / 'claude-live-canary.md'}")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
