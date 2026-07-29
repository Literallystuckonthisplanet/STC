#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Правила «линзы запроса» (H22 / FR-30) — ЕДИНСТВЕННЫЙ источник.

Импортируют оба потребителя:
  - `core/hooks/prompt-lens.sh`    — рантайм: приписка-подсказка к запросу;
  - `core/scripts/prompt-audit.py` — офлайн: месячный аудит здоровья правил;
  - `core/hooks/tests/prompt-lens.test.sh` — страж по корпусу.

ЗАЧЕМ ОДИН МОДУЛЬ. Раньше правила жили в трёх копиях, и копия в аудите была
без контекстных гейтов: аудит показывал MULTI_TASK 206 там, где хук срабатывал
69 раз. Измеритель, живущий отдельно от правила, врёт по определению — и не
замечает, что правило умерло. Правило и его счётчик обязаны быть одним кодом.

ADR (buy-vs-build): взяли стандартный `re`, не морфологию (pymorphy3/natasha),
потому что модуль стартует на КАЖДОЕ сообщение пользователя — нужен нулевой
вес и отсутствие зависимостей. Тяжёлую морфологию проект уже сознательно
держит только в офлайн-аудите.

ГЛАВНАЯ ЛОВУШКА (см. core/memory/reference_cyrillic_regex.md):
нормализация переводит латинские двойники В КИРИЛЛИЦУ, поэтому регулярку
НЕЛЬЗЯ писать латиницей — `stc` после нормализации это `сtc`, и латинская
альтернатива не совпадёт никогда. Все словари ниже пропускаются через
`normalize()` при сборке — руками альтернативы не пишем.
"""
from __future__ import annotations
import re

# --- нормализация ---------------------------------------------------------
# Двойники кириллица↔латиница — артефакт диктовки и раскладки. Нормализуем
# В КИРИЛЛИЦУ: человек диктует по-русски, правила кириллические.
LAT2CYR = str.maketrans({
    "s": "с", "e": "е", "o": "о", "a": "а", "p": "р", "x": "х", "y": "у", "k": "к",
    "S": "С", "E": "Е", "O": "О", "A": "А", "P": "Р", "X": "Х", "Y": "У", "K": "К",
})


def normalize(text: str) -> str:
    """Текст для сравнения внутри линзы. Запрос пользователя НЕ переписывается."""
    if not text:
        return ""
    return text.replace("ё", "е").replace("Ё", "Е").translate(LAT2CYR).lower()


# --- границы токена (без \w/\b — они не знают кириллицу) ------------------
EDGE = r"(?:^|[^а-яa-z0-9])"
EDGEE = r"(?:[^а-яa-z0-9]|$)"
# Для кличек дефис и подчёркивание — ЧАСТЬ токена: иначе «forest» совпадает
# внутри «forest-echoes-www», и линза расшифровывает то, что уже написано.
NICK_EDGE = r"(?:^|[^а-яa-z0-9_-])"
NICK_EDGEE = r"(?:[^а-яa-z0-9_-]|$)"


def _alt(words) -> str:
    """Альтернация из нормализованных слов, длинные — первыми."""
    norm_words = sorted({normalize(w) for w in words}, key=len, reverse=True)
    return "|".join(re.escape(w) for w in norm_words)


DANGLING_WORDS = ["это", "там", "то же самое", "как раньше", "вот это", "тот самый"]
DEGREE_WORDS = ["немного", "чуть-чуть", "чуть", "поаккуратнее", "получше", "пожёстче",
                "нейтральнее", "немножко", "помягче", "посильнее", "вроде", "типа"]
OPEN_VERBS = ["сделай", "посмотри", "проверь", "почини", "поправь", "исправь",
              "обнови", "убери"]
TASK_VERBS = ["сделай", "сделать", "добавь", "добавить", "проверь", "проверить",
              "почини", "поправь", "обнови", "убери", "вынеси", "перенеси",
              "переименуй", "запусти", "настрой"]

RE_DANGLING = re.compile(EDGE + "(" + _alt(DANGLING_WORDS) + ")" + EDGEE)
RE_DEGREE = re.compile(EDGE + "(" + _alt(DEGREE_WORDS) + ")" + EDGEE)
RE_OPEN_VERB = re.compile(EDGE + "(" + _alt(OPEN_VERBS) + ")" + EDGEE)
RE_TASK_VERB = re.compile(EDGE + "(" + _alt(TASK_VERBS) + ")" + EDGEE)

# Гейт градуса: слово-градус опасно только когда правят существующий текст/вид.
RE_EDIT = re.compile(_alt(["стил", "текст", "тон", "голос", "нейтральн", "формал",
                           "пост", "описани", "копирайт", "лент", "письм", "страниц"]))

# Гейт открытого глагола: критерий готовности уже назван словами.
RE_CRITERION = re.compile(_alt(["готово", "чтобы", "чтоб", "должн", "критери",
                                "как только", "при услови", "пока не"]))

# Конкретный объект: путь, ссылка, имя файла, что-то в обратных кавычках.
RE_OBJECT = re.compile(
    r"(/[a-zA-Zа-яА-Я]|https?://|~/|`[^`]+`"
    r"|[-\w]+\.(?:md|py|sh|ts|tsx|js|jsx|json|yaml|yml|css|sql|toml|txt|env))"
)

# Куски, где клички не считаются: ссылки, пути, доменные имена.
RE_URL_OR_PATH = re.compile(
    r"(https?://\S+|~?/[\w./~-]+|[\w-]+\.(?:com|ru|dev|io|org|net)\b)"
)
# Цитаты чужого текста: глаголы внутри них — не задачи пользователя.
RE_QUOTED = re.compile(r"(«[^»]*»|\"[^\"]*\"|```.*?```|`[^`]+`)", re.S)

MULTI_TASK_MIN = 3

# --- клички проектов ------------------------------------------------------
# Каждая кличка ПОСЧИТАНА по корпусу (страж-тест валится, если у клички <3
# реальных срабатываний). Поэтому здесь нет «стц» (0 срабатываний) и «wt»
# (1) — кандидат без частоты не включается.
# Пути проверены на диске: проекты лежат в ~/Work/projects/<name>.
PROJECTS = [
    {"key": "forest-echoes",
     "aliases": ["фе", "fe", "форест", "forest"],
     "expansion": "forest-echoes-www (~/Work/projects/forest-echoes-www)"},
    {"key": "driada",
     "aliases": ["дриада", "driada"],
     "expansion": "driada-www (~/Work/projects/driada-www)"},
    {"key": "stc",
     "aliases": ["stc"],
     "expansion": "STC (~/Work/STC)"},
    # «лекс» (2 срабатывания) и «црм» (0) сюда НЕ попали: страж-тест их
    # отбраковал по частоте. Кандидат без частоты не включается.
    {"key": "lex-digest",
     "aliases": ["lex"],
     "expansion": "lex-digest (~/Work/projects/lex-digest)"},
    {"key": "crm",
     "aliases": ["crm"],
     "expansion": "forest-echoes-crm (~/Work/projects/forest-echoes-crm)"},
    {"key": "worktree",
     "aliases": ["вт", "ворктри"],
     "expansion": "git worktree (команда, не проект)"},
]

_NICK2PROJECT = {}
for _p in PROJECTS:
    for _a in _p["aliases"]:
        _NICK2PROJECT[normalize(_a)] = _p
RE_NICK = re.compile(NICK_EDGE + "(" + _alt([a for p in PROJECTS for a in p["aliases"]])
                     + ")" + NICK_EDGEE)

MIN_LEN = 4          # короче — шум, не запрос
MAX_WARNINGS = 4     # анти-обои
MAX_NICKS = 2


def _strip(rx, text: str) -> str:
    """Вырезать кусок, СОХРАНИВ длину — чтобы позиции совпадали с исходником.

    Замена на один пробел сдвигает индексы, и тогда по совпадению уже нельзя
    достать то, что человек реально написал (кличка печаталась как «driаdа» —
    внутренний нормализованный вид вместо «driada»).
    """
    return rx.sub(lambda m: " " * len(m.group(0)), text)


def analyze(prompt: str, min_len: int = MIN_LEN, fresh_context: bool | None = None) -> list[dict]:
    """Вернуть флаги линзы для запроса.

    Каждый флаг: {"rule", "hit", "ru", "en"}. Пустой список = линза молчит.
    Ровно эта функция работает и в хуке, и в аудите — цифры отчёта равны
    реальным срабатываниям по построению.

    fresh_context: True — разговор только начался (у агента нет контекста),
    False — контекст уже наработан, None — неизвестно. Влияет на висячие
    ссылки: «это/там» в середине разговора почти всегда указывает на то, что
    обсуждалось минуту назад. По корпусу: из 137 срабатываний правила только
    7 приходились на первое сообщение сессии — в остальных 130 подсказка
    «контекста нет, переспроси» была просто неверной.
    """
    if not prompt or len(prompt) < min_len:
        return []
    norm_full = normalize(prompt)
    # Цитаты вырезаем для ВСЕХ правил: «сделай проверь поправь» в пересказе
    # чужих слов — не поручение. Длина сохраняется, позиции = позиции в prompt.
    norm = _strip(RE_QUOTED, norm_full)
    warnings: list[dict] = []

    has_object = bool(RE_OBJECT.search(prompt))
    has_criterion = bool(RE_CRITERION.search(norm_full))

    # 1. Висячая ссылка — только когда объекта рядом нет, запрос короткий И
    #    контекста в разговоре ещё нет (первое сообщение сессии).
    m = RE_DANGLING.search(norm)
    if m and not has_object and len(prompt) < 200 and fresh_context is not False:
        warnings.append({
            "rule": "DANGLING", "hit": m.group(1),
            "ru": "⚠ висячая ссылка «%s»: контекста нет — не угадывать, переспросить одной строкой." % m.group(1),
            "en": "⚠ dangling ref «%s»: no context — do not guess, ask in one line." % m.group(1),
        })

    # 2. Слово-градус — только при правке существующего текста/вида.
    m = RE_DEGREE.search(norm)
    if m and RE_EDIT.search(norm):
        warnings.append({
            "rule": "DEGREE", "hit": m.group(1),
            "ru": "⚠ градус без меры «%s» → предъяви шкалу (сейчас X/10 → предлагаю Y/10), не исполняй на глаз." % m.group(1),
            "en": "⚠ degree word «%s» without measure → show a scale, do not execute on guess." % m.group(1),
        })

    # 3. Открытый глагол — только когда НЕТ ни критерия готовности, ни
    #    конкретного объекта. Без этого гейта флаг спорил с самим запросом
    #    («поправь X в footer.tsx, готово когда тесты зелёные» → «без критерия»).
    m = RE_OPEN_VERB.search(norm)
    if m and not has_criterion and not has_object:
        warnings.append({
            "rule": "OPEN_VERB", "hit": m.group(1),
            "ru": "⚠ открытый глагол «%s» без критерия и без объекта → добавь «готово, когда: …»." % m.group(1),
            "en": "⚠ open verb «%s» with no criterion and no object → add a done-when line." % m.group(1),
        })

    # 4. Несколько задач разом. Глаголы внутри цитат не считаем — это чужой
    #    текст, а не поручение.
    n_tasks = len(RE_TASK_VERB.findall(norm))
    if n_tasks >= MULTI_TASK_MIN:
        warnings.append({
            "rule": "MULTI_TASK", "hit": str(n_tasks),
            "ru": "⚠ в сообщении ~%d задач → подтверди разбивку, бери одну." % n_tasks,
            "en": "⚠ ~%d tasks in one message → confirm the split, take one." % n_tasks,
        })

    # 5. Клички. Расшифровка нужна там, где проект назван ТОЛЬКО кличкой:
    #    если в сообщении уже есть путь, ссылка или имя файла, агент и так
    #    знает, где работать, — лишняя строка это шум (по корпусу такой гейт
    #    снимает больше половины срабатываний).
    nicks: list[dict] = []
    seen_projects = set()
    for m in ([] if has_object else RE_NICK.finditer(_strip(RE_URL_OR_PATH, norm))):
        proj = _NICK2PROJECT.get(m.group(1))
        if not proj or proj["key"] in seen_projects:
            continue
        seen_projects.add(proj["key"])
        # Показываем то, что человек написал сам (позиции сохранены), а не
        # внутренний нормализованный вид.
        nick = prompt[m.start(1):m.end(1)]
        nicks.append({
            "rule": "NICK", "hit": nick,
            "ru": "• кличка «%s» → %s." % (nick, proj["expansion"]),
            "en": "• nick «%s» → %s." % (nick, proj["expansion"]),
        })

    return warnings[:MAX_WARNINGS] + nicks[:MAX_NICKS]


# --- канарейки: чем проверяется, что линза жива ---------------------------
# Используют и страж-тест, и месячный аудит. Правило, которое молча перестало
# срабатывать, ловится здесь, а не через месяц по отсутствию флагов.
CANARIES = [
    ("посмотри это и поправь тоже", "DANGLING"),
    ("стиль немного нейтральнее сделай", "DEGREE"),
    ("посмотри логи", "OPEN_VERB"),
    ("сделай x, проверь y, поправь z", "MULTI_TASK"),
    ("фе собери и задеплой", "NICK"),
    ("собери fe и выложи", "NICK"),
    ("почини stc деплой", "NICK"),
    ("обнови driada каталог", "NICK"),
]
# Обратные канарейки: здесь линза ОБЯЗАНА молчать по этому правилу.
SILENT_CANARIES = [
    ("я немного устал сегодня", "DEGREE"),
    ("поправь заголовок в footer.tsx, готово когда тесты зелёные", "OPEN_VERB"),
    ("посмотри ~/Work/STC/core/hooks/prompt-lens.sh", "OPEN_VERB"),
    ("вот что написал заказчик: «сделай проверь поправь» — что он имел в виду", "MULTI_TASK"),
    ("открой https://forest-echoes.com/catalog", "NICK"),
]


def self_check() -> list[str]:
    """Прогнать канарейки. Пустой список = линза жива."""
    problems = []
    for text, rule in CANARIES:
        if rule not in {f["rule"] for f in analyze(text)}:
            problems.append(f"правило {rule} НЕ сработало на «{text}»")
    for text, rule in SILENT_CANARIES:
        if rule in {f["rule"] for f in analyze(text)}:
            problems.append(f"правило {rule} сработало там, где должно молчать: «{text}»")
    # Гейт контекста: та же фраза в начале разговора и в его середине.
    dangling = "посмотри это и поправь тоже"
    if "DANGLING" not in {f["rule"] for f in analyze(dangling, fresh_context=True)}:
        problems.append("DANGLING не сработал в начале разговора (fresh_context=True)")
    if "DANGLING" in {f["rule"] for f in analyze(dangling, fresh_context=False)}:
        problems.append("DANGLING сработал в середине разговора (fresh_context=False)")
    return problems


if __name__ == "__main__":
    import sys
    bad = self_check()
    if bad:
        print("линза сломана:")
        for b in bad:
            print("  -", b)
        sys.exit(1)
    print(f"линза жива: {len(CANARIES)} канареек + {len(SILENT_CANARIES)} обратных — ок")
