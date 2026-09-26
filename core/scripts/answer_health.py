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
* **развилки не по карточке** — доля ответов с развилкой (маркер `🗳`), где
  хоть одна развилка предъявлена меньше чем с двумя отдельными вариантами ЛИБО
  с отсылкой к прошлым сообщениям («прежняя развилка», «как писал выше»). Это
  соответствие карточке развилки из профиля, а НЕ доказанная доля развилок, по
  которым Антон не может ответить: на «так или иначе?» прозой ответить можно,
  но это ровно тот вид, из-за которого он просил «повтори что за развилка».
  До 24.09 показатель назывался «слепые развилки» и обещал больше, чем мерил;
* **без совета** — доля ответов, где варианты есть, а рекомендации нет.

ГРАНИЦА ТОЧНОСТИ. «Последствия у каждого варианта» программа НЕ проверяет: по
тексту их надёжно не отличить от описания варианта. Это проверяется глазами на
выборке — см. `deploy/tests/fixtures/answer_forks/` и ручную сверку в
заметке `2026-09-22-answer-format-for-anton.md`.

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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import decision_health  # noqa: E402  единственный источник «что считать развилкой»

RAW_ROOT = Path.home() / "Work" / "transcripts" / "raw"
RAW_DEFAULT = RAW_ROOT / "claude"
HARNESSES = ("claude", "codex")

LONG_ANSWER = 2000

CONFUSED = re.compile(
    r"(не понял|не понимаю|непонятн|повтори что|что от меня|зачем мне это|"
    r"объясни проще|я ничего не понимаю)",
    re.I,
)
# Коды правил и этапов: H06, FR-26, I17, S01, R19-7, Ш2, Б3б, П53. Буквенные
# коды без цифр (БК, БИ) НЕ ловятся сознательно: тот же вид у обычных слов
# («ПО», «ИП», «РФ»), и замер начал бы считать речь, а не коды.
CODE = re.compile(r"(?<![\w-])(?:H\d{2}|FR-\d+|I\d{2}|S\d{2}|R\d+-\d+|[ШБП]\d+[а-я]?)(?![\w-])")
FORK_MARK = "🗳"
# Строка-вариант: после необязательных маркера списка, жирного и эмодзи идёт
# метка варианта — «1.», «1)», «A —», «А:», «(а)», «Вариант 1», «Вариант А».
# Ревью 24.09 на свежих ответах: «- **Вариант 1 — …**» и строка без маркера
# списка «**Вариант 2 — …**» не распознавались, и обе полноценные развилки
# уходили в слепые.
OPTION_LINE = re.compile(
    r"^[\s>*_-]*(?:🗳️?\s*)?\*{0,2}\s*"
    r"(?:(\d{1,2})[.)]\s"
    r"|([A-DА-Г])(?:\s*\([^)\n]{1,20}\))?\s*[—–:.)-]\*{0,2}\s"
    r"|\(([абвгA-D])\)"
    r"|вариант\s+(\d{1,2}|[A-DА-Г])\b)",
    re.I | re.M,
)
# Варианты жирными пунктами без номеров: «- **Влить сейчас (советую).** …».
# Считаются, только если таких пунктов хотя бы два: одиночный жирный пункт —
# это акцент, а не выбор. Ручная сверка 24.09: карточка из двух таких пунктов
# с советом считалась слепой. И только рядом с вопросом или советом: иначе это
# список тем (ревью 26.09: «🗳️ Скоро понадобятся решения: **Объём**, **Кто
# прочитает**» засчитывался развилкой из трёх вариантов). По архиву на 26.09
# все десять настоящих карточек такого вида несут совет, ложная — ни того, ни другого.
BOLD_BULLET = re.compile(r"^\s*[-*•]\s+\*\*([^*\n]{3,80})\*\*", re.M)
# Варианты в одну строку: «(а) делаю сейчас; (б) держим план».
INLINE_OPTION = re.compile(r"\(([абвгA-D])\)")
# Варианты строками таблицы: «| **ещё круг** | … |». Заголовок и разделитель
# не варианты. Ручная сверка 24.09: развилка из трёх строк таблицы с советом
# считалась слепой.
TABLE_ROW = re.compile(r"^\s*\|(?!\s*:?-{3})\s*([^|]+?)\s*\|", re.M)
RECOMMEND = re.compile(r"(советую|рекоменд|я за\b|я бы взял|предлагаю|склоняюсь)", re.I)
# Развилка кончается там, где начинается другой раздел ответа: заголовок или
# строка с другим маркером профиля. Без этой границы «🙋 нужно твоё решение»,
# за которым идёт раздел «✅ Сделано» с нумерацией, засчитывался как развилка с
# вариантами — ошибка, найденная внешним ревью 23.09.
SECTION = re.compile(r"^\s*(?:#{1,4}\s|\*{0,2}(?:✅|📚|📊|🎯|🔬|🧠|📌|⏳|🔎|🚩|⚠️)\s)", re.M)
# Потолок куска, если после развилки нет ни раздела, ни следующей развилки.
# Прежние 1200 знаков резали длинную карточку до второго варианта (ревью 26.09).
FORK_TAIL = 4000
BACKREF = re.compile(r"(прежн\w+ развилк|вопрос за тобой прежний|как писал выше|"
                     r"развилка (?:всё ещё|по-прежнему)|та же развилка|ранее предлагал)", re.I)
