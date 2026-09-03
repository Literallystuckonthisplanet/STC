import importlib.util
import json
import os
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "core" / "scripts" / "agent_cost.py"
SPEC = importlib.util.spec_from_file_location("agent_cost", SCRIPT)
AGENT_COST = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(AGENT_COST)


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def _usage(input_tokens, output_tokens, *, write_5m=0, write_1h=0, read=0):
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": write_5m + write_1h,
        "cache_read_input_tokens": read,
        "cache_creation": {
            "ephemeral_5m_input_tokens": write_5m,
            "ephemeral_1h_input_tokens": write_1h,
        },
    }


def _row(request_id, message_id, timestamp, usage):
    return {
        "requestId": request_id,
        "timestamp": timestamp,
        "message": {
            "id": message_id,
            "model": "claude-sonnet-5",
            "usage": usage,
        },
    }


def test_cost_of_deduplicates_a_request_and_keeps_componentwise_maximum(tmp_path):
    jsonl = tmp_path / "agent-a.jsonl"
    _write_jsonl(
        jsonl,
        [
            _row(
                "req-1",
                "msg-1",
                "2026-08-14T10:00:00Z",
                _usage(10, 1, write_5m=4, write_1h=2, read=3),
            ),
            _row(
                "req-1",
                "msg-1",
                "2026-08-14T10:00:01Z",
                _usage(12, 2, write_5m=3, write_1h=5, read=2),
            ),
            _row(
                "req-1",
                "msg-1",
                "2026-08-14T10:00:02Z",
                _usage(1, 0, write_5m=1, write_1h=1, read=1),
            ),
        ],
    )

    result = AGENT_COST.cost_of(str(jsonl))

    breakdown = result["breakdown"]
    assert len(breakdown) == 1
    assert breakdown[0]["model"] == "claude-sonnet-5"
    assert breakdown[0]["input"] == 12
    assert breakdown[0]["output"] == 2
    assert breakdown[0]["cache_write_5m"] == 4
    assert breakdown[0]["cache_write_1h"] == 5
    assert breakdown[0]["cache_read"] == 3
    assert breakdown[0]["usd"] == 0.0001
    assert result["usage"].get("tokens") == 26


def test_replayed_incomplete_fragment_cannot_lower_the_request_usage(tmp_path):
    jsonl = tmp_path / "agent-replay.jsonl"
    _write_jsonl(
        jsonl,
        [
            _row(
                "req-replay",
                "msg-replay",
                "2026-08-14T10:00:00Z",
                _usage(100, 10, write_5m=20, write_1h=30, read=40),
            ),
            _row(
                "req-replay",
                "msg-replay",
                "2026-08-14T10:00:01Z",
                _usage(1, 1, write_5m=1, write_1h=1, read=1),
            ),
        ],
    )

    result = AGENT_COST.cost_of(str(jsonl))

    assert result["usage"]["input"] == 100
    assert result["usage"]["cache_write_5m"] == 20
    assert result["usage"]["cache_write_1h"] == 30
    assert result["usage"]["cache_read"] == 40
    assert result["usage"]["output"] == 10


def test_cost_of_falls_back_to_message_id_when_request_id_is_missing(tmp_path):
    jsonl = tmp_path / "agent-fallback.jsonl"
    _write_jsonl(
        jsonl,
        [
            _row(
                None,
                "msg-fallback",
                "2026-08-14T10:00:00Z",
                _usage(5, 1),
            ),
            _row(
                None,
                "msg-fallback",
                "2026-08-14T10:00:01Z",
                _usage(7, 2),
            ),
        ],
    )

    result = AGENT_COST.cost_of(str(jsonl))

    assert len(result["breakdown"]) == 1
    assert result["breakdown"][0]["input"] == 7
    assert result["breakdown"][0]["output"] == 2


