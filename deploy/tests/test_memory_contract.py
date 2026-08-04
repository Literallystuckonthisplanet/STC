"""The active memory contract describes the current pipeline positively."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_active_rules_do_not_reintroduce_retired_save_boundaries():
    paths = [
        ROOT / "core" / "rules" / "session.md",
        ROOT / "core" / "rules" / "behavior.md",
        ROOT / "core" / "rules" / "pev.md",
        ROOT / "core" / "memory" / "skills_triggers.md",
        ROOT / "user" / "profile.md",
        ROOT / "user" / "profile.example.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()

    assert "session end has no memory-rotation protocol" not in text
    assert "not a memory-save boundary" not in text
    assert "memory rotation, i26" not in text
    assert "raw transcripts" in text
    assert "offline ingest" in text


def test_commit_jit_message_stays_about_commit_verification():
    text = (ROOT / "core" / "hooks" / "block-dangerous-git.sh").read_text(encoding="utf-8").lower()

    assert "memory rotation" not in text
    assert "before commit" in text
