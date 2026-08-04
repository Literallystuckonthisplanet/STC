import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "core" / "scripts" / "agentshield_scan.py"
PLIST = Path(__file__).resolve().parents[1] / "launchd" / "com.xtoshin.stc-agentshield.plist"
SPEC = importlib.util.spec_from_file_location("agentshield_scan", SCRIPT)
SCAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCAN)


def test_scan_command_is_static_pinned_and_never_auto_fixes(tmp_path):
    command = SCAN.build_scan_command(
        Path("/opt/agentshield"),
        tmp_path / ".codex",
        baseline=tmp_path / "baseline.json",
    )

    assert command[:2] == ["/opt/agentshield", "scan"]
    assert command[command.index("--path") + 1] == str(tmp_path / ".codex")
    assert command[command.index("--format") + 1] == "json"
    assert "--supply-chain" in command
    assert "--baseline" in command and "--gate" in command
    for forbidden in ("--fix", "--opus", "--deep", "--supply-chain-online"):
        assert forbidden not in command


def test_sanitize_keeps_triage_fields_but_drops_raw_evidence():
    raw = {
        "score": {"grade": "C", "numericScore": 66},
        "findings": [
            {
                "id": "HOOK-1",
                "title": "Unsafe hook",
                "severity": "high",
                "category": "hooks",
                "runtimeConfidence": "active",
                "evidence": "SECRET=must-not-survive",
                "file": "/private/path/settings.json",
            }
        ],
    }

    result = SCAN.sanitize_result("codex", raw, returncode=0)

    assert result["score"] == {"grade": "C", "numericScore": 66}
    assert result["findings"] == [{
        "id": "HOOK-1",
        "title": "Unsafe hook",
        "severity": "high",
        "category": "hooks",
        "runtimeConfidence": "active",
    }]
    assert "SECRET" not in str(result)
    assert "/private/path" not in str(result)


def test_aggregate_fails_on_high_finding_and_guards_iso_week():
    aggregate = SCAN.aggregate([
        {"target": "claude", "status": "ok", "findings": []},
        {
            "target": "codex",
            "status": "ok",
            "findings": [{"id": "X", "severity": "high"}],
        },
    ])
    assert aggregate["verdict"] == "FAIL"
    assert aggregate["summary"]["high"] == 1


def test_agentshield_runs_before_monday_weekly_audit():
    import plistlib

    schedule = plistlib.loads(PLIST.read_bytes())["StartCalendarInterval"]
    assert schedule == {"Weekday": 1, "Hour": 9, "Minute": 50}
