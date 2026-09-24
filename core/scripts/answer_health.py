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
не машинный пересказ истории (`isCompactSummary`), без служебных вставок
харнесса. Запасное правило ЗАВЫШАЕТ знаменатель, и на границе версий доли чуть
занижены; --strict считает только по `origin`.

ОДНА РЕПЛИКА — ОДИН РАЗ. Каталог сырья хранит несколько копий одного разговора
(517 файлов, 71 535 записей ответов, 42 334 разных). Без сведения по `uuid`
доли считались по копиям: первый замер 23.09 объявил 10 995 ответов там, где
их вдвое меньше. Ключ — `uuid` записи, запасной — сессия плюс отпечаток текста.

ДВА ХАРНЕССА. Claude и Codex пишут сырьё по-разному, поэтому читателя два, а
показатели общие: Антон разговаривает с обоими, и улучшение только в одном —
не улучшение.

Использование:
    python3 core/scripts/answer_health.py                  # всё время, по месяцам
    python3 core/scripts/answer_health.py --since 2026-09-23   # после внедрения
    python3 core/scripts/answer_health.py --harness claude      # только один
    python3 core/scripts/answer_health.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAW_ROOT = Path.home() / "Work" / "transcripts" / "raw"
RAW_DEFAULT = RAW_ROOT / "claude"
HARNESSES = ("claude", "codex")

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
OPTION = re.compile(r"^\s*(?:\d+[.)]|[-*]\s+\*{0,2}(?:[A-DА-Г]\s*[—–:-]|\(?[абв]\)))|\([абвA-C]\)",
                    re.M)
# Развилка кончается там, где начинается другой раздел ответа: заголовок или
# строка с другим маркером профиля. Без этой границы «🙋 нужно твоё решение»,
# за которым идёт раздел «✅ Сделано» с нумерацией, засчитывался как развилка с
# вариантами — ошибка, найденная внешним ревью 23.09.
SECTION = re.compile(r"^\s*(?:#{1,4}\s|\*{0,2}(?:✅|📚|📊|🎯|🔬|🧠|📌|⏳|🔎|🚩|⚠️)\s)", re.M)
FORK_TAIL = 1200
BACKREF = re.compile(r"(прежн\w+ развилк|как писал выше|развилка (?:всё ещё|по-прежнему)|"
                     r"та же развилка|ранее предлагал)", re.I)
# Служебные вставки харнесса приезжают в роли user, но пишет их не Антон.
SERVICE = ("<task-notification>", "<system-reminder>", "<command-name>",
           "Caveat: The messages below", "<local-command-stdout>")
# То же у Codex: подсказки харнесса и результаты хуков приезжают ролью user.
CODEX_SERVICE = ("<recommended", "<user_instructions", "<environment_context",
                 "## Hook output", "<hook", "=== ОБЯЗАТЕЛЬНЫЙ КОНТЕКСТ СТАРТА")


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
        block = _fork_block(text, i)
        if OPTION.search(block) and not BACKREF.search(block):
            return False
        start = i + 1


def _fork_block(text: str, at: int) -> str:
    """Текст самой развилки: от маркера до следующего раздела ответа."""
    tail = text[at:at + FORK_TAIL]
    end = SECTION.search(tail, 1)
    return tail[:end.start()] if end else tail


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
    if rec.get("isSidechain") or rec.get("promptSource") or rec.get("isCompactSummary"):
        return False
    text = _text((rec.get("message") or {}).get("content"))
    return bool(text.strip()) and not any(mark in text for mark in SERVICE)


def _empty_row() -> dict[str, int]:
    return {"anton_msgs": 0, "confused": 0, "answers": 0, "long": 0,
            "with_code": 0, "forks": 0, "blind_forks": 0}


def _read_claude(rec: dict, strict: bool):
    """(роль, текст, ключ) из записи Claude, либо None — если это не реплика."""
    kind = rec.get("type")
    if kind == "user" and _is_anton(rec, strict):
        role = "anton"
    elif kind == "assistant" and not rec.get("isSidechain"):
        role = "agent"
    else:
        return None
    text = _text((rec.get("message") or {}).get("content")).strip()
    key = rec.get("uuid") or (rec.get("message") or {}).get("id")
    return role, text, key


def _read_codex(rec: dict, strict: bool):
    """То же для Codex: разговор лежит в `response_item` → `payload.message`.

    `origin` у Codex нет вовсе, поэтому --strict его реплики Антона не считает
    (знаменатель честнее пустого). Промпты субагентам приезжают ролью
    `developer`, а не `user`, и отсекаются сами.
    """
    if rec.get("type") != "response_item":
        return None
    payload = rec.get("payload") or {}
    if payload.get("type") != "message":
        return None
    role = {"assistant": "agent", "user": "anton"}.get(payload.get("role"))
    if role is None or (role == "anton" and strict):
        return None
    text = "\n".join(p.get("text", "") for p in payload.get("content") or []
                     if isinstance(p, dict) and p.get("type", "").endswith("text")).strip()
    if role == "anton" and any(mark in text for mark in SERVICE + CODEX_SERVICE):
        return None
    return role, text, payload.get("id")


READERS = {"claude": _read_claude, "codex": _read_codex}


def scan(raw_dir: Path, since: str | None, strict: bool,
         harness: str = "claude", months: dict | None = None) -> dict:
    """Доли по месяцам. `months` можно передать, чтобы слить два харнесса."""
    months = {} if months is None else months
    read = READERS[harness]
    seen: set = set()

    for path in sorted(raw_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            stamp = rec.get("timestamp") or ""
            if not stamp or (since and stamp[:10] < since):
                continue
            parsed = read(rec, strict)
            if parsed is None:
                continue
            role, text, key = parsed
            if not text:
                continue              # шаг с одними вызовами инструментов — не ответ
            # Одна реплика — один раз: каталог хранит копии одних разговоров.
            fingerprint = key or (stamp, role, hash(text))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            row = months.setdefault(stamp[:7], _empty_row())
            if role == "anton":
                row["anton_msgs"] += 1
                if CONFUSED.search(text):
                    row["confused"] += 1
                continue
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
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT,
                        help="каталог сырья: <root>/claude, <root>/codex")
    parser.add_argument("--harness", choices=HARNESSES, action="append",
                        help="по умолчанию оба")
    parser.add_argument("--since", help="YYYY-MM-DD, включительно")
    parser.add_argument("--strict", action="store_true",
                        help="только реплики с origin.kind=human (свежие сессии Claude)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    wanted = args.harness or list(HARNESSES)
    months: dict = {}
    scanned = []
    for harness in wanted:
        raw = args.raw_root / harness
        if not raw.is_dir():
            print(f"пропущен {harness}: нет каталога {raw}", file=sys.stderr)
            continue
        scan(raw, args.since, args.strict, harness=harness, months=months)
        scanned.append(harness)
    if not scanned:
        print(f"нет каталогов транскриптов в {args.raw_root}", file=sys.stderr)
        return 2
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
    print(f"\nхарнессы: {', '.join(scanned)}; реплик Антона {total['anton_msgs']}, "
          f"ответов {total['answers']}, развилок {total['forks']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
