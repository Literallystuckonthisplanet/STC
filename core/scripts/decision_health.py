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
# Та же порода, но слово-отсылка ПОСЛЕ маркера: «🗳️ — мой собственный явный
# маркер развилки, 229 раз» (живая реплика, найдена ручной сверкой 24.09).
MENTION_AFTER = re.compile(
    r"^️?\s*[—–-]\s*(?:(?:\S+\s+){0,3}(?:маркер\w*|значк\w*|значок|символ\w*|эмодзи)"
    r"|развилк\w*\s*,)", re.I)
# Вторая ветка — легенда набора значков: «🗳️ — развилка, выбери вариант»
# (ручная сверка 24.09). Живая развилка так не пишется: «🗳️ **Развилка:**».
# Значок в перечислении через запятую: «🙋 нужен ты, 🗳️ выбор, ⚠️ важно».
# Живая развилка после запятой не начинается никогда.
IN_ENUMERATION = re.compile(r",\s*$")
# И перечень значков подряд: «🗳️ ✍️ | ⚠️ 🚩» — за маркером сразу другой значок
# или разделитель таблицы.
ENUMERATION_AFTER = re.compile(r"^\uFE0F?\s*(?:\||[\U0001F300-\U0001FAFF\u2600-\u27BF])")
# Образец внутри блока кода — текст о развилке, а не сама развилка.
CODE_FENCE = re.compile(r"```.*?(?:```|$)", re.S)
FENCE = re.compile(r"```decision\s*\n(.*?)```", re.S)
KEY_KEPT = "принято"
KEY_DROPPED = "отклонено"
# Причина — только после явного слова: «отклонено: X; причина: Y». До 26.09
# причиной считалось всё после тире, и «отклонено: Пилот — неделя проверки без
# оплаты» читалось как вариант «Пилот» с причиной, которой никто не называл
# (ревью 25.09). Тире внутри названия варианта — обычное дело, слово «причина»
# в нём — нет. Записи старого вида теперь честно читаются как «без причины».
REASON = re.compile(r"[\s;,—–-]*\bпричина\s*:\s*(\S.*)$", re.I)
# Реплика человека, которая спрашивает, а не выбирает: «Сколько будет стоить A?»
# Вопрос без слова согласия развилку не закрывает — ни для сторожа, ни для
# счётчика (ревью 25.09: такой вопрос засчитывался как выбор).
APPROVE = re.compile(
    r"(?<!\w)(да|ок|окей|ok|okay|делай|делаем|давай|согласен|согласна|берём|берем|беру|"
    r"выбираю|оставляем|го|поехали|принято|пойдёт|пойдет|годится)(?!\w)", re.I)
# Явная ссылка на вариант — сильная: она перевешивает знак вопроса («1 - вариант
# 1 … а нужен ли номер?» — выбор с попутным вопросом, ревью 26.09). Это метка в
# начале строки («1 -», «Б.», «Б+В»), метка в скобках («(б)», «2)»), «вариант 2» в
# начале строки и буква после глагола выбора («сделай Б»). Заглавная буква в
# начале фразы без знака после неё — не метка: «В общем, я не решил», «В
# [tables.py]» во вставленном ревью (ревью 26.09).
STRONG_CUE = re.compile(
    r"^\s*\d(?=[\s.,:;)!+—–-]|$)"
    r"|^\s*[A-DА-Г](?=[.,:;)!+—–-]|\s*$)"
    r"|\((?:[абвгa-d]|\d)\)|(?<!\w)(?:[абвгa-d]|\d)\)"
    r"|^\s*(?i:вариант)\s+(?:\d|[A-DА-Гa-dа-г])(?!\w)"
    r"|(?<!\w)(?i:сделай|делай|делаем|давай|берём|берем|беру|выбираю|оставляем)"
    r"\s+[A-DА-Г](?!\w)"
    # «Сужаем до отказов - это»: вариант повторён отдельной строкой с «это».
    r"|^[^\n?]{3,80}\s[—–-]\s*это\s*$",
    re.M)
