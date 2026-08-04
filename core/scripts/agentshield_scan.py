#!/usr/bin/env python3
"""Run the deterministic AgentShield scanner weekly without a model/harness.

The wrapper scans both live Claude and Codex configuration roots, never uses
``--fix`` or model-powered analysis, keeps accepted baselines separate, and
writes a small redacted result consumed by the STC weekly audit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


TARGETS = {
    "claude": Path("~/.claude"),
    "codex": Path("~/.codex"),
}
SAFE_FINDING_FIELDS = ("id", "title", "severity", "category", "runtimeConfidence")


def build_scan_command(
    binary: Path,
    target: Path,
    *,
    baseline: Path | None = None,
    save_baseline: Path | None = None,
) -> list[str]:
    command = [
        str(binary),
        "scan",
        "--path",
        str(target),
        "--format",
        "json",
        "--min-severity",
        "info",
        "--supply-chain",
    ]
    if baseline is not None:
        command.extend(["--baseline", str(baseline), "--gate"])
    if save_baseline is not None:
        command.extend(["--save-baseline", str(save_baseline)])
    return command


def sanitize_result(target: str, raw: dict[str, Any], returncode: int) -> dict[str, Any]:
    score = raw.get("score") if isinstance(raw.get("score"), dict) else {}
    safe_score = {
        key: score[key]
        for key in ("grade", "numericScore")
        if key in score and isinstance(score[key], (str, int, float))
    }
    findings = []
    raw_findings = raw.get("findings") if isinstance(raw.get("findings"), list) else []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        safe = {}
        for key in SAFE_FINDING_FIELDS:
            value = finding.get(key)
            if isinstance(value, (str, int, float, bool)):
                safe[key] = value
        if "id" not in safe and isinstance(finding.get("ruleId"), str):
            safe["id"] = finding["ruleId"]
        if "title" not in safe and isinstance(finding.get("message"), str):
            safe["title"] = finding["message"][:240]
        findings.append(safe)
    return {
        "target": target,
        "status": "ok",
        "scanner_exit_code": returncode,
        "score": safe_score,
        "findings": findings,
    }


def _extract_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AgentShield JSON root is not an object")
    return payload


def run_target(
    name: str,
    target: Path,
    binary: Path,
    baseline: Path | None,
    save_baseline: Path | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = build_scan_command(
        binary,
        target,
        baseline=baseline,
        save_baseline=save_baseline,
    )
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=os.environ.copy(),
        )
        payload = _extract_json(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as exc:
        return {
            "target": name,
            "status": "error",
            "error": type(exc).__name__,
            "findings": [],
        }
    return sanitize_result(name, payload, proc.returncode)


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {severity: 0 for severity in ("critical", "high", "medium", "low", "info")}
    findings = []
    for result in results:
        for finding in result.get("findings", []):
            item = dict(finding)
            item["target"] = result.get("target")
            severity = str(item.get("severity", "info")).lower()
            if severity in counts:
                counts[severity] += 1
            findings.append(item)
    if any(result.get("status") != "ok" for result in results):
        verdict = "ERROR"
    elif counts["critical"] or counts["high"]:
        verdict = "FAIL"
    elif counts["medium"] or counts["low"]:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "schema_version": 1,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "status": verdict,
        "summary": counts | {"totalFindings": len(findings)},
        "targets": results,
        "findings": findings,
    }


def _week_key(day: date | None = None) -> str:
    year, week, _ = (day or date.today()).isocalendar()
    return f"{year}-W{week:02d}"


def _is_due(state_path: Path, week: str) -> bool:
    try:
        return json.loads(state_path.read_text(encoding="utf-8")).get("attempted_week") != week
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return True


def _record(state_path: Path, week: str, verdict: str) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({
            "attempted_week": week,
            "verdict": verdict,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="~/Work/memory/infra-audit/agentshield")
    parser.add_argument("--binary", default=os.environ.get("AGENTSHIELD_CLI", "~/.local/bin/agentshield"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args(argv)

    output_root = Path(args.output_root).expanduser().resolve()
    state_path = output_root / ".state.json"
    week = _week_key()
    if not args.force and not _is_due(state_path, week):
        print(f"SKIP: AgentShield already attempted for {week}")
        return 0

    binary = Path(args.binary).expanduser()
    baseline_root = output_root / "baselines"
    baseline_root.mkdir(parents=True, exist_ok=True)
    results = []
    for name, raw_target in TARGETS.items():
        target = raw_target.expanduser().resolve()
        baseline_path = baseline_root / f"{name}.json"
        compare = baseline_path if baseline_path.is_file() and not args.write_baseline else None
        save = baseline_path if args.write_baseline else None
        results.append(run_target(
            name,
            target,
            binary,
            compare,
            save,
            args.timeout_seconds,
        ))
    report = aggregate(results)
    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "agentshield-result.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _record(state_path, week, report["verdict"])
    print(f"{report['verdict']}: {report_path}")
    return 1 if report["verdict"] == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
