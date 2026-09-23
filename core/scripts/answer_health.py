#!/usr/bin/env python3
"""Понятны ли мои ответы Антону: замер снаружи, а не самооценкой.

Антон 21.09.2026: «много ненужного текста, одно и то же разными словами
повторяется, много технических непонятных терминов, сложно вытащить суть,
размытые формулировки развилок на меня». Правило «простым языком» в профиле
стояло с 29.06 и не держало — значит, отчёт агента о самом себе здесь ничего
не стоит. Цифру считает посторонняя программа по сырым транскриптам.

Четыре показателя, все — доля, а не абсолют (сессии разной длины):

* **переспросы** — доля реплик Антона вида «не понял / повтори / что от меня
  надо». Это единственный показатель, где судья — он сам, остальные три
  объясняют, ПОЧЕМУ переспрашивает;
* **длинные ответы** — доля ответов длиннее 2000 знаков. Порог не выдуман:
  ответ, после которого он написал «пока не понимаю какая развилка за мной»,
  весил 2383 знака, а следующий за ним «я ничего не понимаю» — 3419;
* **внутренние коды** — доля ответов, где встречается код правила или этапа
  (H14, FR-26, R19-7, Ш2, Б3б). По профилю их в ответе быть не должно вообще,
  так что честная цель здесь — ноль;
* **слепые развилки** — доля развилок (маркер `🗳`), где нет ни одного
  пронумерованного варианта ЛИБО есть отсылка к прошлым сообщениям
  («прежняя развилка», «как писал выше»). Ровно тот дефект, из-за которого
  Антон дважды просил «повтори что за развилка».

ЧЕЙ ЭТО ГОЛОС. Реплика Антона — `origin.kind == "human"`, структурное поле
харнесса. Оно появилось только в свежих версиях, поэтому для старых сессий
работает запасное правило: не сайдчейн, не промпт субагенту (`promptSource`),
без служебных вставок харнесса. Запасное правило ЗАВЫШАЕТ знаменатель, и на
границе версий доли чуть занижены; --strict считает только по `origin`.

Использование:
    python3 core/scripts/answer_health.py                  # всё время, по месяцам
    python3 core/scripts/answer_health.py --since 2026-09-23   # после внедрения
    python3 core/scripts/answer_health.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAW_DEFAULT = Path.home() / "Work" / "transcripts" / "raw" / "claude"

LONG_ANSWER = 2000

CONFUSED = re.compile(
    r"(не понял|не понимаю|непонятн|повтори что|что от меня|зачем мне это|"
    r"объясни проще|я ничего не понимаю)",
    re.I,
)
# Коды правил и этапов: H06, FR-26, I17, S01, R19-7, Ш2, Б3б, П53, БК, БИ.
CODE = re.compile(r"(?<![\w-])(?:H\d{2}|FR-\d+|I\d{2}|S\d{2}|R\d+-\d+|[ШБП]\d+[а-я]?)(?![\w-])")
FORK_MARK = "🗳"
# Вариант выбора: «1.» / «1)» / «- **A —» в начале строки либо «(а)» в строку.
# Считается ТОЛЬКО после маркера развилки: нумерация в других частях ответа к
# выбору отношения не имеет. Без этой привязки замер 22.09 засчитал как
# размеченные две развилки, где нумерованным был соседний список находок.
OPTION = re.compile(r"^\s*(?:\d+[.)]|[-*]\s*\*{0,2}[A-DА-Г]\s*[—–-])|\([абвA-C]\)", re.M)
# Сколько текста после маркера считается самой развилкой.
FORK_TAIL = 1200
BACKREF = re.compile(r"(прежн\w+ развилк|как писал выше|развилка (?:всё ещё|по-прежнему)|"
                     r"та же развилка|ранее предлагал)", re.I)
# Служебные вставки харнесса приезжают в роли user, но пишет их не Антон.
SERVICE = ("<task-notification>", "<system-reminder>", "<command-name>",
           "Caveat: The messages below", "<local-command-stdout>")


def is_blind_fork(text: str) -> bool:
    """Развилка предъявлена так, что по ней нельзя ответить.

    Слепая = после маркера нет ни одного варианта выбора ЛИБО есть отсылка к
    прошлым сообщениям. Хватает одной внятной развилки в ответе: считается
    лучшая из предъявленных, иначе длинный отчёт с двумя маркерами штрафуется
    дважды за один и тот же дефект.
    """
    start = 0
    while True:
        i = text.find(FORK_MARK, start)
        if i < 0:
            return True
        tail = text[i:i + FORK_TAIL]
        if OPTION.search(tail) and not BACKREF.search(tail):
            return False
        start = i + 1


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _is_anton(rec: dict, strict: bool) -> bool:
    origin = rec.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    if strict:
        return False
    if rec.get("isSidechain") or rec.get("promptSource"):
        return False
    text = _text((rec.get("message") or {}).get("content"))
    return bool(text.strip()) and not any(mark in text for mark in SERVICE)


def scan(raw_dir: Path, since: str | None, strict: bool) -> dict:
    months: dict[str, dict[str, int]] = {}

    def bucket(stamp: str) -> dict[str, int]:
        key = stamp[:7]
        return months.setdefault(key, {
            "anton_msgs": 0, "confused": 0,
            "answers": 0, "long": 0, "with_code": 0,
            "forks": 0, "blind_forks": 0,
        })

    for path in sorted(raw_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            stamp = rec.get("timestamp") or ""
            if not stamp or (since and stamp[:10] < since):
                continue
            kind = rec.get("type")
            if kind == "user" and _is_anton(rec, strict):
                row = bucket(stamp)
                row["anton_msgs"] += 1
                if CONFUSED.search(_text((rec.get("message") or {}).get("content"))):
                    row["confused"] += 1
            elif kind == "assistant" and not rec.get("isSidechain"):
                text = _text((rec.get("message") or {}).get("content")).strip()
                if not text:
                    continue          # шаг с одними вызовами инструментов — не ответ
                row = bucket(stamp)
                row["answers"] += 1
                if len(text) > LONG_ANSWER:
                    row["long"] += 1
                if CODE.search(text):
                    row["with_code"] += 1
                if FORK_MARK in text:
                    row["forks"] += 1
                    if is_blind_fork(text):
                        row["blind_forks"] += 1
    return months


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    parser.add_argument("--since", help="YYYY-MM-DD, включительно")
    parser.add_argument("--strict", action="store_true",
                        help="только реплики с origin.kind=human (свежие сессии)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.raw.is_dir():
        print(f"нет каталога транскриптов: {args.raw}", file=sys.stderr)
        return 2

    months = scan(args.raw, args.since, args.strict)
    if args.json:
        print(json.dumps(months, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print(f"{'месяц':8} {'переспросы':>12} {'длинные':>9} {'с кодами':>10} {'слепые развилки':>17}")
    total = {k: 0 for k in ("anton_msgs", "confused", "answers", "long",
                            "with_code", "forks", "blind_forks")}
    for month in sorted(months):
        row = months[month]
        for key in total:
            total[key] += row[key]
        print(f"{month:8} "
              f"{_pct(row['confused'], row['anton_msgs']):>12} "
              f"{_pct(row['long'], row['answers']):>9} "
              f"{_pct(row['with_code'], row['answers']):>10} "
              f"{_pct(row['blind_forks'], row['forks']):>17}")
    print(f"{'ИТОГО':8} "
          f"{_pct(total['confused'], total['anton_msgs']):>12} "
          f"{_pct(total['long'], total['answers']):>9} "
          f"{_pct(total['with_code'], total['answers']):>10} "
          f"{_pct(total['blind_forks'], total['forks']):>17}")
    print(f"\nреплик Антона {total['anton_msgs']}, ответов {total['answers']}, "
          f"развилок {total['forks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