# Слабая: слово «вариант», порядковое («первый», «второе»), «п2», «оба». Она
# означает выбор, только если человек ничего не спросил: «А что будет со
# вторым?» — вопрос.
# Одиночная буква в середине фразы — НЕ метка: «в» и «а» — предлог и союз, и
# без этой оговорки «сохрани выводы в память» считалось выбором варианта «В».
CHOICE_CUE = re.compile(
    STRONG_CUE.pattern
    + r"|(?i:вариант)"
    r"|(?<!\w)(?i:перв|втор|трет)\w*"
    r"|(?<!\w)(?i:оба|обе)(?!\w)"
    r"|(?<!\w)(?i:п)\.?\s?\d",
    re.M)
# Слова человека — без вставленного и процитированного. Антон часто отвечает на
# развилку вставкой чужого ревью («посмотри ревью: <10 000 знаков>»), и «да» или
# «Берём его» глубоко во вставке делали из просьбы выбор: 22 из 25 длинных
# ответов в архиве на 26.09 так и классифицировались (ревью 26.09).
PASTED = re.compile(r"<pasted_content[^>]*>.*?(?:</pasted_content>|$)", re.S)
HTML_NOTE = re.compile(r"<!--.*?-->", re.S)
# Вставка целиком: начинается с кавычки или значка отчёта агента.
PASTE_START = re.compile(r"^\s*(?:[\"«“]|🔎|🎯|✅|🔬|🔁|🚩|⚠️|📊|#)")
# Вставка после вводных слов: «посмотри ревью:», «ПРОВЕРЯЙ:», «вот ещё на ревью:».
INTRO_MAX = 80        # вводные слова короче строки
PASTE_MIN = 400       # вставка длиннее обычной реплики
# Название варианта в карточке: жирное в начале строки-варианта.
OPTION_NAME = re.compile(
    r"^[\s>*•\d.)-]*(?:🗳️?\s*)?\*\*([^*\n]{4,160})\*\*", re.M)
OPTION_LABEL = re.compile(
    r"^\s*(?:\(?[A-DА-Гa-dа-г\d]\)|[A-DА-Г\d][.:—–-]|вариант\s+\S+\s*[—–:-]?)\s*", re.I)
# Заполнитель из объяснения формата: «принято: <что делаем>», «отклонено:
# <что не делаем>; причина: <…>». Такой блок — пример в ответе пользователю, а
# не решение. Без фильтра объяснение формата засчиталось бы как соблюдение
# правила: метрику можно было бы накрутить, ни одного решения не записав.
# Якоря на конец нет намеренно — вторая форма несёт за заполнителем причину.
PLACEHOLDER = re.compile(r"^<[^>]*>")
DASH = re.compile(r"\s[—–-]\s")


def presents_fork(text: str) -> bool:
    """Реплика ПРЕДЪЯВЛЯЕТ выбор, а не рассказывает про маркер.

    Единственный источник правила: хук `decision-record.sh` спрашивает отсюда
    же. Разведённые копии одного правила уже расходились — в линзе аудит
    считал не то, что срабатывало (см. шапку lens_rules.py).
    """
    return bool(fork_positions(text))


def fork_positions(text: str) -> list[int]:
    """Где в реплике стоят НАСТОЯЩИЕ предъявления выбора, без упоминаний.

    Отдельной функцией для замера понятности ответов (`answer_health.py`):
    ему нужна каждая развилка, а не только факт, что она есть.
    """
    fences = [m.span() for m in CODE_FENCE.finditer(text)]
    found, start = [], 0
    while (i := text.find(FORK_MARK, start)) >= 0:
        start = i + 1
        if any(a <= i < b for a, b in fences):
            continue                 # значок в образце кода, а не в ответе
        before = text[max(0, i - 40):i]
        after = text[i + len(FORK_MARK):i + len(FORK_MARK) + 60]
        if (MENTION.search(before) or IN_ENUMERATION.search(before)
                or MENTION_AFTER.search(after) or ENUMERATION_AFTER.search(after)):
            continue
        found.append(i)
    return found


