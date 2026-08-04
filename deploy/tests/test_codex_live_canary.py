import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "core" / "scripts" / "codex_live_canary.py"
SPEC = importlib.util.spec_from_file_location("codex_live_canary", SCRIPT)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


def test_command_is_ephemeral_read_only_luna_max(tmp_path):
    command = CANARY.build_command(
        codex_bin=Path("/opt/codex"),
        repo=tmp_path,
        schema_path=tmp_path / "schema.json",
        answer_path=tmp_path / "answer.json",
    )

    assert command[:2] == ["/opt/codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="max"' in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command


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


def test_month_guard_records_one_attempt_even_when_failed(tmp_path):
    state = tmp_path / "state.json"
    assert CANARY.is_due(state, "2026-08") is True

    CANARY.record_attempt(state, "2026-08", "fail")

    assert CANARY.is_due(state, "2026-08") is False
    assert CANARY.is_due(state, "2026-09") is True
