#!/usr/bin/env python3
"""Run one repeatable, read-only STC harness applicability bundle.

The bundle separates three questions that are often conflated:

* can STC render and validate the requested harness adapter;
* do the repository behavior tests pass;
* does a real harness see the deployed contract (only Codex currently has a
  live canary; Claude and ZCode are reported as UNVERIFIED).

It never runs ``deploy.py apply`` or ``uninstall``.  Reports are written under
the shared Obsidian-backed memory root, while source and live deployment files
are only read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_REPORTS_ROOT = Path("~/Work/memory/reports/stc").expanduser()
DEFAULT_STC_HOME = Path("~/.stc").expanduser()
LIVE_CANARY_TARGETS = {"codex"}
STEP_STATUSES = {"PASS", "FAIL", "WARN", "UNVERIFIED", "SKIPPED"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_config(repo: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment contract
        raise RuntimeError("PyYAML is required to read stc.yaml") from exc
    path = repo / "stc.yaml"
    if not path.is_file():
        raise ValueError(f"missing config: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("stc.yaml must contain an object")
    return payload


def resolve_targets(repo: Path | str, target_arg: str | None) -> list[str]:
    """Resolve and validate one target list without applying anything."""
    repo = Path(repo).expanduser().resolve()
    if target_arg:
        raw = [part.strip() for part in target_arg.split(",")]
        targets = list(dict.fromkeys(part for part in raw if part))
    else:
        config = _load_config(repo)
        targets = list(((config.get("deploy") or {}).get("targets") or []))
    if not targets:
        raise ValueError("no harness targets configured")
    for target in targets:
        if not (repo / "adapters" / target / "adapter.yaml").is_file():
            raise ValueError(f"unknown harness target: {target}")
    return targets


def build_static_commands(
    repo: Path | str,
    targets: Iterable[str],
    *,
    include_tests: bool = True,
) -> list[dict[str, Any]]:
    """Build the source/render/test commands; no command mutates live config."""
    repo = Path(repo).expanduser().resolve()
    python = sys.executable
    commands: list[dict[str, Any]] = [{
        "name": "deploy-precheck",
        "category": "contract",
        "command": [python, str(repo / "deploy" / "deploy.py"), "check"],
    }]
    for target in targets:
        commands.append({
            "name": f"render-{target}",
            "category": "contract",
            "command": [
                python,
                str(repo / "deploy" / "deploy.py"),
                "render",
                "--target",
                target,
                "--dry-run",
            ],
        })
    if include_tests:
        commands.append({
            "name": "pytest-suite",
            "category": "contract",
            "command": [python, "-m", "pytest", "-q", str(repo / "deploy" / "tests")],
        })
    return commands


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_parity(
    repo: Path | str,
    stc_home: Path | str | None = None,
) -> dict[str, Any]:
    """Compare source and deployed shared STC Snapshot without writing them."""
    repo = Path(repo).expanduser().resolve()
    home = Path(stc_home).expanduser().resolve() if stc_home else DEFAULT_STC_HOME.resolve()
    source = repo / "core" / "memory" / "SNAPSHOT.md"
    live = home / "core" / "memory" / "SNAPSHOT.md"
    result: dict[str, Any] = {
        "source": str(source),
        "live": str(live),
    }
    if not source.is_file():
        return {**result, "status": "FAIL", "reason": "source Snapshot is missing"}
    result["source_sha256"] = _sha256(source)
    if not live.is_file():
        return {**result, "status": "UNVERIFIED", "reason": "deployed Snapshot is missing"}
    result["live_sha256"] = _sha256(live)
    if result["source_sha256"] != result["live_sha256"]:
        return {**result, "status": "WARN", "reason": "deployed Snapshot differs from source"}
    return {**result, "status": "PASS", "reason": "source and deployed Snapshot match"}


def _step(
    name: str,
    category: str,
    status: str,
    **details: Any,
) -> dict[str, Any]:
    if status not in STEP_STATUSES:
        raise ValueError(f"unknown step status: {status}")
    return {"name": name, "category": category, "status": status, **details}


def _run_command(item: dict[str, Any], repo: Path, timeout_seconds: int) -> dict[str, Any]:
    command = list(item["command"])
    try:
        process = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _step(
            item["name"],
            item["category"],
            "FAIL",
            command=command,
            reason=str(exc),
        )
    output = "\n".join(part for part in (process.stdout, process.stderr) if part).strip()
    if len(output) > 6000:
        output = output[-6000:]
    return _step(
        item["name"],
        item["category"],
        "PASS" if process.returncode == 0 else "FAIL",
        command=command,
        returncode=process.returncode,
        output=output,
    )


def _verdict(steps: Iterable[dict[str, Any]], *, include_live: bool, category: str | None = None) -> str:
    selected = [step for step in steps if category is None or step.get("category") == category]
    if any(step.get("status") == "FAIL" for step in selected):
        return "FAIL"
    if any(step.get("status") == "WARN" for step in selected):
        return "WARN"
    if any(step.get("status") in {"UNVERIFIED", "SKIPPED"} for step in selected):
        return "UNVERIFIED"
    if not selected and include_live:
        return "UNVERIFIED"
    return "PASS"


def build_report(
    *,
    repo: Path | str,
    targets: Iterable[str],
    steps: Iterable[dict[str, Any]],
    include_live: bool,
) -> dict[str, Any]:
    """Build the machine-readable applicability result from observed steps."""
    steps = list(steps)
    contract_verdict = _verdict(steps, include_live=False, category="contract")
    live_steps = [step for step in steps if step.get("category") == "live"]
    live_verdict = "NOT_REQUESTED" if not include_live else _verdict(
        live_steps, include_live=True
    )
    if contract_verdict == "FAIL" or live_verdict == "FAIL":
        verdict = "FAIL"
    elif contract_verdict in {"WARN", "UNVERIFIED"} or live_verdict in {"WARN", "UNVERIFIED"}:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "schema_version": 1,
        "run_at": _now().isoformat(),
        "repo": str(Path(repo).expanduser().resolve()),
        "targets": list(targets),
        "mode": "static+live" if include_live else "static",
        "verdict": verdict,
        "contract_verdict": contract_verdict,
        "live_verdict": live_verdict,
        "steps": steps,
    }


def run_bundle(
    *,
    repo: Path | str,
    targets: Iterable[str],
    include_live: bool = False,
    include_tests: bool = True,
    reports_root: Path | str = DEFAULT_REPORTS_ROOT,
    stc_home: Path | str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run the complete static bundle and optional live checks."""
    repo = Path(repo).expanduser().resolve()
    targets = list(targets)
    steps: list[dict[str, Any]] = []
    for command in build_static_commands(repo, targets, include_tests=include_tests):
        steps.append(_run_command(command, repo, timeout_seconds))

    source_snapshot = repo / "core" / "memory" / "SNAPSHOT.md"
    steps.append(_step(
        "source-snapshot",
        "contract",
        "PASS" if source_snapshot.is_file() else "FAIL",
        path=str(source_snapshot),
    ))
    static_failed = any(
        step.get("category") == "contract" and step.get("status") == "FAIL"
        for step in steps
    )

    if include_live:
        parity = snapshot_parity(repo, stc_home)
        parity_details = {key: value for key, value in parity.items() if key != "status"}
        steps.append(_step("deployed-snapshot", "live", parity["status"], **parity_details))
        for target in targets:
            name = f"{target}-live-canary"
            if static_failed:
                steps.append(_step(
                    name,
                    "live",
                    "SKIPPED",
                    reason="static applicability checks failed; live call not spent",
                ))
            elif target not in LIVE_CANARY_TARGETS:
                steps.append(_step(
                    name,
                    "live",
                    "UNVERIFIED",
                    reason=f"no live canary is implemented for {target}",
                ))
            else:
                command = {
                    "name": name,
                    "category": "live",
                    "command": [
                        sys.executable,
                        str(repo / "core" / "scripts" / "codex_live_canary.py"),
                        "--repo",
                        str(repo),
                        "--reports-root",
                        str(Path(reports_root).expanduser().resolve()),
                        "--force",
                        "--timeout-seconds",
                        str(timeout_seconds),
                    ],
                }
                steps.append(_run_command(command, repo, timeout_seconds + 30))

    return build_report(
        repo=repo,
        targets=targets,
        steps=steps,
        include_live=include_live,
    )


