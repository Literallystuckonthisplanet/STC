"""Roundtable contracts as data, checked by machine.

Ten review rounds were spent on this design, and the overwhelming majority of
findings were not "the idea is wrong" but "this line contradicts that line two
hundred lines away". Prose cannot be checked for totality or consistency; a
table can. Every assertion below corresponds to a defect that actually cost a
paid review round, and the comment on it names that round.

Tables live in core/scripts/roundtable/tables/. The canonical prose document
(docs/roundtable.md) explains *why*; these files are *what*, and they are the
ones the engine will read.
"""

import importlib.util
import itertools
import collections
import copy
import os
import json
import hashlib
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

_CANON = Path(__file__).resolve().parents[2] / "core" / "scripts" / "roundtable" / "tables"
# The ratchet runs the suite against a scratch copy; everything else against
# the canon. One variable, honoured by both the suite and the engine.
TABLES = Path(os.environ.get("ROUNDTABLE_TABLES_DIR") or _CANON)

# One loader for the suite and for the engine (БТ, acceptance criterion 1).
# The strict loader was prototyped here and now lives in the module: a private
# copy is exactly the "two sources" shape this design keeps failing on. The
# module is registered under a fixed name so that both roundtable test files
# get the *same* module object — two copies would defeat the point.
SCRIPTS = _CANON.parents[1]
MODULE_NAME = "roundtable.tables"


def import_tables_module():
    """Import the real package module, not a copy loaded from a path.

    `state.py` imports `tables` as a sibling, so the package has to be importable
    for real; loading the file twice under two names would also give the suite a
    different `StrictLoader` object than the engine's, which is precisely what
    criterion 1 of приёмка_БТ forbids.
    """
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import roundtable.tables
    return roundtable.tables


_MODULE = import_tables_module()
StrictLoader = _MODULE.StrictLoader


def _load(name):
    return _MODULE.load_table(name, TABLES)


VOCAB = _load("vocabulary")
RUN = _load("run")
ISSUES = _load("issues")
FRAMING = _load("framing")
PRECHECK = _load("precheck")
BLOCKS = _load("blocks")
STAGES = _load("stages")

ALL_TABLES = {
    "vocabulary": VOCAB, "run": RUN, "issues": ISSUES,
    "framing": FRAMING, "precheck": PRECHECK, "blocks": BLOCKS,
    "stages": STAGES,
}

def _at(table, *path):
    """Read a nested value, or nothing if the row is gone.

    These constants are built at import. When the mutation ratchet deletes the
    row they read, a KeyError here turned into a *collection error* — the whole
    module failed to load, every test "failed", and the mutant was scored as
    caught for entirely the wrong reason. A missing row must break the tests
    that check it, not the file that holds them.
    """
    for key in path:
        if not isinstance(table, dict) or key not in table:
            return {}
        table = table[key]
    return table


RUN_STATES = set(_at(VOCAB, "состояния_прогона", "рабочие")) | set(
    _at(VOCAB, "состояния_прогона", "терминальные"))
RUN_TERMINAL = set(_at(VOCAB, "состояния_прогона", "терминальные"))
ISSUE_STATUSES = set(itertools.chain.from_iterable(_at(VOCAB, "статусы_issue").values()))
ISSUE_TERMINAL = set(_at(VOCAB, "статусы_issue", "терминальные"))
FRAMING_STATUSES = set(itertools.chain.from_iterable(
    _at(VOCAB, "статусы_возражения").values()))
FRAMING_TERMINAL = set(_at(VOCAB, "статусы_возражения", "терминальные"))

# Decisions that belong to exactly one channel. The round-8 blocker was
# `подтвердить_постановку` sitting in contract E, which routes through the
# author — a framing objection must never reach the author.
FRAMING_ONLY = set(_at(VOCAB, "решения_по_возражению")) - set(_at(VOCAB, "решения_по_issue"))
ISSUE_ONLY = set(_at(VOCAB, "решения_по_issue")) - set(_at(VOCAB, "решения_по_возражению"))


def _reachable(edges, start):
    seen, stack = {start}, [start]
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


# --------------------------------------------------------------------------
# basics
# --------------------------------------------------------------------------

def test_every_table_declares_the_version_the_engine_speaks():
    # One global constant made it impossible to move a single table forward:
    # either it was refused, or the six that had not changed were. The map is
    # the point — each table's shape versions on its own.
    module = import_tables_module()
    for name, table in ALL_TABLES.items():
        assert table.get("версия_контракта") == module.CONTRACT_VERSIONS[name], name


def test_a_table_of_a_foreign_version_is_refused(tmp_path):
    module = import_tables_module()
    for name in module.TABLE_NAMES:
        shutil.copy(TABLES / f"{name}.yaml", tmp_path / f"{name}.yaml")
    victim = tmp_path / "blocks.yaml"
    victim.write_text(
        victim.read_text(encoding="utf-8").replace("версия_контракта: 2",
                                                   "версия_контракта: 99", 1),
        encoding="utf-8")
    with pytest.raises(module.ContractError):
        module.load(tmp_path)


# --------------------------------------------------------------------------
# vocabulary is the single source of allowed values (rounds 8, 9)
# --------------------------------------------------------------------------

def test_issue_statuses_come_only_from_the_vocabulary():
    for row in ISSUES["переходы"]:
        if row["из"] is not None:
            assert row["из"] in ISSUE_STATUSES, row
        for target in row["в"]:
            assert target in ISSUE_STATUSES, row


def test_terminal_issue_statuses_have_no_outgoing_transitions():
    for row in ISSUES["переходы"]:
        assert row["из"] not in ISSUE_TERMINAL, row


def test_every_issue_status_is_reachable():
    edges = {}
    for row in ISSUES["переходы"]:
        edges.setdefault(row["из"], []).extend(row["в"])
    assert ISSUE_STATUSES <= _reachable(edges, None)


def test_framing_statuses_are_separate_and_never_leak_into_issue_tables():
    # Round 8: the objection lived under two automata at once.
    issue_words = yaml.dump(ISSUES, allow_unicode=True)
    for status in FRAMING_TERMINAL - {"остановлено"}:
        assert status not in issue_words, status
    for decision in FRAMING_ONLY:
        assert decision not in issue_words, decision


def test_issue_only_decisions_never_appear_in_the_framing_table():
    framing_words = yaml.dump(FRAMING, allow_unicode=True)
    for decision in ISSUE_ONLY:
        assert decision not in framing_words, decision


# --------------------------------------------------------------------------
# contract E: the set of decisions must match everywhere (round 8)
# --------------------------------------------------------------------------

def test_allowed_decisions_cover_exactly_the_issue_decision_set():
    used = set(itertools.chain.from_iterable(ISSUES["допустимые_решения"].values()))
    assert used == set(VOCAB["решения_по_issue"])


def test_every_issue_type_has_at_least_one_allowed_decision():
    for issue_type, decisions in ISSUES["допустимые_решения"].items():
        assert decisions, issue_type



# --------------------------------------------------------------------------
# verdict table (rounds 6, 9)
# --------------------------------------------------------------------------

def test_verdict_table_is_total_and_ordered():
    rows = ISSUES["вердикт"]
    assert rows[0]["вердикт"] == "НЕПОЛНЫЙ_ПРОГОН", "it dominates everything"
    assert rows[-1]["условие"] == "иначе", "the table must have a default row"
    for row in rows:
        assert row["вердикт"] in VOCAB["вердикты"], row


def test_framing_on_the_idea_stage_appears_in_the_verdict_table():
    # Round 9: §6.12 said "never blocks" while §8.1 said it blocks on идея.
    assert FRAMING["влияние_по_стадиям"]["идея"] == "держит_стадию"
    assert any("идея" in row["условие"] for row in ISSUES["вердикт"])


# --------------------------------------------------------------------------
# run automaton — now condition codes, not sentences (round 11)
# --------------------------------------------------------------------------

def test_run_states_come_only_from_the_vocabulary():
    for row in RUN["переходы"]:
        if row["из"] is not None:
            assert row["из"] in RUN_STATES, row
        assert row["в"] in RUN_STATES, row


def test_terminal_run_states_have_no_outgoing_transitions():
    for row in RUN["переходы"]:
        assert row["из"] not in RUN_TERMINAL, row


def test_every_run_state_is_reachable_from_creation():
    edges = {}
    for row in RUN["переходы"]:
        edges.setdefault(row["из"], []).append(row["в"])
    assert RUN_STATES <= _reachable(edges, None)


def test_conditions_are_closed_codes_with_declared_values():
    # Round 11: a condition written as a Russian sentence cannot be evaluated,
    # so its meaning would be re-implemented in Python — two sources again.
    codes = VOCAB["коды_условий"]
    for row in RUN["переходы"]:
        for key, value in (row.get("условия") or {}).items():
            assert key in codes, f"unknown condition code {key}"
            assert value in codes[key], f"{key}={value!r} is not a declared value"


def test_actions_and_refusals_are_closed_codes():
    declared = set(VOCAB["коды_действий"])
    documented = set(RUN["действия"])
    assert declared == documented, "every action code needs one written meaning"
    for row in RUN["переходы"]:
        for action in row.get("действия") or []:
            assert action in declared, action
        if "отказ" in row:
            assert row["отказ"] in VOCAB["коды_отказа"], row["отказ"]


def test_no_two_transitions_can_fire_at_once():
    # THE determinism invariant. Two transitions from the same (state, event)
    # must disagree on at least one condition key, otherwise both match and the
    # engine has to guess. This is what catches "the same rule written twice in
    # slightly different words" — round 11 demonstrated the old string
    # comparison could not.
    grouped = {}
    for row in RUN["переходы"]:
        grouped.setdefault((row["из"], row["событие"]), []).append(row)
    for key, rows in grouped.items():
        for i, first in enumerate(rows):
            for second in rows[i + 1:]:
                a, b = first.get("условия") or {}, second.get("условия") or {}
                shared = set(a) & set(b)
                conflicting = any(a[k] != b[k] for k in shared)
                assert conflicting, f"{key}: two transitions can fire together"


def test_every_verdict_has_an_outcome_from_a_running_round():
    outcomes = {
        row["условия"]["verdict"]: row["в"]
        for row in RUN["переходы"]
        if row["из"] == "идёт_круг" and row["событие"] == "вердикт"
    }
    assert outcomes == {
        "ОДОБРЕНО": "завершён",
        "НУЖНЫ_ПРАВКИ": "ждёт_автора",
        "РЕШЕНИЕ_АНТОНА": "ждёт_Антона",
        "НЕПОЛНЫЙ_ПРОГОН": "неполный",
    }


def test_every_issue_decision_has_a_transition():
    used = {row["условия"].get("decision") for row in RUN["переходы"]
            if row["событие"] == "submit-decision"}
    assert used == set(VOCAB["решения_по_issue"])


def test_a_revision_either_starts_a_round_or_goes_to_anton():
    branches = {
        row["условия"]["budget_allows_round"]: row["в"]
        for row in RUN["переходы"] if row["событие"] == "submit-revision"
    }
    assert branches == {True: "идёт_круг", False: "ждёт_Антона"}


def test_accepting_a_risk_has_both_the_waiting_and_the_finishing_branch():
    branches = {
        row["условия"]["all_verdict_blocking_resolved"]: row["в"]
        for row in RUN["переходы"]
        if row["условия"].get("decision") == "принять_риск"
    }
    assert branches == {False: "ждёт_Антона", True: "завершён"}


def test_confirming_the_framing_covers_a_round_that_is_and_is_not_running():
    running = {
        row["условия"].get("round_running")
        for row in RUN["переходы"]
        if row["из"] == "идёт_круг"
        and row["условия"].get("framing_decision") == "подтвердить_постановку"
    }
    assert running == {True, False}


def test_asking_for_another_round_waits_for_the_author_not_the_critics():
    # Round 11: one place sent the run straight to идёт_круг while the event
    # table said ждёт_автора. Anton's decision carries no new revision, so
    # there is nothing to hand the critics yet.
    rows = [r for r in RUN["переходы"]
            if r["событие"] == "submit-decision"
            and r["условия"].get("decision") == "запросить_ещё_правку"]
    allowed = [r for r in rows if r["условия"].get("budget_fits_quorum") is True]
    refused = [r for r in rows if r["условия"].get("budget_fits_quorum") is False]
    assert [r["в"] for r in allowed] == ["ждёт_автора"]
    assert refused and refused[0]["отказ"] == "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ"


def test_both_branches_of_changing_the_solution_exist():
    branches = {
        row["условия"]["change_index"]: row["в"]
        for row in RUN["переходы"]
        if row["условия"].get("decision") == "сменить_решение"
        and row["событие"] == "submit-decision"
    }
    assert branches == {
        "первая": "ждёт_автора",
        "вторая": "остановлено_для_перепроектирования",
    }


def test_framing_decisions_reach_every_state_a_run_can_be_in():
    # Round 11: `неполный` had no framing transition at all — yet a critic can
    # raise an objection and the other critic then die, which is exactly how a
    # run becomes неполный.
    working = set(VOCAB["состояния_прогона"]["рабочие"])
    for decision in VOCAB["решения_по_возражению"]:
        have = {r["из"] for r in RUN["переходы"]
                if r["событие"] == "submit-framing-decision"
                and r["условия"].get("framing_decision") == decision}
        assert have == working, f"{decision}: missing {working - have}"


def test_confirming_the_framing_never_kills_a_running_round():
    for row in RUN["переходы"]:
        if row["событие"] != "submit-framing-decision":
            continue
        actions = row.get("действия") or []
        if row["условия"]["framing_decision"] == "подтвердить_постановку":
            assert "kill_process_group" not in actions, row
            assert row["в"] == row["из"], "confirming does not move the run"
        elif row["из"] == "идёт_круг":
            assert "kill_process_group" in actions, row
            assert "mark_results_stale" in actions, row


def test_accepting_an_objection_supersedes_rather_than_rewrites():
    for row in RUN["переходы"]:
        if row["событие"] != "submit-framing-decision":
            continue
        if row["условия"]["framing_decision"] in ("изменить_цель", "сменить_решение"):
            actions = row["действия"]
            assert "mark_run_superseded" in actions and "spawn_linked_run" in actions
        if row["условия"]["framing_decision"] == "остановить":
            assert "spawn_linked_run" not in row["действия"], "stop spawns nothing"


def test_a_run_can_be_cancelled_from_every_working_state():
    working = set(VOCAB["состояния_прогона"]["рабочие"])
    have = {row["из"] for row in RUN["переходы"] if row["событие"] == "cancel-run"}
    assert have == working


def test_every_working_state_has_a_way_forward_not_only_a_way_out():
    for state in VOCAB["состояния_прогона"]["рабочие"]:
        forward = [r for r in RUN["переходы"]
                   if r["из"] == state
                   and r["событие"] not in ("cancel-run", "submit-framing-decision")]
        assert forward, f"{state} can only be cancelled"
    events = {(r["из"], r["событие"]) for r in RUN["переходы"]}
    assert ("неполный", "resume") in events
    assert ("ждёт_автора", "submit-revision") in events
    assert ("ждёт_Антона", "submit-decision") in events


def test_stop_is_a_decision_outcome_not_a_computed_verdict():
    assert all(row["вердикт"] != "СТОП" for row in ISSUES["вердикт"])
    assert "СТОП" in ISSUES["вердикт_вне_таблицы"]
    stopped = [r for r in RUN["переходы"]
               if r["событие"] == "submit-decision"
               and r["условия"].get("decision") == "остановить"]
    assert [r["в"] for r in stopped] == ["завершён"]


def test_revoke_operation_states_both_the_allowed_and_the_refused_case():
    revoke = RUN["revoke_operation"]
    assert revoke["цель"] == "operation_id"
    assert revoke["отката_истории"] is False
    assert revoke["разрешено_если"] and revoke["зависимое_событие"]
    assert revoke["иначе"] in VOCAB["коды_отказа"]
    assert revoke["компенсация"]


# --------------------------------------------------------------------------
# framing registry (rounds 8, 10)
# --------------------------------------------------------------------------