def own_words(reply: str) -> str:
    """Что человек написал сам: без вставок, цитат и служебной разметки."""
    text = HTML_NOTE.sub("\n", PASTED.sub("\n", reply))
    text = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith(">")).strip()
    if len(text) > PASTE_MIN and PASTE_START.match(text):
        return ""                       # вставлен чужой текст целиком
    colon = text.find(":")
    if 0 <= colon <= INTRO_MAX and "\n" not in text[:colon] \
            and len(text) - colon > PASTE_MIN:
        return text[:colon].strip()     # «посмотри ревью: <вставка>»
    return text


def _norm(text: str) -> str:
    text = re.sub(r"\((?:советую|рекомендую)\)", " ", text.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def names_option(words: str, fork_text: str) -> bool:
    """Ответ — название варианта из карточки («Влить в ветку ВК сейчас»)."""
    said = _norm(words)
    if len(said) < 8:
        return False
    for m in OPTION_NAME.finditer(fork_text):
        name = _norm(OPTION_LABEL.sub("", m.group(1)))
        if len(name) >= 8 and (name in said or said in name):
            return True
    return False


def is_question_only(reply: str) -> bool:
    """Человек спросил, а не выбрал."""
    return reply_kind(reply) == "question"


def reply_kind(reply: str, fork_text: str = "") -> str:
    """Как ответ человека соотносится с развилкой.

    * `question` — спросил и не выбрал: развилка остаётся открытой, запись не нужна;
    * `choice` — есть ссылка на вариант или согласие: выбор сделан, запись ждём;
    * `unclear` — ни того ни другого («эмоджи не мешают», «дай инструкцию по
      другой теме»). Выбор ли это — видит только агент, читающий разговор;
      регулярка тут не судья. В долю не идёт ни с записью, ни без неё.

    Судятся только собственные слова человека (`own_words`), а явная ссылка на
    вариант проверяется раньше знака вопроса. `fork_text` — сама карточка:
    по ней узнаётся выбор, названный словами варианта.
    """
    words = own_words(reply)
    if not words:
        return "unclear"
    if STRONG_CUE.search(words) or (fork_text and names_option(words, fork_text)):
        return "choice"
    if "?" in words and not APPROVE.search(words):
        return "question"
    if APPROVE.search(words) or CHOICE_CUE.search(words):
        return "choice"
    return "unclear"


def human_text(obj: dict) -> str | None:
    """Текст реплики человека, либо None — если это не человек.

    Сообщение, набранное, пока агент работает, пишется вложением
    `queued_command`, а не репликой user (ревью 26.09: такие ответы не видел
    никто, и запись приписывалась чужой развилке).
    """
    msg = obj.get("message")
    if isinstance(msg, dict) and msg.get("role") == "user" \
            and (obj.get("origin") or {}).get("kind") == "human":
        return _text(msg.get("content"))
    att = obj.get("attachment")
    if isinstance(att, dict) and att.get("type") == "queued_command" \
            and (att.get("origin") or {}).get("kind") == "human":
        prompt = att.get("prompt")
        return prompt if isinstance(prompt, str) else _text(prompt)
    return None


def is_human(obj: dict) -> bool:
    """Реплика человека, а не промпт субагенту и не результат инструмента."""
    return human_text(obj) is not None


def open_fork_in_tail(lines: list[str], current_prompt: str = "") -> bool:
    """Предъявил ли агент выбор в ПОСЛЕДНЕМ своём ходе — для сторожа."""
    return bool(fork_turn_in_tail(lines, current_prompt))


def fork_turn_in_tail(lines: list[str], current_prompt: str = "") -> str:
    """Текст хода с открытой развилкой, либо пустая строка.

    Ход — все мои реплики с текстом после предыдущей реплики человека. Ревью
    25.09: сторож смотрел только последнюю реплику, а счётчик — любую до ответа
    человека, и «выбор → ещё реплика без значка → человек выбрал» сторож
    пропускал, а счётчик засчитывал. Теперь оба смотрят на ход целиком, и
    правило живёт здесь одно.

    `current_prompt` — если харнесс уже дописал новое сообщение в транскрипт до
    срабатывания сторожа, его надо перешагнуть, а не принять за границу хода.

    Уточняющий вопрос человека развилку не закрывает: «🗳️ A или B?» →
    «Сколько стоит A?» → мой ответ без значка → «берём A» — выбор по той же
    развилке (ревью 26.09: раньше она терялась). Поэтому вопрос перешагивается,
    и ход тянется до реплики человека, которая вопросом не была.
    """
    texts: list[str] = []
    skipped_current = False
    for line in reversed(lines):
        if '"message"' not in line and '"queued_command"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        said = human_text(obj)
        if said is not None:
            said = said.strip()
            if (not texts and not skipped_current and current_prompt
                    and said == current_prompt.strip()):
                skipped_current = True
                continue
            if reply_kind(said) == "question":
                continue
            break
        msg = obj.get("message")
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            text = _text(msg.get("content"))
            if text.strip():
                texts.append(text)
    turn = "\n".join(reversed(texts))
    return turn if presents_fork(turn) else ""


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
            what = (value[: m.start()] if m else value).strip(" ;,—–-")
            if not what:
                continue      # «отклонено: —» — отказа нет
            dropped.append({"what": what, "reason": m.group(1).strip() if m else ""})
    return {"kept": kept, "dropped": dropped}


def _events(path: Path):
    """Реплики одной сессии по порядку: ('human'|'assistant', текст, запись)."""
    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            if '"message"' not in line and '"queued_command"' not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            said = human_text(obj)
            if said is not None:
                yield "human", said, obj
                continue          # промпт субагенту, ретрай, координатор — не человек
            msg = obj.get("message")
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                yield "assistant", _text(msg.get("content")), obj


def scan(raw_root: Path, since: datetime | None):
    """Считает развилки и разметку, идя по сессии как по конечному автомату.

    Состояния: нет развилки → развилка предъявлена (🗳️ в моём ходе) → человек
    ответил (выбор / вопрос / неясно) → ждём блок. Блок принимается в ЛЮБОЙ
    моей реплике до следующей реплики человека: он может лечь и в первый ответ,
    и в последний после длинной работы с инструментами. Ход и вид ответа
    определяются теми же функциями, что у сторожа (`open_fork_in_tail`,
    `reply_kind`), чтобы правило и измеритель не разъезжались.
    """
    forks = marked = 0
    # Ревью 25.09, чтобы метрику нельзя было накрутить и чтобы она не считала
    # того, чего не было:
    # * `without_rejection` — блок с одним «принято»: развилка из двух и больше
    #   вариантов без единого отказа — не записанный отказ, а его отсутствие;
    # * `phantom` — блок после вопроса человека: решения не было, а журнал его
    #   записал;
    # * `unclear` — ответ без ссылки на вариант и без согласия, и агент записи
    #   не поставил: выбор ли это, неизвестно, в долю такие не идут;
    # * `after_unclear` — запись после такого же неясного ответа. В долю тоже
    #   не идёт: иначе запись после «продолжай» поднимала долю, а пропуск её
    #   никогда не опускал (ревью 26.09).
    without_rejection = phantom = unclear = questions = after_unclear = 0
    records: list[dict] = []
    # Одна сессия лежит в нескольких файлах (resume/fork копии), и без дедупа
    # та же развилка считается трижды: живой прогон давал 213 против 84
    # уникальных. Ключ — сессия плюс время ответа, как в `collect_corpus`.
    seen: set[tuple] = set()
    for path in sorted(raw_root.rglob("*.jsonl")):
        turn: list[str] = []    # мои реплики с текстом после последней реплики человека
        awaiting = None         # человек ответил на развилку; ждём блок в моём ходе
        carry = ""              # развилка, на которую человек пока только спросил

        def close(pending):
            nonlocal forks, unclear
            if pending["kind"] == "choice":
                forks += 1              # выбор сделан, записи нет
            elif pending["kind"] == "unclear":
                unclear += 1

        for role, text, obj in _events(path):
            ts = _parse_ts(obj.get("timestamp"))
            if since and ts and ts < since:
                continue

            if role == "human":
                if awaiting is not None:
                    close(awaiting)
                    awaiting = None
                fork_text = "\n".join(turn)
                turn = []
                if not presents_fork(fork_text):
                    fork_text = carry   # уточняющий вопрос развилку не закрыл
                carry = ""
                if not fork_text:
                    continue
                key = (obj.get("sessionId"), obj.get("timestamp"))
                if key in seen:
                    continue            # тот же разговор из копии файла
                seen.add(key)
                kind = reply_kind(text, fork_text)
                if kind == "question":
                    questions += 1
                    carry = fork_text
                awaiting = {
                    "kind": kind,
                    "session": obj.get("sessionId"),
                    "timestamp": obj.get("timestamp"),
                    "cwd": obj.get("cwd"),
                }
                continue

            if text.strip():
                turn.append(text)
            if awaiting is None:
                continue
            m = FENCE.search(text)
            if not m:
                continue
            rec = parse_block(m.group(1))
            if not (rec["kept"] or rec["dropped"]):
                continue                # блок-пример из объяснения формата
            kind = awaiting.pop("kind")
            rec.update(awaiting)
            awaiting = None
            if kind == "question":
                phantom += 1
                continue
            if kind == "unclear":
                after_unclear += 1
                if rec["dropped"]:
                    records.append(rec)
                continue
            forks += 1
            if rec["dropped"]:
                marked += 1
                records.append(rec)
            else:
                without_rejection += 1
        if awaiting is not None:
            close(awaiting)
    return {"forks": forks, "marked": marked, "records": records,
            "without_rejection": without_rejection, "phantom": phantom,
            "unclear": unclear, "questions": questions, "after_unclear": after_unclear}


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
        "without_rejection": res.get("without_rejection", 0),
        "phantom": res.get("phantom", 0),
        "unclear": res.get("unclear", 0),
        "questions": res.get("questions", 0),
        "after_unclear": res.get("after_unclear", 0),
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
    if stat["without_rejection"]:
        print(f"из них без разметки — блок с одним «принято», без отказов: "
              f"{stat['without_rejection']}")
    print(f"вне доли: ответ-вопрос {stat['questions']} (из них с лишней записью "
          f"{stat['phantom']}), неясный ответ: без записи {stat['unclear']}, "
          f"с записью {stat['after_unclear']}")
    if stat["rejections"]:
        print(f"отказов записано: {stat['rejections']}, из них без названной "
              f"причины: {stat['rejections_without_reason']} "
              f"(доля {stat['no_reason_share']})")
        dashed = sum(1 for r in res["records"] for d in r["dropped"]
                     if not d["reason"] and DASH.search(d["what"]))
        if dashed:
            print(f"  из них {dashed} — старый формат «вариант — причина» (до 26.09): "
                  f"причина, возможно, была, но читается только после «причина:»")
    print("\nОговорка: развилкой считается мой ход с маркером 🗳️, разрешением — "
          "ответ человека со ссылкой на вариант или согласием; ответ-вопрос "
          "развилку не закрывает. Развилка, предъявленная БЕЗ маркера, "
          "в знаменатель не попадает — это известная дыра метрики. Отказ без "
          "причины не дефект: причина ставится только если прозвучала.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
