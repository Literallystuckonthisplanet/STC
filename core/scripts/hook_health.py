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

# Три формы, которыми срабатывание доходит до модели. Замерены по корпусу
# 20.09 по подписи харнесса — пути к файлу хука в скобках, а не по слову
# «hook»: слово встречается в 2000+ мест, где я САМ рассказываю про хуки.
#
# 1. блокировка инструмента:
#    «PreToolUse:Bash hook error: [/…/graphify-first.stc.sh]: 🔎 (H18): …»
RE_BLOCKING = re.compile(
    r"PreToolUse:(?P<tool>\w+) hook error: \[(?P<path>[^\]]+)\]:\s*(?P<msg>.*)",
    re.S,
)
# 2. возражение на конце ответа — приходит ОБЫЧНОЙ репликой и без слова
#    «error», поэтому прежний фильтр её молча съедал. Из-за этого живой H08
#    (37 срабатываний в 37 сессиях) числился мёртвым: измеритель, созданный
#    как лекарство от недостоверности, врал ровно тем способом, от которого
#    лечит.
RE_STOP = re.compile(
    r"Stop hook feedback:\s*\[(?P<path>[^\]]+)\]:\s*(?P<msg>.*)",
    re.S,
)
# 3. ненавязчивая вставка в запрос. Идентичности хука в тексте НЕТ — только
#    событие, поэтому считается по событию и в «мёртвые» не участвует.
RE_INJECT = re.compile(r"(?P<event>UserPromptSubmit|SessionStart) hook success:")
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
            if not any(k in line for k in ('"PreToolUse', '"tool_use"', '"hookName"',
                                           '"text"', 'hook feedback', 'hook success:')):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(obj.get("timestamp"))
            if since and ts and ts < since:
                continue
            first = len(events)       # события этой записи получат её uuid ниже

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
                if "hook success:" in text:
                    mi = RE_INJECT.search(text)
                    if mi:
                        events.append({"kind": "advice", "tool": mi.group("event"),
                                       "hook": None, "code": None, "ts": ts})
                if "hook error" not in text and "hook feedback" not in text:
                    continue
                m = RE_BLOCKING.search(text)
                tool = m.group("tool") if m else None
                if not m:
                    m = RE_STOP.search(text)
                    tool = "Stop"
                if not m:
                    continue
                events.append({
                    "kind": "block",
                    "tool": tool,
                    "hook": _hook_name(m.group("path")),
                    "ts": ts,
                })
            # Одна запись лежит в нескольких файлах архива (копии resume/fork).
            # Ключ события — uuid записи и номер события в ней: ревью 25.09
            # показало, что оригинал и копия давали два срабатывания вместо одного.
            # Без uuid (старые записи, выгрузки) — сессия плюс время записи.
            uid = obj.get("uuid") or (
                f"{obj.get('sessionId')}|{obj.get('timestamp')}"
                if obj.get("sessionId") and obj.get("timestamp") else None)
            for n, ev in enumerate(events[first:]):
                ev["uid"] = f"{uid}#{n}" if uid else None
    return events