def test_framing_automaton_is_closed_and_reachable():
    edges = {}
    for row in FRAMING["переходы"]:
        assert row["из"] is None or row["из"] in FRAMING_STATUSES, row
        assert row["в"] in FRAMING_STATUSES, row
        edges.setdefault(row["из"], []).append(row["в"])
    assert FRAMING_STATUSES <= _reachable(edges, None)
    for row in FRAMING["переходы"]:
        assert row["из"] not in FRAMING_TERMINAL - {"принято"}, row


def test_stage_rules_cover_every_stage():
    stages = set(VOCAB["стадии"]["в_MVP"]) | set(VOCAB["стадии"]["вне_MVP"])
    assert set(FRAMING["влияние_по_стадиям"]) == stages
    assert set(FRAMING["права_по_стадиям"]) == stages


def test_framing_and_solution_criteria_are_separate_lists():
    # Round 9: forcing "we are solving the wrong problem" to masquerade as
    # over-engineering is how junk findings get made.
    solution = {row["код"] for row in FRAMING["критерии_решения"]}
    stated = {row["код"] for row in FRAMING["критерии_постановки"]}
    assert solution & stated == set()
    assert set(FRAMING["считает_движок_без_права_поднимать"]) == {"несходимость", "цена_согласования"}


def test_the_one_change_limit_is_a_policy_not_budget_arithmetic():
    # Round 8 disproved the arithmetic: a change can happen in round one.
    assert FRAMING["ограничитель_смены_решения"]["природа"] == "политика_цикла"
    assert FRAMING["ограничитель_смены_решения"]["исход_второй"] in RUN_TERMINAL


def test_the_run_record_outlives_the_objection_that_needs_it():
    # Round 10: the registry promised to outlive the run while runs were
    # deleted after 90 days, leaving late decisions nothing to apply to.
    keep = FRAMING["хранение"]["неизменяемая_запись_прогона"]["срок"]
    assert "открытое возражение" in keep and "связанный прогон" in keep


# --------------------------------------------------------------------------
# evidence fingerprints (round 10)
# --------------------------------------------------------------------------

def test_evidence_fingerprints_exclude_identity_and_time():
    # Round 10: re-sending the same span produced a fresh id, which defeated
    # the "only with new evidence" rule entirely.
    for kind, fields in VOCAB["отпечаток"].items():
        assert kind in VOCAB["типы_доказательства"]
        assert not {"id", "время"} & set(fields), kind
    assert set(VOCAB["отпечаток"]) == set(VOCAB["типы_доказательства"])


def test_only_the_author_side_can_produce_an_executed_command():
    # Critics run with --tools "" and cannot execute anything.
    assert "критик" not in VOCAB["создатели_доказательства"]["command_run"]
    assert "критик" in VOCAB["создатели_доказательства"]["source_span"]


# --------------------------------------------------------------------------
# precheck (rounds 9, 10)
# --------------------------------------------------------------------------

def test_precheck_codes_are_unique_and_each_declares_a_fixture():
    codes = [row["код"] for row in PRECHECK["коды"]]
    assert len(codes) == len(set(codes))
    for row in PRECHECK["коды"]:
        # Declared, not yet present: the files land with Б15. Round 11 was
        # right that the old name promised more than the assertion did.
        assert row["фикстура"], row["код"]


def test_precheck_depends_on_the_package_block_only():
    # Round 10: B15 depended on B4 while standing before it in the order.
    assert PRECHECK["зависимость_блока"] == "Б2"
    assert BLOCKS["блоки"]["Б15"]["зависит"] == ["Б2"]


def test_precheck_states_what_it_cannot_do():
    assert PRECHECK["вне_возможностей"], "the promise must name its own limits"


# --------------------------------------------------------------------------
# plan consistency (round 10)
# --------------------------------------------------------------------------

def test_every_dependency_comes_earlier_in_the_order():
    order = BLOCKS["порядок"]
    position = {block: i for i, block in enumerate(order)}
    for block, spec in BLOCKS["блоки"].items():
        if block not in position:
            continue
        for dep in spec["зависит"]:
            assert dep in position, f"{block} depends on unplanned {dep}"
            assert position[dep] < position[block], f"{block} runs before its dependency {dep}"


def test_planned_blocks_and_the_block_table_agree():
    listed = set(BLOCKS["блоки"])
    assert set(BLOCKS["порядок"]) <= listed
    assert set(BLOCKS["вне_порядка"]) <= listed
    assert listed == set(BLOCKS["порядок"]) | set(BLOCKS["вне_порядка"])


def test_declared_counts_match_the_lists_they_describe():
    # "Six fixture files" against four actually named cost a review round.
    sources = {
        "схемы_контрактов": VOCAB["схемы_контрактов"],
        "операции": VOCAB["операции"],
        "коды_предпроверки": PRECHECK["коды"],
        **BLOCKS["списки"],
    }
    checked = 0
    for block, spec in BLOCKS["блоки"].items():
        for list_name, declared in (spec.get("объявленное_количество") or {}).items():
            assert declared == len(sources[list_name]), f"{block}: {list_name}"
            checked += 1
    assert checked >= 4, "counts stopped being cross-checked"


# --------------------------------------------------------------------------
# coverage of the tables themselves
#
# Measured by mutate_roundtable_tables.py: delete one row at a time and see
# whether anything fails. The first cut caught 57% — 22 of 29 automaton
# transitions and all 17 validation rules could be deleted silently. A green
# suite that does not look at the rows is the same failure STC already had on
# 2026-07-29, when a guard with no corpus printed "skipping" and exited green.
# The assertions below pin whole rows by the invariant they belong to, not by
# their text, so they stay meaningful rather than becoming change detectors.
# --------------------------------------------------------------------------


def test_author_and_critic_turns_both_exist_in_the_issue_lifecycle():
    # Deleting either half leaves a lifecycle where an issue can be raised but
    # never answered, or answered but never confirmed.
    targets = {t for row in ISSUES["переходы"] for t in row["в"]}
    assert {"принят_автором", "оспорен_автором"} <= targets, "author has no move"
    assert {"закрыт_исправлением", "возражение_снято"} <= targets, "critic cannot close"
    for status in VOCAB["статусы_issue"]["ждут_автора"]:
        answered = [r for r in ISSUES["переходы"]
                    if r["из"] == status and "принят_автором" in r["в"]]
        assert answered, f"{status}: the author has no move from here"


def test_every_route_to_anton_exists_from_both_author_statuses():
    # Round 11: a fresh finding is always `открыт`, so a route declared only
    # from `остался` left the blocker stuck with a verdict that demanded a
    # decision Anton had no way to make.
    routes = {}
    for row in ISSUES["переходы"]:
        if "вынесен_Антону" in row["в"] and row["из"] is not None:
            routes.setdefault(row["условие"], set()).add(row["из"])
    kinds = [
        "блокер сменой_решения, любой круг",
        "блокер только_сменой_цели, любой круг",
        "неизвестное высокой существенности, любой круг",
        "блокер правкой, круги исчерпаны",
    ]
    assert set(routes) == set(kinds)
    for kind in kinds:
        assert routes[kind] == {"открыт", "остался"}, kind


def test_every_blocking_kind_reaches_the_verdict_table():
    conditions = " | ".join(row["условие"] for row in ISSUES["вердикт"])
    for kind in VOCAB["устранимость"]:
        assert kind in conditions, kind
    # Both branches of "fixable" must exist: with rounds left, and without.
    assert "круги не исчерпаны" in conditions
    assert "блокер правкой, круги исчерпаны" in conditions
    assert "неизвестное высокой существенности" in conditions


def test_every_constrained_element_has_at_least_one_validation_rule():
    # 17 rules with no test meant any of them could vanish unnoticed. Each
    # phrase below is distinctive to exactly one rule, so losing that rule
    # fails here — while rewording any of them stays free.
    rules = " | ".join(row["правило"] for row in ISSUES["валидация"])
    for element in (
        "нечего_добавить=да", "нечего_добавить=нет",
        "альтернатива", "при классе не блокирующая", "с полем устранимость",
        "не из перечня", "area_id", "evidence пуст",
        "кода возврата", "создан критиком",
        "не найден в реестре решений", "отсутствует при",
        "reopens_issue_id", "отпечат", "вне списка допустимых",
        "поле вердикта", "разбиение секретаря",
    ):
        assert element in rules, element
    outcomes = {row["исход"] for row in ISSUES["валидация"]}
    assert outcomes <= {"отказ", "находка_невалидна", "ответ_отвергнут", "резюме_отвергнуто"}


def test_who_may_close_an_issue_is_fully_stated():
    closers = ISSUES["кто_завершает"]
    assert set(closers["поднявший_критик"]) | set(closers["Антон"]) == ISSUE_TERMINAL
    assert closers["никто_иной"], "the exclusion must be written down, not implied"


def test_the_package_rules_are_complete_and_pinned():
    # Guarantee 1 lives on these seven rows: what is refused, what never enters,
    # how big is too big, and why a build carries no timestamp. Б2 reads every
    # one of them, so losing a row here would quietly widen the package.
    package = VOCAB["пакет"]
    assert package["предел_файла_байт"] > 0 and package["предел_пакета_байт"] > 0
    assert package["предел_файла_байт"] < package["предел_пакета_байт"]
    assert set(package["отвергается"]) == {
        "симлинк", "путь_с_родительским_переходом", "путь_вне_корня",
        "превышение_размера", "отсутствие_обязательного_файла"}
    assert set(package["не_попадает"]) == {
        "инструкции_харнесса", "прошлые_протоколы", "git_история",
        "ответы_других_критиков", "имя_автора"}
    assert package["реестры"] == ["решения", "области", "журнал_доказательств"]
    assert set(package["виды_решений_в_реестре"]) == {"closed_decision", "framing"}
    assert "времени сборки" in package["канонизация"], (
        "the reason two builds must hash the same has to stay written down")


def test_the_attempt_journal_declares_its_key_states_and_flag():
    # Б1 reads all four out of the table: a private copy inside state.py would
    # be the "two sources" shape again, and this journal is what decides whether
    # a critic gets called twice.
    attempt = VOCAB["попытка"]
    assert attempt["ключ"] == ["прогон", "стадия", "круг", "критик", "попытка"]
    assert attempt["состояния"] == [
        "подготовлена", "запущена", "получена", "провалидирована", "зафиксирована"]
    assert attempt["флаг_неопределённого_окна"] == "возможен_дубль"
    assert attempt["почему"], "the unreachable guarantee must keep its reason"


def test_precheck_file_classes_and_fixture_home_are_declared():
    assert set(PRECHECK["классы_файлов"]) == {"existing_evidence", "planned_output"}
    assert PRECHECK["фикстуры"]["каталог"].endswith("precheck/")
    assert PRECHECK["фикстуры"]["не_смешивать_с"], "tune/holdout test models, not code"




def test_the_change_limit_states_its_number_and_its_reason():
    limit = FRAMING["ограничитель_смены_решения"]
    assert limit["сколько"] == 1 and limit["за"] == "стадию"
    assert limit["почему"], "a policy without a reason gets re-litigated"


def test_retention_covers_every_class_of_run():
    assert set(FRAMING["хранение"]) == {
        "неизменяемая_запись_прогона", "полные_материалы", "незавершённые_и_ждёт_Антона",
    }


def test_vocabulary_subsets_stay_inside_their_parents():
    assert set(VOCAB["операции_без_бюджета"]) <= set(VOCAB["операции"])
    assert set(VOCAB["схемы_вне_контрактов"]) & set(VOCAB["схемы_контрактов"]) == set()
    assert set(VOCAB["действительность_прогона"]) == {"актуален", "superseded"}


def test_closed_vocabularies_are_pinned_exactly():
    # These are contracts, not lists that grow: dropping a value silently
    # narrows what the engine will accept, and nothing else would notice.
    assert set(VOCAB["устранимость"]) == {"правкой", "сменой_решения", "только_сменой_цели"}
    assert "СТОП" in VOCAB["вердикты"]
    assert set(VOCAB["операции_без_бюджета"]) == {"precheck", "publish-check", "status"}
    assert VOCAB["схемы_вне_контрактов"] == ["precheck_frontmatter"]
    assert PRECHECK["схема_входа"].endswith("precheck_frontmatter.json")



def test_every_type_that_reaches_anton_has_decisions_he_may_take():
    # A route to Anton with no allowed decision is a dead end for him.
    assert len(ISSUES["допустимые_решения"]) == 4
    for issue_type, decisions in ISSUES["допустимые_решения"].items():
        assert decisions, issue_type
    assert "неизвестное_высокой_существенности" in ISSUES["допустимые_решения"]


def test_precheck_fixtures_declare_their_oracle_and_their_rule():
    assert PRECHECK["фикстуры"]["эталон"].endswith(".json")
    assert "на чистом документе" in PRECHECK["фикстуры"]["правило"]


def test_a_review_conclusion_is_not_a_permission_to_execute():
    # Six rounds in a row these two were welded together under the word
    # "разрешение", and every time the weld leaked a permission granted to
    # oneself. A critic says "ready"; Anton says "go". Two registries.
    conclusions = {b for e in BLOCKS["заключения_ревью"] for b in e["блоки"]}
    grants = {b for g in BLOCKS["разрешения_исполнения"] for b in g["блоки"]}
    assert conclusions, "заключения ревью пропали из таблицы"
    assert grants, "разрешения исполнения пропали из таблицы"
    for entry in BLOCKS["заключения_ревью"]:
        assert "круг" in entry, "заключение без круга — не заключение"
    for grant in BLOCKS["разрешения_исполнения"]:
        assert grant.get("кем"), "разрешение без того, кто его дал"


def test_a_permission_must_point_at_something_resolvable():
    # "Строка непустая" is what let through a citation I could not confirm.
    for grant in BLOCKS["разрешения_исполнения"]:
        basis = grant["основание"]
        assert basis["вид"] in ("событие_транскрипта", "план_артефакт"), basis["вид"]
        if basis["вид"] == "событие_транскрипта":
            assert basis["сессия"] and basis["цитата"]
        else:
            assert basis["путь"] and len(basis["sha256"]) == 64


def _mutated(module, **_):
    return copy.deepcopy(module.load().raw)


def test_a_permission_is_granted_for_a_scope_and_not_for_a_name():
    # A block can keep its name while the work behind it grows, and the old
    # permission would silently cover the new scope. The hash is over the whole
    # effective record — acceptance *text*, declared counts, MVP membership,
    # absorption and gate membership included.
    module = import_tables_module()
    tables = module.load()
    plan = tables.plan
    block = tables.blocks["Б1"]
    before = block.scope_sha256(plan)

    widened = replace(block, writes=block.writes + ("core/scripts/roundtable/cli.py",))
    assert widened.scope_sha256(plan) != before, "расширение области записи не заметили"

    first = block.acceptance[0]
    rewritten = replace(block, acceptance=(replace(first, condition="что угодно"),)
                        + block.acceptance[1:])
    assert rewritten.scope_sha256(plan) != before, "подмена текста критерия под тем же ID"

    assert replace(block, declared_counts={"таблицы": 7}).scope_sha256(plan) != before
    assert replace(block, outside_mvp=True).scope_sha256(plan) != before
    assert replace(block, absorbed_by="БИ").scope_sha256(plan) != before
    assert replace(block, name="Б1-бис").scope_sha256(plan) != before

    # dropping a block out of a gate removes a precondition without touching
    # its own row — the permission must not survive that either
    thinner = copy.deepcopy(plan)
    thinner["шлюзы"]["ремонт_после_ревью_12"]["до_закрытия"].remove("Б1")
    assert block.scope_sha256(thinner) != before, "членство в шлюзе вне отпечатка"

    # moving a block earlier changes what runs next while every field of every
    # block stays identical
    reordered = copy.deepcopy(plan)
    reordered["порядок"].remove("БТ2")
    reordered["порядок"].insert(reordered["порядок"].index("Б1"), "БТ2")
    assert tables.blocks["БТ2"].scope_sha256(reordered) \
        != tables.blocks["БТ2"].scope_sha256(plan), "место в порядке вне отпечатка"

    # weakening a gate by swapping its precondition for an already-closed block
    # removes the safety boundary without touching the guarded block's row
    weakened = copy.deepcopy(plan)
    weakened["шлюзы"]["изоляция_подтверждена"]["до_закрытия"] = ["Б0а"]
    assert tables.blocks["Б3б"].scope_sha256(weakened) \
        != tables.blocks["Б3б"].scope_sha256(plan), "содержимое шлюза вне отпечатка"


