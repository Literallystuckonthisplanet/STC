"""Страж для поиска по отжатому слою и проверки связей.

Стережётся то, что было выведено замером, а не догадкой: без стемминга и без
пар ru/en поиск по русскому корпусу с латинскими именами файлов не работает.
Запрос «короткая память агента» не находил заметку «движки памяти для агентов»
ровно поэтому — и именно так тема, разобранная 28.07, переоткрывалась заново.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import memory_graph  # noqa: E402


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    (tmp_path / "notes" / "research").mkdir(parents=True)
    (tmp_path / "specs").mkdir()
    monkeypatch.setattr(memory_graph, "ROOT", tmp_path)
    return tmp_path


def _note(vault, rel, desc, body=""):
    p = vault / rel
    p.write_text(f'---\ndescription: "{desc}"\n---\n\n# {desc[:40]}\n\n{body}\n',
                 encoding="utf-8")
    return p


def test_stemming_bridges_russian_word_forms(vault):
    """Формы одного слова должны сходиться.

    Слова взяты ВНЕ словаря пар ru/en намеренно: первая версия теста брала
    «память», и он проходил даже с выключенным стеммингом — пара памят↔memor
    сводила формы за него. Тест, зелёный по чужой причине, ничего не стережёт.
    """
    _note(vault, "notes/research/rules.md", "Разбор критериев приёмки и сценариев")
    docs = memory_graph.load()
    q = memory_graph.terms("критерий и сценарий")
    assert not (memory_graph.PAIRS.keys() & q), "слова теста не должны быть в словаре пар"
    assert q & docs[0]["terms"], "стемминг не связал формы слова"


def test_latin_filename_is_reachable_by_a_russian_query(vault):
    """57 из 66 узлов названы латиницей при русском описании — без пар ru/en они немы."""
    _note(vault, "specs/context-economy-handoff.md", "Передача блоков: расход на пересборку")
    docs = memory_graph.load()
    q = memory_graph.terms("экономия контекста")
    assert q & docs[0]["terms"]


def test_pairs_are_symmetric(vault):
    """Пара работает в обе стороны, иначе поиск зависит от языка запроса."""
    assert "memor" in memory_graph.terms("память")
    assert "памят" in memory_graph.terms("memory")


def test_check_flags_a_spec_without_acceptance_criteria(vault, capsys):
    _note(vault, "specs/no-criteria.md", "Фича без критериев приёмки")
    _note(vault, "specs/with-criteria.md", "Фича с критериями",
          "- [ ] первый критерий #ac\n[[no-criteria]]")
    args = type("A", (), {"limit": 8, "strict": False})()
    memory_graph.cmd_check(args)
    out = capsys.readouterr().out
    assert "спеки без AC" in out
    assert "no-criteria.md" in out


def test_empty_result_is_an_answer_not_a_failure(vault, capsys):
    """«Не разбирали» — валидный ответ: значит решение принимается впервые."""
    _note(vault, "notes/research/unrelated.md", "Совершенно другая тема про доставку")
    args = type("A", (), {"query": "квантовая криптография", "limit": 5,
                          "min_score": 0.3, "json": False})()
    assert memory_graph.cmd_search(args) == 0
    assert "Ничего" in capsys.readouterr().out


def test_strict_mode_fails_when_there_are_findings(vault):
    _note(vault, "specs/lonely.md", "Спека без критериев и без связей")
    args = type("A", (), {"limit": 8, "strict": True})()
    assert memory_graph.cmd_check(args) == 1
