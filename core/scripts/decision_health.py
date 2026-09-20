#!/usr/bin/env python3
"""Развилки без записанного отказа: сколько выборов прошло молча.

Когда из нескольких вариантов выбирают один, остальные отвергаются МОЛЧА.
Принятое оставляет след в коде, отвергнутое — нигде, и потому предлагается
заново. Замер 04.09: поиск по прошлым разговорам звался 15 раз за всё время
против 121 чтения снапшотов, а правила «проверь, разбиралось ли» в rules не
было вообще. Разобранный случай: заметка о пяти кругах ревью пролежала
сиротой месяц, и тот же вопрос разбирался с нуля.

Правило I30 требует в ответе на разрешённую развилку ставить служебный блок
```decision. Скрипт отвечает на два вопроса:

* **доля размеченных развилок** — соблюдается ли I30. Правило без внешней
  проверки по `reference_defect_ledger.md` рецидивирует, поэтому цифра
  считается снаружи, а не предъявляется агентом о себе;
* **доля отказов без причины** — сколько решений принято на ощупь. Это НЕ
  дефект формата: причина ставится только если прозвучала, и пустота честнее
  домысла. Локальная модель, которой дали домысливать причину, в замере
  17.09 перевернула стороны — записала принятое как отклонённое.

ЧТО СЧИТАЕТСЯ РАЗВИЛКОЙ. Не текст ответа пользователя, а МОЙ маркер `🗳️` —
им я по набору маркеров профиля обозначаю предъявленный выбор (229 раз по
корпусу). Три подхода до этого отбраковано замером:

* шаблон «ответ по пунктам» по сырым транскриптам — 190 попаданий, в выборке
  почти всё мусор: мои же нумерованные промпты субагентам и вставки файлов с
  номерами строк (`cat -n`, grep);
* тот же шаблон по отобранному корпусу `collect_corpus` — 103 попадания, в
  выборке из 12 реальных развилок 2: корпус пропускает промпты субагентов,
  потому что у них тоже роль user;
* он же по сообщениям с `origin.kind == "human"` — 214 попаданий и уже
  половина живых, но вторая половина — вставки МОЕГО текста, которые
  пользователь цитирует, отвечая.

Маркер свободен от всего этого: он мой, ставится осознанно и один на развилку.
Дыра у него одна и известная: развилка, предъявленная без маркера, в
знаменатель не попадёт. Она измеряется отдельно и здесь не латается.

Разрешением развилки считается ответ пользователя с `origin.kind == "human"` —
структурное поле харнесса. Оно есть только у claude, поэтому замер
claude-only; codex/zcode такого поля не несут.

Использование:
    python3 core/scripts/decision_health.py [--since 2026-09-17] [--json]
    python3 core/scripts/decision_health.py --extract     # сами записи
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lens_rules  # noqa: E402  нормализация двойников кириллица↔латиница

RAW_DEFAULT = Path.home() / "Work" / "transcripts" / "raw" / "claude"

FORK_MARK = "🗳"          # без вариационного селектора: он в тексте не всегда
# Маркер ПОСЛЕ отсылающего слова — это разговор о маркере, а не предъявленный
# выбор. 20.09 хук сработал на фразе «развилка без маркера 🗳 в знаменатель не
# попадает»: та же порода, что «считал упоминания вместо вызовов» в замере
# graphify. По корпусу (264 реплики с маркером) правило отсекает ровно одно
# упоминание и ни одного живого предъявления.
#
# Позицию в строке проверять бесполезно — проверял: маркер законно стоит и
# после «## », и после «**Шаг 3.** », так что якорь на начало строки выбросил
# бы 87 настоящих развилок из 264.
MENTION = re.compile(r"(?:маркер\w*|значк\w*|значок|символ\w*|эмодзи)\s*\*{0,2}\s*$", re.I)
FENCE = re.compile(r"```decision\s*\n(.*?)```", re.S)
KEY_KEPT = "принято"
KEY_DROPPED = "отклонено"
# Причина — после тире: «отклонено: X — потому что Y». Тире любое из трёх.
REASON = re.compile(r"\s[-–—]\s+(\S.*)$")
# Заполнитель из объяснения формата: «принято: <что делаем>», «отклонено:
# <что не делаем> — <причина>». Такой блок — пример в ответе пользователю, а
# не решение. Без фильтра объяснение формата засчиталось бы как соблюдение
# правила: метрику можно было бы накрутить, ни одного решения не записав.
# Якоря на конец нет намеренно — вторая форма несёт за заполнителем причину.
PLACEHOLDER = re.compile(r"^<[^>]*>")


def presents_fork(text: str) -> bool:
    """Реплика ПРЕДЪЯВЛЯЕТ выбор, а не рассказывает про маркер.

    Единственный источник правила: хук `decision-record.sh` спрашивает отсюда
    же. Разведённые копии одного правила уже расходились — в линзе аудит
    считал не то, что срабатывало (см. шапку lens_rules.py).
    """
    start = 0
    while True:
        i = text.find(FORK_MARK, start)
        if i < 0:
            return False
        if not MENTION.search(text[max(0, i - 40):i]):
            return True          # хотя бы одно настоящее предъявление
        start = i + 1


def _text(content) -> str:
    """Текст реплики. Разбирается здесь, а не через `transcript_corpus`.

    Причина не в дублировании: общий разборщик отдаёт role/text и ВЫБРАСЫВАЕТ
    `origin`, а именно оно отличает сообщение человека от промпта субагенту
    (у того тоже role=user). Без `origin` знаменатель загрязняется вдвое.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _parse_ts(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_block(body: str) -> dict:
    """Строки блока → запись.

    Ключи сверяются по нормализованному тексту: `с/c`, `о/o`, `р/p` — артефакт
    раскладки (`reference_cyrillic_regex.md`), и строка с латинской «о» внутри
    русского слова разбиралась бы как обычный текст, то есть молча терялась.
    """
    kept: list[str] = []
    dropped: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        norm = lens_rules.normalize(line)
        value = line.split(":", 1)[1].strip()
        if PLACEHOLDER.match(value):
            continue          # блок-пример из объяснения формата, не решение
        if norm.startswith(KEY_KEPT):
            if value:
                kept.append(value)
        elif norm.startswith(KEY_DROPPED):
            if not value:
                continue
            m = REASON.search(value)
            dropped.append({
                "what": (value[: m.start()] if m else value).strip(),
                "reason": m.group(1).strip() if m else "",
            })
    return {"kept": kept, "dropped": dropped}


def _events(path: Path):
    """Реплики одной сессии по порядку: ('human'|'assistant', текст, запись)."""
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            if '"message"' not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "user":
                if (obj.get("origin") or {}).get("kind") != "human":
                    continue      # промпт субагенту, ретрай, координатор
                yield "human", _text(msg.get("content")), obj
            elif role == "assistant":
                yield "assistant", _text(msg.get("content")), obj


def scan(raw_root: Path, since: datetime | None):
    """Считает развилки и разметку, идя по сессии как по конечному автомату.

    Состояния: нет развилки → развилка предъявлена (🗳️) → развилка разрешена
    (ответил человек) → ждём блок. Блок принимается в ЛЮБОЙ моей реплике до
    следующей реплики человека: он может лечь и в первый ответ, и в последний
    после длинной работы с инструментами.
    """
    forks = marked = 0
    records: list[dict] = []
    # Одна сессия лежит в нескольких файлах (resume/fork копии), и без дедупа
    # та же развилка считается трижды: живой прогон давал 213 против 84
    # уникальных. Ключ — сессия плюс время ответа, как в `collect_corpus`.
    seen: set[tuple] = set()
    for path in sorted(raw_root.rglob("*.jsonl")):
        fork_open = False       # я предъявил выбор
        awaiting = None         # человек ответил; ждём блок
        for role, text, obj in _events(path):
            ts = _parse_ts(obj.get("timestamp"))
            if since and ts and ts < since:
                continue

            if role == "human":
                if awaiting is not None:
                    forks += 1          # предыдущая развилка закрылась пустой
                    awaiting = None
                if fork_open:
                    fork_open = False
                    key = (obj.get("sessionId"), obj.get("timestamp"))
                    if key in seen:
                        continue        # тот же разговор из копии файла
                    seen.add(key)
                    awaiting = {
                        "session": obj.get("sessionId"),
                        "timestamp": obj.get("timestamp"),
                        "cwd": obj.get("cwd"),
                    }
                continue

            # моя реплика: сперва блок по открытому долгу, потом новая развилка
            if awaiting is not None:
                m = FENCE.search(text)
                if m:
                    rec = parse_block(m.group(1))
                    if rec["kept"] or rec["dropped"]:
                        forks += 1
                        marked += 1
                        rec.update(awaiting)
                        records.append(rec)
                        awaiting = None
            if presents_fork(text):
                fork_open = True
        if awaiting is not None:
            forks += 1
    return {"forks": forks, "marked": marked, "records": records}


def summarize(res: dict) -> dict:
    forks, marked = res["forks"], res["marked"]
    dropped = [d for r in res["records"] for d in r["dropped"]]
    no_reason = sum(1 for d in dropped if not d["reason"])
    return {
        "forks": forks,
        "marked": marked,
        "unmarked": forks - marked,
        "marked_share": round(marked / forks, 2) if forks else None,
        "rejections": len(dropped),
        "rejections_without_reason": no_reason,
        "no_reason_share": round(no_reason / len(dropped), 2) if dropped else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", default=str(RAW_DEFAULT), help="корень сырых транскриптов")
    ap.add_argument("--since", help="нижняя граница окна, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--extract", action="store_true", help="печатать сами записи")
    args = ap.parse_args()

    raw_root = Path(os.path.expanduser(args.raw))
    if not raw_root.is_dir():
        print(f"нет корпуса транскриптов: {raw_root}", file=sys.stderr)
        return 2
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    res = scan(raw_root, since)
    stat = summarize(res)

    if args.json:
        print(json.dumps({**stat, "records": res["records"]},
                         ensure_ascii=False, indent=2))
        return 0

    if args.extract:
        if not res["records"]:
            print("записей нет")
            return 0
        for r in res["records"]:
            where = (r.get("cwd") or "").rstrip("/").split("/")[-1] or "—"
            print(f"\n{str(r.get('timestamp'))[:16]}  {where}  "
                  f"сессия {str(r.get('session'))[:8]}")
            for k in r["kept"]:
                print(f"  ✓ принято:   {k}")
            for d in r["dropped"]:
                tail = f" — {d['reason']}" if d["reason"] else "   (причина не названа)"
                print(f"  ✗ отклонено: {d['what']}{tail}")
        return 0

    print(f"развилок: {stat['forks']}"
          + (f", окно с {args.since}" if args.since else ""))
    if not stat["forks"]:
        print("нечего мерить: развилок в окне нет")
        return 0
    print(f"с разметкой: {stat['marked']}   без разметки: {stat['unmarked']}"
          f"   доля соблюдения: {stat['marked_share']}")
    if stat["rejections"]:
        print(f"отказов записано: {stat['rejections']}, из них без названной "
              f"причины: {stat['rejections_without_reason']} "
              f"(доля {stat['no_reason_share']})")
    print("\nОговорка: развилкой считается моя реплика с маркером 🗳️, "
          "разрешением — ответ человека. Развилка, предъявленная БЕЗ маркера, "
          "в знаменатель не попадает — это известная дыра метрики. Отказ без "
          "причины не дефект: причина ставится только если прозвучала.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