def health(raw_root: Path, since: datetime | None, codes: dict | None = None):
    codes = codes or {}
    fired = defaultdict(int)
    blind = defaultdict(int)
    aware = defaultdict(int)
    advice = defaultdict(int)
    sessions = files = 0
    counted: set[str] = set()

    for path in sorted(raw_root.rglob("*.jsonl")):
        files += 1
        events = scan_session(path, since)
        if not events:
            continue
        sessions += 1
        for i, ev in enumerate(events):
            if ev["kind"] in ("advice", "block") and ev.get("uid"):
                if ev["uid"] in counted:
                    continue            # то же событие из копии файла
                counted.add(ev["uid"])
            if ev["kind"] == "advice":
                advice[ev["tool"]] += 1
                continue
            if ev["kind"] != "block":
                continue
            # Код берётся ИЗ РЕЕСТРА по имени файла, а не из текста: сообщение
            # одного хука сплошь и рядом упоминает чужие коды, и один
            # block-dangerous-git разъезжался на три строки — 116, 5 и 2.
            key = ev["hook"] + (f" ({codes[ev['hook']]})" if ev["hook"] in codes else "")
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
    codes: dict[str, str] = {}
    # Развёрнутая копия живёт в ~/.stc, а adapters/ туда не копируется. Пока
    # код правила выдёргивался из текста сообщения, это было незаметно; после
    # перехода на реестр развёрнутый счётчик потерял и коды, и — что хуже —
    # список объявленных хуков, из-за чего «мёртвых нет» стало ПУСТОЙ ПРАВДОЙ:
    # сравнивать оказалось не с чем, а отчёт выглядел благополучным.
    for cand in (repo,
                 Path(os.environ.get("STC_SOURCE", "")) if os.environ.get("STC_SOURCE") else None,
                 Path.home() / "Work" / "STC"):
        if cand is None:
            continue
        adapter = cand / "adapters" / "claude" / "adapter.yaml"
        if adapter.is_file():
            break
    else:
        return blocking, quiet, codes
    if not adapter.is_file():
        return blocking, quiet, codes
    for line in adapter.read_text(encoding="utf-8").splitlines():
        m = re.search(r"binding:\s*\{\s*file:\s*([\w.-]+)\.sh", line)
        if not m:
            continue
        code = re.search(r"^\s*(H\d{2})_", line)
        name = m.group(1) + (f" ({code.group(1)})" if code else "")
        if code:
            codes[m.group(1)] = code.group(1)
        # Файл хука ищем в ТОМ ЖЕ корне, где нашёлся реестр, и только потом
        # рядом со скриптом: иначе реестр берётся из исходников, а признак
        # «умеет блокировать» — из несуществующего пути, и все объявленные
        # хуки молча уезжают в «тихие», то есть в неподсудные.
        can_block = False
        for base in (adapter.parents[2], repo):
            src = base / "core" / "hooks" / f"{m.group(1)}.sh"
            try:
                can_block = "exit 2" in src.read_text(encoding="utf-8")
                break
            except OSError:
                continue
        (blocking if can_block else quiet).add(name)
    return blocking, quiet, codes


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

    repo = Path(__file__).resolve().parents[2]
    blocking, quiet, codes = declared_hooks(repo)
    res = health(raw_root, since, codes)
    # Имя из адаптера может не нести кода, а сообщение — нести; сверяем по файлу.
    seen_base = {k.split(" (")[0] for k in res["fired"]}
    dead = sorted(d for d in blocking if d.split(" (")[0] not in seen_base)
    invisible = sorted(quiet)

    if args.json:
        # Пустой реестр — «не знаю», а не «мёртвых нет». До 25.09 машинный вывод
        # отдавал dead=[] и код 0, и предупреждение жило только в тексте (ревью).
        if not blocking:
            print(json.dumps({**res, "dead": None, "invisible": None,
                              "unverified": "реестр хуков не найден — укажи STC_SOURCE"},
                             ensure_ascii=False, indent=2))
            return 3
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
    if not blocking:
        # Пустой реестр — это «не знаю», а не «всё живо». Молчание измерителя,
        # выглядящее как благополучие, — тот самый дефект, который этот скрипт
        # и чинит.
        print("  ⚠ реестр хуков не найден — сказать нечего. Укажи STC_SOURCE "
              "на каталог исходников STC.")
    else:
        print("  " + (", ".join(dead) if dead else "нет"))
    print("\nневидимы этим методом (тихие, без exit 2) — молчание ничего не доказывает:")
    print("  " + (", ".join(invisible) if invisible else "нет"))
    print("\nОговорка: «повтор» — это тот же вызов после блокировки. Для "
          "acknowledge-once хуков осознанный повтор штатен и правилу не "
          "противоречит; сигналом считается слепой — когда агент повторил, не "
          "написав между делом ни слова. Подсказки не несут кода хука в "
          "транскрипте, поэтому считаются по инструменту, а не по правилу.")
    return 0 if blocking else 3


if __name__ == "__main__":
    raise SystemExit(main())
