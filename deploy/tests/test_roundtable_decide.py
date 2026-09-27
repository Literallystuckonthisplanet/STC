"""БТ — the tables are executable, and this is what proves it.

The eight acceptance criteria live in blocks.yaml → `приёмка_БТ`; each one has
its own test here. The load-bearing ones are the last three:

* changing a temporary copy of the YAML changes what `decide` returns, with no
  Python edited — that is the whole difference between "rules in a table" and
  "rules restated in code next to a table";
* generation is idempotent, and a hand edit inside a managed block is detected;
* the mutations that a suite normally sleeps through — a deleted row, a
  duplicated key, a swapped target, a reordered verdict — are all refused.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# The same import helper the table suite uses, and deliberately the same module
# object: criterion 1 of приёмка_БТ is one loader, not one loader per file.
_SUITE_SPEC = importlib.util.spec_from_file_location(
    "roundtable_tables_suite", Path(__file__).with_name("test_roundtable_tables.py"))
_SUITE = importlib.util.module_from_spec(_SUITE_SPEC)
sys.modules[_SUITE_SPEC.name] = _SUITE
_SUITE_SPEC.loader.exec_module(_SUITE)

T = _SUITE.import_tables_module()
TABLES = T.load()


def _raises(exc, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except exc as error:
        return error
    raise AssertionError(f"expected {exc.__name__}")


def _copy(tmp_path):
    target = tmp_path / "tables"
    shutil.copytree(T.TABLES_DIR, target)
    return target


def _edit(directory, name, mutate):
    path = directory / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# --------------------------------------------------------------------------
# 1. one strict loader, used by the suite and by the engine
# --------------------------------------------------------------------------

def test_the_suite_and_the_engine_share_one_loader():
    # The prototype used to live inside test_roundtable_tables.py. If it drifts
    # back into a private copy, these are two different classes and this fails.
    assert _SUITE.StrictLoader is T.StrictLoader
    assert _SUITE._load("run") == T.load_table("run")
    assert not hasattr(_SUITE, "_StrictLoader"), "the private copy came back"


# --------------------------------------------------------------------------
# 2. duplicates, unknown sections and a foreign contract version are refused
# --------------------------------------------------------------------------

def test_a_duplicated_key_is_refused_rather_than_silently_overwritten(tmp_path):
    # yaml.safe_load keeps the last value without a word, so a table could hold
    # two answers for one rule and look perfectly healthy.
    path = tmp_path / "dup.yaml"
    path.write_text("версия_контракта: 1\nпереходы: []\nпереходы: []\n", encoding="utf-8")
    _raises(yaml.constructor.ConstructorError,
            yaml.load, path.read_text(encoding="utf-8"), Loader=T.StrictLoader)


def test_an_unregistered_top_level_section_is_refused(tmp_path):
    directory = _copy(tmp_path)
    _edit(directory, "run", lambda data: data.update({"переходи": []}))
    error = _raises(T.ContractError, T.load_table, "run", directory)
    assert "переходи" in str(error)


def test_a_foreign_contract_version_is_refused(tmp_path):
    directory = _copy(tmp_path)
    _edit(directory, "run", lambda data: data.update({"версия_контракта": 2}))
    error = _raises(T.ContractError, T.load_table, "run", directory)
    assert "contract version" in str(error)


def test_an_unknown_field_in_a_row_is_refused_at_load(tmp_path):
    directory = _copy(tmp_path)

    def add_typo(data):
        data["переходы"][0]["деиствия"] = []

    _edit(directory, "run", add_typo)
    error = _raises(T.ContractError, T.load, directory)
    assert "деиствия" in str(error)


# --------------------------------------------------------------------------
# 3. conditions, actions and refusals are closed codes
# --------------------------------------------------------------------------

def test_every_condition_action_and_refusal_is_a_declared_code():
    TABLES.check()  # raises on the first code that is not in the vocabulary
    codes = TABLES.vocabulary["коды_условий"]
    for transition in TABLES.transitions:
        for key, value in transition.conditions.items():
            assert key in codes and value in codes[key], transition


def test_decide_refuses_a_condition_code_that_was_never_declared():
    _raises(T.ContractError, TABLES.decide, "ждёт_Антона", "submit-decision",
            {"decision": "принять_риск", "погода": "ясная"})
    _raises(T.ContractError, TABLES.decide, "ждёт_Антона", "submit-decision",
            {"decision": "передумать"})
    _raises(T.ContractError, TABLES.decide, "ждёт_Антона", "выпить_чаю", {})
    _raises(T.ContractError, TABLES.decide, "летит", "submit-decision", {})


# --------------------------------------------------------------------------
# 4. exactly one outcome for every combination — the core of the block
# --------------------------------------------------------------------------

def test_every_pair_and_every_combination_yields_exactly_one_outcome():
    total = 0
    for state, event in TABLES.pairs():
        for conditions in TABLES._combinations(state, event):
            outcome = TABLES.decide(state, event, conditions)
            assert outcome.to in TABLES._states()
            total += 1
    assert total >= 78, "the combination space shrank; a condition code was lost"


def test_a_refusal_is_an_outcome_and_not_an_exception():
    # Round 8: "the operation is refused" left the run in an undefined place.
    outcome = TABLES.decide("ждёт_Антона", "submit-decision",
                            {"decision": "запросить_ещё_правку", "budget_fits_quorum": False})
    assert outcome.refusal == "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ"
    assert outcome.to == "ждёт_Антона", "a refusal does not move the run"


def test_the_second_change_of_solution_is_a_valid_command():
    outcome = TABLES.decide("ждёт_Антона", "submit-decision",
                            {"decision": "сменить_решение", "change_index": "вторая"})
    assert outcome.to == "остановлено_для_перепроектирования"
    assert outcome.refusal is None


def test_confirming_the_framing_never_kills_a_running_round():
    outcome = TABLES.decide("идёт_круг", "submit-framing-decision",
                            {"framing_decision": "подтвердить_постановку",
                             "round_running": True})
    assert outcome.to == "идёт_круг"
    assert "kill_process_group" not in outcome.actions


def test_two_matching_rows_are_an_error_and_never_a_first_match_win(tmp_path):
    directory = _copy(tmp_path)

    def duplicate_a_transition(data):
        twin = dict(data["переходы"][2])          # идёт_круг + вердикт=ОДОБРЕНО
        twin["в"] = "неполный"
        data["переходы"].append(twin)

    _edit(directory, "run", duplicate_a_transition)
    tables = T.load(directory)
    error = _raises(T.ContractError, tables.decide, "идёт_круг", "вердикт",
                    {"verdict": "ОДОБРЕНО"})
    assert "2 outcomes" in str(error)


def test_swapping_the_target_of_a_transition_does_not_survive(tmp_path):
    # The fourth mutation named in приёмка_БТ. A swapped target is still made of
    # legal states, so only a pinned expectation catches it — this is that pin,
    # and it is the same one test_roundtable_tables.py asserts on the real files.
    expected = {"ОДОБРЕНО": "завершён", "НУЖНЫ_ПРАВКИ": "ждёт_автора",
                "РЕШЕНИЕ_АНТОНА": "ждёт_Антона", "НЕПОЛНЫЙ_ПРОГОН": "неполный"}
    actual = {t.conditions["verdict"]: t.target for t in TABLES.transitions
              if t.source == "идёт_круг" and t.event == "вердикт"}
    assert actual == expected

    directory = _copy(tmp_path)

    def swap_targets(data):
        rows = [row for row in data["переходы"]
                if row["из"] == "идёт_круг" and row["событие"] == "вердикт"]
        rows[0]["в"], rows[1]["в"] = rows[1]["в"], rows[0]["в"]

    _edit(directory, "run", swap_targets)
    mutated = T.load(directory)
    assert mutated.decide("идёт_круг", "вердикт", {"verdict": "ОДОБРЕНО"}).to == "ждёт_автора"
    assert {t.conditions["verdict"]: t.target for t in mutated.transitions
            if t.source == "идёт_круг" and t.event == "вердикт"} != expected


def test_a_missing_row_is_an_error_and_never_a_silent_no_op(tmp_path):
    directory = _copy(tmp_path)
    _edit(directory, "run", lambda data: data["переходы"].pop(2))
    tables = T.load(directory)
    _raises(T.ContractError, tables.decide, "идёт_круг", "вердикт", {"verdict": "ОДОБРЕНО"})
    _raises(T.ContractError, tables.check)


# --------------------------------------------------------------------------
# 5. every working state has a way forward, not only a way out
# --------------------------------------------------------------------------

def test_every_working_state_has_a_continuation(tmp_path):
    for state in TABLES.vocabulary["состояния_прогона"]["рабочие"]:
        forward = [t for t in TABLES.transitions
                   if t.source == state
                   and t.event not in ("cancel-run", "submit-framing-decision")]
        assert forward, f"{state}: the only way out is cancellation"

    directory = _copy(tmp_path)

    def strip_resume(data):
        data["переходы"] = [row for row in data["переходы"] if row["событие"] != "resume"]

    _edit(directory, "run", strip_resume)
    error = _raises(T.ContractError, T.load(directory).check)
    assert "неполный" in str(error)


# --------------------------------------------------------------------------
# 6. editing the YAML changes behaviour with no Python edited — round 11's test
# --------------------------------------------------------------------------

def test_editing_a_temporary_copy_of_the_yaml_changes_what_decide_returns(tmp_path):
    before = TABLES.decide("идёт_круг", "вердикт", {"verdict": "НУЖНЫ_ПРАВКИ"})
    assert before.to == "ждёт_автора"

    directory = _copy(tmp_path)

    def reroute(data):
        for row in data["переходы"]:
            if row.get("условия", {}).get("verdict") == "НУЖНЫ_ПРАВКИ":
                row["в"] = "ждёт_Антона"

    _edit(directory, "run", reroute)
    after = T.load(directory).decide("идёт_круг", "вердикт", {"verdict": "НУЖНЫ_ПРАВКИ"})
    assert after.to == "ждёт_Антона", "the engine did not read the edited table"


def test_a_new_action_added_only_in_yaml_reaches_the_outcome(tmp_path):
    directory = _copy(tmp_path)

    def add_action(data):
        for row in data["переходы"]:
            if row.get("условия", {}).get("verdict") == "ОДОБРЕНО":
                row["действия"] = ["record_reason"]

    _edit(directory, "run", add_action)
    outcome = T.load(directory).decide("идёт_круг", "вердикт", {"verdict": "ОДОБРЕНО"})
    assert outcome.actions == ("record_reason",)


# --------------------------------------------------------------------------
# 7. the normative sections of the document are generated, not typed
# --------------------------------------------------------------------------

def test_generation_is_idempotent_and_the_document_is_already_current():
    assert T.render_document(T.DOCUMENT, TABLES, write=False) is False, (
        "docs/roundtable.md drifted from the tables — run `tables.py render`")


def test_a_hand_edit_inside_a_managed_block_is_detected(tmp_path):
    copy = tmp_path / "roundtable.md"
    copy.write_text(T.DOCUMENT.read_text(encoding="utf-8"), encoding="utf-8")
    text = copy.read_text(encoding="utf-8").replace("`НУЖНЫ_ПРАВКИ`", "`ОДОБРЕНО`", 1)
    copy.write_text(text, encoding="utf-8")
    assert T.render_document(copy, TABLES, write=False) is True


def test_every_generated_section_actually_appears_in_the_document():
    text = T.DOCUMENT.read_text(encoding="utf-8")
    for name in T.SECTIONS:
        assert T.BEGIN.format(name=name) in text, name
        assert T.END.format(name=name) in text, name


def test_a_missing_marker_is_an_error_not_a_silent_append():
    error = _raises(T.ContractError, T.inject_sections, "# документ без маркеров\n", TABLES)
    assert "missing" in str(error)


def test_the_generated_verdict_table_keeps_the_order_of_the_yaml():
    # Reordering the verdict table changes the verdict: it is checked top to
    # bottom, and НЕПОЛНЫЙ_ПРОГОН dominating everything is that order.
    block = T.render_section("verdict", TABLES)
    positions = [block.index(row.verdict) for row in TABLES.verdict[:1]]
    assert positions, "the verdict table rendered empty"
    lines = [line for line in block.split("\n") if line.startswith("| ")]
    numbered = [line for line in lines if line.startswith("| 1 ") or line.startswith("| 8 ")]
    assert "НЕПОЛНЫЙ_ПРОГОН" in numbered[0]
    assert "ОДОБРЕНО" in numbered[-1]


def test_swapping_two_verdict_rows_changes_the_generated_section(tmp_path):
    directory = _copy(tmp_path)

    def swap(data):
        data["вердикт"][0], data["вердикт"][1] = data["вердикт"][1], data["вердикт"][0]

    _edit(directory, "issues", swap)
    assert T.render_section("verdict", T.load(directory)) != T.render_section("verdict", TABLES)


# --------------------------------------------------------------------------
# 8. typed rows — a mistyped field fails at load, not at first use
# --------------------------------------------------------------------------

def test_rows_are_typed_objects_and_not_bare_dictionaries():
    assert isinstance(TABLES.transitions[0], T.Transition)
    assert isinstance(TABLES.issue_transitions[0], T.IssueTransition)
    assert isinstance(TABLES.verdict[0], T.VerdictRow)
    assert isinstance(TABLES.precheck_codes[0], T.PrecheckCode)
    assert isinstance(TABLES.blocks["БТ"], T.Block)
    assert TABLES.blocks["Ш1"].depends == ("Б3а",)
    assert TABLES.blocks["БТ"].acceptance, "the block plan carries its own acceptance"


def test_a_row_missing_a_mandatory_field_is_refused(tmp_path):
    directory = _copy(tmp_path)

    def drop_target(data):
        del data["переходы"][0]["в"]

    _edit(directory, "run", drop_target)
    error = _raises(T.ContractError, T.load, directory)
    assert "'в'" in str(error)


def test_the_cli_answers_check_render_and_decide(capsys=None):
    assert T.main(["check"]) == 0
    assert T.main(["render", "--check"]) == 0
    assert T.main(["decide", "--state", "ждёт_Антона", "--event", "submit-decision",
                   "--condition", "decision=принять_риск",
                   "--condition", "all_verdict_blocking_resolved=true"]) == 0
    assert T.main(["decide", "--state", "ждёт_Антона", "--event", "submit-decision"]) == 1


# ==========================================================================
# БТ2 — доисполнение таблиц: закрытые коды для issue и возражений, пятый
# вход автомата возражений, честный храповик мутаций. Каждый критерий
# БТ2-1…БТ2-9 (blocks.yaml → блоки.БТ2.приёмка) держится своим тестом ниже.
#
# DECIDED: «пять входов» (БТ2-2) — пять мест, где закрытый код человеческого
# решения входит в автоматы этого модуля и обязан развести «легитимный, но
# возможно отказанный, исход» (данные — Outcome, никогда исключение) от
# «сломанного вызова или таблицы» (T.ContractError). Ни один из пяти не
# документирован по номерам где-либо ещё, поэтому нумерация — техническое
# решение исполнителя этого блока, а не цитата из спецификации:
#   1. run-автомат, событие submit-decision (контракт E на прогоне);
#   2. run-автомат, событие submit-framing-decision (эффект возражения на прогон);
#   3. decide_issue_transition, событие anton-decision (контракт E на issue);
#   4. decide_framing_transition, событие anton-decision (решение по возражению);
#   5. decide_issue_transition, события lead-response и critic-outcome
#      (ответы ведущего и поднявшего критика).
# Вход 5 — «пятый» из R16-3/R21-5 в блоке — decide_framing_transition; здесь
# он занимает позицию 4, поскольку входы 1 и 2 существовали до БТ2 (БТ, round 8/11).
# ==========================================================================

def test_input_1_run_decide_on_issue_decisions_separates_refusal_from_breakage():
    refused = TABLES.decide("ждёт_Антона", "submit-decision",
                            {"decision": "запросить_ещё_правку", "budget_fits_quorum": False})
    assert refused.refusal == "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ", "легитимный отказ — данные, не исключение"
    assert refused.to == "ждёт_Антона"
    _raises(T.ContractError, TABLES.decide, "ждёт_Антона", "submit-decision",
            {"decision": "передумать"})


def test_input_2_run_decide_on_framing_decisions_separates_refusal_from_breakage():
    outcome = TABLES.decide("идёт_круг", "submit-framing-decision",
                            {"framing_decision": "подтвердить_постановку", "round_running": True})
    assert outcome.to == "идёт_круг" and outcome.refusal is None
    _raises(T.ContractError, TABLES.decide, "идёт_круг", "submit-framing-decision",
            {"framing_decision": "передумать"})


def test_input_3_issue_anton_decision_separates_refusal_from_breakage():
    outcome = TABLES.decide_issue_transition(
        "вынесен_Антону", "anton-decision",
        {"decision": "принять_риск", "блокер": "сменой_решения"})
    assert outcome.to == "риск_принят" and outcome.refusal is None

    # контракт E: решение вне списка допустимых для типа issue — легитимный
    # отказ пользователя (Outcome.refusal), не падение движка (БТ2-2, БТ2-3).
    refused = TABLES.decide_issue_transition(
        "вынесен_Антону", "anton-decision",
        {"decision": "изменить_цель", "блокер": "сменой_решения"})
    assert refused.refusal == "РЕШЕНИЕ_ВНЕ_ТИПА"
    assert refused.to == "вынесен_Антону", "отказ не двигает issue"

    _raises(T.ContractError, TABLES.decide_issue_transition,
            "вынесен_Антону", "anton-decision", {"decision": "передумать"})


def test_input_4_framing_anton_decision_separates_refusal_from_breakage():
    outcome = TABLES.decide_framing_transition(
        "открыто", "anton-decision", {"framing_decision": "подтвердить_постановку"})
    assert outcome.to == "подтверждено"
    _raises(T.ContractError, TABLES.decide_framing_transition,
            "открыто", "anton-decision", {"framing_decision": "передумать"})
    _raises(T.ContractError, TABLES.decide_framing_transition,
            "подтверждено", "anton-decision", {"framing_decision": "остановить"})


def test_input_5_issue_lead_and_critic_responses_separate_refusal_from_breakage():
    lead = TABLES.decide_issue_transition("открыт", "lead-response",
                                          {"ответ_ведущего": "оспорил"})
    assert lead.to == "оспорен_автором"
    _raises(T.ContractError, TABLES.decide_issue_transition, "открыт", "lead-response",
            {"ответ_ведущего": "промолчал"})

    critic = TABLES.decide_issue_transition("принят_автором", "critic-outcome",
                                            {"итог_критика": "осталось"})
    assert critic.to == "остался"
    _raises(T.ContractError, TABLES.decide_issue_transition, "принят_автором", "critic-outcome",
            {"итог_критика": "передумал"})


# --------------------------------------------------------------------------
# БТ2-1 — no free-text `условие` is consulted by anything executable
# --------------------------------------------------------------------------

def test_the_prose_condition_text_is_never_consulted_by_either_automaton(tmp_path):
    before_issue = TABLES.decide_issue_transition(
        "открыт", "escalate", {"блокер": "сменой_решения"})
    before_framing = TABLES.decide_framing_transition(
        "открыто", "anton-decision", {"framing_decision": "остановить"})

    directory = _copy(tmp_path)

    def mangle(data):
        for row in data["переходы"]:
            row["условие"] = "бессмысленная строка, не код"

    _edit(directory, "issues", mangle)
    _edit(directory, "framing", mangle)
    mutated = T.load(directory)

    after_issue = mutated.decide_issue_transition(
        "открыт", "escalate", {"блокер": "сменой_решения"})
    after_framing = mutated.decide_framing_transition(
        "открыто", "anton-decision", {"framing_decision": "остановить"})
    assert after_issue == before_issue
    assert after_framing == before_framing


# --------------------------------------------------------------------------
# БТ2-3 — a framing (objection) transition through the ISSUE decider is refused
# --------------------------------------------------------------------------

def test_a_framing_channel_code_routed_through_the_issue_decider_is_refused():
    # `framing_decision` is a closed code of a DIFFERENT automaton (framing.yaml)
    # — feeding it to decide_issue_transition must not be quietly accepted as
    # if it were an issue `decision`.
    _raises(T.ContractError, TABLES.decide_issue_transition,
            "вынесен_Антону", "anton-decision", {"framing_decision": "остановить"})
    # the framing STATUS itself is foreign to the issue automaton
    _raises(T.ContractError, TABLES.decide_issue_transition,
            "открыто", "anton-decision", {"decision": "остановить"})


# --------------------------------------------------------------------------
# БТ2-4 (closing R12-5) — load() itself refuses a typo'd condition code
# --------------------------------------------------------------------------

def test_load_refuses_a_typo_in_a_condition_code_with_no_explicit_check_call(tmp_path):
    directory = _copy(tmp_path)

    def typo(data):
        for row in data["переходы"]:
            if row.get("условия", {}).get("блокер") == "сменой_решения":
                row["условия"] = {"блокер": "сменой_решениа"}  # опечатка

    _edit(directory, "issues", typo)
    # This is `T.load`, not `T.load(...).check()` — R12-5 was exactly a typo
    # that loaded silently and only showed up if someone remembered `check()`.
    error = _raises(T.ContractError, T.load, directory)
    assert "сменой_решениа" in str(error)


# --------------------------------------------------------------------------
# БТ2-5 — strict nesting: a fabricated nested field is refused
# --------------------------------------------------------------------------

def test_a_fabricated_field_inside_an_outcome_entry_is_refused(tmp_path):
    directory = _copy(tmp_path)

    def add_ghost_field(data):
        row = next(r for r in data["переходы"] if r.get("событие") == "lead-response")
        row["исходы"][0]["призрак"] = True

    _edit(directory, "issues", add_ghost_field)
    error = _raises(T.ContractError, T.load, directory)
    assert "призрак" in str(error)


def test_a_fabricated_blocker_code_desynced_from_allowed_decisions_is_refused(tmp_path):
    directory = _copy(tmp_path)

    def add_ghost_blocker(data):
        data["коды_условий"]["блокер"] = list(data["коды_условий"]["блокер"]) + ["выдуманный"]

    _edit(directory, "issues", add_ghost_blocker)
    error = _raises(T.ContractError, T.load, directory)
    assert "расходятся" in str(error)


# --------------------------------------------------------------------------
# БТ2-6 — the ratchet mutates a TEMPORARY copy, never the canon
# --------------------------------------------------------------------------

def _load_ratchet():
    path = ROOT / "deploy" / "tests" / "mutate_roundtable_tables.py"
    spec = importlib.util.spec_from_file_location("rt_ratchet_bt2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_ratchet_loads_its_mutant_from_a_temporary_directory_not_the_canon(tmp_path):
    ratchet = _load_ratchet()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for source in ratchet.CANON.glob("*.yaml"):
        shutil.copy(source, scratch / source.name)

    victim = scratch / "framing.yaml"
    data = yaml.safe_load(victim.read_text(encoding="utf-8"))
    for row in data["переходы"]:
        if row.get("условия", {}).get("framing_decision") == "остановить":
            row["условия"]["framing_decision"] = "передумать"  # опечатка, не код
    victim.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    _raises(T.ContractError, T.load, scratch)
    T.load(ratchet.CANON)  # the canon is untouched and loads exactly as before


# --------------------------------------------------------------------------
# БТ2-7 (closing R15-8) — the ratchet runs tables, decide AND idea-stage tests
# --------------------------------------------------------------------------

def test_the_ratchet_runs_all_three_suites_not_one():
    ratchet = _load_ratchet()
    names = {path.name for path in ratchet.SUITES}
    assert names == {"test_roundtable_tables.py", "test_roundtable_decide.py",
                     "test_roundtable_context.py"}, (
        "R15-8: a row guarded only by one of the other two files must be "
        "counted — running one file alone leaves it out of the denominator")


# --------------------------------------------------------------------------
# БТ2-8 — four independent mutation classes, each its own generator
# --------------------------------------------------------------------------

def test_the_ratchet_has_four_independent_mutation_class_generators():
    ratchet = _load_ratchet()
    assert set(ratchet.CLASSES) == {
        "убрать_правило", "подменить_значение_на_допустимое",
        "подменить_текст_сохранив_ID", "подсунуть_недопустимое",
    }

    # Finding 3: every generator returns `(value, reason)` — a miss ALWAYS
    # carries a non-empty reason, never a bare `None`.
    assert ratchet.CLASSES["убрать_правило"]({"id": "X-1", "условие": "т"}) == (ratchet._Deleted, None)

    value, reason = ratchet.CLASSES["подменить_значение_на_допустимое"]({"a": True})
    assert value == {"a": False} and reason is None
    value, reason = ratchet.CLASSES["подменить_значение_на_допустимое"]({"a": "текст"})
    assert value is None and reason, (
        "a row with no boolean anywhere is not eligible for this class, and must say so")

    kept_id, reason = ratchet.CLASSES["подменить_текст_сохранив_ID"]({"id": "X-1", "условие": "т"})
    assert kept_id["id"] == "X-1" and kept_id["условие"] != "т" and reason is None
    value, reason = ratchet.CLASSES["подменить_текст_сохранив_ID"]({"a": "текст"})
    assert value is None and reason, "a row with no id is not eligible for this class, and must say so"

    value, reason = ratchet.CLASSES["подсунуть_недопустимое"]({"a": "текст"})
    assert value == {"a": "текст", ratchet.UNKNOWN_FIELD: True} and reason is None
    value, reason = ratchet.CLASSES["подсунуть_недопустимое"]("проза")
    assert value == ratchet.MUTATION_SENTINEL and reason is None
    value, reason = ratchet.CLASSES["подсунуть_недопустимое"](True)
    assert value is None and reason, (
        "every bool is a valid bool — there is no generic invalid substitute, and must say so")


# --------------------------------------------------------------------------
# БТ2-9 — an admissible value substitution changes the outcome, and only a
# behavioural pin catches it (never the loader or the full `check()`)
# --------------------------------------------------------------------------

def test_admissible_decision_code_swap_changes_the_route_and_only_a_pin_catches_it(tmp_path):
    pinned = {
        "принять_риск": "риск_принят", "остановить": "остановлено",
        "изменить_цель": "цель_изменена", "сменить_решение": "решение_изменено",
        "запросить_ещё_правку": "открыт",
    }
    actual = {o.conditions["decision"]: o.target
              for t in TABLES.issue_transitions if t.event == "anton-decision"
              for o in t.outcomes}
    assert actual == pinned, "if this line changes, the swap below stops proving anything"

    directory = _copy(tmp_path)

    def swap_two_admissible_values(data):
        row = next(r for r in data["переходы"] if r.get("событие") == "anton-decision")
        by_decision = {o["условия"]["decision"]: o for o in row["исходы"]}
        by_decision["принять_риск"]["условия"]["decision"] = "остановить"
        by_decision["остановить"]["условия"]["decision"] = "принять_риск"

    _edit(directory, "issues", swap_two_admissible_values)
    mutated = T.load(directory)
    mutated.check()  # the loader AND the full check stay silent: every code is
                     # still declared and coverage is still exhaustive — this
                     # IS "an admissible substitution", by construction

    swapped = mutated.decide_issue_transition(
        "вынесен_Антону", "anton-decision", {"decision": "принять_риск"})
    assert swapped.to == "остановлено", "the swap moved silently until this pin"

    after = {o.conditions["decision"]: o.target for t in mutated.issue_transitions
            if t.event == "anton-decision" for o in t.outcomes}
    assert after != pinned


# ==========================================================================
# БТ2 rework — a review of the ratchet found seven more ways it could report
# coverage that was not there. Findings 1-5 are about the MEASUREMENT
# (mutate_roundtable_tables.py); 6-7 are about rules nothing was watching.
# ==========================================================================

def _ratchet_module():
    path = ROOT / "deploy" / "tests" / "mutate_roundtable_tables.py"
    spec = importlib.util.spec_from_file_location("rt_ratchet_rework", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# Finding 1 — a typo in --only/--class matched nothing and reported "100 %"
# --------------------------------------------------------------------------

def test_a_typo_in_only_or_class_is_refused_not_silently_all_green():
    ratchet = _ratchet_module()
    # Before the fix this returned 0 with every class printed as
    # "мутировано: 0, замечено: 0 (100%)" — a filter matching nothing looked
    # exactly like a full, green pass.
    assert ratchet.main(only="frmaing.yaml") != 0
    assert ratchet.main(only_class="выдуманный_класс") != 0
    # the real names still work, unaffected by the new validation
    assert "framing.yaml" in {p.name for p in ratchet.CANON.glob("*.yaml")}
    assert "убрать_правило" in ratchet.CLASSES


# --------------------------------------------------------------------------
# Finding 2 — a bare scalar top-level field was invisible to `_targets`
# --------------------------------------------------------------------------

def test_targets_walk_reaches_a_bare_scalar_top_level_field():
    ratchet = _ratchet_module()
    data = {"версия_контракта": 1, "статус": "отложен", "список": [1, 2]}
    targets = ratchet._targets(data, "synthetic.yaml")
    assert ("статус",) in targets, "a scalar field must be its own target"


def test_the_shared_resolver_status_is_pinned_until_it_actually_ships():
    # Finding 2's real hole: precheck.yaml's `общий_резолвер: отложен` is a
    # PROJECT-STATE claim ("not built yet"), not descriptive prose — flipping
    # it to `готово` used to pass the whole suite silently, because no
    # top-level scalar was ever a mutation target and nothing else read this
    # one either.
    assert TABLES.raw["precheck"]["общий_резолвер"] == "отложен", (
        "flip this only alongside actually building the shared resolver "
        "(see the comment above the field in precheck.yaml)")


# --------------------------------------------------------------------------
# Finding 3 — a generator's `None` looked the same whether deliberate or buggy
# --------------------------------------------------------------------------

def test_every_mutation_generator_returns_a_reason_alongside_a_miss():
    ratchet = _ratchet_module()
    # a value the class DOES apply to: no reason required, but returning one
    # is not tested here — only that a MISS always carries a reason.
    for name, generate in ratchet.CLASSES.items():
        value, reason = generate("бесформенная строка без булевых полей и id")
        if value is None:
            assert reason and reason.strip(), (
                f"{name}: None без причины — дефект генератора")


def test_a_generator_returning_none_without_a_reason_is_a_ratchet_defect():
    # NOT `ratchet.main(...)` here: `main` shells out to a real `pytest` over
    # SUITES, which includes THIS file — calling it from inside a test that
    # lives in that same file would have the subprocess re-collect and
    # re-run this very test, recursively, with no base case. `_run_generator`
    # is the exact rule under test, split out for precisely this reason.
    ratchet = _ratchet_module()

    def broken(_value):
        return None, ""  # empty reason — exactly the bug finding 3 named

    _raises(ratchet.RatchetDefect, ratchet._run_generator, broken, "x", "synthetic label")

    # a real class, given a value it legitimately has nothing to say about,
    # must NOT raise — only an EMPTY reason is the defect.
    value, reason = ratchet._run_generator(
        ratchet.CLASSES["подменить_значение_на_допустимое"], "текст без булевых полей",
        "synthetic label")
    assert value is None and reason


# --------------------------------------------------------------------------
# Finding 4 — CLASS_EXCLUSIONS was pinned by nothing outside this file
# --------------------------------------------------------------------------

def test_the_class_exclusions_are_named_and_nothing_more():
    # Named one by one, the same shape the findings registry uses — not a
    # hash. A silently added or silently widened entry fails this by name.
    ratchet = _ratchet_module()
    expected = {
        "убрать_правило": {
            ("precheck.yaml", "почему"),
        },
        "подменить_значение_на_допустимое": {
            ("vocabulary.yaml", "коды_условий", "run_finished"),
        },
        "подсунуть_недопустимое": {
            ("framing.yaml", "хранение"),
            ("issues.yaml", "валидация"),
            ("precheck.yaml", "классы_файлов"),
            ("precheck.yaml", "фикстуры", "не_смешивать_с"),
            ("precheck.yaml", "почему"),
            ("stages.yaml", "стадии", "идея"),
            ("stages.yaml", "стадии", "план"),
            ("stages.yaml", "стадии", "ревью"),
            ("stages.yaml", "слепой_вопрос"),
            ("stages.yaml", "сигнал_нежизнеспособности"),
            ("stages.yaml", "метрика_цены_понимания"),
            ("stages.yaml", "приоритет_расхода"),
            ("blocks.yaml", "заключения_ревью", 0),
            ("blocks.yaml", "разрешения_исполнения", 0),
            ("blocks.yaml", "разрешения_исполнения", 1),
            ("blocks.yaml", "история_разрешений", 0),
            ("blocks.yaml", "история_разрешений", 1),
            ("blocks.yaml", "история_разрешений", 2),
            ("blocks.yaml", "шлюзы", "ремонт_после_ревью_12"),
            ("blocks.yaml", "шлюзы", "изоляция_подтверждена"),
            ("blocks.yaml", "исполнение", "роли"),
            ("blocks.yaml", "исполнение", "проверки"),
            ("blocks.yaml", "сверка_записи", "код_движка"),
            ("blocks.yaml", "порядок_критики", "почему"),
            ("vocabulary.yaml", "операции", 2),
            ("vocabulary.yaml", "операции", 4),
            ("vocabulary.yaml", "операции", 5),
            ("vocabulary.yaml", "операции", 6),
            ("vocabulary.yaml", "операции", 7),
            ("vocabulary.yaml", "операции", 8),
            ("vocabulary.yaml", "операции", 9),
            ("vocabulary.yaml", "операции", 10),
            ("vocabulary.yaml", "схемы_контрактов", 0),
            ("vocabulary.yaml", "схемы_контрактов", 1),
            ("vocabulary.yaml", "схемы_контрактов", 2),
            ("vocabulary.yaml", "схемы_контрактов", 3),
            ("vocabulary.yaml", "схемы_контрактов", 4),
            ("vocabulary.yaml", "схемы_контрактов", 5),
            ("vocabulary.yaml", "схемы_контрактов", 6),
            ("vocabulary.yaml", "схемы_контрактов", 7),
            ("vocabulary.yaml", "схемы_контрактов", 8),
            ("vocabulary.yaml", "попытка", "почему"),
            ("vocabulary.yaml", "повтор_невалидного_ответа", "порядок"),
            ("vocabulary.yaml", "повтор_невалидного_ответа", "оба_невалидны"),
            ("findings.yaml", "находки"),
        },
    }
    actual = {cls: set(entries) for cls, entries in ratchet.CLASS_EXCLUSIONS.items()}
    assert actual == expected
    for cls, entries in ratchet.CLASS_EXCLUSIONS.items():
        for entry, reason in entries.items():
            assert reason and reason.strip(), f"{cls}:{entry} исключён без причины"


# --------------------------------------------------------------------------
# Finding 5 — a collection error was classified by matching truncated text
# --------------------------------------------------------------------------

def test_a_collection_error_is_classified_by_loading_the_mutant_in_process(tmp_path):
    ratchet = _ratchet_module()
    directory = _copy(tmp_path)

    def typo(data):
        for row in data["переходы"]:
            if row.get("условия", {}).get("блокер") == "сменой_решения":
                row["условия"] = {"блокер": "сменой_решениа"}

    _edit(directory, "issues", typo)
    assert ratchet._is_contract_refusal(directory) is True

    # a directory holding no tables at all is a DIFFERENT failure (missing
    # files), never the contract's own refusal — classified as such too
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ratchet._is_contract_refusal(empty) is False


# --------------------------------------------------------------------------
# Finding 6 — one row's `исходы` could be reordered with nothing noticing
# --------------------------------------------------------------------------

def test_every_issue_and_framing_route_is_pinned_end_to_end():
    # Every row, every outcome, both automata — spelled out literally so that
    # swapping which condition routes to which `в` INSIDE one row (the exact
    # shape of the reordering finding 6 named) fails this assertion instead
    # of passing `check()` silently (both codes stay declared, coverage stays
    # exhaustive — `check()` was never going to see it).
    issue_pins = {
        (None, "new-finding", ()): "открыт",
        ("открыт", "lead-response", (("ответ_ведущего", "принял"),)): "принят_автором",
        ("открыт", "lead-response", (("ответ_ведущего", "оспорил"),)): "оспорен_автором",
        ("остался", "lead-response", (("ответ_ведущего", "принял"),)): "принят_автором",
        ("остался", "lead-response", (("ответ_ведущего", "оспорил"),)): "оспорен_автором",
        ("принят_автором", "critic-outcome", (("итог_критика", "исправлено"),)): "закрыт_исправлением",
        ("принят_автором", "critic-outcome", (("итог_критика", "осталось"),)): "остался",
        ("оспорен_автором", "critic-outcome", (("итог_критика", "исправлено"),)): "возражение_снято",
        ("оспорен_автором", "critic-outcome", (("итог_критика", "осталось"),)): "остался",
        ("открыт", "escalate", (("блокер", "сменой_решения"),)): "вынесен_Антону",
        ("остался", "escalate", (("блокер", "сменой_решения"),)): "вынесен_Антону",
        ("открыт", "escalate", (("блокер", "только_сменой_цели"),)): "вынесен_Антону",
        ("остался", "escalate", (("блокер", "только_сменой_цели"),)): "вынесен_Антону",
        ("открыт", "escalate", (("блокер", "неизвестное_высокой_существенности"),)): "вынесен_Антону",
        ("остался", "escalate", (("блокер", "неизвестное_высокой_существенности"),)): "вынесен_Антону",
        ("открыт", "escalate", (("блокер", "правкой_круги_исчерпаны"),)): "вынесен_Антону",
        ("остался", "escalate", (("блокер", "правкой_круги_исчерпаны"),)): "вынесен_Антону",
        ("вынесен_Антону", "anton-decision", (("decision", "принять_риск"),)): "риск_принят",
        ("вынесен_Антону", "anton-decision", (("decision", "остановить"),)): "остановлено",
        ("вынесен_Антону", "anton-decision", (("decision", "изменить_цель"),)): "цель_изменена",
        ("вынесен_Антону", "anton-decision", (("decision", "сменить_решение"),)): "решение_изменено",
        ("вынесен_Антону", "anton-decision", (("decision", "запросить_ещё_правку"),)): "открыт",
    }
    actual_issue = {
        (t.source, t.event, tuple(sorted(o.conditions.items()))): o.target
        for t in TABLES.issue_transitions for o in t.outcomes}
    assert actual_issue == issue_pins

    framing_pins = {
        (None, "new-objection", ()): "открыто",
        ("открыто", "anton-decision", (("framing_decision", "подтвердить_постановку"),)): "подтверждено",
        ("открыто", "anton-decision", (("framing_decision", "изменить_цель"),)): "принято",
        ("открыто", "anton-decision", (("framing_decision", "сменить_решение"),)): "принято",
        ("открыто", "anton-decision", (("framing_decision", "остановить"),)): "остановлено",
        ("принято", "run-spawned", ()): "породило_новый_прогон",
    }
    actual_framing = {
        (t.source, t.event, tuple(sorted(o.conditions.items()))): o.target
        for t in TABLES.framing_transitions for o in t.outcomes}
    assert actual_framing == framing_pins

    for pins, decide in ((issue_pins, TABLES.decide_issue_transition),
                        (framing_pins, TABLES.decide_framing_transition)):
        for (source, event, conditions), target in pins.items():
            assert decide(source, event, dict(conditions)).to == target


def test_swapping_two_outcomes_inside_one_critic_outcome_row_is_caught(tmp_path):
    # The coordinator's exact repro: swap which target "исправлено" and
    # "осталось" route to, inside the `оспорен_автором` row only. Both codes
    # stay declared and coverage stays exhaustive, so `check()` stays silent
    # — only the end-to-end pin above tells the two routes apart.
    directory = _copy(tmp_path)

    def swap_inside_one_row(data):
        row = next(r for r in data["переходы"]
                  if r.get("из") == "оспорен_автором" and r.get("событие") == "critic-outcome")
        by_outcome = {o["условия"]["итог_критика"]: o for o in row["исходы"]}
        by_outcome["исправлено"]["в"] = "остался"
        by_outcome["осталось"]["в"] = "возражение_снято"

    _edit(directory, "issues", swap_inside_one_row)
    mutated = T.load(directory)
    mutated.check()  # loader and full check stay silent — this is the point

    swapped = mutated.decide_issue_transition(
        "оспорен_автором", "critic-outcome", {"итог_критика": "исправлено"})
    assert swapped.to == "остался", "the swap moved silently until this pin"


def test_targets_address_an_outcome_entry_inside_исходы_on_its_own():
    ratchet = _ratchet_module()
    row = {"из": "принят_автором", "в": ["закрыт_исправлением", "остался"],
          "кто": "поднявший_критик", "условие": "т", "событие": "critic-outcome",
          "исходы": [{"условия": {"итог_критика": "исправлено"}, "в": "закрыт_исправлением"},
                     {"условия": {"итог_критика": "осталось"}, "в": "остался"}]}
    data = {"версия_контракта": 1, "переходы": [row]}
    targets = ratchet._targets(data, "synthetic.yaml")
    assert ("переходы", 0, "исходы", 0) in targets
    assert ("переходы", 0, "исходы", 1) in targets


# --------------------------------------------------------------------------
# Finding 7 — the prose `условие` and the structural route could drift apart
# --------------------------------------------------------------------------
#
# DECIDED: pin the (prose, structural route) PAIR literally in this test,
# rather than require the prose to name every structural condition code by
# word. Free Russian text matched against code identifiers is its own source
# of false confidence — a prose edit that keeps meaning but changes wording
# would either false-positive (word missing) or the check would have to be
# loose enough to miss a real drift anyway. A literal pin fails the moment
# EITHER side changes without the other, which is the actual guarantee
# БТ2-1 asks for, and needs no new matching heuristic in tables.py.

def test_the_prose_and_the_structural_route_are_pinned_as_one_pair():
    pinned_issue_prose = [
        (None, "new-finding", "принята валидная находка"),
        ("открыт", "lead-response", "контракт C"),
        ("остался", "lead-response", "контракт C"),
        ("принят_автором", "critic-outcome", "контракт D"),
        ("оспорен_автором", "critic-outcome", "контракт D"),
        ("открыт", "escalate", "блокер сменой_решения, любой круг"),
        ("остался", "escalate", "блокер сменой_решения, любой круг"),
        ("открыт", "escalate", "блокер только_сменой_цели, любой круг"),
        ("остался", "escalate", "блокер только_сменой_цели, любой круг"),
        ("открыт", "escalate", "неизвестное высокой существенности, любой круг"),
        ("остался", "escalate", "неизвестное высокой существенности, любой круг"),
        ("открыт", "escalate", "блокер правкой, круги исчерпаны"),
        ("остался", "escalate", "блокер правкой, круги исчерпаны"),
        ("вынесен_Антону", "anton-decision", "контракт E, в границах допустимых решений"),
    ]
    actual_issue = [(t.source, t.event, t.condition) for t in TABLES.issue_transitions]
    assert actual_issue == pinned_issue_prose

    pinned_framing_prose = [
        (None, "new-objection", "принята валидная находка класса возражение_к_постановке"),
        ("открыто", "anton-decision", "решение подтвердить_постановку, в любой момент"),
        ("открыто", "anton-decision", "решение изменить_цель или сменить_решение, в любой момент"),
        ("открыто", "anton-decision", "решение остановить, в любой момент"),
        ("принято", "run-spawned", "создан новый связанный прогон"),
    ]
    actual_framing = [(t.source, t.event, t.condition) for t in TABLES.framing_transitions]
    assert actual_framing == pinned_framing_prose