def test_cost_of_prices_each_model_and_separates_cache_ttls(tmp_path):
    jsonl = tmp_path / "agent-prices.jsonl"
    sonnet = _row(
        "req-sonnet",
        "msg-sonnet",
        "2026-08-14T10:00:00Z",
        _usage(100, 10, write_5m=20, write_1h=30, read=40),
    )
    haiku = _row(
        "req-haiku",
        "msg-haiku",
        "2026-08-14T10:00:01Z",
        _usage(100, 10, write_5m=20, write_1h=30, read=40),
    )
    haiku["message"]["model"] = "claude-haiku-4-5-20251001"
    _write_jsonl(jsonl, [sonnet, haiku])

    result = AGENT_COST.cost_of(str(jsonl))

    breakdown = {item["model"]: item for item in result["breakdown"]}
    assert breakdown["claude-sonnet-5"]["price_prefix"] == "claude-sonnet-5"
    assert breakdown["claude-sonnet-5"]["cache_write_5m"] == 20
    assert breakdown["claude-sonnet-5"]["cache_write_1h"] == 30
    assert breakdown["claude-sonnet-5"]["usd"] == 0.0005
    assert breakdown["claude-haiku-4-5-20251001"]["price_prefix"] == "claude-haiku-4-5"
    assert breakdown["claude-haiku-4-5-20251001"]["usd"] == 0.0002
    assert result["usd"] == 0.0007


def test_unknown_model_is_visible_and_output_carries_price_metadata(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    jsonl = projects / "project" / "session" / "subagents" / "agent-unknown.jsonl"
    record = _row(
        "req-unknown",
        "msg-unknown",
        "2026-08-14T10:00:00Z",
        _usage(1, 1, write_5m=1, write_1h=1, read=1),
    )
    record["message"]["model"] = "future-model-9"
    _write_jsonl(jsonl, [record])
    monkeypatch.setattr(AGENT_COST, "PROJECTS", str(projects))
    monkeypatch.setattr(sys, "argv", ["agent_cost.py", "--latest"])

    AGENT_COST.main()

    result = AGENT_COST.cost_of(str(jsonl))
    output = capsys.readouterr().out
    assert result["unknown_model"] is True
    assert result["unknown_models"] == ["future-model-9"]
    assert result["price_version"] == "2026-08-14"
    assert result["price_date"] == "2026-08-14"
    assert "PRICE: version=2026-08-14 date=2026-08-14" in output
    assert "unknown-price model" in output


def test_window_and_latest_use_event_time_instead_of_file_mtime(tmp_path, monkeypatch, capsys):
    projects = tmp_path / "projects"
    old_event = projects / "project" / "session-old" / "subagents" / "agent-old.jsonl"
    new_event = projects / "project" / "session-new" / "subagents" / "agent-new.jsonl"
    _write_jsonl(
        old_event,
        [_row("req-old", "msg-old", "2026-08-14T10:00:00Z", _usage(10, 1))],
    )
    _write_jsonl(
        new_event,
        [_row("req-new", "msg-new", "2026-08-13T10:00:00Z", _usage(20, 1))],
    )
    # Deliberately make filesystem order disagree with event order.
    os.utime(old_event, (2, 2))
    os.utime(new_event, (3, 3))

    windowed = AGENT_COST.cost_of(str(old_event), since="2026-08-14")
    assert windowed["usage"]["input"] == 10
    assert windowed["event_time"] == "2026-08-14T10:00:00Z"

    monkeypatch.setattr(AGENT_COST, "PROJECTS", str(projects))
    monkeypatch.setattr(sys, "argv", ["agent_cost.py", "--latest", "--json"])
    AGENT_COST.main()
    latest = json.loads(capsys.readouterr().out)
    assert latest[0]["agent_id"] == "old"


def test_reordering_transcript_lines_does_not_change_usage(tmp_path):
    records = [
        _row(
            "req-1",
            "msg-1",
            "2026-08-14T10:00:00Z",
            _usage(10, 1, write_5m=4, write_1h=2, read=3),
        ),
        _row(
            "req-2",
            "msg-2",
            "2026-08-14T10:00:01Z",
            _usage(20, 2, write_5m=1, write_1h=5, read=6),
        ),
        _row(
            "req-1",
            "msg-1",
            "2026-08-14T10:00:02Z",
            _usage(8, 3, write_5m=6, write_1h=1, read=2),
        ),
    ]
    first = tmp_path / "agent-first.jsonl"
    second = tmp_path / "agent-second.jsonl"
    _write_jsonl(first, records)
    _write_jsonl(second, list(reversed(records)))

    left = AGENT_COST.cost_of(str(first))
    right = AGENT_COST.cost_of(str(second))

    assert left["event_time"] == right["event_time"]
    assert left["usage"] == right["usage"]
    assert left["breakdown"] == right["breakdown"]
    assert left["usd"] == right["usd"]