# Служебные вставки харнесса приезжают в роли user, но пишет их не Антон.
SERVICE = ("<task-notification>", "<system-reminder>", "<command-name>",
           "Caveat: The messages below", "<local-command-stdout>")
# То же у Codex: подсказки харнесса и результаты хуков приезжают ролью user.
CODEX_SERVICE = ("<recommended", "<user_instructions", "<environment_context",
                 "## Hook output", "<hook", "=== ОБЯЗАТЕЛЬНЫЙ КОНТЕКСТ СТАРТА")


def fork_blocks(text: str) -> list[str]:
    """Каждая предъявленная развилка ответа — отдельным куском текста.

    Упоминание значка («развилка без маркера 🗳 не попадает») развилкой не
    считается; правило общее с хуком записи решений.
    """
    # Значок на строке-варианте («🗳️ **(б)** …») продолжает ту же развилку, а
    # не начинает новую: так выглядит карточка, где значок стоит у каждого варианта.
    starts = [at for i, at in enumerate(decision_health.fork_positions(text))
              if i == 0 or not OPTION_LINE.match(_line_at(text, at))]
    return [_fork_block(text, at, nxt) for at, nxt in zip(starts, starts[1:] + [None])]


def count_options(block: str) -> int:
    """Сколько РАЗНЫХ вариантов предъявлено в куске развилки.

    Строка с вопросительным знаком — отдельный вопрос, а не вариант: «Два
    решения за тобой: 1. Делаем дубль? 2. Спека сначала?» — это две развилки
    без вариантов, а не одна с двумя (ручная сверка 24.09).
    """
    labels = set()
    for m in OPTION_LINE.finditer(block):
        if "?" in _line_at(block, m.start()):
            continue
        labels.add(next(g for g in m.groups() if g).lower())
    bold = [m.group(1).lower() for m in BOLD_BULLET.finditer(block)
            if "?" not in _line_at(block, m.start())]
    if len(bold) >= 2 and ("?" in block or RECOMMEND.search(block)):
        labels.update(f"bullet:{b}" for b in bold)
    for m in INLINE_OPTION.finditer(block):
        labels.add(m.group(1).lower())
    rows = [m.group(1).strip("* ").lower() for m in TABLE_ROW.finditer(block)]
    if len(rows) >= 3:                    # заголовок + хотя бы два варианта
        labels.update(f"table:{row}" for row in rows[1:])
    return len(labels)


def _line_at(text: str, pos: int) -> str:
    end = text.find("\n", pos)
    return text[text.rfind("\n", 0, pos) + 1:end if end >= 0 else len(text)]


def is_blind_block(block: str) -> bool:
    """Слепая развилка: меньше двух вариантов либо отсылка к прошлому.

    Выбор из одного варианта — не выбор: «🗳️ Что выбираешь? 1. Сделать»
    прежде засчитывался как понятный (ревью 24.09).
    """
    return count_options(block) < 2 or bool(BACKREF.search(block))


