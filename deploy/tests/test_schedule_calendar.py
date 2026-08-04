#!/usr/bin/env python3
"""Behavior tests for the deterministic STC launchd calendar export."""

import sys
import plistlib
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import schedule_calendar as SC  # noqa: E402


def test_generator_emits_one_daily_event_from_a_launchd_plist():
    calendar = SC.generate_ics(REPO / "deploy" / "launchd")

    assert calendar.startswith("BEGIN:VCALENDAR\r\n")
    assert "X-WR-TIMEZONE:Asia/Yerevan\r\n" in calendar
    assert "UID:stc-com.xtoshin.stc-memory-ingest@stc\r\n" in calendar
    assert "SUMMARY:STC Memory Ingest\r\n" in calendar
    assert "DTSTART;TZID=Asia/Yerevan:20260101T100000\r\n" in calendar
    assert "RRULE:FREQ=DAILY\r\n" in calendar
    assert "DESCRIPTION:Offline transcript ingest for the shared STC memory/Wiki.\r\n" in calendar
    assert "stc-ollama-serve" not in calendar


def test_generator_emits_monthly_event_for_a_day_of_month_schedule():
    calendar = SC.generate_ics(REPO / "deploy" / "launchd")

    assert "UID:stc-com.xtoshin.stc-infra-audit@stc\r\n" in calendar
    assert "SUMMARY:STC Infrastructure Audit\r\n" in calendar
    assert "DTSTART;TZID=Asia/Yerevan:20260101T100000\r\n" in calendar
    assert "RRULE:FREQ=MONTHLY;BYMONTHDAY=1\r\n" in calendar
    assert "DESCRIPTION:Harness-neutral\\, deterministic STC infrastructure audit.\r\n" in calendar


def test_weekly_audit_gets_a_follow_up_for_the_obsidian_report():
    with tempfile.TemporaryDirectory() as temporary:
        plist_dir = Path(temporary)
        plist = {
            "Label": "com.xtoshin.stc-weekly-audit",
            "Description": "Weekly STC infrastructure audit.",
            "StartCalendarInterval": {"Weekday": 1, "Hour": 9, "Minute": 0},
        }
        with (plist_dir / "com.xtoshin.stc-weekly-audit.plist").open("wb") as handle:
            plistlib.dump(plist, handle)

        calendar = SC.generate_ics(plist_dir)

    assert calendar.count("BEGIN:VEVENT\r\n") == 2
    assert "UID:stc-com.xtoshin.stc-weekly-audit@stc\r\n" in calendar
    assert "UID:stc-com.xtoshin.stc-weekly-audit-obsidian-review@stc\r\n" in calendar
    assert "DTSTART;TZID=Asia/Yerevan:20260105T090000\r\n" in calendar
    assert "DTSTART;TZID=Asia/Yerevan:20260105T093000\r\n" in calendar
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO\r\n" in calendar
    assert "SUMMARY:STC Weekly Audit: Review Obsidian Report\r\n" in calendar
    unfolded = calendar.replace("\r\n ", "")
    assert "If it is RED or WARN\\, decide whether a separate session is needed." in unfolded


def test_agentshield_scan_does_not_create_a_second_report_review_event():
    with tempfile.TemporaryDirectory() as temporary:
        plist_dir = Path(temporary)
        with (plist_dir / "agentshield.plist").open("wb") as handle:
            plistlib.dump(
                {
                    "Label": "com.xtoshin.stc-agentshield",
                    "Description": "Weekly AgentShield scan used by the main audit.",
                    "StartCalendarInterval": {"Weekday": 2, "Hour": 9, "Minute": 50},
                },
                handle,
            )

        calendar = SC.generate_ics(plist_dir)

    assert calendar.count("BEGIN:VEVENT\r\n") == 1
    assert "obsidian-review" not in calendar


def test_ollama_run_at_load_is_an_always_on_note_not_an_event():
    calendar = SC.generate_ics(REPO / "deploy" / "launchd")
    unfolded = calendar.replace("\r\n ", "")
    tasks = SC.read_tasks(REPO / "deploy" / "launchd")
    scheduled_count = sum(bool(task.schedules) for task in tasks)
    follow_up_count = sum(
        1
        for task in tasks
        for schedule in task.schedules
        if "Weekday" in schedule
        and any(
            marker in " ".join((task.label, task.source.stem)).lower()
            for marker in ("weekly-audit",)
        )
    )

    assert "UID:stc-com.xtoshin.stc-ollama-serve@stc\r\n" not in calendar
    assert calendar.count("BEGIN:VEVENT\r\n") == scheduled_count + follow_up_count
    assert (
        "X-STC-NOTE:STC Ollama Service is always-on\\; RunAtLoad and KeepAlive "
        "are intentionally excluded from timed events.\r\n"
    ) in unfolded


def test_cli_writes_one_idempotent_ics_to_output_path():
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "calendar" / "stc-scheduled.ics"
        plist_files = sorted((REPO / "deploy" / "launchd").glob("*.plist"))
        before = {path: path.read_bytes() for path in plist_files}
        command = [
            sys.executable,
            str(REPO / "core" / "scripts" / "schedule_calendar.py"),
            "--output",
            str(output),
        ]
        first_run = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        assert first_run.returncode == 0, first_run.stderr
        assert output.is_file(), "CLI did not create the requested output"
        first = output.read_bytes()
        second_run = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        assert second_run.returncode == 0, second_run.stderr
        second = output.read_bytes()
        after = {path: path.read_bytes() for path in plist_files}

    assert first == second
    assert first.startswith(b"BEGIN:VCALENDAR\r\n")
    assert before == after


def test_cli_refuses_to_use_a_launchd_plist_as_output():
    with tempfile.TemporaryDirectory() as temporary:
        plist_dir = Path(temporary) / "launchd"
        plist_dir.mkdir()
        plist_path = plist_dir / "task.plist"
        with plist_path.open("wb") as handle:
            plistlib.dump(
                {
                    "Label": "com.xtoshin.stc-task",
                    "StartCalendarInterval": {"Hour": 10, "Minute": 0},
                },
                handle,
            )
        before = plist_path.read_bytes()
        result = subprocess.run(
            [
                sys.executable,
                str(REPO / "core" / "scripts" / "schedule_calendar.py"),
                "--plist-dir",
                str(plist_dir),
                "--output",
                str(plist_path),
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        after = plist_path.read_bytes()

    assert result.returncode != 0
    assert after == before


if __name__ == "__main__":
    test_generator_emits_one_daily_event_from_a_launchd_plist()
    test_generator_emits_monthly_event_for_a_day_of_month_schedule()
    test_weekly_audit_gets_a_follow_up_for_the_obsidian_report()
    test_agentshield_scan_does_not_create_a_second_report_review_event()
    test_ollama_run_at_load_is_an_always_on_note_not_an_event()
    test_cli_writes_one_idempotent_ics_to_output_path()
    test_cli_refuses_to_use_a_launchd_plist_as_output()
    print("7 passed")