def write_reports(report: dict[str, Any], reports_root: Path | str) -> tuple[Path, Path]:
    """Write JSON and Markdown evidence under the current month."""
    root = Path(reports_root).expanduser().resolve()
    timestamp = datetime.fromisoformat(report["run_at"]).astimezone(timezone.utc)
    folder = root / timestamp.strftime("%Y-%m")
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"harness-applicability-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"
    json_path = folder / f"{stem}.json"
    markdown_path = folder / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# STC harness applicability",
        "",
        f"- Запуск: `{report['run_at']}`",
        f"- Targets: `{', '.join(report['targets'])}`",
        f"- Режим: `{report['mode']}`",
        f"- Итог: **{report['verdict']}**",
        f"- Контракт: **{report['contract_verdict']}**",
        f"- Live: **{report['live_verdict']}**",
        "",
        "## Проверки",
        "",
    ]
    for step in report.get("steps", []):
        detail = step.get("reason") or step.get("output", "").splitlines()[-1:]
        if isinstance(detail, list):
            detail = detail[0] if detail else ""
        lines.append(f"- **{step['status']}** `{step['name']}` — {detail}")
    lines.extend([
        "",
        "## Интерпретация",
        "",
        "- Contract PASS означает, что STC валиден и рендерится для target; это не доказывает live-поведение.",
        "- Live PASS означает, что для данного target есть пройденный живой canary.",
        "- Live UNVERIFIED означает отсутствие автоматического canary, а не доказанную поломку.",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--target", help="one or more harness ids, comma-separated")
    parser.add_argument("--live", action="store_true", help="run live canary where available")
    parser.add_argument("--skip-tests", action="store_true", help="skip the pytest suite")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--stc-home", default=str(DEFAULT_STC_HOME))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--format", choices=("summary", "json", "markdown", "both"), default="summary")
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args(argv)

    try:
        repo = Path(args.repo).expanduser().resolve()
        targets = resolve_targets(repo, args.target)
        report = run_bundle(
            repo=repo,
            targets=targets,
            include_live=args.live,
            include_tests=not args.skip_tests,
            reports_root=args.reports_root,
            stc_home=args.stc_home,
            timeout_seconds=args.timeout_seconds,
        )
        json_path, markdown_path = write_reports(report, args.reports_root)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.format in {"summary", "both"}:
        print(f"{report['verdict']}: STC applicability ({', '.join(targets)})")
        print(f"contract={report['contract_verdict']} live={report['live_verdict']}")
        for step in report["steps"]:
            print(f"{step['status']}: {step['name']}")
        print(f"JSON: {json_path}")
        print(f"Markdown: {markdown_path}")
    if args.format in {"json", "both"}:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.format == "markdown":
        print(render_markdown(report), end="")

    if report["verdict"] == "FAIL":
        return 1
    if args.fail_on_warn and report["verdict"] == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