def is_blind_fork(text: str) -> bool:
    """В ответе есть хоть одна развилка, по которой нельзя ответить.

    Раньше считалась лучшая из развилок ответа, и одна полная прятала вторую
    пустую (ревью 24.09). Показатель — доля ОТВЕТОВ, поэтому ответ с двумя
    слепыми развилками штрафуется один раз, а не дважды.
    """
    blocks = fork_blocks(text)
    return not blocks or any(is_blind_block(b) for b in blocks)


def lacks_advice(text: str) -> bool:
    """Развилка с вариантами, но без совета, какой брать."""
    return any(not is_blind_block(b) and not RECOMMEND.search(b)
               for b in fork_blocks(text))


def _fork_block(text: str, at: int, next_fork: int | None = None) -> str:
    """Текст самой развилки: от маркера до следующего раздела или развилки.

    Без границы по следующей развилке первый вариант соседней карточки
    доставался предыдущей (ревью 26.09).
    """
    stop = at + FORK_TAIL if next_fork is None else min(next_fork, at + FORK_TAIL)
    tail = text[at:stop]
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
            "with_code": 0, "forks": 0, "blind_forks": 0, "no_advice": 0}


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
         harness: str = "claude", months: dict | None = None,
         until: str | None = None) -> dict:
    """Доли по месяцам. `months` можно передать, чтобы слить два харнесса.

    `until` — дата, с которой записи уже не считаются: база «до» и замер
    «после» считаются одним счётчиком по одному архиву (ревью 26.09).
    """
    months = {} if months is None else months
    read = READERS[harness]
    seen: set = set()
    newest = months.setdefault("_newest", {})

    for path in sorted(raw_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            stamp = rec.get("timestamp") or ""
            if not stamp:
                continue
            if stamp > newest.get(harness, ""):
                newest[harness] = stamp
            if since and stamp[:10] < since:
                continue
            if until and stamp[:10] >= until:
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
            if fork_blocks(text):
                row["forks"] += 1
                if is_blind_fork(text):
                    row["blind_forks"] += 1
                if lacks_advice(text):
                    row["no_advice"] += 1
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
    parser.add_argument("--until", help="YYYY-MM-DD, не включая: для базы «до»")
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
        scan(raw, args.since, args.strict, harness=harness, months=months,
             until=args.until)
        scanned.append(harness)
    if not scanned:
        print(f"нет каталогов транскриптов в {args.raw_root}", file=sys.stderr)
        return 2
    newest = months.pop("_newest", {})
    if args.json:
        print(json.dumps({"months": months, "newest": newest},
                         ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    print(f"{'месяц':8} {'переспросы':>12} {'длинные':>9} {'с кодами':>10} "
          f"{'не по карточке':>17} {'без совета':>11}")
    total = dict.fromkeys(_empty_row(), 0)
    for month in sorted(months):
        row = months[month]
        for key in total:
            total[key] += row[key]
        print(f"{month:8} "
              f"{_pct(row['confused'], row['anton_msgs']):>12} "
              f"{_pct(row['long'], row['answers']):>9} "
              f"{_pct(row['with_code'], row['answers']):>10} "
              f"{_pct(row['blind_forks'], row['forks']):>17} "
              f"{_pct(row['no_advice'], row['forks']):>11}")
    print(f"{'ИТОГО':8} "
          f"{_pct(total['confused'], total['anton_msgs']):>12} "
          f"{_pct(total['long'], total['answers']):>9} "
          f"{_pct(total['with_code'], total['answers']):>10} "
          f"{_pct(total['blind_forks'], total['forks']):>17} "
          f"{_pct(total['no_advice'], total['forks']):>11}")
    print(f"\nхарнессы: {', '.join(scanned)}; реплик Антона {total['anton_msgs']}, "
          f"ответов {total['answers']}, развилок {total['forks']}")
    # Архив пополняется раз в сутки. Сравнение «после» по архиву, который
    # кончается раньше внедрения, молча вернёт пустоту (ревью 24.09).
    print("последняя запись в архиве: " + ", ".join(
        f"{h} {newest.get(h, 'нет')[:16].replace('T', ' ')} UTC" for h in scanned))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
