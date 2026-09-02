#!/usr/bin/env python3
"""Отжатый слой памяти: поиск «что мы про это уже решали» + проверка связей.

Два режима над одним разбором, как `infra_graph.py` — снапшот и `--check`.

**search** отвечает на вопрос, которого до сих пор не задавали: разбиралось ли
это раньше. Ищет НЕ по сырым транскриптам, а по отжатому слою — заметки
research, спеки, ADR, задачи. Причина в замере: подстрочный поиск по корпусу
дал одно осмысленное попадание из четырёх, потому что в транскриптах лексика
случайная, а в описании заметки — уже отжатая суть.

Две вещи, без которых поиск по русскому не работает и которые проверены
замером, а не предположением:

* **стемминг** — «памяти» и «память» это разные строки, и без обрезки
  окончаний запрос «короткая память агента» не находит заметку «движки памяти
  для агентов». С обрезкой находит (0.67);
* **пары ru/en** — 57 из 66 узлов названы латиницей при русском описании, так
  что «экономия контекста» и `context-economy` расходятся. Словарь пар ниже
  закрывает доменные термины; он намеренно короткий, кандидат в него
  добавляется по факту промаха, а не про запас.

**check** ищет дыры в связях между артефактами тем же приёмом, каким
`infra_graph.py --check` ищет сирот и дубли в инфраструктуре: спека без AC
непроверяема, узел без единой ссылки выпал из графа, задача без спеки не
знает, откуда взялась.

Использование:
    python3 core/scripts/memory_graph.py search "короткая память агента"
    python3 core/scripts/memory_graph.py check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path.home() / "Work" / "memory"
AREAS = ("notes/research", "specs", "notes", "tasks")

STOP = set("""и в во не что на я с со как а то все так но да ты к у же вы за по для из о от при
над про это эти этот там где его её они мы вам нам был была было были есть быть или либо если
чтобы когда уже ещё еще только тоже также без под над между""".split())

# Пары ru↔en доменных терминов. Короткий по умыслу: слово попадает сюда после
# зафиксированного промаха поиска, а не «на всякий случай».
PAIRS = {
    "памят": "memor", "хук": "hook", "контекст": "context", "решен": "decision",
    "тест": "test", "задач": "task", "спек": "spec", "правил": "rule",
    "поиск": "search", "сессия": "session", "сесси": "session", "агент": "agent",
    "граф": "graph", "снапшот": "snapshot", "истор": "histor", "сжат": "compact",
    # Добавлено по промаху 2026-08-13: запрос «круглый стол забывает решения» не
    # находил разбор пяти кругов ревью — в его описании вендорское Roundtable.
    "стол": "roundtable", "ревью": "review", "круг": "round",
}
PAIRS.update({v: k for k, v in PAIRS.items()})

# Порядок значим: длинные окончания проверяются раньше коротких, иначе
# «критериев» срежется по «ев» до «критери», а «критерий» по «ий» до «критер»,
# и формы одного слова разойдутся. Список рос по промахам, не про запас.
SUFFIXES = ("ениями", "ениям", "ования", "ование", "ениях", "иями", "ения",
            "ению", "ением", "иях", "иям", "иев", "ием", "ами", "ями", "ии",
            "ию", "ов", "ев", "ей", "ий", "ая", "ое", "ые", "ый", "ь", "и",
            "ы", "а", "у", "е", "о", "я")

WORD = re.compile(r"[а-яa-zё][а-яa-z0-9ё-]{2,}", re.I)


def stem(word: str) -> str:
    w = word.lower()
    for suf in SUFFIXES:
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> set[str]:
    """Слова → основы → плюс их пара на другом языке."""
    base = {stem(w) for w in WORD.findall(text) if w.lower() not in STOP}
    out = set(base)
    for t in base:
        for key, twin in PAIRS.items():
            if t.startswith(key):
                out.add(twin)
    return out


def load() -> list[dict]:
    docs = []
    for area in AREAS:
        d = ROOT / area
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                head = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            desc_m = re.search(r'^description:\s*"?(.+?)"?\s*$', head[:2000], re.M)
            h1_m = re.search(r"^#\s+(.+)$", head[:2000], re.M)
            desc = desc_m.group(1) if desc_m else ""
            docs.append({
                "path": f,
                "area": area,
                "name": f.stem,
                "desc": desc,
                "title": h1_m.group(1) if h1_m else "",
                "terms": terms(f.stem.replace("-", " ") + " " + desc + " " + (h1_m.group(1) if h1_m else "")),
                "links": set(re.findall(r"\[\[([^\]|#]+)", head)),
                "ac": head.count("#ac"),
                "body": head,
            })
    return docs


def cmd_search(args) -> int:
    docs = load()
    q = terms(args.query)
    if not q:
        print("пустой запрос", file=sys.stderr)
        return 2
    scored = []
    for d in docs:
        hit = q & d["terms"]
        if hit:
            scored.append((len(hit) / len(q), d, hit))
    scored.sort(key=lambda x: -x[0])
    scored = [s for s in scored if s[0] >= args.min_score][: args.limit]

    if args.json:
        print(json.dumps([{"score": round(s, 2), "path": str(d["path"]),
                           "desc": d["desc"]} for s, d, _ in scored],
                         ensure_ascii=False, indent=2))
        return 0
    print(f"узлов в отжатом слое: {len(docs)}; запрос: «{args.query}»\n")
    if not scored:
        print("  Ничего — тему в отжатом слое не разбирали.")
        print("  Это ответ, а не сбой: значит решение принимается впервые.")
        return 0
    for s, d, hit in scored:
        print(f"  {s:.2f}  {d['path'].relative_to(ROOT)}")
        if d["desc"]:
            print(f"        {d['desc'][:150]}")
        print(f"        совпало: {', '.join(sorted(hit))}")
    return 0


def cmd_check(args) -> int:
    docs = load()
    by_name = {d["name"]: d for d in docs}
    incoming = {d["name"]: 0 for d in docs}
    for d in docs:
        for link in d["links"]:
            key = link.strip().replace(" ", "-")
            for cand in (link.strip(), key):
                if cand in incoming:
                    incoming[cand] += 1

    specs = [d for d in docs if d["area"] == "specs" and not d["name"].startswith("_")]
    no_ac = [d for d in specs if d["ac"] == 0]
    no_out = [d for d in docs if not d["links"] and not d["name"].startswith("_")]
    orphan = [d for d in docs
              if incoming[d["name"]] == 0 and not d["name"].startswith(("_", "00-"))]
    ac_no_test = [d for d in specs
                  if d["ac"] > 0 and not re.search(r"e2e|playwright|сценар|тест", d["body"], re.I)]

    def show(title, items, hint):
        print(f"\n{title}: {len(items)}")
        if hint and items:
            print(f"  ({hint})")
        for d in items[: args.limit]:
            print(f"  - {d['path'].relative_to(ROOT)}")

    print(f"узлов: {len(docs)} (спек: {len(specs)})")
    show("спеки без AC — принять работу не по чему", no_ac,
         "AC это то, чем закрывается задача; без них спека нечитаема как контракт")
    show("спеки с AC, но без единого упоминания теста или сценария", ac_no_test,
         "критерий есть, проверять его нечем — разрыв AC↔e2e")
    show("узлы без единой исходящей ссылки", no_out,
         "выпали из графа: до них не дойти по связям")
    show("узлы, на которые никто не ссылается", orphan,
         "написано и забыто — ровно то, что потом переоткрывают")
    total = len(no_ac) + len(ac_no_test) + len(no_out) + len(orphan)
    print(f"\nвсего замечаний: {total}")
    return 1 if (args.strict and total) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="что мы про это уже решали")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--min-score", type=float, default=0.3)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)
    c = sub.add_parser("check", help="дыры в связях артефактов")
    c.add_argument("--limit", type=int, default=8)
    c.add_argument("--strict", action="store_true", help="ненулевой код при замечаниях")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
