"""Retired in-session memory mechanisms must not remain deployable artifacts."""

from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[2]


def test_session_checkpoint_implementation_is_removed_not_placeholdered():
    assert not (REPO / "core" / "scripts" / "session_checkpoint.py").exists()
    assert not (REPO / "core" / "skills" / "session-checkpoint").exists()
    assert not (REPO / "deploy" / "tests" / "test_session_checkpoint.py").exists()
    for path in (REPO / "adapters").glob("*/adapter.yaml"):
        if path.parent.name == "_template":
            continue
        assert "session-checkpoint" not in path.read_text(encoding="utf-8")


def test_precompact_memory_hook_is_removed_from_active_catalog():
    assert not (REPO / "core" / "hooks" / "precompact-memory-guard.sh").exists()
    for relative in (
        "README.md",
        "core/hooks/README.md",
        "adapters/claude/adapter.yaml",
        "adapters/codex/adapter.yaml",
        "adapters/zcode/adapter.yaml",
    ):
        text = (REPO / relative).read_text(encoding="utf-8")
        assert "H19_precompact_memory" not in text
        assert "precompact-memory-guard" not in text


def test_h03_human_name_matches_prompt_safety_behavior():
    hook = REPO / "core" / "hooks" / "prompt-safety-reminder.sh"
    assert hook.is_file()
    assert not (REPO / "core" / "hooks" / "stop_services_reminder.sh").exists()
    for name in ("claude", "codex", "zcode"):
        adapter = yaml.safe_load(
            (REPO / "adapters" / name / "adapter.yaml").read_text(encoding="utf-8")
        )
        hooks = adapter["hooks"]["capabilities"]
        assert "H03_prompt_safety" in hooks
        assert hooks["H03_prompt_safety"]["binding"]["file"] == "prompt-safety-reminder.sh"
        assert "H03_stop_services" not in hooks
