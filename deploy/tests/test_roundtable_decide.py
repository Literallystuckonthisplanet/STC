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
