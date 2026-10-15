"""Regression tests for the explicit PEV task-scale thresholds."""

from pathlib import Path


PEV = Path(__file__).resolve().parents[2] / "core" / "rules" / "pev.md"


def test_pev_does_not_have_the_ambiguous_global_non_trivial_trigger():
    text = PEV.read_text(encoding="utf-8")

    assert "Any non-trivial task goes through all three phases" not in text
    assert "PEV mode is selected by the task-scale table below" in text


def test_pev_has_explicit_file_thresholds_and_overrides():
    text = PEV.read_text(encoding="utf-8")

    assert "1 file" in text
    assert "2–5 files" in text
    assert "6+ files" in text
    assert "2+ dependent implementation steps" in text
    assert "2+ executors" in text
    for trigger in ("architecture", "API", "data schema", "lifecycle", "security", "irreversible"):
        assert trigger in text
    assert "Routine\nproduction/deploy is not an override" in text
    assert "one unresolved implementation fork" in text


def test_pev_has_bounded_targeted_execution_policy_with_precedence():
    text = " ".join(PEV.read_text(encoding="utf-8").lower().split())

    required = (
        "one planned targeted verification packet per block",
        "cheapest capable executor owns source, tests, tools, fixes",
        "main owns the short brief",
        "after two failed repair cycles, stop the block",
        "owner approval",
        "money, access, or data-layer changes",
        "claude + codex",
        "targeted execution policy takes precedence",
    )
    for phrase in required:
        assert phrase in text, f"missing targeted policy phrase: {phrase!r}"

    assert "do not" in text and "automatically start another repair round" in text


def test_pev_has_common_operational_delegation_for_both_harnesses():
    text = " ".join(PEV.read_text(encoding="utf-8").lower().split())

    for phrase in (
        "operational work defaults",
        "inventory/search",
        "docs, logs",
        "diagnostics",
        "triage",
        "reports",
        "large source contexts/logs stay with executor",
        "codex luna executor, sol main",
        "claude sonnet",
        "haiku mechanical work",
        "configured main model",
        "no subagent is needed",
    ):
        assert phrase in text, f"missing common delegation phrase: {phrase!r}"


def test_pev_scopes_rechecks_by_impact_not_line_count():
    text = " ".join(PEV.read_text(encoding="utf-8").lower().split())

    for phrase in (
        "behavior, invariants, affected modules",
        "rerun failed scenario and direct neighbors",
        "shared contract/schema/runtime dependency/auth impact",
        "explicit release/ci gate",
        "record paths, reason, scope",
        "just in case",
        "no mandatory final full-block rerun",
    ):
        assert phrase in text, f"missing verification-scope phrase: {phrase!r}"
