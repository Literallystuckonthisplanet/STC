import json
import plistlib
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import weekly_audit as audit  # noqa: E402


EXPECTED_NAMES = {
    "deploy",
    "always/profile",
    "hooks contracts",
    "PEV/delegation/model/caveman/isolation",
    "skills/commands/MCP",
    "security/AgentShield",
    "memory/transcripts/ingest",
    "snapshots/Graphify",
    "DS",
    "TDD/docs-first/buy-vs-build",
    "review/QA/security/E2E",
    "token budget",
    "launchd",
    "docs/retired/upstream",
    "backup",
    "H22/H11",
    "usage matrix",
}


def test_run_audit_writes_stable_catalog_and_canonical_week_paths(tmp_path):
    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )

    assert result["status"] == "ok"
    assert Path(result["report"]).name == "weekly-2026-W32.md"
    assert Path(result["report"]).parent == tmp_path / "memory" / "reports" / "stc" / "2026-08"
    assert Path(result["latest_report"]).name == "latest.md"
    assert Path(result["json_report"]).name == "weekly-2026-W32.json"
    assert Path(result["latest_json"]).name == "latest.json"

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    assert payload["iso_week"] == "2026-W32"
    assert {item["name"] for item in payload["capabilities"]} == EXPECTED_NAMES
    assert all(
        item["code"] and item["description"] and item["status"] in audit.STATUSES
        for item in payload["capabilities"]
    )
    assert set(payload["counts"]) >= {"eligible", "invoked", "completed", "violations"}


def test_infra_machine_evidence_sets_status_and_is_redacted(tmp_path, monkeypatch):
    secret = "token=super-secret-value-123456789"

    def fake_run(*args, **kwargs):
        assert "infra_audit_local.py" in str(args[0])
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "checks": [
                    {"name": "deploy-precheck", "status": "fail", "details": [secret]},
                ],
            }),
            stderr="audit stderr " + secret,
        )

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    deploy = next(item for item in payload["capabilities"] if item["name"] == "deploy")
    assert deploy["status"] == "FAIL"
    assert deploy["invoked"] == 1
    assert deploy["completed"] == 1
    assert deploy["violations"] >= 1
    rendered = Path(result["report"]).read_text(encoding="utf-8") + json.dumps(payload)
    assert secret not in rendered
    assert "<REDACTED_SECRET>" in rendered


def test_transcript_evidence_is_read_only(tmp_path):
    corpus_root = tmp_path / "transcripts"
    corpus_root.mkdir()
    database = corpus_root / "sessions.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE events (event_key TEXT, searchable INTEGER)")
    connection.execute("INSERT INTO events VALUES ('event-1', 1)")
    connection.commit()
    connection.close()
    before = database.read_bytes()

    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=corpus_root,
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    memory = next(item for item in payload["capabilities"] if item["name"] == "memory/transcripts/ingest")
    assert memory["status"] == "PASS"
    assert any("events=1" in detail for detail in memory["details"])
    assert database.read_bytes() == before


def test_agentshield_result_file_is_optional_but_never_hides_findings(tmp_path):
    result_root = tmp_path / "agentshield"
    result_root.mkdir()
    (result_root / ".state.json").write_text(
        json.dumps({"verdict": "FAIL", "attempted_week": "2026-W32"}),
        encoding="utf-8",
    )
    (result_root / "baselines").mkdir()
    (result_root / "baselines" / "claude.json").write_text(
        json.dumps({"verdict": "PASS", "findings": []}),
        encoding="utf-8",
    )
    (result_root / "agentshield-result.json").write_text(
        json.dumps({"verdict": "FAIL", "findings": [{"severity": "high"}]}),
        encoding="utf-8",
    )

    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        agentshield_root=result_root,
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    security = next(item for item in payload["capabilities"] if item["name"] == "security/AgentShield")
    assert security["status"] == "FAIL"
    assert security["violations"] == 1
    assert any("findings=1" in detail for detail in security["details"])

    no_sample = audit.collect_agentshield_evidence(tmp_path / "missing-agentshield")
    assert no_sample["status"] == "NO_SAMPLE"


def test_always_profile_contract_is_checked_from_source(tmp_path):
    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    always = next(item for item in payload["capabilities"] if item["name"] == "always/profile")
    assert always["status"] == "PASS"
    assert "core/rules/session.md" in " ".join(always["evidence"])


def test_weekly_guard_is_idempotent_by_iso_week_and_force_bypasses_it(tmp_path):
    kwargs = {
        "repo": REPO,
        "memory_root": tmp_path / "memory",
        "corpus_root": tmp_path / "transcripts",
        "as_of": date(2026, 8, 4),
        "no_model": True,
    }
    first = audit.run_audit(**kwargs)
    second = audit.run_audit(**kwargs)
    forced = audit.run_audit(**kwargs, force=True)

    assert first["status"] == "ok"
    assert second["status"] == "skipped"
    assert second["reason"] == "already-ran-this-iso-week"
    assert forced["status"] == "ok"
    state = json.loads((tmp_path / "memory" / "weekly-audit" / "state.json").read_text())
    assert state["last_successful_week"] == "2026-W32"


def test_launchd_evidence_reads_state_and_logs_without_raw_log_content(tmp_path):
    launchd_root = tmp_path / "launchd"
    launchd_root.mkdir()
    (launchd_root / "state.json").write_text(
        json.dumps({"last_successful_week": "2026-W32", "status": "ok"}),
        encoding="utf-8",
    )
    (launchd_root / "launchd.stdout.log").write_text(
        "weekly audit completed\nprivate-token=super-secret-value-123456789\n",
        encoding="utf-8",
    )
    before = (launchd_root / "launchd.stdout.log").read_bytes()

    evidence = audit.collect_launchd_evidence(launchd_root, "2026-W32")

    assert evidence["status"] == "PASS"
    assert any("last_successful_week=2026-W32" in detail for detail in evidence["details"])
    assert evidence["log_errors"] == 0
    assert "super-secret-value" not in json.dumps(evidence)
    assert (launchd_root / "launchd.stdout.log").read_bytes() == before


