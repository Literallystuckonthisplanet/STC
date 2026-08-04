#!/usr/bin/env python3
"""Export STC launchd schedules as one deterministic iCalendar file.

The generator reads only ``deploy/launchd/*.plist`` and the referenced Python
module docstrings.  It never imports or edits Calendar, launchd files, or the
scheduled programs themselves.
"""

from __future__ import annotations

import argparse
import ast
import plistlib
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable


TIMEZONE = "Asia/Yerevan"
ANCHOR_DATE = date(2026, 1, 1)
EVENT_DURATION = timedelta(minutes=30)
DTSTAMP = "20260101T000000Z"
FOLLOW_UP_SUMMARY = "STC Weekly Audit: Review Obsidian Report"
FOLLOW_UP_DESCRIPTION = (
    "After the weekly audit, check the Obsidian report. If it is RED or WARN, "
    "decide whether a separate session is needed."
)

_LABEL_PREFIX = "com.xtoshin.stc-"
_HUMAN_WORDS = {
    "graphify": "Graphify",
    "infra": "Infrastructure",
    "memory": "Memory",
    "ingest": "Ingest",
    "ollama": "Ollama",
    "project": "Project",
    "snapshot": "Snapshot",
    "maintenance": "Maintenance",
    "audit": "Audit",
    "serve": "Service",
}
_WEEKDAY_NAMES = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")


@dataclass(frozen=True)
class ScheduledTask:
    """The stable, human-facing data extracted from one launchd plist."""

    label: str
    name: str
    description: str
    schedules: tuple[dict[str, Any], ...]
    source: Path
    always_on: bool


@dataclass(frozen=True)
class CalendarEvent:
    """One recurring event before it is rendered as iCalendar text."""

    uid: str
    summary: str
    description: str
    start: datetime
    rrule: str


def humanize_label(label: str) -> str:
    """Turn an STC launchd label into a predictable human-readable name."""

    suffix = label[len(_LABEL_PREFIX):] if label.startswith(_LABEL_PREFIX) else label
    words = []
    for word in re.split(r"[-_.]+", suffix):
        if not word:
            continue
        words.append(_HUMAN_WORDS.get(word.lower(), word.capitalize()))
    return "STC " + " ".join(words) if words else "STC Scheduled Task"


def _calendar_schedules(value: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(value, dict):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, dict))
    return ()


def _script_path(program_arguments: Any, plist_path: Path) -> Path | None:
    if not isinstance(program_arguments, list):
        return None
    repo_root = plist_path.parents[2]
    for argument in program_arguments:
        if not isinstance(argument, str) or not argument.endswith(".py"):
            continue
        candidate = Path(argument).expanduser()
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        if candidate.is_file():
            return candidate
    return None


def _module_description(script: Path | None) -> str | None:
    if script is None:
        return None
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    except (OSError, SyntaxError, UnicodeError):
        return None
    docstring = ast.get_docstring(tree, clean=True)
    if not docstring:
        return None
    return " ".join(docstring.split("\n\n", 1)[0].split())


def _description(plist: dict[str, Any], plist_path: Path) -> str:
    explicit = plist.get("Description")
    if isinstance(explicit, str) and explicit.strip():
        return " ".join(explicit.split())

    from_script = _module_description(_script_path(plist.get("ProgramArguments"), plist_path))
    if from_script:
        return from_script

    name = humanize_label(str(plist.get("Label", "STC scheduled task")))
    if "ollama" in name.lower():
        return "Always-on Ollama service for local STC processing."
    return f"Scheduled {name} task."


def read_tasks(plist_dir: Path | str) -> tuple[ScheduledTask, ...]:
    """Read and normalize all launchd plists in a directory, in stable order."""

    directory = Path(plist_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"launchd directory does not exist: {directory}")

    tasks = []
    for plist_path in sorted(directory.glob("*.plist")):
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
        label = plist.get("Label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"plist has no usable Label: {plist_path}")
        tasks.append(
            ScheduledTask(
                label=label,
                name=humanize_label(label),
                description=_description(plist, plist_path),
                schedules=_calendar_schedules(plist.get("StartCalendarInterval")),
                source=plist_path,
                always_on=bool(plist.get("RunAtLoad") and plist.get("KeepAlive")),
            )
        )
    return tuple(tasks)


def _integer(schedule: dict[str, Any], key: str, default: int) -> int:
    value = schedule.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"StartCalendarInterval {key} must be an integer")
    return value


