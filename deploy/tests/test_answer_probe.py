"""Проба формата судит сам ответ, а не память модели о правиле.

Образцы — живые ответы из ревью 24.09: Codex вывел «91%» и «635 проверок»,
зная правило; Claude в тех же заданиях уложился в формат.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "scripts"))

import answer_probe as P  # noqa: E402

CASES = ROOT / "deploy" / "tests" / "fixtures" / "answer_probe"


def _read(name: str) -> str:
    return (CASES / name).read_text(encoding="utf-8")


def test_check_numbers_in_a_report_are_violations():
    assert any("91%" in p for p in P.judge("report", _read("report_bad_codex_percent.md")))
    assert any("635" in p for p in P.judge("report", _read("report_bad_codex_count.md")))


def test_scenario_only_report_passes():
    assert P.judge("report", _read("report_good_claude.md")) == []


def test_real_choice_cards_pass():
    assert P.judge("choice", _read("choice_good_claude.md")) == []
    assert P.judge("choice", _read("choice_good_codex.md")) == []


def test_lost_choice_answered_by_reference_fails():
    answer = "🎯 Выбор тот же.\n\n🗳️ Прежняя развилка всё ещё за тобой — ответь, как решишь."
    assert P.judge("choice", answer)


def test_ordinary_numbers_are_not_check_reporting():
    """Срок «1 день» и дата — не отчётность о проверках."""
    answer = "🎯 Готово к 8 октября.\n\n🙋 От тебя: ничего. Подготовка займёт 1 день."
    assert P.judge("report", answer) == []


def test_a_failed_launch_is_unverified_not_a_format_failure(monkeypatch):
    """Ревью 26.09: без входа Claude печатает «Not logged in» в stdout с кодом 1.

    Раньше эта строка уходила в судью как ответ модели и давала ложный
    «провал формата». Сбой запуска — неизвестность, а не нарушение.
    """
    import subprocess

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="Not logged in · Please run /login\n",
                                           stderr="")

    monkeypatch.setattr(P.subprocess, "run", fake_run)
    answer, failure = P.ask("claude", "проба", None)
    assert answer == ""
    assert "Not logged in" in failure

    monkeypatch.setattr(sys, "argv", ["answer_probe.py", "--harness", "claude",
                                      "--scenario", "report"])
    assert P.main() == 2


def test_a_failed_answer_is_shown_so_it_can_be_read(monkeypatch, capsys):
    """Проба 26.09: Codex однажды не поставил значок развилки, но ответ не
    сохранился, и разобрать причину было нельзя. Провал печатается с ответом."""
    monkeypatch.setattr(P, "ask", lambda *a: ("Выбери: автоматически или вручную.", ""))
    monkeypatch.setattr(sys, "argv", ["answer_probe.py", "--harness", "codex",
                                      "--scenario", "choice"])
    assert P.main() == 1
    assert "Выбери: автоматически или вручную." in capsys.readouterr().out


def test_a_codex_failure_with_a_partial_answer_is_unverified(monkeypatch):
    """Ревью 27.09: Codex успел сохранить частичный ответ и упал с кодом 1 —
    проба судила частичный ответ и выходила с успехом."""
    import subprocess
    from pathlib import Path

    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("--output-last-message") + 1]).write_text(
            "🎯 Готово.\n🙋 От тебя: ничего.", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ERROR interrupted")

    monkeypatch.setattr(P.subprocess, "run", fake_run)
    answer, failure = P.ask("codex", "проба", None)
    assert answer == "" and "interrupted" in failure
    monkeypatch.setattr(sys, "argv", ["answer_probe.py", "--harness", "codex",
                                      "--scenario", "report"])
    assert P.main() == 2


def test_a_number_after_the_check_word_is_still_check_reporting():
    for answer in ("✅ Автопроверки прошли: 635.", "✅ Проверок прошло 635.",
                   "✅ Тесты: 635 из 635 прошли."):
        assert any("отчётность" in p for p in P.judge("report", "🙋 От тебя: ничего.\n" + answer)), answer
    assert P.judge("report", "🙋 От тебя: ничего.\n✅ Прошло 635 проверок.")
    # Срок и дата рядом со словом «проверка» — не отчётность о проверках.
    assert P.judge("report", "🙋 От тебя: ничего.\nПроверка займёт 1 день, к 8 октября.") == []
