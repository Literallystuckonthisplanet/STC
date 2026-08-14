#!/usr/bin/env python3
"""Здоровье хуков: сколько раз каждый сработал и сколько раз это ничего не изменило.

Телеметрию в сами хуки писать не нужно — каждое срабатывание уже лежит в
транскрипте. Блокирующее приходит как `tool_result` с текстом
`PreToolUse:<Tool> hook error: [<файл хука>]: …`, ненавязчивое — как
attachment с полем `hookName`. Скрипт восстанавливает срабатывания оттуда,
ровно тем же приёмом, каким `prompt-audit.py:rule_health` восстанавливает
срабатывания линзы, прогоняя её правила по корпусу.

Три вопроса, на которые отвечает вывод:

* **мёртвый** — ни одного срабатывания за окно; правило есть, повода нет.
  Считается ТОЛЬКО для хуков, умеющих блокировать (`exit 2`): тихий хук
  оставляет след не всегда и попал бы в мёртвые ошибочно;
* **слепой повтор** — агент повторил ТОТ ЖЕ вызов, не сказав между делом ни
  слова. Блокировка одноразовая, поэтому повтор проходит; молчаливый повтор
  и есть «advisory ≠ enforcement» из `reference_defect_ledger.md`;
* **осознанный повтор** — тот же вызов, но между блокировкой и повтором агент
  что-то написал или сделал. Для acknowledge-once хуков это ШТАТНЫЙ выход
  («нужен именно точный поиск — повтори вызов»), а не игнор. Не смешивать:
  первая версия этого скрипта смешивала и записала в игнор соблюдение правил.

Читает `~/Work/transcripts/raw` (полный корпус), а НЕ `~/.claude/projects`:
харнесс подрезает свой каталог примерно до 40 дней, и счёт по нему молча
занижен — та же ловушка, что чинили в `collect_corpus.py` 2026-08-12.

Использование:
    python3 core/scripts/hook_health.py [--since 2026-07-01] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAW_DEFAULT = Path.home() / "Work" / "transcripts" / "raw"

# «PreToolUse:Bash hook error: [/…/graphify-first.stc.sh]: 🔎 graphify-first (H18): …»
RE_BLOCKING = re.compile(
    r"PreToolUse:(?P<tool>\w+) hook error: \[(?P<path>[^\]]+)\]:\s*(?P<msg>.*)",
    re.S,
)
RE_CODE = re.compile(r"\b(H\d{2})\b")


def _hook_name(path: str) -> str:
    """`/…/graphify-first.stc.sh` → `graphify-first`."""
    return Path(path).name.replace(".stc.sh", "").replace(".sh", "")


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _texts(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                for key in ("text", "content"):
                    v = part.get(key)
                    if isinstance(v, str):
                        out.append(v)
                    elif isinstance(v, list):
                        out.extend(x for x in v if isinstance(x, str))
        return out
    return []


def scan_session(path: Path, since: datetime | None):
    """Отдаёт события сессии по порядку: вызовы инструментов и срабатывания хуков.

    Вызовы нужны, чтобы ответить на главный вопрос — повторил ли агент ровно
    тот же вызов после блокировки. Без них видно только «сработало», а это та
    самая четвёртая ступень, которой недостаточно.
    """
    events = []
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return events
    with fh:
        for line in fh:
            # Быстрый отсев. `"text"` обязателен: реплика, где агент только
            # говорит и ничего не вызывает, — единственное, что отличает
            # осознанный повтор от слепого. Без неё соблюдение правила
            # считалось бы нарушением.
            if not any(k in line for k in ('"PreToolUse', '"tool_use"', '"hookName"', '"text"')):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(obj.get("timestamp"))
            if since and ts and ts < since:
                continue

            # ненавязчивая подсказка: attachment с hookName
            hook_name = obj.get("hookName") or (obj.get("attachment") or {}).get("hookName")
            if isinstance(hook_name, str) and hook_name.startswith("PreToolUse"):
                events.append({"kind": "advice", "tool": hook_name.split(":")[-1],
                               "hook": None, "code": None, "ts": ts})

            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")

            # вызов инструмента — запоминаем чем именно, чтобы поймать повтор;
            # текст ассистента — чтобы отличить осознанный повтор от слепого
            if msg.get("role") == "assistant" and isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "tool_use":
                        events.append({
                            "kind": "call",
                            "tool": part.get("name"),
                            "sig": json.dumps(part.get("input"), sort_keys=True,
                                              ensure_ascii=False)[:600],
                            "ts": ts,
                        })
                    elif part.get("type") == "text" and (part.get("text") or "").strip():
                        events.append({"kind": "said", "ts": ts})

            # блокировка — приходит пользователю как tool_result
            for text in _texts(content):
                if "hook error" not in text:
                    continue
                m = RE_BLOCKING.search(text)
                if not m:
                    continue
                code = RE_CODE.search(m.group("msg"))
                events.append({
                    "kind": "block",
                    "tool": m.group("tool"),
                    "hook": _hook_name(m.group("path")),
                    "code": code.group(1) if code else None,
                    "ts": ts,
                })
    return events


def health(raw_root: Path, since: datetime | None):
    fired = defaultdict(int)
    blind = defaultdict(int)
    aware = defaultdict(int)
    advice = defaultdict(int)
    sessions = files = 0

    for path in raw_root.rglob("*.jsonl"):
        files += 1
        events = scan_session(path, since)
        if not events:
            continue
        sessions += 1
        for i, ev in enumerate(events):
            if ev["kind"] == "advice":
                advice[ev["tool"]] += 1
                continue
            if ev["kind"] != "block":
                continue
            key = ev["hook"] + (f" ({ev['code']})" if ev["code"] else "")
            fired[key] += 1
            # Что было ДО блокировки — тот вызов, который её вызвал.
            before = next((events[j] for j in range(i - 1, -1, -1)
                           if events[j]["kind"] == "call"), None)
            # Что стало ПОСЛЕ и сказал ли агент хоть что-то в промежутке.
            after = after_idx = None
            for j in range(i + 1, min(i + 6, len(events))):
                if events[j]["kind"] == "call":
                    after, after_idx = events[j], j
                    break
            if not (before and after and before.get("sig") == after.get("sig")):
                continue
            spoke = any(events[j]["kind"] == "said" for j in range(i + 1, after_idx))
            (aware if spoke else blind)[key] += 1
    return {"fired": dict(fired), "blind": dict(blind), "aware": dict(aware),
            "advice": dict(advice), "files": files, "sessions": sessions}


def declared_hooks(repo: Path) -> tuple[set[str], set[str]]:
    """Объявленные хуки, разделённые на блокирующие и тихие.

    Молчание тихого хука ничего не доказывает — он и в норме не оставляет
    следа в транскрипте. Мёртвым можно честно назвать только блокирующий.
    """
    blocking, quiet = set(), set()
    adapter = repo / "adapters" / "claude" / "adapter.yaml"
    if not adapter.is_file():
        return blocking, quiet
    for line in adapter.read_text(encoding="utf-8").splitlines():
        m = re.search(r"binding:\s*\{\s*file:\s*([\w.-]+)\.sh", line)
        if not m:
            continue
        code = re.search(r"^\s*(H\d{2})_", line)
        name = m.group(1) + (f" ({code.group(1)})" if code else "")
        src = repo / "core" / "hooks" / f"{m.group(1)}.sh"
        try:
            can_block = "exit 2" in src.read_text(encoding="utf-8")
        except OSError:
            can_block = False
        (blocking if can_block else quiet).add(name)
    return blocking, quiet


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(RAW_DEFAULT), help="корень сырых транскриптов")
    ap.add_argument("--since", help="нижняя граница окна, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args()

    raw_root = Path(os.path.expanduser(args.raw))
    if not raw_root.is_dir():
        print(f"нет корпуса транскриптов: {raw_root}", file=sys.stderr)
        return 2
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    res = health(raw_root, since)
    repo = Path(__file__).resolve().parents[2]
    blocking, quiet = declared_hooks(repo)
    # Имя из адаптера может не нести кода, а сообщение — нести; сверяем по файлу.
    seen_base = {k.split(" (")[0] for k in res["fired"]}
    dead = sorted(d for d in blocking if d.split(" (")[0] not in seen_base)
    invisible = sorted(quiet)

    if args.json:
        print(json.dumps({**res, "dead": dead, "invisible": invisible},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"файлов: {res['files']}, сессий со срабатываниями: {res['sessions']}"
          + (f", окно с {args.since}" if args.since else ""))
    print("\nблокирующие срабатывания:")
    print(f"  {'хук':34} {'сработал':>8} {'слепой повтор':>14} {'осознанный':>11}")
    for key, n in sorted(res["fired"].items(), key=lambda x: -x[1]):
        b, a = res["blind"].get(key, 0), res["aware"].get(key, 0)
        mark = "  ⚠" if n >= 5 and b / n >= 0.5 else ""
        print(f"  {key:34} {n:8} {b:14} {a:11}{mark}")
    if res["advice"]:
        print("\nненавязчивые подсказки, по инструменту:")
        for tool, n in sorted(res["advice"].items(), key=lambda x: -x[1]):
            print(f"  {tool:34} {n:5}")
    print("\nмёртвые — умеют блокировать и ни разу не сработали:")
    print("  " + (", ".join(dead) if dead else "нет"))
    print("\nневидимы этим методом (тихие, без exit 2) — молчание ничего не доказывает:")
    print("  " + (", ".join(invisible) if invisible else "нет"))
    print("\nОговорка: «повтор» — это тот же вызов после блокировки. Для "
          "acknowledge-once хуков осознанный повтор штатен и правилу не "
          "противоречит; сигналом считается слепой — когда агент повторил, не "
          "написав между делом ни слова. Подсказки не несут кода хука в "
          "транскрипте, поэтому считаются по инструменту, а не по правилу.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
