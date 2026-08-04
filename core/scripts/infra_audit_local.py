#!/usr/bin/env python3
"""Harness-neutral, deterministic STC infrastructure audit.

This is the always-available monthly layer. It does not require Claude Code,
an Anthropic subscription, sub-agents, or network access. A model review may
be added later as a separate advisory layer; this report is the source for
whether the local wiring is healthy at all.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_CORE = (
    "rules/behavior.md",
    "rules/pev.md",
    "rules/session.md",
    "rules/project_docs.md",
    "hooks/session-start-context.sh",
    "skills/infra-audit/SKILL.md",
    "skills/code-graph/SKILL.md",
)
H06_MAX_BYTES = 10_000


def adapter_delivery_issues(name: str, adapter: dict, core_dir: Path) -> list[str]:
    """Return contract errors for one adapter's rules delivery declaration."""
    facts = adapter.get("harness_facts", {}) or {}
    mode = facts.get("rules_delivery")
    if mode not in {"hook", "inline"}:
        return [
            f"adapter '{name}': rules_delivery must be 'hook' or 'inline' "
            f"(got {mode!r})"
        ]
    if mode != "hook":
        return []
    h06 = (adapter.get("hooks", {}) or {}).get("capabilities", {}).get(
        "H06_session_start_context", {}
    )
    errors = []
    if h06.get("supported") is not True:
        errors.append(f"adapter '{name}': hook delivery requires supported H06")
    if h06.get("event") != "SessionStart":
        errors.append(f"adapter '{name}': H06 must fire on SessionStart")
    script = (h06.get("binding", {}) or {}).get("file")
    if script and not (core_dir / "hooks" / script).is_file():
        errors.append(f"adapter '{name}': missing H06 script {script}")
    return errors


def _load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _result(name: str, status: str, details=None) -> dict:
    return {"name": name, "status": status, "details": details or []}


def h06_size_report(core_dir: Path | str) -> dict:
    """Measure and enforce the compact H06 firing-rule payload contract."""
    core_dir = Path(core_dir)
    sizes = {}
    for name in ("behavior", "pev", "session"):
        path = core_dir / "rules" / f"{name}.md"
        sizes[name] = path.stat().st_size if path.is_file() else 0
    total = sum(sizes.values())
    return {
        "sizes": sizes,
        "total_bytes": total,
        "limit_bytes": H06_MAX_BYTES,
        "status": "fail" if total > H06_MAX_BYTES else "pass",
    }


def audit_repo(repo: Path | str, projects_root: Path | str | None = None) -> dict:
    repo = Path(repo).expanduser().resolve()
    core = repo / "core"
    checks = []

    missing = [path for path in REQUIRED_CORE if not (core / path).is_file()]
    checks.append(_result(
        "core-layout", "fail" if missing else "pass",
        [f"missing: {path}" for path in missing],
    ))

    adapter_errors = []
    adapters_dir = repo / "adapters"
    for path in sorted(adapters_dir.glob("*/adapter.yaml")):
        if path.parent.name == "_template":
            continue
        try:
            data = _load_yaml(path)
        except Exception as exc:
            adapter_errors.append(f"adapter '{path.parent.name}': invalid YAML: {exc}")
            continue
        adapter_errors.extend(adapter_delivery_issues(path.parent.name, data, core))
    checks.append(_result(
        "harness-rules-delivery", "fail" if adapter_errors else "pass",
        adapter_errors,
    ))

    h06 = h06_size_report(core)
    h06_details = [f"{name}={size} bytes" for name, size in h06["sizes"].items()]
    h06_details.append(f"total={h06['total_bytes']} bytes")
    h06_details.append(f"hard_limit={h06['limit_bytes']} bytes")
    checks.append(_result("h06-startup-payload", h06["status"], h06_details))

    try:
        proc = subprocess.run(
            [sys.executable, str(repo / "deploy" / "deploy.py"), "check"],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
        details = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
        checks.append(_result("deploy-precheck", "pass" if proc.returncode == 0 else "fail", details))
    except OSError as exc:
        checks.append(_result("deploy-precheck", "fail", [str(exc)]))

    # Reuse the deployer's public-core secret tripwire without requiring a
    # harness or an external service.
    sys.path.insert(0, str(repo / "deploy"))
    try:
        import checks as deploy_checks
        secret_errors = deploy_checks._no_personal_data_in_core(str(core))
    except Exception as exc:  # audit must report its own failure, not vanish
        secret_errors = [f"secret tripwire unavailable: {exc}"]
    checks.append(_result(
        "public-core-secret-tripwire", "fail" if secret_errors else "pass", secret_errors,
    ))

    # Historical docs may mention the retired location, but source/config
    # paths must not silently diverge again. Keep this as a warning so a
    # historical changelog does not make the whole audit red.
    old_root_hits = []
    for path in (repo / "core", repo / "stc.example.yaml"):
        if path.is_file():
            candidates = [path]
        else:
            candidates = path.rglob("*")
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix in {".md", ".yaml", ".yml"}:
                try:
                    if ".stc-docs" in candidate.read_text(encoding="utf-8", errors="ignore"):
                        old_root_hits.append(str(candidate.relative_to(repo)))
                except OSError:
                    pass
    checks.append(_result(
        "canonical-doc-root", "warn" if old_root_hits else "pass",
        [f"old .stc-docs reference: {path}" for path in old_root_hits],
    ))

    # The configured registry prevents temporary worktrees from being treated
    # as production projects. Missing graphs are warnings, not failures: the
    # scheduled refresh can bootstrap them without blocking infra health.
    config = repo / "stc.yaml"
    sys.path.insert(0, str(repo / "core" / "scripts"))
    try:
        import graphify_maintenance as gm
        configured_root, names = gm.configured_projects(config)
        root = Path(projects_root).expanduser() if projects_root else configured_root
        root = root or Path("~/Work/projects").expanduser()
        statuses = [gm.inspect_project(root / name) for name in names]
        missing_graphs = [s["name"] for s in statuses if s["state"] in {"missing", "invalid"}]
        stale = [s["name"] for s in statuses if s["state"] == "stale"]
        details = [f"configured={len(names)}", f"missing={len(missing_graphs)}", f"stale={len(stale)}"]
        details.extend(f"missing graph: {name}" for name in missing_graphs)
        details.extend(f"stale graph: {name}" for name in stale)
        graph_status = "warn" if missing_graphs or stale else "pass"
    except Exception as exc:
        graph_status, details = "warn", [f"graphify registry unavailable: {exc}"]
    checks.append(_result("graphify-registry", graph_status, details))

    return {
        "schema_version": 1,
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "verdict": "fail" if any(c["status"] == "fail" for c in checks) else (
            "warn" if any(c["status"] == "warn" for c in checks) else "pass"
        ),
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--projects-root")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = audit_repo(args.repo, args.projects_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 1 if report["verdict"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
