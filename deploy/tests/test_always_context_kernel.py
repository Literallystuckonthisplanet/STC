"""Behavior contract for the compact always-loaded STC kernel."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULES = [
    ROOT / "core" / "rules" / "behavior.md",
    ROOT / "core" / "rules" / "pev.md",
    ROOT / "core" / "rules" / "session.md",
]
PROFILE = ROOT / "user" / "profile.md"


def _rules_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in RULES)


def test_h06_kernel_fits_codex_visible_context_budget():
    payload = sum(len(path.read_bytes()) for path in RULES)

    assert payload <= 10_000, f"always rules are {payload} bytes; budget is 10,000"


def test_kernel_has_only_live_memory_architecture():
    text = _rules_text().lower()

    for retired in (
        "session-end",
        "session end",
        "precompact",
        "postcompact",
        "memory rotation",
        "state/changelog",
        "session-checkpoint",
    ):
        assert retired not in text


def test_kernel_keeps_human_named_operational_triggers():
    text = _rules_text()

    for required in (
        "Secrets",
        "Worktrees",
        "Git push",
        "SELF-EXEC",
        "Snapshot",
        "Task scale",
        "Delegation",
        "Escalation",
        "Verify",
        "Always-context",
    ):
        assert required in text


def test_profile_matches_current_harness_and_timezone():
    text = PROFILE.read_text(encoding="utf-8")

    assert "Asia/Yerevan" in text
    assert "Luna Max" in text
    assert "Claude Pro (не Max)" not in text
    assert "Новичок в Claude Code" not in text
