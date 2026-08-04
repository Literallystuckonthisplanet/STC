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
