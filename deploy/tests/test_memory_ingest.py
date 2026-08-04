import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "core" / "scripts" / "memory_ingest.py"
SPEC = importlib.util.spec_from_file_location("memory_ingest", SCRIPT)
MI = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["memory_ingest"] = MI
SPEC.loader.exec_module(MI)


def test_extract_marked_claims_requires_explicit_memory_marker():
    events = [
        {
            "event_key": "e1",
            "session_key": "s1",
            "harness": "codex",
            "session_id": "session-1",
            "line": 4,
            "timestamp": "2026-08-03T10:00:00+00:00",
            "cwd": "/Users/xtoshin/Work/STC",
            "role": "user",
            "text": "📌 MEMORY: транскрипты всех harnesses лежат в общем corpus.",
            "raw_ref": "source:4",
        },
        {
            "event_key": "e2",
            "session_key": "s1",
            "harness": "codex",
            "session_id": "session-1",
            "line": 5,
            "timestamp": "2026-08-03T10:01:00+00:00",
            "cwd": "/Users/xtoshin/Work/STC",
            "role": "assistant",
            "text": "📌 запомнил: это тоже должно остаться в Wiki.",
            "raw_ref": "source:5",
        },
        {
            "event_key": "e3",
            "session_key": "s1",
            "harness": "codex",
            "session_id": "session-1",
            "line": 6,
            "timestamp": "2026-08-03T10:02:00+00:00",
            "cwd": "/Users/xtoshin/Work/STC",
            "role": "user",
            "text": "📌 заметка без явной команды сохранения.",
            "raw_ref": "source:6",
        },
        {
            "event_key": "e4",
            "session_key": "s1",
            "harness": "codex",
            "session_id": "session-1",
            "line": 7,
            "timestamp": "2026-08-03T10:03:00+00:00",
            "cwd": "/Users/xtoshin/Work/STC",
            "role": "assistant",
            "text": "📌 MEMORY\nТип: решение\n- Решение: Instincts остаются кандидатами.\n\nОбычный текст.",
            "raw_ref": "source:7",
        },
    ]

    claims = MI.extract_marked_claims(events)

    assert [claim["text"] for claim in claims] == [
        "транскрипты всех harnesses лежат в общем corpus.",
        "это тоже должно остаться в Wiki.",
        "Instincts остаются кандидатами.",
    ]
    assert all(claim["kind"] == "explicit_memory" for claim in claims)
    assert all(claim["source"]["event_key"] in {"e1", "e2", "e4"} for claim in claims)


def test_store_candidates_is_idempotent(tmp_path):
    candidate = MI.make_candidate({
        "event_key": "e1",
        "session_key": "s1",
        "harness": "codex",
        "session_id": "session-1",
        "line": 4,
        "timestamp": "2026-08-03T10:00:00+00:00",
        "cwd": "/Users/xtoshin/Work/STC",
        "role": "user",
        "text": "📌 MEMORY: общий corpus.",
        "raw_ref": "source:4",
    }, "общий corpus.")

    first = MI.store_candidates(tmp_path, [candidate])
    second = MI.store_candidates(tmp_path, [candidate])

    assert first == {"added": 1, "duplicates": 0}
    assert second == {"added": 0, "duplicates": 1}
    stored = list((tmp_path / "candidates").glob("*.jsonl"))
    assert len(stored) == 1
    assert len(stored[0].read_text(encoding="utf-8").splitlines()) == 1


def test_render_monthly_report_is_in_month_folder(tmp_path):
    candidate = MI.make_candidate({
        "event_key": "e1",
        "session_key": "s1",
        "harness": "codex",
        "session_id": "session-1",
        "line": 4,
        "timestamp": "2026-08-03T10:00:00+00:00",
        "cwd": "/Users/xtoshin/Work/STC",
        "role": "user",
        "text": "📌 MEMORY: общий corpus.",
        "raw_ref": "source:4",
    }, "общий corpus.")

    report = MI.render_monthly_report(
        tmp_path,
        "2026-08",
        [candidate],
        {"imported": {"sources": 2, "events_added": 3}},
    )

    assert report == tmp_path / "reports" / "stc" / "2026-08" / "memory-review.md"
    text = report.read_text(encoding="utf-8")
    assert "month: 2026-08" in text
    assert "общий corpus." in text
    assert "source:4" in text
    assert "status: pending-review" in text


def test_render_monthly_report_applies_persistent_review_decision(tmp_path):
    candidate = MI.make_candidate({
        "event_key": "e1",
        "session_key": "s1",
        "harness": "codex",
        "session_id": "session-1",
        "line": 4,
        "timestamp": "2026-08-03T10:00:00+00:00",
        "cwd": "/Users/xtoshin/Work/STC",
        "role": "user",
        "text": "📌 MEMORY: session-end больше не является точкой сохранения.",
        "raw_ref": "source:4",
    }, "session-end больше не является точкой сохранения.")
    decisions = tmp_path / "reports" / "stc" / "2026-08"
    decisions.mkdir(parents=True)
    (decisions / "review-decisions.json").write_text(
        json.dumps({
            "schema_version": 1,
            "decisions": [{
                "claim": "session-end больше не является точкой сохранения.",
                "status": "accepted-obsolete",
                "decision": "Session-end memory rotation retired; this is no longer an open question.",
                "reviewed_at": "2026-08-04",
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    report = MI.render_monthly_report(
        tmp_path,
        "2026-08",
        [candidate],
        {"imported": {"sources": 1, "events_added": 1}},
    )

    text = report.read_text(encoding="utf-8")
    assert "status: no-candidates" in text
    assert "candidate_count: 0" in text
    assert "resolved_count: 1" in text
    assert "## Принятые и устаревшие решения" in text
    assert "`accepted-obsolete`" in text
    assert "Session-end memory rotation retired" in text


def test_render_monthly_report_reads_cross_month_decision_registry(tmp_path):
    candidate = MI.make_candidate({
        "event_key": "e2",
        "session_key": "s2",
        "harness": "codex",
        "session_id": "session-2",
        "line": 8,
        "timestamp": "2026-09-01T10:00:00+00:00",
        "cwd": "/Users/xtoshin/Work/STC",
        "role": "user",
        "text": "📌 MEMORY: календарь уже настроен.",
        "raw_ref": "source:8",
    }, "календарь уже настроен.")
    registry = tmp_path / "reports" / "stc"
    registry.mkdir(parents=True)
    (registry / "review-decisions.json").write_text(
        json.dumps({
            "schema_version": 1,
            "decisions": [{
                "claim": "календарь уже настроен.",
                "status": "accepted-architecture",
                "decision": "Calendar import is user-confirmed and no longer needs review.",
            }],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    report = MI.render_monthly_report(
        tmp_path,
        "2026-09",
        [candidate],
        {"imported": {"sources": 1, "events_added": 1}},
    )

    text = report.read_text(encoding="utf-8")
    assert "candidate_count: 0" in text
    assert "resolved_count: 1" in text
    assert "Calendar import is user-confirmed" in text


def test_daily_guard_runs_once_per_local_day(tmp_path):
    state = tmp_path / "state.json"
    assert MI.claim_daily_run(state, "2026-08-03") is True
    assert MI.claim_daily_run(state, "2026-08-03") is False
    assert MI.claim_daily_run(state, "2026-08-04") is True
    assert json.loads(state.read_text(encoding="utf-8"))["last_successful_day"] == "2026-08-04"