def test_a_missing_scope_hash_is_not_a_wildcard():
    # `recorded is None` used to mean "covers anything", which turned every
    # permission back into a permission by name.
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    grant = raw["blocks"]["разрешения_исполнения"][0]

    without = copy.deepcopy(raw)
    del without["blocks"]["разрешения_исполнения"][0]["scope_sha256"]
    with pytest.raises(module.ContractError, match="scope_sha256"):
        module.Tables.from_raw(without).check()

    short = copy.deepcopy(raw)
    short["blocks"]["разрешения_исполнения"][0]["scope_sha256"].pop("Б1")
    with pytest.raises(module.ContractError, match="не совпадает с блоками"):
        module.Tables.from_raw(short).check()

    extra = copy.deepcopy(raw)
    extra["blocks"]["разрешения_исполнения"][0]["scope_sha256"]["Б9"] = "f" * 64
    with pytest.raises(module.ContractError, match="не совпадает с блоками"):
        module.Tables.from_raw(extra).check()

    wrong = copy.deepcopy(raw)
    wrong["blocks"]["разрешения_исполнения"][0]["scope_sha256"]["Б1"] = "a" * 64
    with pytest.raises(module.ContractError, match="Б1"):
        module.Tables.from_raw(wrong).check()
    assert grant  # the untouched original is still the one that passes


def test_a_basis_is_resolved_against_the_real_source(tmp_path):
    # "Строка непустая" is what let through a citation I could not confirm.
    module = import_tables_module()
    home = tmp_path
    plan_file = home / "plan.md"
    plan_file.write_text("замысел", encoding="utf-8")
    digest = hashlib.sha256(plan_file.read_bytes()).hexdigest()

    good = {"вид": "план_артефакт", "путь": str(plan_file), "sha256": digest}
    assert module.resolve_basis(good, home) is None
    assert "sha256" in module.resolve_basis({**good, "sha256": "0" * 64}, home)
    assert "артефакта нет" in module.resolve_basis({**good, "путь": str(home / "нет.md")}, home)

    session = "11111111-2222-3333-4444-555555555555"
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    directory = home / ".claude" / "projects" / "proj"
    directory.mkdir(parents=True)
    (directory / f"{session}.jsonl").write_text("\n".join([
        json.dumps({"uuid": uuid, "type": "user",
                    "message": {"content": "<system-reminder>шум</system-reminder>\n\nделай дальше"}}),
        json.dumps({"uuid": "ffffffff-0000-0000-0000-000000000000", "type": "assistant",
                    "message": {"content": "делай дальше"}}),
    ]), encoding="utf-8")

    event = {"вид": "событие_транскрипта", "сессия": session,
             "native_uuid": uuid, "цитата": "делай дальше"}
    # the wrapper is exactly what a filtered search dropped last time
    assert module.resolve_basis(event, home) is None
    assert "цитата не найдена" in module.resolve_basis(
        {**event, "цитата": "этого я никогда не говорил"}, home)
    # 🚩 Ревью #38: пустая цитата «находилась» в любой реплике, а `../..` в
    # идентификаторе сессии уводил чтение за пределы каталога переписок.
    assert "короче" in module.resolve_basis({**event, "цитата": "  "}, home)
    assert "не похожа" in module.resolve_basis({**event, "сессия": "../../../tmp/x"}, home)
    assert "не похоже" in module.resolve_basis({**event, "native_uuid": "не-uuid"}, home)
    assert "события нет" in module.resolve_basis(
        {**event, "native_uuid": "99999999-0000-0000-0000-000000000000"}, home)
    assert "не реплика пользователя" in module.resolve_basis(
        {**event, "native_uuid": "ffffffff-0000-0000-0000-000000000000"}, home)
    assert "сессии нет" in module.resolve_basis({**event, "сессия": uuid}, home)


def test_every_real_permission_actually_resolves():
    # The registry is only worth its lines if the things it points at exist.
    module = import_tables_module()
    plan = module.load().plan
    if not (Path.home() / ".claude" / "projects").exists():
        pytest.skip("транскрипты недоступны в этой среде")
    for registry in ("заключения_ревью", "разрешения_исполнения", "история_разрешений"):
        for entry in plan[registry]:
            problem = module.resolve_basis(entry["основание"])
            assert problem is None, f"{registry} {entry['блоки']}: {problem}"


def test_the_idea_stage_vocabularies_are_closed_sets():
    # Found by the honest ratchet: every row of these three could be deleted
    # and nothing noticed. They are the contract БИ has to implement, so a
    # silently shrinking vocabulary would let the implementer invent values.
    assert VOCAB["оценка_критерия"] == ["pass", "fail", "unknown"], (
        "третье значение — не украшение: ничья не решается в пользу критика")
    assert VOCAB["состояния_кандидата"] == ["годен", "непроходной", "неясен"]
    assert VOCAB["отношение_механизмов"] == ["same", "different", "unknown"], (
        "«не знаю» обязано быть выразимым, иначе критик вынужден соврать")
    assert VOCAB["выбор_кандидата_sentinel"] == "нет_проходящего", (
        "без sentinel честный ответ «все три плохи» невыразим")


def test_a_reopened_block_keeps_the_permission_it_was_first_started_under():
    # The audit trail is the point: Б1 and Б2 were started on Anton's word in
    # August, then reopened. Dropping those rows would erase why they were ever
    # begun, and the live grant would look like the only thing that ever was.
    # Not a loop over reopened blocks: БК was reopened under the grant that is
    # still live, so it has no superseded permission to preserve. The rows that
    # matter are the August ones — the word that started Б1 and Б2 before their
    # scope changed and the grant stopped covering them.
    started_under = {b: g["основание"]["native_uuid"]
                     for g in BLOCKS["история_разрешений"] for b in g["блоки"]}
    assert started_under.get("Б1") == "c25c3feb-8ffd-4efb-ab8b-bbfc12ccac40", (
        "«ну давай дальше делай Б1» — чем блок начинался, стирать нельзя")
    assert started_under.get("Б2") == "126e123a-f916-4d35-822d-1019830a5216", (
        "«делай дальше» — та самая реплика, которую я однажды объявил выдуманной")
    module = import_tables_module()
    tables = module.load()
    for name in ("Б1", "Б2"):
        assert tables.blocks[name].state == "переоткрыт"


def test_a_drifted_fingerprint_closes_the_gate_rather_than_warning():
    # The field says what a mismatch *does*. "Warn" would make the whole
    # fingerprint decorative, which is what it already was once.
    assert BLOCKS["отпечаток_изоляции"]["расхождение"] == "закрывает_шлюз"
    assert BLOCKS["отпечаток_изоляции"]["проверяет_блок"] in BLOCKS["блоки"]


# --------------------------------------------------------------------------
# the ratchet that measures the tables — it once measured nothing at all
# --------------------------------------------------------------------------

