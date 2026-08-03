import json
import sqlite3
import sys
from pathlib import Path

from importlib.util import module_from_spec, spec_from_file_location


SCRIPT = Path(__file__).parents[2] / "core" / "scripts" / "transcript_corpus.py"
SPEC = spec_from_file_location("transcript_corpus", SCRIPT)
TC = module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["transcript_corpus"] = TC
SPEC.loader.exec_module(TC)


def _write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(x) for x in records) + "\n", encoding="utf-8")


def _db(root):
    db = sqlite3.connect(root / "sessions.sqlite")
    db.row_factory = sqlite3.Row
    return db


def test_discover_sources_is_harness_scoped(tmp_path):
    home = tmp_path / "home"
    _write(home / ".claude/projects/p/a.jsonl", [])
    _write(home / ".codex/archived_sessions/a.jsonl", [])
    _write(home / ".zcode/cli/agents/sess/agent/transcript.jsonl", [])
    sources = TC.discover_sources(home)
    assert [(s.harness, s.path.name) for s in sources] == [
        ("claude", "a.jsonl"), ("codex", "a.jsonl"), ("zcode", "transcript.jsonl")
    ]


def test_import_normalizes_three_harnesses_and_keeps_lineage(tmp_path):
    src = tmp_path / "sources"
    claude = src / "claude.jsonl"
    codex = src / "codex.jsonl"
    zcode = src / "zcode.jsonl"
    _write(claude, [{"type": "user", "uuid": "c1", "sessionId": "cs",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "hello"}}])
    _write(codex, [{"type": "session_meta", "payload": {"session_id": "xs", "cwd": "/Work/q"}},
                    {"type": "response_item", "payload": {"type": "user_message", "id": "x1", "content": "question"}}])
    _write(zcode, [{"id": "z1", "sessionId": "zs", "type": "turn_started",
                    "timestamp": "2026-01-01T00:00:00Z", "payload": {"input": "prompt"}},
                   {"id": "z2", "sessionId": "zs", "type": "model_complete",
                    "timestamp": "2026-01-01T00:01:00Z", "payload": {"content": "answer"}}])

    root = tmp_path / "transcripts"
    stats = TC.import_sources([
        TC.Source("claude", claude), TC.Source("codex", codex), TC.Source("zcode", zcode)
    ], root)
    assert stats["events_added"] == 4
    db = _db(root)
    try:
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4
        refs = [r[0] for r in db.execute("SELECT raw_ref FROM events")]
        assert all(":" in ref for ref in refs)
        assert {r[0] for r in db.execute("SELECT DISTINCT harness FROM events")} == {"claude", "codex", "zcode"}
    finally:
        db.close()


def test_import_is_idempotent_and_searchable(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "c1", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "unique needle"}}])
    root = tmp_path / "transcripts"
    spec = [TC.Source("claude", source)]
    first = TC.import_sources(spec, root)
    second = TC.import_sources(spec, root)
    assert first["events_added"] == 1
    assert second["events_added"] == 0
    assert second["duplicates"] == 1
    assert TC.search(root, "needle", project="/Work/p")[0]["text"] == "unique needle"


def test_search_excludes_harness_envelope_but_show_keeps_it(tmp_path):
    source = tmp_path / "codex.jsonl"
    _write(source, [
        {"type": "session_meta", "payload": {"session_id": "s", "cwd": "/Work/p"}},
        {"type": "response_item", "payload": {
            "type": "user_message", "id": "noise", "content": "<app-context> needle"
        }},
        {"type": "response_item", "payload": {
            "type": "user_message", "id": "real", "content": "real needle"
        }},
    ])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("codex", source)], root)
    results = TC.search(root, "needle")
    assert [row["text"] for row in results] == ["real needle"]
    session_key = results[0]["session_key"]
    shown = TC.show(root, session_key)
    assert {row["text"] for row in shown} == {"<app-context> needle", "real needle"}
