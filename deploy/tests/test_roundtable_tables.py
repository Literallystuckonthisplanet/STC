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
import sys
from pathlib import Path

import yaml

TABLES = Path(__file__).resolve().parents[2] / "core" / "scripts" / "roundtable" / "tables"

# One loader for the suite and for the engine (БТ, acceptance criterion 1).
# The strict loader was prototyped here and now lives in the module: a private
# copy is exactly the "two sources" shape this design keeps failing on. The
# module is registered under a fixed name so that both roundtable test files
# get the *same* module object — two copies would defeat the point.
MODULE_NAME = "roundtable_tables"


def import_tables_module():
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    spec = importlib.util.spec_from_file_location(MODULE_NAME, TABLES.parent / "tables.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module  # dataclasses resolve annotations through it
    spec.loader.exec_module(module)
    return module


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

RUN_STATES = set(VOCAB["состояния_прогона"]["рабочие"]) | set(VOCAB["состояния_прогона"]["терминальные"])
RUN_TERMINAL = set(VOCAB["состояния_прогона"]["терминальные"])
ISSUE_STATUSES = set(itertools.chain.from_iterable(VOCAB["статусы_issue"].values()))
ISSUE_TERMINAL = set(VOCAB["статусы_issue"]["терминальные"])
FRAMING_STATUSES = set(itertools.chain.from_iterable(VOCAB["статусы_возражения"].values()))
FRAMING_TERMINAL = set(VOCAB["статусы_возражения"]["терминальные"])

# Decisions that belong to exactly one channel. The round-8 blocker was
# `подтвердить_постановку` sitting in contract E, which routes through the
# author — a framing objection must never reach the author.
FRAMING_ONLY = set(VOCAB["решения_по_возражению"]) - set(VOCAB["решения_по_issue"])
ISSUE_ONLY = set(VOCAB["решения_по_issue"]) - set(VOCAB["решения_по_возражению"])


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

def test_every_table_declares_a_contract_version():
    for name, table in ALL_TABLES.items():
        assert table.get("версия_контракта") == 1, name


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
        "таблицы": BLOCKS["списки"]["таблицы"],
        "фикстуры_репетиции": BLOCKS["списки"]["фикстуры_репетиции"],
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


def test_cleared_work_needs_no_critic_calls_and_no_unbuilt_dependency():
    cleared = BLOCKS["разрешено_начинать_сейчас"]
    assert cleared, "the plan must always name what may be picked up next"
    assert BLOCKS["вызовов_критиков_требуют"] == []
    done = {b for b, spec in BLOCKS["блоки"].items() if spec.get("состояние") == "сделано"}
    for block in cleared:
        unmet = set(BLOCKS["блоки"][block]["зависит"]) - done - set(cleared)
        assert not unmet, f"{block} still waits on {unmet}"
    assert BLOCKS["блоки"]["Ш1"]["зависит"] == ["Б3а"]


def test_an_unfinished_block_states_what_blocks_it():
    # A block that is neither done nor blocked is a block nobody is holding:
    # that is how "waiting on something" quietly becomes "forgotten".
    for name, spec in BLOCKS["блоки"].items():
        if spec.get("состояние") == "неполный":
            assert spec.get("блокер"), f"{name}: не сказано, чем заблокирован"


def test_the_command_is_frozen_only_when_the_spike_actually_passed():
    # The freeze is the promise "this exact command was measured". Writing it
    # down before Ш1 closes is precisely the unverified guarantee this design
    # has already produced three times.
    freeze = BLOCKS["заморозка_команды"]
    assert set(freeze) == {"заморожена", "почему", "отчёт"}
    spike_done = BLOCKS["блоки"]["Ш1"].get("состояние") == "сделано"
    assert freeze["заморожена"] is spike_done
    assert freeze["почему"], "a freeze state with no reason gets re-litigated"
    assert freeze["отчёт"].endswith("isolation-report.json")


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
        "РЕШЕНИЕ_ВНЕ_ТИПА", "ЕСТЬ_ЗАВИСИМЫЕ_СОБЫТИЯ",
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
    criteria = " | ".join(BLOCKS["приёмка_БТ"])
    for requirement in (
        "загрузчик", "дубликаты", "закрытые коды", "ровно один исход",
        "не только отмена", "без правки Python", "генерируются", "мутации",
    ):
        assert requirement in criteria, requirement
