"""The private user profile is part of the always-context contract."""

from pathlib import Path


PROFILE = Path(__file__).resolve().parents[2] / "user" / "profile.md"


def test_profile_keeps_current_memory_contract_and_response_markers():
    text = PROFILE.read_text(encoding="utf-8")

    assert "## Response markers" in text
    assert "📌 запомнил" in text
    assert "transcript" in text.lower()
    assert "session-end (mandatory" not in text.lower()
    assert "ротация памяти по behavior.md" not in text
