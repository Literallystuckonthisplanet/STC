import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import infra_audit_local as audit  # noqa: E402


def test_adapter_delivery_audit_rejects_combined_mode(tmp_path):
    adapter = {"harness_facts": {"rules_delivery": "both"}}
    errors = audit.adapter_delivery_issues("demo", adapter, tmp_path)
    assert errors and "both" in errors[0]


def test_adapter_delivery_audit_requires_h06_for_hook_mode(tmp_path):
    adapter = {"harness_facts": {"rules_delivery": "hook"}, "hooks": {}}
    errors = audit.adapter_delivery_issues("demo", adapter, tmp_path)
    assert any("H06" in error for error in errors)


def test_h06_size_report_exposes_startup_budget_overage(tmp_path):
    (tmp_path / "rules").mkdir()
    for name in ("behavior", "pev", "session"):
        (tmp_path / "rules" / f"{name}.md").write_text("x" * 10000, encoding="utf-8")
    report = audit.h06_size_report(tmp_path)
    assert report["total_bytes"] == 30000
    assert report["limit_bytes"] == 10000
    assert report["status"] == "fail"