def test_qwen_summarizer_is_schema_constrained_and_degrades_after_two_attempts(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"message": {"content": "not-json"}}'

    def fake_urlopen(request, timeout):
        calls.append((json.loads(request.data.decode("utf-8")), timeout))
        return FakeResponse()

    monkeypatch.setattr(audit.urllib.request, "urlopen", fake_urlopen)
    result = audit.summarize_with_ollama(
        {"iso_week": "2026-W32", "capabilities": []},
        endpoint="http://127.0.0.1:11434/api/chat",
        opener=fake_urlopen,
    )

    assert result["degraded"] is True
    assert result["attempts"] == 2
    assert len(calls) == 2
    assert calls[0][1] == 45  # enough for a cold local 4B model load
    body = calls[0][0]
    assert body["model"] == "qwen3:4b"
    assert body["think"] is False
    assert body["options"]["temperature"] == 0
    assert body["format"]["type"] == "object"


def test_graphify_evidence_is_deterministic_and_read_only(tmp_path):
    graph = tmp_path / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text(
        json.dumps({"nodes": [{"id": "n1"}], "links": []}),
        encoding="utf-8",
    )
    before = graph.read_bytes()

    evidence = audit.collect_graphify_evidence(tmp_path)

    assert evidence["status"] == "PASS"
    assert evidence["nodes"] == 1
    assert evidence["links"] == 0
    assert graph.read_bytes() == before


def test_weekly_launchd_plist_runs_at_load_and_monday_1030():
    plist = (REPO / "deploy" / "launchd" / "com.xtoshin.stc-weekly-audit.plist").read_bytes()
    payload = plistlib.loads(plist)

    assert payload["Label"] == "com.xtoshin.stc-weekly-audit"
    assert payload["RunAtLoad"] is True
    assert payload["StartCalendarInterval"] == {"Weekday": 1, "Hour": 10, "Minute": 30}


def test_weekly_launchd_plist_passes_real_machine_evidence_roots():
    plist = (REPO / "deploy" / "launchd" / "com.xtoshin.stc-weekly-audit.plist").read_bytes()
    payload = plistlib.loads(plist)
    args = payload["ProgramArguments"]

    assert "/Users/xtoshin/Work/STC/core/scripts/weekly_audit.py" in args
    assert "--agentshield-root" in args
    assert args[args.index("--agentshield-root") + 1] == "/Users/xtoshin/Work/memory/infra-audit/agentshield"
    assert "--launchd-root" in args
    assert args[args.index("--launchd-root") + 1] == "/Users/xtoshin/Work/memory"
    assert "--force" not in args


def test_public_cli_can_render_markdown_and_json_skip(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        audit,
        "collect_infra_audit",
        lambda _repo: {
            "status": "PASS",
            "invoked": 1,
            "completed": 1,
            "checks": [{"name": "deploy-precheck", "status": "PASS", "details": []}],
            "details": ["checks=1", "returncode=0"],
        },
    )
    args = [
        "--repo", str(REPO),
        "--memory-root", str(tmp_path / "memory"),
        "--corpus-root", str(tmp_path / "transcripts"),
        "--as-of", "2026-08-04",
        "--no-model",
        "--format", "markdown",
    ]
    assert audit.main(args) == 0
    assert capsys.readouterr().out.startswith("# STC weekly offline audit")

    args[-1] = "json"
    assert audit.main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "skipped"
    assert output["reason"] == "already-ran-this-iso-week"


def test_catalog_reports_all_source_backed_blocks_and_aggregate_counts(tmp_path):
    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        as_of=date(2026, 8, 4),
        force=True,
        no_model=True,
    )
    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in payload["capabilities"]}

    for name in EXPECTED_NAMES - {"security/AgentShield", "memory/transcripts/ingest"}:
        assert by_name[name]["status"] in {"PASS", "WARN", "FAIL"}
    assert by_name["security/AgentShield"]["status"] == "NO_SAMPLE"
    assert by_name["memory/transcripts/ingest"]["status"] == "NO_SAMPLE"
    assert payload["counts"]["eligible"] == sum(item["eligible"] for item in payload["capabilities"])
    assert payload["counts"]["violations"] == sum(item["violations"] for item in payload["capabilities"])


def test_model_summary_cannot_downgrade_deterministic_findings(tmp_path, monkeypatch):
    shield_root = tmp_path / "agentshield"
    shield_root.mkdir()
    (shield_root / "result.json").write_text(
        json.dumps({"verdict": "FAIL", "findings": [{"severity": "critical"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        audit,
        "summarize_with_ollama",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "model": "qwen3:4b",
            "attempts": 1,
            "degraded": False,
            "summary": "Все проверки PASS.",
            "highlights": [],
            "next_steps": [],
        },
    )

    result = audit.run_audit(
        repo=REPO,
        memory_root=tmp_path / "memory",
        corpus_root=tmp_path / "transcripts",
        agentshield_root=shield_root,
        as_of=date(2026, 8, 4),
        force=True,
    )

    payload = json.loads(Path(result["json_report"]).read_text(encoding="utf-8"))
    security = next(item for item in payload["capabilities"] if item["name"] == "security/AgentShield")
    assert security["status"] == "FAIL"
    assert payload["verdict"] == "FAIL"
    assert payload["model"]["summary"] == "Все проверки PASS."
