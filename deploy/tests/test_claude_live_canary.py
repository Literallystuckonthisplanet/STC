import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "core" / "scripts" / "claude_live_canary.py"
SPEC = importlib.util.spec_from_file_location("claude_live_canary", SCRIPT)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


def test_command_is_headless_read_only_and_user_scoped():
    command = CANARY.build_command(claude_bin=Path("/opt/claude"))

    assert command[:2] == ["/opt/claude", "-p"]
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--setting-sources") + 1] == "user"
    assert "--strict-mcp-config" in command
    for tool in ("Bash", "Read", "Write", "Edit", "Task"):
        assert tool in command[command.index("--disallowed-tools") + 1]
    assert "--dangerously-skip-permissions" not in command
    assert "--allow-dangerously-skip-permissions" not in command
    assert "--permission-mode" not in command


def test_first_assistant_text_skips_hooks_thinking_and_noise():
    feed = [
        "",
        "not json at all",
        json.dumps({"type": "system", "subtype": "hook_started"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "   "}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": '{"ok": 1}'}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "later"}]}}),
    ]

    assert CANARY.first_assistant_text(feed) == '{"ok": 1}'
    assert CANARY.first_assistant_text([json.dumps({"type": "system"})]) is None


def test_extract_payload_tolerates_code_fences():
    assert CANARY.extract_payload('```json\n{"a": 1}\n```') == {"a": 1}
    assert CANARY.extract_payload('{"a": 1}') == {"a": 1}


def test_evaluate_requires_actual_profile_and_compact_rules():
    good = {
        "timezone": "Asia/Yerevan",
        "main_model": "Luna Max",
        "medium_file_range": "2-5",
        "large_file_minimum": 6,
        "caveman_scope": "read-only exploration, research, docs, status",
        "session_end_memory_required": False,
    }
    verdict, checks = CANARY.evaluate(good)
    assert verdict == "pass"
    assert all(item["status"] == "pass" for item in checks)

    bad = dict(good, timezone="Europe/Moscow", session_end_memory_required=True)
    verdict, checks = CANARY.evaluate(bad)
    assert verdict == "fail"
    assert {item["name"] for item in checks if item["status"] == "fail"} == {
        "user-profile-timezone",
        "retired-session-end-memory",
    }


def test_retired_rule_absent_from_context_is_not_a_failure():
    """"unknown" means the retired rule is not in context — the good outcome."""
    answer = {
        "timezone": "Asia/Yerevan",
        "main_model": "Luna Max",
        "medium_file_range": "2-5",
        "large_file_minimum": 6,
        "caveman_scope": "read-only exploration, research, docs, status",
        "session_end_memory_required": "unknown",
    }
    verdict, _ = CANARY.evaluate(answer)
    assert verdict == "pass"


def test_missing_or_unknown_values_fail_loudly():
    verdict, checks = CANARY.evaluate({"large_file_minimum": "unknown"})
    assert verdict == "fail"
    assert all(item["status"] == "fail" for item in checks if item["name"] != "retired-session-end-memory")


def test_month_guard_records_one_attempt_even_when_failed(tmp_path):
    state = tmp_path / "state.json"
    assert CANARY.is_due(state, "2026-08") is True

    CANARY.record_attempt(state, "2026-08", "fail")

    assert CANARY.is_due(state, "2026-08") is False
    assert CANARY.is_due(state, "2026-09") is True