def _ratchet():
    import importlib.util
    path = Path(__file__).with_name("mutate_roundtable_tables.py")
    spec = importlib.util.spec_from_file_location("rt_ratchet", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_ratchet_never_writes_to_the_canon():
    # It used to mutate the real YAML and restore it in `finally`: a kill -9
    # mid-run left the repository holding a corrupt table. A real interrupt
    # happened on 2026-09-03 and the canon came through untouched.
    source = Path(__file__).with_name("mutate_roundtable_tables.py").read_text(encoding="utf-8")
    assert "mkdtemp" in source, "храповик обязан работать на временной копии"
    assert "CANON" in source and "shutil.copy" in source
    ratchet = _ratchet()
    assert ratchet.CANON.is_dir()
    # nothing in the runner may open a canonical path for writing
    assert "CANON /" not in source.replace("shutil.copy(path, scratch", "")


def test_the_ratchet_demands_a_green_control_base():
    # The whole `322/322 (100%)` was produced on a RED base: a test needing a
    # fixture raised TypeError before any table was read, so every mutant was
    # scored as caught. A dead mutant proves nothing until you know what killed
    # it — and the threshold is 100, not 90.
    source = Path(__file__).with_name("mutate_roundtable_tables.py").read_text(encoding="utf-8")
    assert "контрольная база не зелёная" in source
    assert "percent == 100" in source, "порог обязан быть 100, а не 90"
    assert "RatchetDefect" in source


def test_the_ratchet_runs_the_real_suite_not_hand_called_functions():
    # Calling test functions by hand is what made a fixture argument look like
    # a caught mutation. And it ran a single file, so expectations living in
    # the other test files were not in the denominator at all.
    ratchet = _ratchet()
    source = Path(__file__).with_name("mutate_roundtable_tables.py").read_text(encoding="utf-8")
    assert "-m\", \"pytest" in source or '"pytest"' in source
    assert "getattr(module, name)()" not in source, "вызов тестовых функций руками"
    # an ERROR is a defect of the measurement, never a caught mutation
    assert "ERRORED" in source and "raise RatchetDefect" in source
    assert ratchet.SUITE.exists()


# --------------------------------------------------------------------------
# the register of review findings — "is there agreement or not", made checkable
# --------------------------------------------------------------------------

def _suite_test_names():
    names = set()
    for path in Path(__file__).parent.glob("test_roundtable_*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("def test_"):
                names.add(line[4:].split("(")[0])
    return names


def test_every_review_finding_has_a_status_and_nothing_is_silently_dropped():
    # Nine rounds produced ~60 findings, and "все приняты" was my word against
    # nothing. A finding with no status is a finding quietly forgotten.
    findings = _load("findings")["находки"]
    ids = [f["id"] for f in findings]
    assert len(ids) == len(set(ids)), "дублирующийся ID находки"
    allowed = {"устранена", "назначена_блоку", "избыточна", "открыта", "ждёт_Антона"}
    for finding in findings:
        assert finding["статус"] in allowed, finding["id"]
        assert finding["что"].strip(), finding["id"]
        assert isinstance(finding["круг"], int)


def test_no_finding_can_be_quietly_dropped():
    # Without this the register is a list anyone can shorten: the other tests
    # iterate over whatever is left and stay green. Counts are pinned per round
    # so deleting a single row fails.
    findings = _load("findings")["находки"]
    per_round = collections.Counter(f["круг"] for f in findings)
    assert dict(sorted(per_round.items())) == {12: 5, 13: 8, 14: 11, 15: 10, 16: 8, 17: 9, 19: 7, 20: 5, 21: 5, 22: 3, 23: 3, 24: 5, 25: 8, 26: 6, 27: 4, 28: 2, 29: 1, 30: 2, 31: 3, 32: 1, 33: 4, 34: 3, 35: 2, 36: 2, 37: 1, 38: 9, 39: 3, 40: 4, 41: 1}, (
        "находка исчезла или появилась без обновления замка")
    assert len(findings) == 135


def test_a_finding_marked_fixed_names_a_test_that_actually_exists():
    # Otherwise "устранена" is the same unverified claim as the ones the
    # rounds kept catching.
    known = _suite_test_names()
    for finding in _load("findings")["находки"]:
        if finding["статус"] != "устранена":
            continue
        guard = finding.get("тест")
        assert guard, f"{finding['id']}: устранена, но сторож не назван"
        assert guard in known, f"{finding['id']}: теста {guard} в наборе нет"


def test_a_finding_may_only_be_assigned_to_a_block_still_open():
    # "Назначена блоку" обещает, что починка ЖДЁТ. Указать на критерий уже
    # закрытого блока — тихо объявить находку сделанной, ничего не сделав.
    module = import_tables_module()
    tables = module.load()
    owner = {item.id: name
             for name, block in tables.blocks.items() for item in block.acceptance}
    for finding in _load("findings")["находки"]:
        if finding["статус"] != "назначена_блоку":
            continue
        block = owner.get(finding["критерий"])
        assert block, f"{finding['id']}: критерия {finding['критерий']} нет"
        assert not tables.closed(block), (
            f"{finding['id']}: назначена критерию {finding['критерий']}, "
            f"а блок {block} уже закрыт")


# Замки находок: id → (слепок текста, слепок привязки «поломка/сторож/критерий»).
# 🚩 Ревью #38: один общий слепок на весь реестр падал одинаково и от подмены
# текста, и от честного добавления находки — опыт «подменить текст» засчитывался
# по чужой причине. Пофамильный замок называет ИМЕННО подменённую запись.
FINDING_PINS = {
    "R12-1": ("d42435e985cb", "47f0fb0e39bc"),
    "R12-2": ("0564a10f5873", "69abc15709b7"),
    "R12-3": ("dcf654104cbe", "49359eb63ad0"),
    "R12-4": ("4d5e8e6c7b4f", "8203d1780a9c"),
    "R12-5": ("88870441b246", "d2adb66fecfb"),
    "R13-1": ("f4a1639d8eb9", "daac94d1a879"),
    "R13-2": ("0d92d292b923", "87b917cdae7a"),
    "R13-3": ("f8066d738986", "7020e9135d15"),
    "R13-4": ("419f575afe06", "cc6a5fc005ff"),
    "R13-5": ("9eafa61d5627", "4f88b03248cf"),
    "R13-6": ("e6bb12ea053a", "7020e9135d15"),
    "R13-7": ("e1796e50cb6a", "238c8bcb8020"),
    "R13-8": ("9a8fea56b1ce", "ab7d603ae34c"),
    "R14-1": ("23c0d8967e00", "bc0690af21eb"),
    "R14-2": ("1f52fbec5228", "9c55c7378c55"),
    "R14-3": ("32787caa1755", "a92948a682c7"),
    "R14-4": ("ed5e8deb8117", "3cf57480d6e7"),
    "R14-5": ("ac422876d92e", "4f88b03248cf"),
    "R14-6": ("cb6dc064ffbd", "59ee143f6595"),
    "R14-7": ("ccb9c39d9248", "130a30a902f7"),
    "R14-8": ("5467b0850b03", "5caa504f9d55"),
    "R14-9": ("e1366bbbbbbb", "7020e9135d15"),
    "R14-10": ("f50bb3e9a008", "9512f329eb20"),
    "R14-11": ("8180865842d5", "1c38a9362331"),
    "R15-1": ("1c104b3fc7e7", "2ee762796553"),
    "R15-2": ("9d98cc6bd966", "21fcaa3d3373"),
    "R15-3": ("e01825a51396", "8a13d4a06981"),
    "R15-4": ("db5173af613a", "9eb37aef1baf"),
    "R15-5": ("0737cccb138c", "616b705cc1de"),
    "R15-6": ("07ec9b9f9bed", "9a4caf58c3dc"),
    "R15-7": ("92450cbbfbdd", "874dfc52afb1"),
    "R15-8": ("47885c40a92b", "8696927d13fa"),
    "R15-9": ("2fe280ccf96d", "130a30a902f7"),
    "R15-10": ("38b913648760", "1760c70038c6"),
    "R16-1": ("a1d424315908", "bc0690af21eb"),
    "R16-2": ("cea556de1fbc", "9ae5c4dd83a4"),
    "R16-3": ("1bd741f174cb", "e12c610faf33"),
    "R16-4": ("0b8e109c78c0", "4a92fa7800dc"),
    "R16-5": ("9bf55e10b199", "ffaecc1dd0d3"),
    "R16-6": ("944e866fbb12", "e47ebbc027c1"),
    "R16-7": ("9db50d82952b", "5caa504f9d55"),
    "R16-8": ("7d5aceae7883", "e14e5061d017"),
    "R17-1": ("cb5780caccf1", "4545c8a3af83"),
    "R17-2": ("c0aab0411a78", "042a0b8ab63d"),
    "R17-3": ("1bba815466bd", "9ae5c4dd83a4"),
    "R17-4": ("a0f59d2f458d", "b40e3f3db766"),
    "R17-5": ("7ecf5768210f", "639003c64aa8"),
    "R17-6": ("cef11703a077", "942ab7451e81"),
    "R17-7": ("71592858481f", "9a4caf58c3dc"),
    "R17-8": ("71739bc8db4f", "ef35dadd5758"),
    "R17-9": ("1899aac7bced", "e47ebbc027c1"),
    "R19-1": ("2435387d4f38", "0e91c4863728"),
    "R19-2": ("67e0592b0d42", "f5d66a1c863c"),
    "R19-3": ("d68c3419c54c", "9eb37aef1baf"),
    "R19-4": ("984607a8b8de", "942ab7451e81"),
    "R19-5": ("8f23ef086ef6", "bc68a2fedc3d"),
    "R19-6": ("bab1914bd7e7", "4a92fa7800dc"),
    "R19-7": ("b45323d1dc8d", "70004e5011fe"),
    "R20-1": ("8dcb4985bc98", "ab7d603ae34c"),
    "R20-2": ("db5deb721868", "238c8bcb8020"),
    "R20-3": ("df6c21e99d57", "3f8359c2198f"),
    "R20-4": ("ea5bb429f8cd", "1c38a9362331"),
    "R20-5": ("97767c4744d1", "254da468c88e"),
    "R21-1": ("697e5326bf9e", "53b44945d9f4"),
    "R21-2": ("9374a33f13e2", "5af7747f5f79"),
    "R21-3": ("423e84c75283", "ab7d603ae34c"),
    "R21-4": ("a716e3ecc86b", "30119aa7f3ab"),
    "R21-5": ("3bf8811d6d49", "7628650c351d"),
    "R22-1": ("e6d64e6d4e48", "53b44945d9f4"),
    "R22-2": ("a6bfae47ddbb", "30119aa7f3ab"),
    "R22-3": ("71cb12d78bf4", "d6ffad4b2500"),
    "R23-1": ("7e861b64e208", "aec37d45c1fb"),
    "R23-2": ("34280630bd43", "53b44945d9f4"),
    "R23-3": ("f35869380d4c", "cc6a5fc005ff"),
    "R24-1": ("a694ca063639", "ae557c6966cb"),
    "R24-2": ("945fbd19db58", "1640b0a651d7"),
    "R24-3": ("3a8e7ca36453", "23eae7d0475f"),
    "R24-4": ("b1af8f4b4155", "9dd5d0828467"),
    "R24-5": ("759811342653", "9bfc9bcf799e"),
    "R25-1": ("de91281f1e9c", "bfe633052095"),
    "R25-2": ("350cf56aacce", "ae1f849438b7"),
    "R25-3": ("950bc8f39d06", "5d3042f89fcf"),
    "R25-4": ("aa8f894cc09c", "c817ad2289e9"),
    "R25-5": ("86f9eed4daf2", "2447e9cf3b0f"),
    "R25-6": ("ee166703f0ca", "aa36a6d54968"),
    "R25-7": ("5910bba6201c", "9dd5d0828467"),
    "R25-8": ("7d791e5b64bb", "e1bb7c7b25de"),
    "R26-1": ("9950f98d68a8", "2b72b62b2f23"),
    "R26-2": ("156d59b72fa1", "9f1a184c1a32"),
    "R26-3": ("61236a6512ac", "5fc2391698e1"),
    "R26-4": ("a9447ca8b7b8", "92747f60cd6e"),
    "R26-5": ("9f6cf5c4af28", "92747f60cd6e"),
    "R26-6": ("8e23fb8815df", "a92948a682c7"),
    "R27-1": ("d9189328c2be", "53c980f9fb85"),
    "R27-2": ("953c38908491", "18677725582b"),
    "R27-3": ("f4df0ca3a0a2", "2eec6c296f37"),
    "R27-4": ("9bebcf6c8f17", "7825db2be5fe"),
    "R28-1": ("d571190fde10", "48f73092b0f6"),
    "R28-2": ("6f431e024e37", "18677725582b"),
    "R29-1": ("02a6a3004349", "74a234fd8e39"),
    "R30-1": ("98599398f960", "e3f3027abd50"),
    "R30-2": ("9cb3ccea900c", "66254a190734"),
    "R31-1": ("f9fcee077e41", "f8a5c2bd7179"),
    "R31-2": ("b92ca1a0e7fc", "f8a5c2bd7179"),
    "R31-3": ("ac97255021f8", "717872dd8acb"),
    "R32-1": ("69c10618ad8d", "6f6a602f6678"),
    "R33-1": ("993cea2ecfe2", "55b739124fa1"),
    "R33-2": ("fb17eb6ae416", "3ef1250b6cb6"),
    "R33-3": ("19b18287247a", "5d0ee2db039d"),
    "R33-4": ("9b260b0f97f4", "1b62207271ec"),
    "R34-1": ("a82f78a5db09", "c984092de990"),
    "R34-2": ("c7aefff882ce", "fbe5d6a70e4b"),
    "R34-3": ("aac2be7f0b44", "d4cc6846859a"),
    "R35-1": ("2541c4ec0653", "c4e6c76728f6"),
    "R35-2": ("61ae7c4dba61", "0a2c20839104"),
    "R36-1": ("e51874bf555a", "00ab4cc5c291"),
    "R36-2": ("9beb9a5355bc", "1e04f13cac09"),
    "R37-1": ("178324d8fe37", "b14772569e28"),
    "R38-1": ("3e90660040df", "fb37793fb35f"),
    "R38-2": ("0ac4670cb9ca", "7bc2e2942921"),
    "R38-3": ("a72104d51f6b", "16728a3e8010"),
    "R38-4": ("09005f6f02ce", "65d27aecfb31"),
    "R38-5": ("42f18f906d96", "53d263c8eff8"),
    "R38-6": ("5911649beacc", "63bec5b2d7bf"),
    "R38-7": ("d03eabfe8ec0", "f4aa85503842"),
    "R38-8": ("8e481468c39f", "eac22f0fedd8"),
    "R38-9": ("d4385f6c9ac4", "53343132d309"),
    "R39-1": ("211df7dee553", "fb37793fb35f"),
    "R39-2": ("17c3c7892981", "70d53e7f5525"),
    "R39-3": ("81a50cb0dbf3", "1760c70038c6"),
    "R40-1": ("9c50696680e3", "e6558ba600c2"),
    "R40-2": ("2f0eb56853fc", "6f2c03db38a0"),
    "R40-3": ("2d680a75656d", "53d263c8eff8"),
    "R40-4": ("6738249749a3", "4cfa9fff251f"),
    "R41-1": ("1ad0290b689c", "1760c70038c6"),
}


def _finding_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def test_the_text_of_every_finding_is_pinned():
    # ID можно сохранить, а текст заменить — тогда находка «есть», но говорит
    # уже о другом.
    findings = _load("findings")["находки"]
    known = {f["id"] for f in findings}
    lost = sorted(set(FINDING_PINS) - known)
    assert not lost, f"замок есть, находки нет: {lost}"
    for finding in findings:
        pinned = FINDING_PINS.get(finding["id"])
        assert pinned, f"{finding['id']}: находка без замка"
        assert _finding_digest(finding["что"]) == pinned[0], (
            f"{finding['id']}: текст находки подменён — «{finding['что'][:60]}»")


def test_the_binding_between_a_finding_and_its_break_is_pinned():
    """Связь «находка ↔ поломка ↔ сторож» закреплена целиком.

    Проверка «поломка существует и её сторож совпадает с тестом» ловила только
    полбеды: поломку можно было подменить на чужую существующую, а её сторожа
    переписать следом — и ложная «устранена» возвращалась при зелёных тестах.

    Смысловую связь «эта поломка проверяет ИМЕННО этот дефект» программа не
    выведет. Её устанавливают один раз при ревью и дальше защищают замком:
    любая перепривязка меняет слепок. Критерий входит наравне с поломкой и
    сторожем: ревью #28 вернуло R23-1 с положительной приёмки на отрицательную,
    и прежний замок этого не заметил.
    """
    for finding in _load("findings")["находки"]:
        pinned = FINDING_PINS.get(finding["id"])
        assert pinned, f"{finding['id']}: находка без замка"
        binding = [finding.get("поломка", "—"), finding.get("тест", "—"),
                   finding.get("критерий", "—")]
        assert _finding_digest(binding) == pinned[1], (
            f"{finding['id']}: привязка изменена — поломка {binding[0]}, "
            f"сторож {binding[1]}, критерий {binding[2]}")


def test_a_fixed_finding_names_a_guard_that_actually_guards_it():
    # Существующего имени теста недостаточно: можно сослаться на посторонний
    # проходящий тест. Там, где гарантию выражает табличная поломка, находка
    # обязана назвать её ID, и сторож поломки обязан совпасть с тестом.
    import importlib.util
    path = Path(__file__).with_name("test_roundtable_mutations.py")
    spec = importlib.util.spec_from_file_location("rt_mutations", path)
    mutations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutations)
    guards = {case[0]: case[3] for case in mutations.CASES}

    for finding in _load("findings")["находки"]:
        if finding["статус"] != "устранена":
            continue
        break_id = finding.get("поломка")
        assert break_id, f"{finding['id']}: не сказано, какой поломкой это проверяется"
        if break_id == "вне_таблиц":
            assert finding.get("почему_без_поломки", "").strip(), (
                f"{finding['id']}: заявлено «вне таблиц» без объяснения")
            continue
        assert break_id in guards, f"{finding['id']}: поломки {break_id} в наборе нет"
        expected = guards[break_id]
        if expected not in ("контракт", "загрузчик"):
            assert finding["тест"] == expected, (
                f"{finding['id']}: сторож поломки {break_id} — {expected}, "
                f"а находка ссылается на {finding['тест']}: тест не стережёт эту находку")


def test_a_finding_assigned_to_a_block_names_a_criterion_that_exists():
    criteria = {item["id"]
                for spec in BLOCKS["блоки"].values()
                for item in spec["приёмка"]}
    for finding in _load("findings")["находки"]:
        if finding["статус"] != "назначена_блоку":
            continue
        criterion = finding.get("критерий")
        assert criterion, f"{finding['id']}: назначена, но критерий не назван"
        assert criterion in criteria, f"{finding['id']}: критерия {criterion} нет"


def test_a_dismissed_or_open_finding_carries_its_reason():
    # "Избыточна" without an argument is just a finding deleted quietly, and
    # "открыта" without one hides what is still missing.
    for finding in _load("findings")["находки"]:
        if finding["статус"] in ("избыточна", "открыта", "ждёт_Антона"):
            assert finding.get("почему", "").strip(), (
                f"{finding['id']}: {finding['статус']} без обоснования")


def test_the_table_list_matches_the_tables_the_engine_loads():
    module = import_tables_module()
    assert BLOCKS["списки"]["таблицы"] == list(module.TABLE_NAMES)


# Блоки конвейера целиком плюс два правила, живущие в соседних блоках.
# Прежняя версия замка перечисляла девять критериев, выбранных РУКАМИ, и ревью
# #25 удалило БУ-3 — его в списке просто не было. Набор больше не выбирается.
CONVEYOR_BLOCKS = ("БУ", "БА", "БП")
CONVEYOR_EXTRA = ("БИ-13", "Б12-8")


def _conveyor_pairs():
    pairs = []
    for name in CONVEYOR_BLOCKS:
        pairs += [[i["id"], i["условие"]] for i in BLOCKS["блоки"][name]["приёмка"]]
    everywhere = {i["id"]: i["условие"]
                  for spec in BLOCKS["блоки"].values() for i in spec["приёмка"]}
    for identifier in CONVEYOR_EXTRA:
        pairs.append([identifier, everywhere.get(identifier, "—")])
    return pairs


def test_the_conveyor_rules_survive_as_acceptance_criteria():
    """Правила конвейера закреплены ПОЛНЫМ текстом, а не поиском слов.

    Ревью #25 прогнало две подмены против прежней версии этого замка и обе
    прошли: удаление БУ-3 он не заметил вовсе, а БП-1, переписанный в «готовность
    НЕ требует трёх условий… личное принятие не требуется», сохранил слова
    «трёх условий» и прошёл проверку. Поиск слов — не защита смысла, и называть
    его так было очередным «сильнее реализации».
    """
    pairs = _conveyor_pairs()
    assert all(condition != "—" for _, condition in pairs), "критерий конвейера пропал"
    digest = hashlib.sha256(
        json.dumps(pairs, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert digest == "95437b17498d3db0e1d089ebe60eed8d44f8afbaecd6495ae7cabe1133f592f4", (
        "правило конвейера удалено или выхолощено под прежним ID")


def test_the_consent_rule_is_mandatory_and_pinned():
    """Раздел `согласия` обязателен, и его содержание закреплено.

    Ревью #26 удалило раздел целиком из копии: `check()` прошёл, 114 тестов
    прошли, отпечатки объёма не шелохнулись. Загрузчик лишь РАЗРЕШАЛ такое имя
    поля. Критерии БУ-9 и БА-8 ссылаются на правило — значит исполнитель мог
    получить другое правило при тех же критериях и зелёных проверках.
    """
    consent = BLOCKS.get("согласия")
    assert consent, "раздел согласий пропал — критерии ссылаются в пустоту"
    assert consent["сколько"] == 2, "решение Антона 16.09: два этапа — два ОК"
    assert len(consent["цепочка"]) == 2
    assert "передачу" in consent["цепочка"][1]["разрешает"]
    assert consent["передача"], "должно быть сказано, что передача своего ОК не требует"
    digest = hashlib.sha256(
        json.dumps(consent, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert digest == "887cd71a252a8dc65caa429622cb12332d94a29f9009d2b613037e0348fa8590", "правило согласий изменено без обновления замка"


def test_a_rule_a_criterion_points_at_is_part_of_the_scope():
    # Иначе правило переписывается целиком, а разрешение на блок остаётся
    # действующим: блок живёт по другому правилу с прежним отпечатком.
    module = import_tables_module()
    tables = module.load()
    plan = tables.plan
    for name in ("БУ", "БА"):
        block = tables.blocks[name]
        assert "`согласия`" in " ".join(i.condition for i in block.acceptance), name
        assert block.scope(plan)["правила_по_ссылке"]["согласия"] == plan["согласия"]
    thinner = copy.deepcopy(plan)
    thinner["согласия"]["сколько"] = 99
    assert tables.blocks["БУ"].scope_sha256(thinner) != tables.blocks["БУ"].scope_sha256(plan)


def _as_if_complete(tables):
    """Отпечаток, в котором всё объявленное считается.

    Положительный контроль проверок изоляции ставится на ПОЛНОМ отпечатке:
    с несчитаемыми полями шлюз закрыт всегда (ревью #31), и контроль «хороший
    отчёт проходит» был бы невыполним.
    """
    spec = tables.plan["отпечаток_изоляции"]
    deferred = set(spec["пока_не_вычисляется"])
    spec["входит_в_отпечаток"] = [f for f in spec["входит_в_отпечаток"] if f not in deferred]
    spec["пока_не_вычисляется"] = {}


def test_missing_versions_are_never_read_as_agreement(tmp_path, monkeypatch):
    """Нет данных — это отказ, а не согласие.

    Ревью #28: «не смогли спросить» возвращало None, отсутствующее поле в
    отчёте — тоже None, и два неизвестных сравнивались как РАВНЫЕ. Шлюз
    открывался. Проверка идёт с ПОДСТАВЛЕННЫМ ответом среды, иначе на машине
    без вендоров она бы просто пропускалась — а именно там дыра и жила.
    """
    module = import_tables_module()
    tables = module.load()
    spec = tables.plan["отпечаток_изоляции"]
    _as_if_complete(tables)
    for relative in spec["артефакты"].values():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((module.ROOT / relative).read_bytes())
    report = tmp_path / spec["отчёт"]
    report.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    live = {"claude": "версия-A", "codex": "версия-B"}
    base = {"отпечаток": tables.isolation_fingerprint(),
            "verdict": "PASS", "command_frozen": True}

    monkeypatch.setattr(module, "observe_cli_versions", lambda commands: live)
    report.write_text(json.dumps({**base, "versions": live}), encoding="utf-8")
    assert not tables.isolation_drift(), "успешный отчёт при живой среде должен проходить"

    # среда молчит — согласия из этого не возникает
    monkeypatch.setattr(module, "observe_cli_versions", lambda commands: None)
    assert tables.isolation_drift(), "недоступная среда принята за совпадение"

    for broken in ({}, {"versions": None}, {"versions": {"claude": "A"}},
                   {"versions": {"claude": "", "codex": ""}}):
        report.write_text(json.dumps({**base, **broken}), encoding="utf-8")
        monkeypatch.setattr(module, "observe_cli_versions", lambda commands: live)
        assert tables.isolation_drift(), f"отчёт без версий принят: {broken}"


def test_the_mandatory_artefacts_cannot_be_dropped_from_the_rule():
    """Защищено не только содержимое списка, но и его состав.

    Ревью #30 удалило запись `хеш_probe` из `артефакты` — и её просто перестали
    проверять: контракт валиден, 122 теста зелёные, а Ш1 закрывался при
    отсутствующем файле шипа. Проверять каждый ОСТАВШИЙСЯ элемент мало: нужно,
    чтобы обязательный не исчез из самого правила.
    """
    fingerprint = BLOCKS["отпечаток_изоляции"]
    assert set(fingerprint["требуются_всегда"]) == {"хеш_adapters_py", "хеш_probe"}
    for name in fingerprint["требуются_всегда"]:
        assert name in fingerprint["артефакты"], f"{name}: выброшен из артефактов"
        assert name in fingerprint["входит_в_отпечаток"], name


def test_the_fingerprint_does_not_promise_more_than_it_computes():
    """Объявлено семь полей, считается три — и это сказано, а не спрятано.

    Найдено при починке предыдущей находки: `входит_в_отпечаток` перечислял
    argv, env, схему ответа и CODEX_HOME, которых не считает никто. Таблица
    обещала больше, чем проверяет, — тот же класс, что «сильнее реализации».
    """
    fingerprint = BLOCKS["отпечаток_изоляции"]
    # Состав запёрт здесь, а не в таблице: выкинь поле сразу из обоих списков —
    # и контракт согласится, что обещано ровно то, что считается (ревью #31).
    assert set(fingerprint["входит_в_отпечаток"]) == {
        "версии_CLI", "хеш_adapters_py", "хеш_probe", "хеш_нормализованных_argv",
        "хеш_нормализованного_env", "хеш_схемы_ответа", "конфигурация_CODEX_HOME",
    }, "состав отпечатка сужен"
    computed = set(fingerprint["артефакты"]) | {"версии_CLI"}
    promised = set(fingerprint["входит_в_отпечаток"]) - computed
    assert promised == set(fingerprint["пока_не_вычисляется"]), (
        "объявленное поле отпечатка не считается и не объяснено")
    for name, entry in fingerprint["пока_не_вычисляется"].items():
        assert entry["почему"].strip(), f"{name}: сказано «пока не считается» без причины"


def test_every_deferred_field_has_an_owner_with_acceptance():
    """Отсрочка без владельца — ничья работа.

    Ревью #32: четыре поля стояли с причиной, но ни один блок не был обязан их
    вычислить, а повторное подтверждение изоляции не требовало всех семи. Теперь
    каждое поле указывает критерий Ш2, Ш2 держит шлюз изоляции, запуск его ждёт,
    а текст приёмки закреплён целиком — выхолостить его под тем же ID нельзя.
    """
    module = import_tables_module()
    tables = module.load()
    fingerprint = BLOCKS["отпечаток_изоляции"]
    owner = tables.blocks["Ш2"]
    ids = {item.id: item.condition for item in owner.acceptance}
    for field_name, entry in fingerprint["пока_не_вычисляется"].items():
        assert entry["закрывает"] in ids, f"{field_name}: владелец не Ш2"
        assert field_name in ids[entry["закрывает"]], field_name
    assert "Ш2" in BLOCKS["шлюзы"]["изоляция_подтверждена"]["до_закрытия"]
    assert "Ш2" in tables.blocks[fingerprint["блок_запуска"]].depends, (
        "запуск не ждёт полного отпечатка")
    pairs = [[item.id, item.condition] for item in owner.acceptance]
    digest = hashlib.sha256(json.dumps(pairs, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert digest == "6918ea7a27111afef8a5927fd763b95e7cf0a20b26b10985073bb27e34219548", "приёмка полного отпечатка удалена или выхолощена"


def test_an_incomplete_fingerprint_never_opens_the_gate(tmp_path, monkeypatch):
    """Три поля из семи — не подтверждение изоляции.

    Ревью #31: идеальный отчёт по трём вычисляемым полям давал `isolation` 0 и
    `closed("Ш1")` True, а документ перечислял все семь полей и писал
    «совпадает». Окружение и HOME/CODEX_HOME при этом меняются, не трогая ни
    одного хешируемого файла. Пока поле не считается, шлюз закрыт — и документ
    говорит это, а не «совпадает».
    """
    module = import_tables_module()
    tables = module.load()
    spec = tables.plan["отпечаток_изоляции"]
    assert spec["пока_не_вычисляется"], "проверка имеет смысл, пока есть несчитаемое"
    for relative in spec["артефакты"].values():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((module.ROOT / relative).read_bytes())
    report = tmp_path / spec["отчёт"]
    report.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    live = {"claude": "версия-A", "codex": "версия-B"}
    monkeypatch.setattr(module, "observe_cli_versions", lambda commands: live)
    report.write_text(json.dumps({"отпечаток": tables.isolation_fingerprint(),
                                  "verdict": "PASS", "command_frozen": True,
                                  "versions": live}), encoding="utf-8")

    drift = tables.isolation_drift()
    for field_name in spec["пока_не_вычисляется"]:
        assert f"{field_name}: не вычисляется" in drift, field_name
    assert not tables.closed("Ш1"), "неполный отпечаток закрыл Ш1"

    text = "\n".join(module._render_blocks(tables))
    assert "Сейчас **совпадает**" not in text, "документ выдал частичное за полное"
    assert "Не вычисляется" in text
    for field_name in spec["пока_не_вычисляется"]:
        assert field_name in text.split("Не вычисляется", 1)[1].split("\n", 1)[0], (
            f"{field_name}: не назван среди несчитаемых")

    # положительный контроль: тот же отчёт на полном отпечатке проходит
    _as_if_complete(tables)
    assert not tables.isolation_drift()
    assert "Сейчас **совпадает** полностью" in "\n".join(module._render_blocks(tables))


def test_a_missing_file_is_never_read_as_a_matching_fingerprint(tmp_path, monkeypatch):
    """Пропавший файл — отказ, а не совпадение с пустотой.

    Ревью #29, тот же класс, что и с версиями, но во второй половине проверки:
    отсутствующий файл давал пустую строку, пустая строка в отчёте — тоже, и
    два «ничего» сходились. Обязательный файл пропал — шлюз обязан закрыться,
    что бы ни лежало в отчёте.
    """
    module = import_tables_module()
    tables = module.load()
    spec = tables.plan["отпечаток_изоляции"]
    _as_if_complete(tables)
    for relative in spec["артефакты"].values():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((module.ROOT / relative).read_bytes())
    report = tmp_path / spec["отчёт"]
    report.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    live = {"claude": "версия-A", "codex": "версия-B"}
    monkeypatch.setattr(module, "observe_cli_versions", lambda commands: live)

    def _write(fingerprint):
        report.write_text(json.dumps({"отпечаток": fingerprint, "verdict": "PASS",
                                      "command_frozen": True, "versions": live}),
                          encoding="utf-8")

    field, relative = next(iter(spec["артефакты"].items()))
    good = tables.isolation_fingerprint()
    _write(good)
    assert not tables.isolation_drift(), "контроль: целые файлы должны проходить"

    _write({**good, field: ""})
    assert tables.isolation_drift(), "пустой отпечаток в отчёте принят за доказательство"

    (tmp_path / relative).unlink()
    for fingerprint in (good, {**good, field: ""}):
        _write(fingerprint)
        assert tables.isolation_drift(), "пропавший файл принят за совпадение"
        assert not tables.closed("Ш1")


def test_the_architecture_stage_waits_for_the_machinery_it_needs():
    # Критерии БА-3 и БА-6 требуют работающего цикла замечаний и вердикта.
    # Проверка порядка зависимостей этого не стережёт: удалённой зависимости
    # для неё уже не существует, проверять нечего (ревью #28).
    module = import_tables_module()
    tables = module.load()
    depends = set(tables.blocks["БА"].depends)
    for needed, why in (("Б5", "реестры находок"), ("Б6", "вердикт и круги"),
                        ("Б3б", "запуск вендоров"), ("БУ", "цикл уточнений")):
        assert needed in depends, (
            f"БА обещает полную стадию, но не ждёт {needed} — {why}")


def test_the_launcher_is_a_block_that_can_actually_launch():
    """Роль запускателя нельзя переназначить на того, кто не запускает.

    Ревью #27 подменило `блок_запуска` на Б3а — блок, прямо описанный как
    «сборщик команд, БЕЗ запуска». check и все тесты прошли: правило проверяло
    путь к указанному имени, но не то, годится ли это имя.
    """
    module = import_tables_module()
    tables = module.load()
    launcher = BLOCKS["отпечаток_изоляции"]["блок_запуска"]
    assert launcher in tables.blocks, launcher
    external = set(tables.blocks[launcher].external)
    assert "запуск_процесса" in external, (
        f"{launcher} назначен запускателем, а процессов не запускает")
    assert "вызов_модели" in external, (
        f"{launcher} назначен запускателем, а вендоров не зовёт")


def test_the_isolation_report_must_be_a_successful_one():
    """Совпадение хешей — не доказательство успеха.

    Ревью #27 подставило отчёт с теми же хешами и вердиктом FAIL: шлюз
    открывался. Отпечаток доказывает, что проверяли ЭТУ команду; вердикт — что
    проверка удалась. Нужны оба.
    """
    spec = BLOCKS["отпечаток_изоляции"]
    assert spec["успешный_вердикт"] == "PASS"
    assert set(spec["версии_команд"]) == {"claude", "codex"}
    module = import_tables_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'report.get("verdict")' in source
    assert 'report.get("command_frozen")' in source
    assert "observe_cli_versions" in source, (
        "версии обязаны спрашиваться у среды, а не только когда их передали")


def test_a_block_calling_models_must_depend_on_the_launcher():
    """Объявил вызов вендора — обязан зависеть от блока, который умеет звать.

    Ревью #26 сняло ребро БА→Б3б: `check()` и 114 тестов прошли, а в модели
    будущего состояния архитектура переставала удерживаться, хотя запускать
    вызовы ещё нечем. Зависимость «по смыслу» механизм не видит.
    """
    module = import_tables_module()
    tables = module.load()
    launcher = BLOCKS["отпечаток_изоляции"]["блок_запуска"]
    prover = BLOCKS["отпечаток_изоляции"]["проверяет_блок"]

    def ancestors(name, seen=None):
        seen = seen if seen is not None else set()
        for dependency in tables.blocks[name].depends:
            if dependency not in seen:
                seen.add(dependency)
                ancestors(dependency, seen)
        return seen

    for name, block in tables.blocks.items():
        if "вызов_модели" not in block.external or block.outside_mvp:
            continue
        if name in (prover, launcher):
            continue
        assert launcher in ancestors(name), (
            f"{name}: зовёт вендора, но не зависит от {launcher} — звать нечем")


def test_a_block_calling_models_is_held_by_the_isolation_gate():
    """Блок, зовущий вендора, обязан ждать доказательства изоляции.

    БА зовёт модель и не был под шлюзом: архитектуру можно было писать вызовами,
    про которые не доказано, что критик не видит лишнего. Правило общее, а не
    про один блок, — иначе следующий такой блок заведут так же.
    """
    module = import_tables_module()
    tables = module.load()
    held = set(BLOCKS["шлюзы"]["изоляция_подтверждена"]["блокирует"])
    # Единственное исключение — блок, который изоляцию и доказывает: держать его
    # её же шлюзом значило бы требовать доказательство до доказательства.
    prover = BLOCKS["отпечаток_изоляции"]["проверяет_блок"]
    for name, block in tables.blocks.items():
        if "вызов_модели" not in block.external or block.outside_mvp or name == prover:
            continue
        assert name in held, (
            f"{name}: объявлен вызов_модели, а шлюзом изоляции не удерживается")


def test_the_conveyor_is_mandatory_for_release():
    # Блоки конвейера стояли в списке, но выпуск от них не зависел: положение в
    # порядке ничего не держит, механизм пропускает недостижимые блоки.
    module = import_tables_module()
    tables = module.load()

    def ancestors(name, seen=None):
        seen = seen if seen is not None else set()
        for dependency in tables.blocks[name].depends:
            if dependency not in seen:
                seen.add(dependency)
                ancestors(dependency, seen)
        return seen

    required = {"БУ", "БА", "БП"} - ancestors("Б13")
    assert not required, f"выпуск не зависит от конвейера: {sorted(required)}"


def test_the_handoff_names_all_six_pev_points():
    # Выход стола — план уровня L по PEV. Шесть пунктов, не пять и не «примерно».
    points = BLOCKS["списки"]["пункты_плана_PEV"]
    assert len(points) == 6
    assert "делегирование_модель_изоляция" in points, (
        "без пункта «кто и на какой модели берёт блок» план не передаётся агенту")
    assert "неразрешённые_решения_пользователя" in points


def test_the_review_protocol_is_written_down_not_remembered():
    # Шесть кругов чтения прозы стоили больше, чем весь блок БК. Порядок
    # критики — такое же правило, как остальные, и живёт в таблице.
    protocol = BLOCKS["порядок_критики"]
    # 🚩 Ревью #38: правило переписывалось на «годится любое падение», а слова,
    # которые искал этот сторож, сохранялись. Текст закреплён целиком.
    digest = hashlib.sha256(protocol["правило"].encode("utf-8")).hexdigest()
    assert digest == "262849a1734552184bde1b75c4919efb458b9bb717d4c3e230196c2901a4af44", (
        "правило критики переписано: " + protocol["правило"][:120])
    assert len(protocol["классы_мутаций"]) >= 7
    steps = [next(iter(step)) for step in protocol["шаги"]]
    assert steps == ["прогнать_имеющееся", "ломать_на_временной_копии",
                     "отчёт_таблицей"], "порядок шагов — часть правила, а не список"
    assert protocol["чего_не_найдёт"] == "отсутствующее_правило", (
        "метод обязан называть свою границу, иначе им начнут закрывать всё")
    assert protocol["почему"]


def test_the_retry_budget_is_pinned_and_not_left_to_the_implementer():
    # Found by the honest ratchet: every row of this rule could be deleted and
    # nothing noticed. "Попытка повторяется" with no budget is exactly the shape
    # that makes an implementer invent a spending policy for Anton's weekly
    # limit on its own.
    budget = VOCAB["повтор_невалидного_ответа"]
    assert budget["максимум_на_ответ"] == 1
    assert budget["область"] == "на_критика"
    assert budget["тратит_бюджет"] is True, "бесплатный повтор = бесконечный повтор"
    assert budget["порядок"], "недетерминированный порядок копит перекос вендора"
    assert budget["оба_невалидны"], "случай «оба сразу» обязан иметь исход"
    assert budget["сохранённый_валидный_ответ_не_повторять"] is True
    assert budget["после_исчерпания"] in VOCAB["вердикты"]
    # the counter has to survive a crash, so it lives where the journal is
    assert budget["счётчик_живёт_в"] == "журнал_попыток"
    assert set(VOCAB["попытка"]["ключ"]) >= {"критик", "попытка"}


def test_the_cli_fails_when_it_prints_a_failure():
    # `authority` printed «✗ отпечаток изоляции …» and returned 0, so a red
    # result sailed straight through an `&&` chain. Isolation is now its own
    # command with its own exit code — a stale proof must not block the
    # offline blocks, but it must not be silent either.
    module = import_tables_module()
    script = Path(module.__file__)
    # The invariant is environment-independent: whatever the state of the
    # transcripts, the memory or the CLI versions, a printed ✗ must be a
    # non-zero exit. `check` additionally has to be green everywhere, because
    # it reads nothing but the tables.
    for command in ("check", "authority", "isolation"):
        done = subprocess.run([sys.executable, str(script), command],
                              capture_output=True, text=True)
        assert (done.returncode == 0) == ("✗" not in done.stdout), (
            f"{command}: печатает отказ и возвращает успех\n{done.stdout}")
        if command == "check":
            assert done.returncode == 0, done.stdout + done.stderr


def test_the_memory_receipt_names_the_current_canon_and_not_any_old_one(tmp_path, monkeypatch):
    # Any historic canon commit used to pass, so memory could name a long
    # superseded state and still look fresh.
    module = import_tables_module()
    plan = copy.deepcopy(module.load().plan)
    current = module.canon_commit(plan)
    if current is None:
        pytest.skip("git недоступен")

    home = tmp_path
    note = home / "memory" / "project.md"
    note.parent.mkdir(parents=True)
    plan["проверка_памяти"] = {"файлы": [str(note)],
                               "канон": plan["проверка_памяти"]["канон"],
                               "ведутся_записями": []}

    note.write_text(f"канон на коммите `{current[:7]}`", encoding="utf-8")
    assert module.memory_receipt(plan, home) == []

    note.write_text("канон на коммите `bb8ead7`", encoding="utf-8")
    assert module.memory_receipt(plan, home), "устаревший коммит принят как свежий"

    note.write_text("никаких ссылок", encoding="utf-8")
    assert module.memory_receipt(plan, home)


def test_the_isolation_gate_is_computed_and_not_declared(tmp_path, monkeypatch):
    # The gate used to read `closed("Ш1")` and nothing else, so the proof was
    # eternal: change adapters.py without touching a CLI version and it stayed
    # green on evidence that no longer described what runs.
    module = import_tables_module()
    tables = module.load()
    spec = tables.plan["отпечаток_изоляции"]
    _as_if_complete(tables)

    for relative in spec["артефакты"].values():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((module.ROOT / relative).read_bytes())
    report = tmp_path / spec["отчёт"]
    report.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    # Успешный отчёт целиком: совпавший отпечаток, вердикт PASS, замороженная
    # команда и те версии, что стоят сейчас. Меньшего для «закрыт» не хватает.
    versions = module.observe_cli_versions(spec["версии_команд"])
    def _report(**changes):
        base = {"отпечаток": tables.isolation_fingerprint(), "verdict": "PASS",
                "command_frozen": True, "versions": versions}
        base.update(changes)
        return json.dumps(base)

    report.write_text(_report(), encoding="utf-8")
    if versions is None:
        pytest.skip("вендоры недоступны в этой среде — версии не спросить")
    assert tables.isolation_ok(), "успешный отчёт должен открывать шлюз"
    assert tables.closed("Ш1")

    for label, changes in (("вердикт", {"verdict": "FAIL"}),
                           ("заморозка", {"command_frozen": False}),
                           ("версии", {"versions": {"claude": "древняя"}})):
        report.write_text(_report(**changes), encoding="utf-8")
        assert tables.isolation_drift(), f"{label}: негодный отчёт открыл шлюз"
    report.write_text(_report(), encoding="utf-8")

    adapters = tmp_path / spec["артефакты"]["хеш_adapters_py"]
    original = adapters.read_bytes()
    adapters.write_bytes(original + "\n# правка\n".encode("utf-8"))
    assert "хеш_adapters_py" in tables.isolation_drift()
    assert not tables.closed("Ш1"), "изменённая команда обязана закрыть шлюз"
    assert any("изоляция_подтверждена" in r for r in tables.hold_reasons("Б3б"))

    adapters.write_bytes(original)
    stale = {"claude": "2.1.227", "codex": "0.147.0"}
    report.write_text(_report(versions=stale), encoding="utf-8")
    assert tables.isolation_drift({"claude": "2.1.999", "codex": "0.150.0"}) == ["версии_CLI"]

    report.unlink()
    assert tables.isolation_drift() == ["отчёта нет"], "нет отчёта — шлюз закрыт"


def test_the_block_table_is_typed_and_closed():
    # Three mutations used to pass straight through Tables.check().
    module = import_tables_module()
    for mutation, pattern in (
        ({"состояние": "сделанно"}, "нет в словаре"),
        ({"внешние_действия": ["удалить_всё"]}, "нет в словаре"),
        ({"пишет": "core/x.py"}, "ожидался список"),
        ({"вне_MVP": "да"}, "boolean"),
        ({"объявленное_количество": {"таблицы": 0}}, "положительное целое"),
        ({"что": "  "}, "непустая строка"),
    ):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["блоки"]["Б9"].update(mutation)
        with pytest.raises(module.ContractError, match=pattern):
            module.Tables.from_raw(raw)


def test_nothing_is_worked_on_without_a_live_permission():
    # In-flight work needs a permission for its *current* scope. Finished work
    # needs only to have had one: history explains why closed blocks were
    # closed, it does not authorise anything now.
    module = import_tables_module()
    tables = module.load()
    working = set(VOCAB["состояния_блока"]["рабочие"])
    historic = {b for g in BLOCKS["история_разрешений"] for b in g["блоки"]}
    for name, block in tables.blocks.items():
        if name == "Б0а" or block.state is None:
            continue
        if block.state in working:
            assert tables.permitted(name) is not None, f"{name}: в работе без разрешения"
        else:
            assert tables.permitted(name) or name in historic, f"{name}: разрешения нет нигде"


def test_a_block_cannot_be_worked_on_under_a_stale_permission():
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    raw["blocks"]["блоки"]["Б1"]["приёмка"].append(
        {"id": "Б1-99", "условие": "дописал себе работы после разрешения"})
    with pytest.raises(module.ContractError, match="Б1: в работе"):
        module.Tables.from_raw(raw).check()


def test_a_gate_holds_everything_downstream_until_the_repair_is_closed():
    module = import_tables_module()
    tables = module.load()
    for gate, spec in BLOCKS["шлюзы"].items():
        assert not set(spec["блокирует"]) & set(spec["до_закрытия"]), (
            f"{gate}: блок не может одновременно держать шлюз и держаться им")
        if all(tables.closed(b) for b in spec["до_закрытия"]):
            continue
        for held in spec["блокирует"]:
            assert f"удерживается шлюзом {gate}" in tables.hold_reasons(held)


def test_the_gate_actually_refuses_a_block_started_too_early():
    # The invariant is only worth its line if it fires. Round 14 caught me
    # weakening exactly this kind of assertion in the same commit as the data.
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    raw["blocks"]["блоки"]["Б15"]["состояние"] = "сделано"
    with pytest.raises(module.ContractError, match="шлюз"):
        module.Tables.from_raw(raw).check()


def test_every_hold_reason_is_reported_not_just_the_first():
    # A block can be unpermitted *and* waiting on a dependency *and* under a
    # gate. Printing one of the three sends the reader to fix the wrong thing.
    tables = import_tables_module().load()
    reasons = tables.hold_reasons("Б15")
    assert len(reasons) >= 3, reasons
    assert any("нет разрешения" in r for r in reasons)
    assert any("ждёт зависимость" in r for r in reasons)
    assert any("шлюзом" in r for r in reasons)


def test_the_header_reports_completion_and_stoppage_not_just_progress():
    # "Следующий блок — Б1" was typed by hand and went stale. The two branches
    # nobody exercises are the interesting ones: everything done, and nothing
    # runnable.
    module = import_tables_module()

    finished = copy.deepcopy(module.load().raw)
    for name in finished["blocks"]["порядок"]:
        finished["blocks"]["блоки"][name]["состояние"] = "сделано"
    tables = module.Tables.from_raw(finished)
    # Ш1 is derived: with the fingerprint adrift it is not closed, and the
    # header must not claim completion. That branch is the point of the gate.
    assert "Остановлено" in "\n".join(module.SECTIONS["status"](tables))
    object.__setattr__(tables, "isolation_drift", lambda observed=None: [])
    assert "MVP завершён" in "\n".join(module.SECTIONS["status"](tables))

    stuck = copy.deepcopy(module.load().raw)
    stuck["blocks"]["разрешения_исполнения"] = []
    tables = module.Tables.from_raw(stuck)
    text = "\n".join(module.SECTIONS["status"](tables))
    assert "Остановлено" in text and "нет разрешения" in text


def test_an_absorbed_block_closes_only_with_its_absorber():
    # БИ waited on БТ2 while БТ2 closed with БИ: a deadlock running through two
    # different kinds of edge, which no cycle check would have seen.
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    blocks = raw["blocks"]["блоки"]
    blocks["БТ2"]["состояние"] = "объединён_с"
    blocks["БТ2"]["объединён_с"] = "БИ"
    blocks["БИ"]["поглощает"] = ["БТ2"]
    with pytest.raises(module.ContractError, match="тупик"):
        module.Tables.from_raw(raw).check()

    blocks["БИ"]["зависит"] = ["Б2", "БТ"]
    with pytest.raises(module.ContractError, match="приёмка"):
        module.Tables.from_raw(raw).check()


def test_absorption_cannot_be_circular():
    module = import_tables_module()
    for chain in (["БТ2", "БИ"], ["БТ2", "БИ", "Б9"]):
        raw = copy.deepcopy(module.load().raw)
        blocks = raw["blocks"]["блоки"]
        for name, nxt in zip(chain, chain[1:] + chain[:1]):
            blocks[name]["состояние"] = "объединён_с"
            blocks[name]["объединён_с"] = nxt
            blocks[nxt]["поглощает"] = [name]
        with pytest.raises(module.ContractError, match="цикл поглощения"):
            module.Tables.from_raw(raw).check()


def test_absorbed_acceptance_is_compared_with_its_text():
    # Keeping every id and replacing every condition used to pass: the set
    # comparison saw nothing, and the criteria were gone.
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    blocks = raw["blocks"]["блоки"]
    blocks["БТ2"]["состояние"] = "объединён_с"
    blocks["БТ2"]["объединён_с"] = "БИ"
    blocks["БИ"]["поглощает"] = ["БТ2"]
    blocks["БИ"]["зависит"] = ["Б2", "БТ"]
    blocks["БИ"]["пишет"] = sorted(set(blocks["БИ"]["пишет"]) | set(blocks["БТ2"]["пишет"]))
    blocks["БИ"]["читает"] = sorted(set(blocks["БИ"]["читает"]) | set(blocks["БТ2"]["читает"]))
    blocks["БИ"]["приёмка"] = blocks["БИ"]["приёмка"] + [
        {"id": item["id"], "условие": "ПОДМЕНЕНО"} for item in blocks["БТ2"]["приёмка"]]
    with pytest.raises(module.ContractError, match="потеряна или подменена"):
        module.Tables.from_raw(raw).check()


def test_every_absorption_formula_fires_on_its_own():
    # БК-7. Приёмка сверялась по тексту, а зависимости и области — нет: поглотитель
    # мог потерять ребро или файл поглощённого, и никто этого не видел.
    module = import_tables_module()

    def absorbed():
        raw = copy.deepcopy(module.load().raw)
        blocks = raw["blocks"]["блоки"]
        blocks["БТ2"]["состояние"] = "объединён_с"
        blocks["БТ2"]["объединён_с"] = "БИ"
        blocks["БИ"]["поглощает"] = ["БТ2"]
        blocks["БИ"]["зависит"] = ["Б2", "БТ"]
        for field in ("пишет", "читает"):
            blocks["БИ"][field] = sorted(set(blocks["БИ"][field]) | set(blocks["БТ2"][field]))
        blocks["БИ"]["приёмка"] = blocks["БИ"]["приёмка"] + blocks["БТ2"]["приёмка"]
        return raw, blocks

    raw, blocks = absorbed()
    module.Tables.from_raw(raw).check()          # положительный контроль

    raw, blocks = absorbed()
    blocks["БИ"]["зависит"] = ["Б2"]
    with pytest.raises(module.ContractError, match="зависимости БТ2 потеряны"):
        module.Tables.from_raw(raw).check()

    for field in ("пишет", "читает"):
        raw, blocks = absorbed()
        blocks["БИ"][field] = [p for p in blocks["БИ"][field]
                               if p not in blocks["БТ2"][field]]
        with pytest.raises(module.ContractError, match=f"{field} блока БТ2 не покрыто"):
            module.Tables.from_raw(raw).check()

    raw, blocks = absorbed()
    blocks["БИ"]["поглощает"] = []
    with pytest.raises(module.ContractError, match="не объявил поглощение"):
        module.Tables.from_raw(raw).check()


def test_a_gate_lets_its_own_preconditions_close():
    # БК-6, вторая сторона. Шлюз, который держит и собственные предусловия,
    # не откроется никогда — «блок из до_закрытия закрывается» проверяется
    # закрытием, а не отсутствием пересечения множеств.
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    gate = raw["blocks"]["шлюзы"]["ремонт_после_ревью_12"]
    precondition = next(n for n in gate["до_закрытия"] if n == "БТ2")
    raw["blocks"]["блоки"][precondition].update(состояние="сделано", коммиты=["a" * 40])
    raw["blocks"]["исполнение"]["блоки"].pop(precondition)   # закрытое не исполняется
    tables = module.Tables.from_raw(raw)
    tables.check()
    assert not any("шлюзом" in r for r in tables.hold_reasons(precondition) or [])
    assert tables.closed(precondition)


def test_a_permission_artefact_lives_in_the_repository(tmp_path, monkeypatch):
    # БК-17. 16.09 утверждённый план исчез из ~/.claude/plans, и заключение
    # ревью указывало в пустоту. Основание-артефакт обязано лежать в
    # репозитории и резолвиться от его корня, а не от текущего каталога.
    module = import_tables_module()
    for registry in ("заключения_ревью", "разрешения_исполнения", "история_разрешений"):
        for entry in BLOCKS[registry]:
            basis = entry["основание"]
            if basis["вид"] == "план_артефакт":
                assert (module.ROOT / basis["путь"]).is_file(), basis["путь"]

    for outside in ("~/.claude/plans/plan.md", "/tmp/plan.md", "docs/../../plan.md"):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["заключения_ревью"][0]["основание"]["путь"] = outside
        with pytest.raises(module.ContractError, match="вне репозитория"):
            module.Tables.from_raw(raw).check()

    relative = "deploy/tests/fixtures/roundtable/plan.md"
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_text("замысел", encoding="utf-8")
    digest = hashlib.sha256((tmp_path / relative).read_bytes()).hexdigest()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    basis = {"вид": "план_артефакт", "путь": relative, "sha256": digest}
    assert module.resolve_basis(basis, tmp_path / "home") is None

    # ярлык внутри репозитория, ведущий наружу, — то же «вне репозитория»
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("замысел", encoding="utf-8")
    link = tmp_path / "deploy/tests/fixtures/roundtable/link.md"
    link.symlink_to(outside)
    escaped = {**basis, "путь": "deploy/tests/fixtures/roundtable/link.md"}
    assert "вне репозитория" in (module.resolve_basis(escaped, tmp_path / "home") or "")


def test_acceptance_ids_are_unique_across_the_whole_plan():
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    raw["blocks"]["блоки"]["Б9"]["приёмка"] = [{"id": "Б1-1", "условие": "чужой ID"}]
    with pytest.raises(module.ContractError, match="у двух блоков"):
        module.Tables.from_raw(raw).check()


def test_the_isolation_fingerprint_is_more_than_a_version_string():
    # Change adapters.py without touching the CLI versions and the old gate
    # stayed green on a proof that no longer described the command.
    fingerprint = BLOCKS["отпечаток_изоляции"]
    assert fingerprint["отчёт"].endswith("isolation-report.json")
    parts = set(fingerprint["входит_в_отпечаток"])
    for part in ("версии_CLI", "хеш_нормализованных_argv", "хеш_adapters_py",
                 "хеш_схемы_ответа", "хеш_probe"):
        assert part in parts, part
    # every named artefact must actually be hashable from the tree
    module = import_tables_module()
    for relative in fingerprint["артефакты"].values():
        assert (module.ROOT / relative).is_file(), relative


def test_a_negative_claim_about_an_event_needs_the_raw_source():
    # Cost a whole round: a filtered search dropped a message that existed, and
    # I reported "не нашёл" as "не существует".
    # 🚩 Ревью #38: запрет на вывод по обрезанному поиску можно было удалить —
    # этот сторож смотрел только на два поля, а замер полноты исключал раздел
    # целиком. Правило закреплено целиком и в знаменателе замера.
    rule = BLOCKS["проверки_источников"]["отрицательное_утверждение_о_событии"]
    assert rule["источник"] == "сырой_JSONL"
    assert sorted(rule["запрещено"]) == ["отфильтрованный_корпус",
                                         "поиск_с_ограничением_длины"], (
        f"запрет ослаблен: {rule['запрещено']}")
    assert rule["почему"].strip()


def test_an_unfinished_block_states_what_blocks_it():
    # A block that is neither done nor blocked is a block nobody is holding:
    # that is how "waiting on something" quietly becomes "forgotten".
    for name, spec in BLOCKS["блоки"].items():
        if spec.get("состояние") == "неполный":
            assert spec.get("блокер"), f"{name}: не сказано, чем заблокирован"


def test_the_loader_refuses_a_duplicated_key():
    # Guards the loader itself: without this, a table can hold two values for
    # one rule and the suite reads only the last.
    import io
    with pytest_raises(yaml.constructor.ConstructorError):
        yaml.load(io.StringIO("a: 1\na: 2\n"), Loader=StrictLoader)


def pytest_raises(exc):
    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, kind, value, tb):
            assert kind is not None and issubclass(kind, exc), "expected a refusal"
            return True
    return _Ctx()


# --------------------------------------------------------------------------
# stages: the panel looks for the right solution first (Anton, 2026-08-12)
# --------------------------------------------------------------------------

def test_every_stage_is_described_and_only_the_declared_ones():
    declared = set(VOCAB["стадии"]["в_MVP"]) | set(VOCAB["стадии"]["вне_MVP"])
    assert set(STAGES["стадии"]) == declared


def test_the_idea_stage_asks_before_it_shows():
    idea = STAGES["стадии"]["идея"]
    assert idea["первый_вопрос"] == "предложи_решение"
    assert idea["второй_вопрос"] == "сравни_с_предложенным"
    assert idea["итог"] == "сравнение_подходов", "not a verdict on one option"
    assert idea["критиков"] == 2, "no saving on the cheapest, most valuable stage"


def test_the_blind_question_hides_the_solution_and_nothing_else():
    blind = STAGES["слепой_вопрос"]
    assert "предложенное_решение" in blind["прячем"]
    assert {"задача", "ограничения", "критерий_успеха"} <= set(blind["показываем"])
    assert not set(blind["показываем"]) & set(blind["прячем"])


def test_two_independent_alternatives_reach_anton_before_any_counting():
    signal = STAGES["сигнал_нежизнеспособности"]
    assert signal["действие"] == "сразу_Антону"
    assert signal["до"] == "подсчёта_блокеров"


def test_the_cost_of_understanding_is_recorded_with_a_baseline():
    metric = STAGES["метрика_цены_понимания"]
    assert {"стадия", "круг", "потрачено_вызовов", "кто_назвал"} <= set(metric["что_пишем"])
    assert metric["базовая_точка"]["круг"] == 10, "our own number stays visible"


def test_stage_rules_agree_between_tables():
    for stage, rules in STAGES["стадии"].items():
        expected = FRAMING["влияние_по_стадиям"][stage]
        actual = rules["возражение_к_постановке"]
        assert (actual == "держит_стадию") == (expected == "держит_стадию"), stage
        assert rules["постановка"] == FRAMING["права_по_стадиям"][stage]["постановка"]


def test_spending_priority_favours_the_earliest_stage():
    priority = STAGES["приоритет_расхода"]
    assert "идея" not in priority["экономим_на"]
    assert set(priority["экономим_на"]) <= set(STAGES["стадии"])


def test_closed_code_lists_are_pinned_whole():
    # Deleting a refusal code or a condition code silently narrows what the
    # engine can express, and every other test would still pass.
    assert set(VOCAB["коды_отказа"]) == {
        "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ", "КОНФЛИКТ_ВХОДА",
        "РЕШЕНИЕ_ВНЕ_ТИПА", "ЕСТЬ_ЗАВИСИМЫЕ_СОБЫТИЯ", "ПРОГОН_ЗАНЯТ",
    }
    assert set(VOCAB["коды_условий"]) == {
        "verdict", "decision", "framing_decision", "budget_allows_round",
        "budget_fits_quorum", "change_index", "round_running",
        "run_finished", "all_verdict_blocking_resolved",
    }
    assert set(VOCAB["решения_по_возражению"]) == {
        "подтвердить_постановку", "изменить_цель", "сменить_решение", "остановить",
    }


def test_every_stage_rule_carries_its_reason():
    # A rule with no stated reason gets re-litigated; that is how ten rounds
    # happen. Each block below is a decision Anton made explicitly.
    assert STAGES["слепой_вопрос"]["почему"] and STAGES["слепой_вопрос"]["ограничение"]
    assert STAGES["сигнал_нежизнеспособности"]["условие"] == \
        "оба_критика_независимо_назвали_другой_подход"
    assert STAGES["сигнал_нежизнеспособности"]["почему"]
    assert STAGES["метрика_цены_понимания"]["когда"]
    assert STAGES["метрика_цены_понимания"]["зачем"]
    for key in ("правило", "почему", "отменяет"):
        assert STAGES["приоритет_расхода"][key], key


def test_the_foundation_block_states_what_it_must_deliver():
    # БТ is the block that makes the tables executable rather than decorative;
    # dropping any of its criteria quietly turns it back into a formality.
    criteria = " | ".join(i["условие"] for i in BLOCKS["блоки"]["БТ"]["приёмка"])
    for requirement in (
        "загрузчик", "дубликаты", "закрытые коды", "ровно один исход",
        "не только отмена", "без правки Python", "генерируются", "мутации",
    ):
        assert requirement in criteria, requirement


def test_the_write_scope_rule_is_pinned():
    """R19-7: исключения из сверки записи названы поимённо и заперты.

    Добавь блок в `до_правила` — и он закрывается без коммитов, то есть без
    сверки. Трейлер тоже нельзя переименовать молча: старые коммиты перестали
    бы находиться, и «работа мимо учёта» стала бы невидимой.
    """
    rule = BLOCKS["сверка_записи"]
    assert set(rule["до_правила"]) == {"Б0а", "Б3а", "Ш1", "БТ"}, (
        "список «до правила» расширен — блок ушёл от сверки")
    assert rule["трейлер"] == "Roundtable-Block"
    module = import_tables_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "write_scope_receipt(tables)" in source, "authority перестал сверять запись"


def _git_repo(tmp_path):
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("config", "commit.gpgsign", "false")

    def commit(files, message):
        for relative, text in files.items():
            target = tmp_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            git("add", relative)
        git("commit", "-q", "-m", message)
        return git("rev-parse", "HEAD")
    return git, commit


def test_commits_of_a_closed_block_are_checked_against_its_scope(tmp_path, monkeypatch):
    """Коммит блока, вышедший за `пишет`, — отказ, а не молчание.

    Проверка на настоящем git во временном каталоге: положительный контроль
    (коммит в пределах объявленного проходит), затем по одному нарушению на
    каждый путь обхода — чужой файл, нет трейлера, коммит мимо учёта,
    несуществующий коммит, слияние.
    """
    module = import_tables_module()
    git, commit = _git_repo(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    base = commit({"README": "x"}, "init")

    def tables_with(commits):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["блоки"]["БК"]["коммиты"] = []
        raw["blocks"]["блоки"]["БТ2"]["состояние"] = "сделано"
        raw["blocks"]["блоки"]["БТ2"]["коммиты"] = commits
        return module.Tables.from_raw(raw)

    good = commit({"deploy/tests/test_roundtable_decide.py": "ok"}, "работа\n\nRoundtable-Block: БТ2")
    assert module.write_scope_receipt(tables_with([good])) == [], "контроль: честный коммит"

    wide = commit({"core/scripts/roundtable/adapters.py": "чужое"}, "работа\n\nRoundtable-Block: БТ2")
    problems = module.write_scope_receipt(tables_with([good, wide]))
    assert any("вышел за `пишет`" in p and "adapters.py" in p for p in problems), problems

    bare = commit({"deploy/tests/test_roundtable_decide.py": "ещё"}, "без трейлера")
    assert any("без трейлера" in p for p in module.write_scope_receipt(tables_with([good, bare])))

    # помечен блоком, но в его списке не назван — работа мимо учёта
    assert any("мимо учёта" in p for p in module.write_scope_receipt(tables_with([good])))

    assert any("нет" in p for p in module.write_scope_receipt(tables_with(["0" * 40])))

    git("checkout", "-q", "-b", "side", base)
    commit({"deploy/tests/test_roundtable_decide.py": "бок"}, "бок")
    git("checkout", "-q", "-")
    git("merge", "-q", "--no-edit", "-X", "ours", "side")
    merge = git("rev-parse", "HEAD")
    assert any("слияние" in p for p in module.write_scope_receipt(tables_with([merge])))


def test_staged_work_is_checked_before_the_commit(tmp_path, monkeypatch):
    # Исполнитель сверяет подготовленное ДО коммита: `tables.py scope <блок>`.
    module = import_tables_module()
    git, commit = _git_repo(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    commit({"README": "x"}, "init")
    tables = module.load()
    (tmp_path / "deploy/tests").mkdir(parents=True)
    (tmp_path / "deploy/tests/test_roundtable_decide.py").write_text("ok", encoding="utf-8")
    git("add", "deploy/tests/test_roundtable_decide.py")
    assert module.staged_outside_scope(tables, "БТ2") == [], "контроль: своё проходит"
    (tmp_path / "README").write_text("чужое", encoding="utf-8")
    git("add", "README")
    assert module.staged_outside_scope(tables, "БТ2") == ["README"]


def test_a_block_writing_engine_code_declares_its_tests():
    # R33-1: с включённой сверкой записи блок без объявленного файла тестов либо
    # не смог бы их написать, либо спрятал бы их в чужом файле мимо учёта.
    rule = BLOCKS["сверка_записи"]
    for name, row in BLOCKS["блоки"].items():
        if name in rule["до_правила"] or row.get("состояние") == "сделано":
            continue
        code = [p for p in row["пишет"]
                if p.startswith(rule["код_движка"]) and p.endswith(".py")]
        if code:
            assert any(p.startswith(rule["тесты"]) for p in row["пишет"]), (
                f"{name}: пишет код движка, файл тестов не объявлен")


def test_the_execution_plan_is_checked_by_the_contract():
    # R33-3: план исполнения — данные. Каждый незакрытый блок MVP назван ровно
    # один раз, у каждого внешний критик, параллельные волны — в worktree.
    module = import_tables_module()
    tables = module.load()
    rows = BLOCKS["исполнение"]["блоки"]
    pending = {n for n, b in tables.blocks.items() if b.state != "сделано" and not b.outside_mvp}
    # Ревью #36: здесь оставалось отменённое правило «Ш1 нужен, только пока есть
    # несчитаемые поля». Нужность повторного прогона решают флаг подтверждения и
    # блоки, пишущие во входы отпечатка, — то же, что в контракте.
    fingerprint = BLOCKS["отпечаток_изоляции"]
    writers = {n for n in pending
               if module._overlaps(tables.blocks[n].writes, fingerprint["входы"])}
    if not fingerprint["подтверждение_действует"] or writers:
        pending.add(fingerprint["проверяет_блок"])
    assert set(rows) == pending
    assert writers, "некому отменить подтверждение — проверка потеряла смысл"
    assert all("codex" in row["ревью"] for row in rows.values())
    assert any("scope" in step for step in BLOCKS["исполнение"]["шаги"]), (
        "сверка подготовленного выпала из шагов исполнения")


def test_the_write_scope_check_fails_closed(tmp_path, monkeypatch):
    """Находки независимого ревью #33 — по одной проверке на каждую.

    Молчание git было «пустым diff» и «пустой историей»; корневой коммит
    отвергался и при этом его diff не читался вовсе; имя с пробелом или
    не-ASCII разваливалось; строка «Блок: X» в теле письма засчитывалась
    трейлером.
    """
    module = import_tables_module()
    git, commit = _git_repo(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def tables_with(commits):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["блоки"]["БК"]["коммиты"] = []
        raw["blocks"]["блоки"]["БТ2"]["состояние"] = "сделано"
        raw["blocks"]["блоки"]["БТ2"]["коммиты"] = commits
        raw["blocks"]["блоки"]["БТ2"]["пишет"].append("deploy/tests/fixtures/roundtable/")
        return module.Tables.from_raw(raw)

    # корневой коммит — обычный, и его файлы сверяются
    root = commit({"core/scripts/roundtable/adapters.py": "чужое"}, "корень\n\nRoundtable-Block: БТ2")
    problems = module.write_scope_receipt(tables_with([root]))
    assert not any("слияние" in p for p in problems), problems
    assert any("вышел за" in p for p in problems), "diff корневого коммита не прочитан"

    good = commit({"deploy/tests/fixtures/roundtable/имя с пробелом.md": "ok"},
                  "работа\n\nRoundtable-Block: БТ2")
    problems = module.write_scope_receipt(tables_with([root, good]))
    assert not any(good[:7] in p for p in problems), f"не-ASCII имя с пробелом: {problems}"

    spoof = commit({"deploy/tests/test_roundtable_decide.py": "x"},
                   "в тексте строка\nRoundtable-Block: БТ2\nи продолжение без трейлера")
    assert any("без трейлера" in p for p in module.write_scope_receipt(
        tables_with([root, good, spoof]))), "строка в теле принята за трейлер"

    monkeypatch.setattr(module, "_git", lambda *args: None)
    assert module.write_scope_receipt(tables_with([])), "молчание git принято за чистоту"
    assert module.write_scope_receipt(tables_with([good])), "молчание git принято за чистоту"


def test_a_commit_from_an_unmerged_branch_does_not_count(tmp_path, monkeypatch):
    # Ревью #34: работа исполнителя в своей ветке существует, но ещё не влита —
    # сверка её принимала. Контроль: тот же коммит после влития проходит.
    module = import_tables_module()
    git, commit = _git_repo(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    base = commit({"README": "x"}, "init")

    def tables_with(commits):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["блоки"]["БК"]["коммиты"] = []
        raw["blocks"]["блоки"]["БТ2"]["состояние"] = "сделано"
        raw["blocks"]["блоки"]["БТ2"]["коммиты"] = commits
        return module.Tables.from_raw(raw)

    git("checkout", "-q", "-b", "worker")
    work = commit({"deploy/tests/test_roundtable_decide.py": "ok"},
                  "работа\n\nRoundtable-Block: БТ2")
    git("checkout", "-q", "-")
    problems = module.write_scope_receipt(tables_with([work]))
    assert any("не входит в проверяемую ветку" in p for p in problems), problems
    git("merge", "-q", "--ff-only", "worker")
    assert module.write_scope_receipt(tables_with([work])) == [], "контроль: влитый проходит"
    assert base


def test_the_execution_plan_survives_a_dry_run():
    """Ревью #34: правила по отдельности зелёные, а план не проходится.

    Ш2 ждал Ш1, который закрывается только полным отпечатком от Ш2 — круг;
    Б0б стоял во второй волне под шлюзом, открывающимся после четвёртой.
    Сухой прогон волн с тем же `hold_reasons`, что в бою, ловит оба. Он
    встроен в `check`: «contract valid» теперь значит и «план проходится».
    """
    module = import_tables_module()
    tables = module.load()
    rows = BLOCKS["исполнение"]["блоки"]
    assert "Ш1" not in tables.blocks["Ш2"].depends, "круг Ш2 → Ш1 → полный отпечаток → Ш2"
    assert "Ш1" in rows, "повторный Ш1 выпал из плана при неполном отпечатке"
    assert min(rows["Ш1"]["волна"]) > rows["Ш2"]["волна"]
    assert max(rows["Ш1"]["волна"]) > rows["Б7"]["волна"], (
        "после правки кода запуска подтверждение не восстановлено")
    assert rows["Б0б"]["волна"] > rows["БИ"]["волна"], "Б0б раньше ремонтного шлюза"
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "self._dry_run(" in source, "сухой прогон выпал из проверки контракта"
    tables.check()


def test_completing_the_fingerprint_does_not_confirm_isolation():
    """Ревью #35: «все поля умеем считать» принималось за «изоляция подтверждена».

    Сценарий критика в памяти: Ш2 завершён, список несчитаемых пуст, живого
    подтверждения нет. Прежде проверка требовала УБРАТЬ повторный Ш1 и после
    этого объявляла путь исполнимым. Теперь повторный Ш1 обязателен, пока
    флаг подтверждения ложен или кто-то впереди пишет во входы отпечатка.
    """
    import dataclasses
    module = import_tables_module()

    def after_sh2():
        tables = module.load()
        tables.blocks["Ш2"] = dataclasses.replace(tables.blocks["Ш2"], state="сделано")
        tables.plan["отпечаток_изоляции"]["пока_не_вычисляется"] = {}
        del tables.plan["исполнение"]["блоки"]["Ш2"]
        return tables

    tables = after_sh2()
    tables._check_execution()  # повторный Ш1 остался — план проходится

    tables = after_sh2()
    del tables.plan["исполнение"]["блоки"]["Ш1"]
    with pytest.raises(module.ContractError, match="повторного Ш1"):
        tables._check_execution()

    # правка входа отпечатка отменяет подтверждение: одного Ш1 до Б3б мало
    tables = after_sh2()
    tables.plan["исполнение"]["блоки"]["Ш1"]["волна"] = [8]
    with pytest.raises(module.ContractError, match="состояние запрещено"):
        tables._check_execution()


def test_the_confirmation_flag_is_checked_against_reality():
    # Флаг «подтверждение действует» ставится руками — значит, его сверяет
    # `authority` с настоящим отпечатком, иначе он стал бы новой лазейкой.
    module = import_tables_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'if plan["отпечаток_изоляции"]["подтверждение_действует"]:' in source
    spec = BLOCKS["отпечаток_изоляции"]
    assert spec["подтверждение_действует"] is False, "подтверждения нет: CLI обновились"
    assert set(spec["входы"]) == {
        "core/scripts/roundtable/adapters.py", "deploy/tests/isolation_probe.py",
        "core/scripts/roundtable/schemas/"}, "входы отпечатка сужены"


def test_a_closed_block_under_an_open_gate_needs_a_scheduled_reproof():
    """Ревью #36: прогон разрешал состояние, которое контракт запрещает.

    Б3б правит код запуска, подтверждение изоляции отменяется — и закрытие Б3б
    уже нельзя записать по правилам плана, хотя прогон шёл дальше. Правило
    теперь одно: закрытый блок под открытым шлюзом допустим, только если не
    закрыт ровно доказывающий блок и его повторный прогон стоит в плане позже.
    Переходный случай «всё умеем считать, живого подтверждения нет» — здесь же.
    """
    import dataclasses
    module = import_tables_module()

    def after_sh2():
        tables = module.load()
        tables.blocks["Ш2"] = dataclasses.replace(tables.blocks["Ш2"], state="сделано")
        tables.plan["отпечаток_изоляции"]["пока_не_вычисляется"] = {}
        del tables.plan["исполнение"]["блоки"]["Ш2"]
        return tables

    # контроль: повторный Ш1 после Б3б и Б7 — план проходится
    module.load().check()
    after_sh2()._check_execution()

    # один прогон Ш1 до правок кода запуска — состояние после волны 9 запрещено
    for tables in (module.load(), after_sh2()):
        tables.plan["исполнение"]["блоки"]["Ш1"]["волна"] = [8]
        with pytest.raises(module.ContractError, match="состояние запрещено"):
            tables._check_execution()

    # исключение узкое: ремонтный шлюз им не пользуется
    tables = module.load()
    prover = tables.plan["отпечаток_изоляции"]["проверяет_блок"]
    assert tables.gate_violations(lambda n: n == prover, lambda n: n == "Б15"), (
        "закрытый блок под ремонтным шлюзом обязан оставаться нарушением")


def test_a_really_closed_block_keeps_its_wave_in_the_record():
    """Ревью #37: исключение исчезало ровно при настоящем закрытии блока.

    Волна блока бралась из списка БУДУЩИХ работ, а закрытый блок оттуда
    убирают — и запрет снова срабатывал на уже законно сделанной работе.
    Сценарий критика воспроизведён целиком: Б3б закрыт, его строка удалена,
    повторный прогон доказывающего блока ещё впереди.
    """
    module = import_tables_module()
    raw = copy.deepcopy(module.load().raw)
    plan = raw["blocks"]
    closed_now = {"Б1": 2, "БТ2": 2, "Б2": 3, "БИ": 4, "БУ": 5, "Б15": 5,
                  "Б0б": 5, "Б4": 6, "Ш2": 7, "Б5": 7, "Б6": 8, "Б3б": 9, "Б9": 9}
    for name, wave in closed_now.items():
        plan["блоки"][name]["состояние"] = "сделано"
        plan["блоки"][name]["коммиты"] = ["a" * 40]
        plan["исполнение"]["выполнено"][name] = wave
        plan["исполнение"]["блоки"].pop(name, None)
    plan["отпечаток_изоляции"]["пока_не_вычисляется"] = {}
    tables = module.Tables.from_raw(raw)
    started = lambda n: plan["блоки"][n].get("состояние") == "сделано"
    prover = plan["отпечаток_изоляции"]["проверяет_блок"]

    assert tables.gate_violations(lambda n: n != prover, started) == [], (
        "законно закрытый блок снова стал нарушением, когда ушёл из будущих работ")

    # повторного прогона в плане нет — исключение не действует
    without = copy.deepcopy(raw)
    del without["blocks"]["исполнение"]["блоки"][prover]
    assert module.Tables.from_raw(without).gate_violations(
        lambda n: n != prover,
        lambda n: without["blocks"]["блоки"][n].get("состояние") == "сделано"), (
        "блок закрыт без запланированного повторного доказательства")

    # блока нет ни в будущих работах, ни в выполненных — когда он закрылся, неизвестно
    forgotten = copy.deepcopy(raw)
    del forgotten["blocks"]["исполнение"]["выполнено"]["Б3б"]
    assert module.Tables.from_raw(forgotten).gate_violations(
        lambda n: n != prover,
        lambda n: forgotten["blocks"]["блоки"][n].get("состояние") == "сделано"), (
        "закрытие без записанной волны принято за законное")


def test_a_permission_cannot_be_rewritten_in_place():
    """Разрешение — запись, а не переменная.

    🚩 Ревью #38: расширить себе объём можно было, пересчитав хеш в той же
    таблице: сравнивались два значения, оба правимые. Настоящая независимая
    сторона — реплика Антона в транскрипте, её подделать нельзя (это проверяет
    `authority`). Здесь закрепляется вторая половина: выданные разрешения
    неизменяемы, новое можно только ДОБАВИТЬ, и это видно в изменениях.
    """
    grants = [[g["кем"], sorted(g["блоки"]), str(g["дата"]), g["scope_sha256"],
               {k: str(v) for k, v in g["основание"].items()}]
              for g in BLOCKS["разрешения_исполнения"]]
    digest = hashlib.sha256(
        json.dumps(grants, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert digest == "3c2d4ec98b41a2ac36d35befbb245664322fec647a36fc819b3c1f930f3991d0", (
        "выданное разрешение переписано: хеш объёма, список блоков или основание")


def test_the_memory_receipt_cannot_be_switched_off():
    # 🚩 Ревью #38: пустой список файлов выключал проверку памяти, а отчёт
    # при этом сообщал, что память актуальна.
    module = import_tables_module()
    files = BLOCKS["проверка_памяти"]["файлы"]
    assert set(files) == {"~/Work/memory/project_roundtable.md",
                          "~/Work/memory/MEMORY.md"}, f"список файлов памяти изменён: {files}"
    empty = copy.deepcopy(module.load().plan)
    empty["проверка_памяти"]["файлы"] = []
    assert module.memory_receipt(empty), "пустой список принят за пройденную проверку"


def test_the_document_header_counts_the_real_tables():
    # 🚩 Ревью #38: в шапке документа стояло «7 таблиц», в каноне их восемь.
    module = import_tables_module()
    text = (module.ROOT / "docs/roundtable.md").read_text(encoding="utf-8")
    declared = len(BLOCKS["списки"]["таблицы"])
    assert declared == len(module.TABLE_NAMES)
    assert f"**{declared} таблиц**" in text, (
        f"шапка документа называет не {declared} таблиц")


def test_the_break_list_itself_is_pinned():
    """Опыт нельзя тихо удалить из списка поломок.

    🚩 Ревью #38: список опытов правится как обычный файл — вычеркнул строку,
    и «замечено 100 %» считается по оставшимся. Список закреплён поимённо.
    """
    import importlib.util
    path = Path(__file__).with_name("test_roundtable_mutations.py")
    spec = importlib.util.spec_from_file_location("rt_mutations", path)
    mutations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutations)
    ids = [case[0] for case in mutations.CASES]
    assert len(ids) == len(set(ids)), "повторяющийся ID опыта"
    # 🚩 Ревью #40: точную ожидаемую причину можно было заменить общим словом —
    # и опыт переставал отличать настоящую поимку от случайного падения.
    # Закрепляется вся запись: опыт, назначенный сторож и текст причины.
    records = sorted([case[0], case[3], case[4]] for case in mutations.CASES)
    digest = hashlib.sha256(
        json.dumps(records, ensure_ascii=False).encode("utf-8")).hexdigest()
    assert digest == "d89bceae3dbff2b255f3defbdedff31250fb921d4317725ec68549ab20a24f6a", f"список опытов изменён: сейчас {len(ids)}"
    for case in mutations.CASES:
        assert case[4].strip(), f"{case[0]}: опыт без ожидаемой причины"


def test_a_second_copy_of_a_generated_section_is_rejected(tmp_path):
    """🚩 Ревью #38: второй такой же блок с противоположным выводом дописывался
    в документ, а генератор обновлял только первое вхождение — читатель верил
    любому из двух."""
    module = import_tables_module()
    tables = module.load()
    document = (module.ROOT / "docs/roundtable.md").read_text(encoding="utf-8")
    assert module.inject_sections(document, tables), "контроль: обычный документ проходит"
    begin = module.BEGIN.format(name="status")
    end = module.END.format(name="status")
    forged = document + f"\n{begin}\nMVP завершён, идите дальше\n{end}\n"
    with pytest.raises(module.ContractError, match="дважды"):
        module.inject_sections(forged, tables)


def test_what_the_ratchet_does_not_measure_is_named():
    """Замер защищает ИЗМЕРЯЕМЫЕ строки, а не «каждую строку правил».

    🚩 Ревью #39: критик подменил смысловой критерий годности решения на
    «годится любое», и замер всё равно отчитался о полном результате — раздел
    исключён из знаменателя. Исключения теперь названы в таблице с причиной,
    и этот сторож сверяет список с настоящими исключениями: вывести раздел
    из-под замера молча нельзя.
    """
    import importlib.util
    path = Path(__file__).with_name("mutate_roundtable_tables.py")
    spec = importlib.util.spec_from_file_location("rt_ratchet", path)
    ratchet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratchet)
    real = {f"{table}:{section}" for table, section in ratchet.NOTES}
    named = BLOCKS["порядок_критики"]["вне_замера"]
    assert set(named) == real, (
        f"список вне замера разошёлся с храповиком: "
        f"лишние {sorted(set(named) - real)}, необъявленные {sorted(real - set(named))}")
    for section, why in named.items():
        assert why.strip(), f"{section}: исключено из замера без причины"


def test_the_ratchet_refuses_an_experiment_without_a_green_control(monkeypatch, tmp_path):
    """Храповик обязан отказаться, когда сторож красный ДО мутации.

    🚩 Ревью #40: положительный контроль можно было удалить из храповика, и
    мёртвый сторож считался бы рабочим — измеритель переставал измерять, а
    отчёт оставался зелёным. Здесь подставляется заведомо красный сторож.
    """
    import importlib.util
    path = Path(__file__).with_name("test_roundtable_mutations.py")
    spec = importlib.util.spec_from_file_location("rt_mutations_meta", path)
    mutations = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutations)

    module = import_tables_module()
    scratch = tmp_path / "tables"
    scratch.mkdir()
    for name in module.TABLE_NAMES:
        source = module.TABLES_DIR / f"{name}.yaml"
        (scratch / f"{name}.yaml").write_bytes(source.read_bytes())

    case = ("МЕТА", "мутация, до которой сторож уже красный",
            lambda raw: raw["blocks"]["блоки"]["Б5"].update(состояние="сделано"),
            "test_a_deliberately_red_guard", "нарочно красный")
    monkeypatch.setenv("ROUNDTABLE_META_FAIL", "1")
    with pytest.raises(AssertionError, match="падает ДО мутации"):
        mutations.run_case(case, scratch)


def test_a_deliberately_red_guard():
    """Красный сторож по требованию — предмет метапроверки храповика выше.

    🚩 Ревью #40: положительный контроль можно было просто удалить из
    храповика, и мёртвый сторож считался бы рабочим. Без включённой
    переменной этот тест пропускается и на обычный прогон не влияет.
    """
    if os.environ.get("ROUNDTABLE_META_FAIL") != "1":
        pytest.skip("включается только метапроверкой храповика")
    assert False, "нарочно красный сторож"


def test_memory_is_not_fresh_just_because_a_hash_was_pasted_in(tmp_path, monkeypatch):
    """🚩 Ревью #40: старый текст с дописанным текущим хешем проходил как
    обновлённая память. Файл, который ведётся записями, обязан нести запись
    с датой не раньше даты канона."""
    module = import_tables_module()
    tables = module.load()
    plan = copy.deepcopy(tables.plan)
    canon = module.canon_commit(plan)
    day = module.canon_date(plan)
    assert canon and day, "git не ответил о каноне"

    home = tmp_path
    for relative in plan["проверка_памяти"]["файлы"]:
        path = home / str(relative).replace("~/", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"память\n- {day}, свежая запись\nканон {canon}\n", encoding="utf-8")
    assert module.memory_receipt(plan, home) == [], "контроль: свежая память проходит"

    kept = plan["проверка_памяти"]["ведутся_записями"]
    assert kept, "ни один файл памяти не ведётся записями — принято за обновление"
    stale = home / kept[0].replace("~/", "")
    stale.write_text(f"память\n- 2026-01-01, старая запись\nканон {canon}\n", encoding="utf-8")
    problems = module.memory_receipt(plan, home)
    assert any("не раньше" in p for p in problems), (
        f"хеш дописан в старый текст — принято за обновление: {problems}")


def test_a_block_row_with_a_broken_acceptance_list_is_refused():
    """🚩 Ревью #40: `приёмка: null` роняла загрузчик сырым TypeError.

    Повреждённая запись обязана приходить как названный отказ с путём поля,
    иначе непонятная ошибка выглядит поломкой движка, а не порчей данных.
    """
    module = import_tables_module()
    for broken in (None, [], "строка", [None], ["не запись"]):
        raw = copy.deepcopy(module.load().raw)
        raw["blocks"]["блоки"]["Б9"]["приёмка"] = broken
        with pytest.raises(module.ContractError, match="приёмка"):
            module.Tables.from_raw(raw)


def test_one_reply_cannot_back_two_permissions():
    """🚩 R39-3, частично: расширить себе объём можно было, сославшись на ту же
    реплику Антона второй раз. Основание — однократное: одна реплика, одно
    разрешение, и каждое следующее выдано позже предыдущего."""
    module = import_tables_module()
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "одна реплика, два разрешения" in source, (
        "проверка повторного использования основания выпала из authority")
    grants = BLOCKS["разрешения_исполнения"]
    keys = [g["основание"].get("native_uuid") or g["основание"].get("sha256")
            for g in grants]
    assert len(keys) == len(set(keys)), "одно основание под двумя разрешениями"
    dates = [str(g["дата"]) for g in grants]
    assert dates == sorted(dates), "разрешения записаны не по порядку выдачи"
