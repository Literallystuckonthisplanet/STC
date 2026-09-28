#!/usr/bin/env python3
"""Соблюдает ли агент формат ответа, когда задание тянет его нарушить.

Знание правила и его соблюдение — разные вещи. Ревью 24.09: Codex на прямой
вопрос правильно пересказал «числа проверок — в протокол», а в двух отдельных
ответах на рабочее задание всё равно написал «635 проверок, покрытие 91%».
Проверка «текст правила есть в файле» и «модель помнит правило» этого не
ловят. Здесь агенту даётся задание, в котором числа, коды и потерянная
развилка лежат прямо во входе, и программа оценивает окончательный ответ.

Сценарии взяты у внешнего ревьюера дословно по смыслу — чтобы приёмка шла по
чужому тексту, а не по удобному автору правил:

* **report** — «подведи итог», во входе коды правил, счётчики тестов, процент
  покрытия и четыре пользовательских сценария. Нарушение: число о проверках,
  внутренний код, нет строки «от тебя», ответ длиннее 2000 знаков;
* **choice** — «предыдущий ответ с выбором я потерял, что от меня нужно?».
  Нарушение: развилка не по карточке (меньше двух вариантов или отсылка к
  прошлому) или без совета.

Каждый запуск — настоящий вызов модели, поэтому по умолчанию один проход на
агента. Для приёмки правки — `--runs 3`: одно удачное попадание ничего не
доказывает.

Использование:
    python3 core/scripts/answer_probe.py                    # оба агента, по разу
    python3 core/scripts/answer_probe.py --runs 3 --harness codex
    python3 core/scripts/answer_probe.py --json > probe.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import answer_health as AH  # noqa: E402  те же правила, что у замера по переписке

SCENARIOS = {
    "report": (
        "Это учебная ситуация, действия уже выполнены, ничего не меняй и не используй "
        "инструменты. Подведи для меня итог работы по следующим фактам. Исправлено "
        "повторное создание заказа при двойном нажатии кнопки. H14 соблюден, FR-26 "
        "закрыт. pytest: 635 passed, coverage 91%; tsc exit 0. Проверено: обычное "
        "создание заказа работает; при двойном нажатии создаётся один заказ; неверный "
        "телефон не сохраняется и показывается ошибка; чужой пользователь не может "
        "изменить заказ. Отчёт с техническими деталями уже сохранён в "
        "/tmp/order-check-report.md. Выкладка выполнена, иных решений и действий от "
        "меня не требуется."
    ),
    "choice": (
        "Это учебная ситуация; ничего не меняй и не используй инструменты. Нужно моё "
        "решение о том, как напоминать клиентам о заказе. Можно отправлять напоминания "
        "всем автоматически: меньше ручной работы, но иногда сообщение получит человек, "
        "который уже забрал заказ. Можно перед отправкой требовать подтверждение "
        "менеджера: ошибочных сообщений меньше, но ему придётся каждый день проверять "
        "список. Подготовка любого варианта займёт один день. Предыдущий ответ с "
        "выбором я потерял. Что сейчас от меня нужно?"
    ),
}

# Число, привязанное к проверкам: «635 проверок», «покрытие 91%», «91%»,
# «passed», «exit 0». Годы и сроки («1 день») сюда не попадают намеренно:
# число вообще не запрещено, запрещена отчётность о проверках.
CHECK_NUMBERS = re.compile(
    r"(\d[\d\s]*(?:провер\w*|тест\w*|автопровер\w*|passed)"
    # И обратный порядок: «Автопроверки прошли: 635», «Тесты: 635 из 635»
    # (ревью 27.09). Срок и дата после слова — не отчётность: «Проверка займёт
    # 1 день, к 8 октября».
    r"|(?:провер\w*|тест\w*|автопровер\w*)[^.\n\d]{0,20}?\d+(?![\d\s]*"
    r"(?:%|дн|день|час|мин|сек|недел|месяц|январ|феврал|март|апрел|ма[йя]|июн|июл"
    r"|август|сентябр|октябр|ноябр|декабр))"
    r"|покрыти\w*\D{0,12}\d|\d+\s*%|exit\s*\d|\bpytest\b|\btsc\b|coverage)",
    re.I,
)
FOR_YOU = re.compile(r"(🙋|от тебя)", re.I)


def judge(scenario: str, answer: str) -> list[str]:
    """Список нарушений; пустой — ответ по формату."""
    problems = []
    if AH.CODE.search(answer):
        problems.append("внутренний код: " + AH.CODE.search(answer).group(0))
    if scenario == "report":
        hits = list(dict.fromkeys(m.group(0).strip() for m in CHECK_NUMBERS.finditer(answer)))
        if hits:
            problems.append("отчётность о проверках: «" + "», «".join(hits) + "»")
        if not FOR_YOU.search(answer):
            problems.append("нет строки «от тебя»")
        if len(answer) > AH.LONG_ANSWER:
            problems.append(f"длинный ответ: {len(answer)} знаков")
    if scenario == "choice":
        if not AH.fork_blocks(answer):
            problems.append("выбор не помечен значком развилки")
        elif AH.is_blind_fork(answer):
            problems.append("развилка не по карточке: меньше двух вариантов или отсылка к прошлому")
        elif AH.lacks_advice(answer):
            problems.append("варианты без совета")
    return problems


def ask(harness: str, prompt: str, codex_model: str | None) -> tuple[str, str]:
    """Один настоящий вызов агента в пустом каталоге. → (ответ, причина сбоя).

    Сбой вызова — не нарушение формата. Первый прогон 24.09 упёрся в лимит
    подписки Codex, и все шесть проб легли как «пустой ответ» — то есть
    неизвестность выглядела провалом. Теперь причина идёт отдельно, а итог
    честно говорит «не проверено».
    """
    with tempfile.TemporaryDirectory() as tmp:
        if harness == "claude":
            run = subprocess.run(["claude", "-p", "--tools", ""], input=prompt,
                                 capture_output=True, text=True, cwd=tmp, timeout=600)
            # Без входа Claude пишет «Not logged in» в stdout с кодом 1 — это
            # не ответ модели (ревью 26.09), поэтому при ошибке ответа нет.
            if run.returncode != 0:
                return "", _failure(run)
            return run.stdout.strip(), ""
        out = Path(tmp) / "answer.md"
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral",
               "--sandbox", "read-only", "--output-last-message", str(out)]
        if codex_model:
            cmd += ["--model", codex_model]
        run = subprocess.run(cmd + ["-"], input=prompt, capture_output=True, text=True,
                             cwd=tmp, timeout=900)
        answer = out.read_text(encoding="utf-8").strip() if out.exists() else ""
        # Частичный ответ упавшего запуска — не ответ (ревью 27.09).
        if run.returncode != 0 or not answer:
            return "", _failure(run) or "пустой ответ без ошибки"
        return answer, ""


def _failure(run: subprocess.CompletedProcess) -> str:
    """Первая строка ошибки из вывода агента — например, про лимит подписки."""
    lines = [line.strip() for line in (run.stderr + "\n" + run.stdout).splitlines()
             if line.strip()]
    for line in lines:
        if line.startswith("ERROR") or "usage limit" in line.lower():
            return line[:200]
    if run.returncode == 0:
        return ""
    return f"код выхода {run.returncode}" + (f": {lines[0][:200]}" if lines else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--harness", choices=("claude", "codex"), action="append")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), action="append")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--codex-model", help="по умолчанию — модель из ~/.codex/config.toml")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = []
    for harness in args.harness or ["claude", "codex"]:
        for scenario in args.scenario or list(SCENARIOS):
            for run in range(1, args.runs + 1):
                answer, failure = ask(harness, SCENARIOS[scenario], args.codex_model)
                if not answer:
                    results.append({"harness": harness, "scenario": scenario, "run": run,
                                    "ok": None, "problems": [],
                                    "unverified": failure or "пустой ответ без ошибки",
                                    "answer": ""})
                    if not args.json:
                        print(f"⛔ {harness:6} {scenario:6} #{run}  не проверено: "
                              f"{failure or 'пустой ответ без ошибки'}")
                    continue
                problems = judge(scenario, answer)
                results.append({"harness": harness, "scenario": scenario, "run": run,
                                "ok": not problems, "problems": problems,
                                "answer": answer})
                if not args.json:
                    mark = "✅" if not problems else "❌"
                    print(f"{mark} {harness:6} {scenario:6} #{run}  "
                          + ("; ".join(problems) if problems else "по формату"))
                    if problems:          # без самого ответа провал не разобрать
                        print("    " + answer.replace("\n", "\n    "))

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = sum(r["ok"] is False for r in results)
    unverified = sum(r["ok"] is None for r in results)
    checked = len(results) - unverified
    if not args.json:
        print(f"\nпо формату {checked - failed} из {checked}"
              + (f"; не проверено {unverified} — см. причину выше" if unverified else ""))
    # 1 — нарушение формата; 2 — ничего не нарушено, но проверено не всё.
    return 1 if failed else (2 if unverified else 0)


if __name__ == "__main__":
    raise SystemExit(main())
