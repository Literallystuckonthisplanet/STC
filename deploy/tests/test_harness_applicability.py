"""Contract tests for the single-command harness applicability bundle."""

import importlib.util
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "core" / "scripts" / "harness_applicability.py"


def _load_bundle():
    assert SCRIPT.is_file(), "applicability bundle is not implemented yet"
    spec = importlib.util.spec_from_file_location("harness_applicability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["harness_applicability"] = module
    spec.loader.exec_module(module)
    return module


def test_default_targets_follow_deploy_config():
    bundle = _load_bundle()

    assert bundle.resolve_targets(REPO, None) == ["claude", "codex"]


def test_static_bundle_contains_only_read_only_commands():
    bundle = _load_bundle()

    commands = bundle.build_static_commands(REPO, ["claude", "codex"])
    flattened = [arg for item in commands for arg in item["command"]]

    assert any(item["name"] == "deploy-precheck" for item in commands)
    assert any(item["name"] == "render-claude" for item in commands)
    assert any(item["name"] == "render-codex" for item in commands)
    assert any(item["name"] == "pytest-suite" for item in commands)
    assert "apply" not in flattened
    assert "uninstall" not in flattened


def test_snapshot_parity_distinguishes_missing_and_stale_live_snapshot(tmp_path):
    bundle = _load_bundle()
    source = tmp_path / "repo" / "core" / "memory"
    source.mkdir(parents=True)
    (source / "SNAPSHOT.md").write_text("source-v1\n", encoding="utf-8")
    stc_home = tmp_path / "stc"

    missing = bundle.snapshot_parity(tmp_path / "repo", stc_home)
    assert missing["status"] == "UNVERIFIED"

    live = stc_home / "core" / "memory"
    live.mkdir(parents=True)
    (live / "SNAPSHOT.md").write_text("source-v1\n", encoding="utf-8")
    assert bundle.snapshot_parity(tmp_path / "repo", stc_home)["status"] == "PASS"

    (live / "SNAPSHOT.md").write_text("old\n", encoding="utf-8")
    stale = bundle.snapshot_parity(tmp_path / "repo", stc_home)
    assert stale["status"] == "WARN"
    assert stale["source_sha256"] != stale["live_sha256"]


def test_report_verdict_warns_when_live_canary_is_unavailable():
    bundle = _load_bundle()

    report = bundle.build_report(
        repo=REPO,
        targets=["claude"],
        steps=[
            {"name": "deploy-precheck", "category": "contract", "status": "PASS"},
            {"name": "render-claude", "category": "contract", "status": "PASS"},
            {"name": "pytest-suite", "category": "contract", "status": "PASS"},
            {"name": "claude-live-canary", "category": "live", "status": "UNVERIFIED"},
        ],
        include_live=True,
    )

    assert report["contract_verdict"] == "PASS"
    assert report["live_verdict"] == "UNVERIFIED"
    assert report["verdict"] == "WARN"
