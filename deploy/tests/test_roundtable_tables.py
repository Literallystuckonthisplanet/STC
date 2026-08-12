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

import itertools
from pathlib import Path

import yaml

TABLES = Path(__file__).resolve().parents[2] / "core" / "scripts" / "roundtable" / "tables"


def _load(name):
    with open(TABLES / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


VOCAB = _load("vocabulary")
RUN = _load("run")
ISSUES = _load("issues")
FRAMING = _load("framing")
PRECHECK = _load("precheck")
BLOCKS = _load("blocks")

ALL_TABLES = {
    "vocabulary": VOCAB, "run": RUN, "issues": ISSUES,
    "framing": FRAMING, "precheck": PRECHECK, "blocks": BLOCKS,
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


def test_run_event_table_matches_the_decision_vocabulary():
    assert set(RUN["события_issue"]) == set(VOCAB["решения_по_issue"])
    assert set(RUN["события_возражения"]) == set(VOCAB["решения_по_возражению"])


# --------------------------------------------------------------------------
# verdict table (rounds 6, 9)
# --------------------------------------------------------------------------

def test_verdict_table_is_total_and_ordered():
    rows = ISSUES["вердикт"]
    assert rows[0]["вердикт"] == "НЕПОЛНЫЙ_ПРОГОН", "it dominates everything"
    assert rows[-1]["условие"] == "иначе", "the table must have a default row"
    for row in rows:
        assert row["вердикт"] in VOCAB["вердикты"], row


def test_stop_is_a_decision_outcome_not_a_computed_verdict():
    # Round 6: СТОП used to be computed from the finding mix, which made the
    # decision `изменить_цель` unreachable.
    assert all(row["вердикт"] != "СТОП" for row in ISSUES["вердикт"])
    assert "СТОП" in ISSUES["вердикт_вне_таблицы"]
    assert "СТОП" in RUN["события_issue"]["остановить"]["побочное"]


def test_framing_on_the_idea_stage_appears_in_the_verdict_table():
    # Round 9: §6.12 said "never blocks" while §8.1 said it blocks on идея.
    assert FRAMING["влияние_по_стадиям"]["идея"] == "держит_стадию"
    assert any("идея" in row["условие"] for row in ISSUES["вердикт"])


# --------------------------------------------------------------------------
# run automaton (rounds 6, 8, 9)
# --------------------------------------------------------------------------

def test_run_states_come_only_from_the_vocabulary():
    for row in RUN["переходы"]:
        if row["из"] is not None:
            assert row["из"] in RUN_STATES, row
        assert row["в"] in RUN_STATES, row


def test_terminal_run_states_have_no_outgoing_transitions():
    # Round 8: `завершён` was terminal yet a late decision had to land on it.
    for row in RUN["переходы"]:
        assert row["из"] not in RUN_TERMINAL, row


def test_every_run_state_is_reachable_from_creation():
    edges = {}
    for row in RUN["переходы"]:
        edges.setdefault(row["из"], []).append(row["в"])
    assert RUN_STATES <= _reachable(edges, None)


def test_no_two_transitions_give_different_outcomes_for_the_same_situation():
    # Round 8: a second сменить_решение was a terminal state in one section and
    # a rejected operation in two others.
    seen = {}
    for row in RUN["переходы"]:
        key = (row["из"], row["событие"], row["условие"])
        assert seen.setdefault(key, row["в"]) == row["в"], key
    assert seen[("ждёт_Антона", "сменить_решение", "вторая смена за стадию")] == \
        "остановлено_для_перепроектирования"


def test_decisions_that_move_the_run_have_a_transition():
    # Round 9: `остановить` and `изменить_цель` declared an effect on the stage
    # with no transition anywhere in the automaton.
    events = {row["событие"] for row in RUN["переходы"]}
    for decision in ("запросить_ещё_правку", "сменить_решение", "остановить", "изменить_цель"):
        assert decision in events, decision
    assert "принять_риск" not in events, "it deliberately leaves the run where it is"


def test_framing_decisions_that_cancel_a_run_have_their_own_events():
    events = {row["событие"] for row in RUN["переходы"]}
    for decision in ("изменить_цель", "сменить_решение", "остановить"):
        assert f"{decision}_framing" in events, decision


# --------------------------------------------------------------------------
# mid-round policy (round 10)
# --------------------------------------------------------------------------

def test_every_framing_decision_declares_a_mid_round_policy():
    policies = set(RUN["политики_середины_круга"])
    for decision, row in RUN["события_возражения"].items():
        assert row["середина_круга"] in policies, decision


def test_confirming_the_framing_never_kills_a_running_round():
    # Round 10: the blanket "any decision kills the critics" rule meant the
    # engine killed them and then computed a verdict on a quorum that no
    # longer existed.
    assert RUN["события_возражения"]["подтвердить_постановку"]["середина_круга"] == "не_трогать"
    for decision in ("изменить_цель", "сменить_решение", "остановить"):
        assert RUN["события_возражения"][decision]["середина_круга"] == "убить_процессы"


def test_revoke_operation_targets_an_operation_and_never_rewrites_history():
    # Round 10: the operation was named without semantics.
    assert RUN["revoke_operation"]["цель"] == "operation_id"
    assert RUN["revoke_operation"]["отката_истории"] is False


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
    assert set(FRAMING["считает_движок_без_права_поднимать"]) <= solution


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

def test_precheck_codes_are_unique_and_each_has_a_fixture():
    codes = [row["код"] for row in PRECHECK["коды"]]
    assert len(codes) == len(set(codes))
    for row in PRECHECK["коды"]:
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
        "фикстуры_репетиции": BLOCKS["списки"]["фикстуры_репетиции"],
    }
    checked = 0
    for block, spec in BLOCKS["блоки"].items():
        for list_name, declared in (spec.get("объявленное_количество") or {}).items():
            assert declared == len(sources[list_name]), f"{block}: {list_name}"
            checked += 1
    assert checked >= 4, "counts stopped being cross-checked"


def test_only_isolation_work_is_cleared_to_start():
    assert BLOCKS["разрешено_начинать_сейчас"] == ["Б3а", "Ш1"]
    assert BLOCKS["блоки"]["Ш1"]["зависит"] == ["Б3а"]
