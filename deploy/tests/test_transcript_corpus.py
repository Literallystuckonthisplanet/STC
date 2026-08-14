import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_fresh_sidecar_search_is_ranked_and_scoped_to_project(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [
        {"type": "user", "uuid": "alpha-1", "sessionId": "alpha",
         "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/alpha",
         "message": {"role": "user", "content": "русский индекс"}},
        {"type": "user", "uuid": "beta-1", "sessionId": "beta",
         "timestamp": "2026-01-01T00:01:00Z", "cwd": "/Work/beta",
         "message": {"role": "user", "content": "русский индекс чужого проекта"}},
        {"type": "user", "uuid": "alpha-2", "sessionId": "alpha",
         "timestamp": "2026-01-01T00:02:00Z", "cwd": "/Work/alpha",
         "message": {"role": "user", "content": "английский search index"}},
        {"type": "user", "uuid": "alpha-secret", "sessionId": "secret",
         "timestamp": "2026-01-01T00:03:00Z", "cwd": "/Work/alpha-secret",
         "message": {"role": "user", "content": "русский индекс утечка"}},
    ])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)

    built = TC.rebuild_search_index(root)
    result = TC.search_with_status(root, "индекс", project="/Work/alpha")
    english = TC.search_with_status(root, "index", project="/Work/alpha")

    assert built["status"] == "ok"
    assert result["index_status"] == "fresh"
    assert result["used_fallback"] is False
    assert [row["cwd"] for row in result["results"]] == ["/Work/alpha"]
    assert [row["cwd"] for row in english["results"]] == ["/Work/alpha"]
    assert all("score" in row for row in result["results"])


def test_search_limit_is_bounded_and_wildcard_project_does_not_broaden_scope(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "bounded needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)

    with pytest.raises(ValueError, match="limit"):
        TC.search(root, "needle", limit=-1)
    result = TC.search_with_status(root, "needle", project="%")

    assert result["results"] == []


def test_fts_prefix_search_preserves_baseline_substring_recall(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "atomically published"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)

    result = TC.search_with_status(root, "atomic")

    assert result["index_status"] == "fresh"
    assert [row["text"] for row in result["results"]] == ["atomically published"]


def test_punctuation_queries_use_baseline_literal_semantics(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [
        {"type": "user", "uuid": "quoted", "sessionId": "s",
         "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": 'a "quoted" marker'}},
        {"type": "user", "uuid": "plain", "sessionId": "s",
         "timestamp": "2026-01-01T00:01:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": "a quoted plain marker"}},
        {"type": "user", "uuid": "star", "sessionId": "s",
         "timestamp": "2026-01-01T00:02:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": "alpha * beta"}},
        {"type": "user", "uuid": "no-star", "sessionId": "s",
         "timestamp": "2026-01-01T00:03:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": "alpha beta"}},
    ])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)

    quoted = TC.search_with_status(root, '"quoted"')
    starred = TC.search_with_status(root, "alpha * beta")

    assert quoted["used_fallback"] is True
    assert [row["text"] for row in quoted["results"]] == ['a "quoted" marker']
    assert starred["used_fallback"] is True
    assert [row["text"] for row in starred["results"]] == ["alpha * beta"]


def test_stale_sidecar_reports_lag_and_uses_authoritative_baseline(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "before", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "before needle"}}])
    root = tmp_path / "transcripts"
    spec = [TC.Source("claude", source)]
    TC.import_sources(spec, root)
    TC.rebuild_search_index(root)

    _write(source, [
        {"type": "user", "uuid": "before", "sessionId": "s",
         "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": "before needle"}},
        {"type": "user", "uuid": "after", "sessionId": "s",
         "timestamp": "2026-01-01T00:01:00Z", "cwd": "/Work/p",
         "message": {"role": "user", "content": "after needle"}},
    ])
    TC.import_sources(spec, root)

    result = TC.search_with_status(root, "after")

    assert result["index_status"] in {"stale", "lagging"}
    assert result["used_fallback"] is True
    assert [row["text"] for row in result["results"]] == ["after needle"]


def test_rebuild_is_read_only_for_source_and_failed_attempt_keeps_previous_index(tmp_path, monkeypatch):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "one needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    database = root / "sessions.sqlite"
    before = database.stat()
    built = TC.rebuild_search_index(root)
    after = database.stat()
    index = root / "sessions.fts5.sqlite"
    original_index = index.read_bytes()

    assert after.st_mtime_ns == before.st_mtime_ns
    assert built["source_watermark"]["fingerprint"] == built["index_watermark"]["fingerprint"]
    connection = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM events_fts")
    finally:
        connection.close()

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("fixture build failure")

    monkeypatch.setattr(TC, "_build_search_index", fail_build)
    with pytest.raises(RuntimeError, match="fixture build failure"):
        TC.rebuild_search_index(root)

    assert index.read_bytes() == original_index
    assert TC.search_index_status(root)["failed_rebuilds"] == 1
    assert not list(root.glob("sessions.fts5.sqlite.*.tmp"))


def test_interrupted_rebuild_keeps_previous_index_and_cleans_temp_file(tmp_path, monkeypatch):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "one needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)
    index = root / "sessions.fts5.sqlite"
    original_index = index.read_bytes()

    def interrupt_build(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(TC, "_build_search_index", interrupt_build)
    with pytest.raises(KeyboardInterrupt):
        TC.rebuild_search_index(root)

    assert index.read_bytes() == original_index
    assert TC.search_index_status(root)["failed_rebuilds"] == 1
    assert not list(root.glob("sessions.fts5.sqlite.*.tmp"))


def test_corrupt_sidecar_is_not_served_and_search_falls_back(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "recoverable needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)
    (root / "sessions.fts5.sqlite").write_bytes(b"not a sqlite database")

    result = TC.search_with_status(root, "recoverable")

    assert result["index_status"] == "corrupt"
    assert result["used_fallback"] is True
    assert [row["text"] for row in result["results"]] == ["recoverable needle"]


def test_atomic_publish_failure_keeps_the_last_good_sidecar(tmp_path, monkeypatch):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "stable needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)
    index = root / "sessions.fts5.sqlite"
    original_index = index.read_bytes()
    real_replace = TC.os.replace

    def fail_publish(source_path, destination):
        if Path(destination) == index:
            raise OSError("fixture publish interruption")
        return real_replace(source_path, destination)

    monkeypatch.setattr(TC.os, "replace", fail_publish)
    with pytest.raises(OSError, match="fixture publish interruption"):
        TC.rebuild_search_index(root)

    assert index.read_bytes() == original_index
    assert TC.search_index_status(root)["failed_rebuilds"] == 1
    assert not list(root.glob("sessions.fts5.sqlite.*.tmp"))


def test_cli_search_emits_status_and_results_as_json(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [{"type": "user", "uuid": "one", "sessionId": "s",
                     "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Work/p",
                     "message": {"role": "user", "content": "cli needle"}}])
    root = tmp_path / "transcripts"
    TC.import_sources([TC.Source("claude", source)], root)
    TC.rebuild_search_index(root)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "search", "needle"],
        cwd=SCRIPT.parents[2], capture_output=True, text=True, check=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["index_status"] == "fresh"
    assert payload["used_fallback"] is False
    assert payload["results"][0]["text"] == "cli needle"
