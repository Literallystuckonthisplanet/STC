# STC scheduled-task calendar

`core/scripts/schedule_calendar.py` exports every calendar-backed launchd job
from `deploy/launchd/*.plist` as one deterministic `.ics` file. It reads the
plists and the referenced Python module docstrings for human-readable names and
descriptions; it does not edit plists and does not import Calendar.

Generate an export outside the repository so the generated file does not
become source data:

```sh
python3 core/scripts/schedule_calendar.py \
  --output ~/Work/memory/stc-scheduled-tasks.ics
```

For a fixture or another launchd directory, pass `--plist-dir` explicitly.
The same inputs always produce the same bytes: the export uses the fixed
`Asia/Yerevan` timezone, stable UIDs, and a fixed recurrence anchor rather
than the current date or time.

The launchd calendar fields map as follows:

- `Hour`/`Minute` → a daily event;
- `Weekday` → a weekly event (`0` and `7` mean Sunday, `1` means Monday);
- `Day` → a monthly event on that day of the month.

`RunAtLoad` is not a second calendar occurrence. A plist with `RunAtLoad` and
`KeepAlive` but no `StartCalendarInterval` is represented as an always-on
calendar note. This is how the Ollama service is shown. A weekly audit also
gets a separate 30-minute follow-up event to check the Obsidian report and
decide whether a separate session is needed when the report is `RED` or
`WARN`.