def _validate_time(schedule: dict[str, Any]) -> tuple[int, int]:
    hour = _integer(schedule, "Hour", 0)
    minute = _integer(schedule, "Minute", 0)
    if not 0 <= hour <= 23:
        raise ValueError(f"StartCalendarInterval Hour is out of range: {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"StartCalendarInterval Minute is out of range: {minute}")
    return hour, minute


def _frequency(schedule: dict[str, Any]) -> str:
    if "Weekday" in schedule:
        return "weekly"
    if "Day" in schedule:
        return "monthly"
    return "daily"


def _weekly_anchor(weekday: int) -> date:
    if weekday == 7:
        weekday = 0
    if not 0 <= weekday <= 6:
        raise ValueError(f"StartCalendarInterval Weekday is out of range: {weekday}")
    python_weekday = 6 if weekday == 0 else weekday - 1
    offset = (python_weekday - ANCHOR_DATE.weekday()) % 7
    return ANCHOR_DATE + timedelta(days=offset)


def _start_and_rule(schedule: dict[str, Any]) -> tuple[datetime, str]:
    hour, minute = _validate_time(schedule)
    if _frequency(schedule) == "weekly":
        weekday = _integer(schedule, "Weekday", 0)
        normalized_weekday = 0 if weekday == 7 else weekday
        start_date = _weekly_anchor(weekday)
        return datetime.combine(start_date, time(hour, minute)), (
            f"FREQ=WEEKLY;BYDAY={_WEEKDAY_NAMES[normalized_weekday]}"
        )
    if _frequency(schedule) == "monthly":
        day = _integer(schedule, "Day", 1)
        if not 1 <= day <= 31:
            raise ValueError(f"StartCalendarInterval Day is out of range: {day}")
        start_date = date(ANCHOR_DATE.year, ANCHOR_DATE.month, day)
        return datetime.combine(start_date, time(hour, minute)), (
            f"FREQ=MONTHLY;BYMONTHDAY={day}"
        )
    return datetime.combine(ANCHOR_DATE, time(hour, minute)), "FREQ=DAILY"


def _safe_uid_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")


def _uid(label: str, schedule_index: int, suffix: str = "") -> str:
    part = _safe_uid_part(label)
    if schedule_index:
        part += f"-{schedule_index + 1}"
    if suffix:
        part += f"-{suffix}"
    return f"stc-{part}@stc"


def _event_for(task: ScheduledTask, schedule: dict[str, Any], index: int) -> CalendarEvent:
    start, rrule = _start_and_rule(schedule)
    return CalendarEvent(
        uid=_uid(task.label, index),
        summary=task.name,
        description=task.description,
        start=start,
        rrule=rrule,
    )


def _is_weekly_audit(task: ScheduledTask, schedule: dict[str, Any]) -> bool:
    if _frequency(schedule) != "weekly":
        return False
    # Only the report-producing weekly audit gets a review reminder. Supporting
    # weekly inputs such as AgentShield are intentionally excluded, otherwise
    # Calendar would show several duplicate "review the report" events.
    markers = " ".join((task.label, task.source.stem)).lower()
    return "weekly-audit" in markers


def _follow_up(task: ScheduledTask, schedule: dict[str, Any], index: int) -> CalendarEvent:
    start, rrule = _start_and_rule(schedule)
    return CalendarEvent(
        uid=_uid(task.label, index, "obsidian-review"),
        summary=FOLLOW_UP_SUMMARY,
        description=FOLLOW_UP_DESCRIPTION,
        start=start + EVENT_DURATION,
        rrule=rrule,
    )


def _escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _fold_line(line: str, limit: int = 75) -> str:
    """Fold an iCalendar content line without splitting a UTF-8 character."""

    pieces = []
    current = ""
    for character in line:
        candidate = current + character
        if current and len(candidate.encode("utf-8")) > limit:
            pieces.append(current)
            current = " " + character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return "\r\n".join(pieces)


def _render_event(event: CalendarEvent) -> list[str]:
    start = event.start.strftime("%Y%m%dT%H%M%S")
    return [
        "BEGIN:VEVENT",
        f"UID:{event.uid}",
        f"DTSTAMP:{DTSTAMP}",
        f"DTSTART;TZID={TIMEZONE}:{start}",
        "DURATION:PT30M",
        f"RRULE:{event.rrule}",
        f"SUMMARY:{_escape_text(event.summary)}",
        f"DESCRIPTION:{_escape_text(event.description)}",
        "END:VEVENT",
    ]


def generate_ics(plist_dir: Path | str) -> str:
    """Return one deterministic iCalendar export for all scheduled STC tasks."""

    events: list[CalendarEvent] = []
    notes: list[str] = []
    for task in read_tasks(plist_dir):
        if not task.schedules:
            if task.always_on:
                notes.append(
                    f"{task.name} is always-on; RunAtLoad and KeepAlive are intentionally "
                    "excluded from timed events."
                )
            continue
        for index, schedule in enumerate(task.schedules):
            events.append(_event_for(task, schedule, index))
            if _is_weekly_audit(task, schedule):
                events.append(_follow_up(task, schedule, index))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//STC//Scheduled Tasks//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:STC Scheduled Tasks",
        f"X-WR-TIMEZONE:{TIMEZONE}",
    ]
    lines.extend(f"X-STC-NOTE:{_escape_text(note)}" for note in sorted(set(notes)))
    for event in sorted(events, key=lambda item: (item.start, item.uid)):
        lines.extend(_render_event(event))
    lines.extend(("END:VCALENDAR",))
    return "\r\n".join(_fold_line(line) for line in lines) + "\r\n"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plist-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "deploy" / "launchd",
        help="directory containing launchd plist files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="path for the generated .ics file",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    plist_dir = args.plist_dir.expanduser().resolve()
    output = args.output.expanduser().resolve()
    input_plists = {path.resolve() for path in plist_dir.glob("*.plist")}
    if output in input_plists:
        parser.error("--output must not overwrite a launchd plist")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_ics(plist_dir), encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
