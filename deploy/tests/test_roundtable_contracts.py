"""БИ, часть 1 — contracts.py: схемы, таблица истинности, исходы, бюджет повтора.

Живых вызовов моделей нет: `ask` здесь — подставная функция, а правила исходов
передаются подставной таблицей, собранной буквально по §4.5 плана (раздел
`stages.исходы_идеи` добавит часть 0).
"""

import copy
import itertools
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "core" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from roundtable import contracts as C  # noqa: E402
from roundtable import state as S  # noqa: E402
from roundtable import tables as T  # noqa: E402

REAL = T.load()
SENTINEL = REAL.vocabulary["выбор_кандидата_sentinel"]
FIXTURES = ROOT / "deploy" / "tests" / "fixtures" / "roundtable" / "idea"

RULES = {
    "строки": [
        {"проверка": "открытое_возражение", "причина": "возражение_держит_стадию", "приоритет": None},
        {"проверка": "оба_нет_проходящего", "причина": "нет_годного_варианта", "приоритет": 1},
        {"проверка": "один_нет_проходящего", "причина": "частичная_негодность", "приоритет": 2},
        {"проверка": "усиленный_случай",
         "причина": "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной", "приоритет": 1},
        {"проверка": "нет_совокупно_годного", "причина": "нет_консенсусно_годного", "приоритет": 1},
        {"проверка": "рисунок_выбора", "причина": "рисунок", "приоритет": None},
    ],
    "рисунки": [
        {"рисунок": "обе_одну_авторскую", "причина": "подтверждён", "приоритет": 4},
        {"рисунок": "обе_одну_неавторскую", "причина": "оба_предпочли_неавторскую", "приоритет": 2},
        {"рисунок": "авторская_и_неавторская", "причина": "расхождение", "приоритет": 3},
        {"рисунок": "разные_неавторские", "причина": "три_подхода_на_столе", "приоритет": 3},
    ],
}


def tables_with(rules=RULES, **vocabulary_patch):
    raw = copy.deepcopy(REAL.raw)
    raw["stages"]["исходы_идеи"] = copy.deepcopy(rules)
    raw["vocabulary"].update(copy.deepcopy(vocabulary_patch))
    return T.Tables.from_raw(raw)


# Настоящая таблица: правила исходов читаются из stages.исходы_идеи. Подставная
# `tables_with(...)` нужна только для опытов «переставили строки → другой исход».
TABLES = REAL

CRITERIA = [
    {"id": "К1", "текст": "работает", "обязательный": True},
    {"id": "К2", "текст": "дёшево", "обязательный": True},
    {"id": "К3", "текст": "красиво", "обязательный": False},
]
ONE = [{"id": "К1", "текст": "работает", "обязательный": True}]
PARSED = C.validate_criteria(CRITERIA)
PARSED_ONE = C.validate_criteria(ONE)


# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------

def proposal(criteria=CRITERIA, tag="x"):
    return {
        "variant": f"вариант {tag}", "premises": ["предпосылка"], "mechanism": f"механизм {tag}",
        "criteria_fit": [{"criterion_id": c["id"], "fit": "подходит"} for c in criteria],
        "cost": "дёшево", "reversibility": "обратимо", "risks": ["риск"],
    }


def comparison(ids, grades, selected, relations=None, criteria=ONE):
    """grades: id -> grade (single criterion К1) or id -> {criterion: grade}."""
    mandatory = [c["id"] for c in criteria if c["обязательный"]]
    rows = []
    for cid in ids:
        g = grades[cid]
        g = g if isinstance(g, dict) else {mandatory[0]: g}
        rows.append({"candidate_id": cid, "criteria": [
            {"criterion_id": k, "grade": v, "reason": "почему"} for k, v in g.items()]})
    rel = relations or {}
    pairs = [{"pair": list(p), "relation": rel.get(frozenset(p), "unknown")}
             for p in itertools.combinations(ids, 2)]
    return {"assessments": rows, "selected_candidate_id": selected, "mechanism_relations": pairs,
            "reasons": ["так"], "unknowns": [], "blockers": []}


def vc(ids, grades, selected, relations=None, critic="c", criteria=ONE):
    return C.validate_comparison(
        comparison(ids, grades, selected, relations, criteria),
        candidate_ids=ids, criteria=C.validate_criteria(criteria), critic=critic, tables=TABLES)


@contextmanager
def locked(directory, tables=TABLES):
    with S.RunLock(directory) as lock:
        yield S.RunStore(directory, tables, _lock=lock)


@pytest.fixture
def directory(tmp_path):
    return started(tmp_path / "run", "run-1")


def started(path, run_id):
    S.RunStore(path, TABLES).create(run_id, "идея")
    with locked(path) as store:
        store.submit("start")
    return path


IDS = ["cand_a", "cand_b", "cand_c"]            # a = автор, b = claude, c = codex


def fixed_ids():
    return iter(IDS).__next__


class Asker:
    """Подставной `ask`: сценарий по критику; считает вызовы."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []

    def __call__(self, critic, request):
        self.calls.append((critic, request["phase"], request["attempt"]))
        steps = self.script[(critic, request["phase"])]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        return step(request) if callable(step) else step

    def count(self, phase=None):
        return len([c for c in self.calls if phase in (None, c[1])])


SECTIONS = {"задача": "перевезти поток заказов", "ограничения": "бюджет ограничен",
            "критерий_успеха": "работает при пике", "уже_закрытые_решения": "язык не меняем"}
WITHHELD = {"автор": "Лунтик", "второй_критик": "Бибигон"}


def stage(directory, ask, **kw):
    kw.setdefault("sections", SECTIONS)
    kw.setdefault("withheld", WITHHELD)
    kw.setdefault("criteria", ONE)
    kw.setdefault("author_card", proposal(ONE, "автор"))
    kw.setdefault("new_id", fixed_ids())
    kw.setdefault("shuffle", lambda order: None)
    kw.setdefault("tables", TABLES)
    with locked(directory) as store:
        return C.run_idea_stage(store, ask=ask, **kw)


def good_blind(tag):
    return json.dumps(proposal(ONE, tag), ensure_ascii=False)


def cmp_answer(grades_by_id, selected, relations=None):
    return lambda request: json.dumps(comparison(
        [c["candidate_id"] for c in request["candidates"]], grades_by_id, selected, relations))


ALL_PASS = {"cand_a": "pass", "cand_b": "pass", "cand_c": "pass"}


# --------------------------------------------------------------------------
# БИ-1 — одна схема-проверка на две схемы
# --------------------------------------------------------------------------

def test_schema_names_come_from_vocabulary():
    names = REAL.vocabulary["схемы_контрактов"]
    for name in ("idea_proposal", "idea_comparison"):
        assert name in names
        assert (C.SCHEMAS_DIR / f"{name}.json").is_file()


def test_schema_enums_equal_vocabulary():
    schema = C.load_schema("idea_comparison")
    grade = schema["properties"]["assessments"]["items"]["properties"]["criteria"]["items"]["properties"]["grade"]
    relation = schema["properties"]["mechanism_relations"]["items"]["properties"]["relation"]
    assert grade["enum"] == REAL.vocabulary["оценка_критерия"]
    assert relation["enum"] == REAL.vocabulary["отношение_механизмов"]


@pytest.mark.parametrize("name", ["idea_proposal", "idea_comparison"])
def test_every_object_in_schema_is_closed(name):
    def walk(node):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        for sub in node.get("properties", {}).values():
            walk(sub)
        if "items" in node:
            walk(node["items"])
    walk(C.load_schema(name))


@pytest.mark.parametrize("schema", [
    {"type": "object", "pattern": "x"},
    {"type": "object", "properties": {"a": {"type": "string", "format": "email"}}},
    {"type": "array", "items": {"$ref": "#/x"}},
    {"type": "number"},
    {"type": "object", "additionalProperties": "no"},
])
def test_unknown_schema_keyword_is_contract_error(schema):
    with pytest.raises(C.ContractError):
        C.validate(schema, {})


def test_validate_does_not_blame_answer_for_our_schema():
    with pytest.raises(C.ContractError):
        C.validate({"type": "object", "oneOf": []}, "not an object")


def _corruptions():
    base = proposal()
    cases = {}
    for key in base:
        broken = copy.deepcopy(base)
        del broken[key]
        cases[f"без {key}"] = broken
    extra = copy.deepcopy(base)
    extra["лишнее"] = 1
    cases["лишнее поле"] = extra
    wrong = copy.deepcopy(base)
    wrong["risks"] = "не список"
    cases["risks не список"] = wrong
    empty = copy.deepcopy(base)
    empty["variant"] = "   "
    cases["пустой variant"] = empty
    nested = copy.deepcopy(base)
    nested["criteria_fit"][0]["лишнее"] = 1
    cases["лишнее вложенное"] = nested
    cases["не объект"] = ["x"]
    return cases


@pytest.mark.parametrize("name", list(_corruptions()))
def test_proposal_corruptions_rejected(name):
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(_corruptions()[name], PARSED, TABLES)


@pytest.mark.parametrize("raw", ["", "не json", '{"a": 1, "a": 2}', "NaN", "[1,", b"\xff\xfe"])
def test_unparseable_answer_rejected(raw):
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(raw, PARSED, TABLES)


def test_proposal_must_cover_every_criterion_exactly():
    short = proposal(CRITERIA[:1])
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(short, PARSED, TABLES)
    doubled = proposal()
    doubled["criteria_fit"].append(doubled["criteria_fit"][0])
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(doubled, PARSED, TABLES)
    foreign = proposal()
    foreign["criteria_fit"][0]["criterion_id"] = "К9"
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(foreign, PARSED, TABLES)
    assert C.validate_proposal(proposal(), PARSED, TABLES)


def test_card_limit_is_package_file_limit():
    big = proposal()
    big["variant"] = "я" * 300000
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(big, PARSED, TABLES)
    small = tables_with(пакет={**REAL.vocabulary["пакет"], "предел_файла_байт": 50})
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(proposal(), PARSED, small)


def test_both_schemas_go_through_the_one_validate(monkeypatch):
    seen = []
    original = C.validate
    monkeypatch.setattr(C, "validate", lambda schema, value, where="$": (
        seen.append(schema["title"]), original(schema, value, where))[1])
    C.validate_proposal(proposal(), PARSED, TABLES)
    vc(IDS, ALL_PASS, "cand_a")
    assert seen == ["idea_proposal", "idea_comparison"]


# --------------------------------------------------------------------------
# БИ-2 — попарная матрица
# --------------------------------------------------------------------------

def _with_pairs(pairs):
    base = comparison(IDS, ALL_PASS, "cand_a")
    base["mechanism_relations"] = pairs
    return base


def _check_pairs(pairs):
    return C.validate_comparison(_with_pairs(pairs), candidate_ids=IDS, criteria=PARSED_ONE, tables=TABLES)


def _pair(a, b, relation="same"):
    return {"pair": [a, b], "relation": relation}


GOOD_PAIRS = [_pair("cand_a", "cand_b"), _pair("cand_a", "cand_c"), _pair("cand_b", "cand_c")]


def test_three_unordered_pairs_accepted_in_any_orientation():
    assert _check_pairs(GOOD_PAIRS)
    assert _check_pairs([_pair("cand_b", "cand_a"), _pair("cand_c", "cand_a"), _pair("cand_c", "cand_b")])


@pytest.mark.parametrize("pairs", [
    GOOD_PAIRS[:2],                                                       # недостающая
    GOOD_PAIRS[:1],
    [],
    GOOD_PAIRS + [_pair("cand_a", "cand_b")],                             # лишняя
    [GOOD_PAIRS[0], _pair("cand_b", "cand_a"), GOOD_PAIRS[2]],            # [a,b]+[b,a]
    [GOOD_PAIRS[0], GOOD_PAIRS[0], GOOD_PAIRS[2]],                        # повтор
    [_pair("cand_a", "cand_a"), GOOD_PAIRS[1], GOOD_PAIRS[2]],            # [a,a]
    [GOOD_PAIRS[0], GOOD_PAIRS[1], _pair("cand_b", "cand_zzz")],          # чужой ID
    [GOOD_PAIRS[0], GOOD_PAIRS[1], _pair("cand_b", "cand_c", "similar")], # отношение вне словаря
    [GOOD_PAIRS[0], GOOD_PAIRS[1], {"pair": ["cand_b"], "relation": "same"}],
    [GOOD_PAIRS[0], GOOD_PAIRS[1], {"pair": ["cand_b", "cand_c", "cand_a"], "relation": "same"}],
])
def test_bad_pair_matrices_rejected(pairs):
    with pytest.raises(C.AnswerRejected):
        _check_pairs(pairs)


@pytest.mark.parametrize("relation", ["same", "different", "unknown"])
def test_relations_from_vocabulary_accepted(relation):
    assert _check_pairs([_pair("cand_a", "cand_b", relation), GOOD_PAIRS[1], GOOD_PAIRS[2]])


# --------------------------------------------------------------------------
# БИ-3 — источник не передаётся, пару достаёт движок
# --------------------------------------------------------------------------

def test_engine_finds_author_pair_itself_and_never_sends_source(directory):
    seen_requests = []

    def record(answer):
        def inner(request):
            seen_requests.append(request)
            return answer(request)
        return inner

    both = record(cmp_answer(ALL_PASS, "cand_b", {frozenset(("cand_a", "cand_b")): "different"}))
    # автор — cand_a; оба выбрали cand_b, автор fail по К1 нельзя (все pass), поэтому усиленного нет
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [both], ("codex", "compare"): [both]})
    result = stage(directory, ask)
    assert result.outcome.reason == "оба_предпочли_неавторскую"
    for request in seen_requests:
        text = json.dumps(request, ensure_ascii=False)
        assert "source" not in text and "источник" not in text
        assert set(request["candidates"][0]) == {"candidate_id", "text"}
    state = S.RunStore(directory, TABLES).load()
    assert {c.source for c in state.idea_candidates} == {C.AUTHOR_SOURCE, "claude", "codex"}


def test_enhanced_case_uses_author_pair_from_run_state(directory):
    grades = {"cand_a": "fail", "cand_b": "pass", "cand_c": "pass"}
    rel = {frozenset(("cand_a", "cand_b")): "different"}
    answer = cmp_answer(grades, "cand_b", rel)
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask)
    assert result.outcome.reason == "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной"


# --------------------------------------------------------------------------
# БИ-4 — таблица истинности
# --------------------------------------------------------------------------

@pytest.mark.parametrize("first,second", list(itertools.product(["pass", "fail", "unknown"], repeat=2)))
def test_truth_table_3x3(first, second):
    expected = first if first == second and first in ("pass", "fail") else "unknown"
    assert C.criterion_verdict(first, second) == expected
    assert C.criterion_verdict(second, first) == expected


def test_candidate_state_first_match_and_all_states_reachable():
    seen = set()
    for combo in itertools.product(["pass", "fail", "unknown"], repeat=3):
        state = C.candidate_state(combo)
        expected = ("непроходной" if "fail" in combo else
                    "годен" if set(combo) == {"pass"} else "неясен")
        assert state == expected
        seen.add(state)
    assert seen == set(REAL.vocabulary["состояния_кандидата"])
    assert C.candidate_state(["pass", "fail"]) == "непроходной"      # fail бьёт unknown и pass
    assert C.candidate_state(["pass", "unknown"]) == "неясен"


# --------------------------------------------------------------------------
# БИ-5 — двусторонний инвариант выбора
# --------------------------------------------------------------------------

@pytest.mark.parametrize("grades", list(itertools.product(["pass", "fail", "unknown"], repeat=3)))
def test_selection_invariant_full_enumeration(grades):
    graded = dict(zip(IDS, grades))
    passing = [c for c, g in graded.items() if g == "pass"]
    for selected in IDS + [SENTINEL, "cand_чужой"]:
        legal = (selected in passing) if passing and selected != SENTINEL else (
            selected == SENTINEL and not passing)
        if legal:
            assert vc(IDS, graded, selected).selected == selected
        else:
            with pytest.raises(C.AnswerRejected):
                vc(IDS, graded, selected)


def test_invariant_uses_this_critics_own_grades():
    # критик, поставивший fail, не может выбрать «этого» кандидата, даже если другой критик его признал
    with pytest.raises(C.AnswerRejected):
        vc(IDS, {"cand_a": "fail", "cand_b": "pass", "cand_c": "pass"}, "cand_a")


def test_invariant_with_two_mandatory_criteria_needs_all_pass():
    both = {"cand_a": {"К1": "pass", "К2": "fail"}, "cand_b": {"К1": "pass", "К2": "pass"},
            "cand_c": {"К1": "unknown", "К2": "pass"}}
    assert vc(IDS, both, "cand_b", criteria=CRITERIA).selected == "cand_b"
    for bad in ("cand_a", "cand_c", SENTINEL):
        with pytest.raises(C.AnswerRejected):
            vc(IDS, both, bad, criteria=CRITERIA)


def test_assessment_coverage_rejected_when_incomplete():
    base = comparison(IDS, ALL_PASS, "cand_a")
    for mutate in (
        lambda d: d["assessments"].pop(),
        lambda d: d["assessments"].append(copy.deepcopy(d["assessments"][0])),
        lambda d: d["assessments"][0]["criteria"].clear(),
        lambda d: d["assessments"][0].__setitem__("candidate_id", "cand_чужой"),
        lambda d: d["assessments"][0]["criteria"][0].__setitem__("criterion_id", "К9"),
    ):
        broken = copy.deepcopy(base)
        mutate(broken)
        with pytest.raises(C.AnswerRejected):
            C.validate_comparison(broken, candidate_ids=IDS, criteria=PARSED_ONE, tables=TABLES)


# --------------------------------------------------------------------------
# БИ-6 — фаза 0 до платного вызова
# --------------------------------------------------------------------------

def _bad_cards():
    broken = proposal(ONE)
    del broken["mechanism"]
    return {"нет поля": broken, "не JSON": "{", "не тот критерий": proposal([{"id": "К9"}]),
            "лишнее": {**proposal(ONE), "x": 1}}


@pytest.mark.parametrize("name", list(_bad_cards()))
def test_phase_zero_refuses_before_any_paid_call(directory, name):
    ask = Asker({})
    with pytest.raises(C.AuthorCardRefused):
        stage(directory, ask, author_card=_bad_cards()[name])
    assert ask.count() == 0
    state = S.RunStore(directory, TABLES).load()
    assert not state.attempts and state.state == "создан" and not state.idea_candidates


@pytest.mark.parametrize("criteria", [
    [], [{"id": "К1", "текст": "x", "обязательный": False}],
    [{"id": "К1", "текст": "x", "обязательный": True}, {"id": "К1", "текст": "y", "обязательный": True}],
    [{"id": "К1", "текст": "", "обязательный": True}],
    [{"id": "К1", "текст": "x"}], "не список",
])
def test_phase_zero_refuses_bad_criteria(directory, criteria):
    ask = Asker({})
    with pytest.raises(C.AuthorCardRefused):
        stage(directory, ask, criteria=criteria)
    assert ask.count() == 0 and not S.RunStore(directory, TABLES).load().attempts


# --------------------------------------------------------------------------
# БИ-7 — меньше двух валидных предложений
# --------------------------------------------------------------------------

def test_one_invalid_proposal_gets_one_retry_then_incomplete(directory):
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): ["мусор"]})
    result = stage(directory, ask)
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and result.run_state == "неполный"
    assert ask.count("blind") == 3 and ask.count("compare") == 0
    assert [c for c in ask.calls if c[0] == "codex"] == [("codex", "blind", 1), ("codex", "blind", 2)]
    state = S.RunStore(directory, TABLES).load()
    assert not state.idea_candidates and not state.idea_candidates_permutation


def test_both_proposals_invalid_each_gets_own_retry(directory):
    ask = Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]})
    result = stage(directory, ask)
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and ask.count("blind") == 4 and ask.count("compare") == 0


def test_retry_rescues_proposal_and_stage_continues(directory):
    answer = cmp_answer(ALL_PASS, "cand_a")
    ask = Asker({("claude", "blind"): ["мусор", good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask)
    assert result.outcome.reason == "подтверждён"


# --------------------------------------------------------------------------
# БИ-8 — повтор ID внутри набора — поломка движка
# --------------------------------------------------------------------------

def test_duplicate_engine_ids_are_contract_error_not_participant_fault(directory):
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")]})
    with pytest.raises(C.ContractError):
        stage(directory, ask, new_id=lambda: "cand_same")
    assert ask.count("compare") == 0
    assert not S.RunStore(directory, TABLES).load().idea_candidates


def test_default_ids_are_distinct_and_permutation_recorded(directory):
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): ["не json"], ("codex", "compare"): ["не json"]})
    stage(directory, ask, new_id=None, shuffle=None)
    state = S.RunStore(directory, TABLES).load()
    ids = [c.candidate_id for c in state.idea_candidates]
    assert len(set(ids)) == 3 and sorted(state.idea_candidates_permutation) == [0, 1, 2]


# --------------------------------------------------------------------------
# БИ-9 — девять исходов: взаимоисключающи и полны
# --------------------------------------------------------------------------

def _spec(first, second, author, framing):
    """Независимое описание: каждый исход — конъюнкция своих условий и отрицаний ранних."""
    sentinel = SENTINEL
    grades_of = lambda cand: [(a, b) for a, b in zip(first.grades[cand].values(), second.grades[cand].values())]
    agreed_fail = lambda cand: any(a == b == "fail" for a, b in grades_of(cand))
    fit = lambda cand: all(a == b == "pass" for a, b in grades_of(cand))
    a, b = first.selected, second.selected
    pair = frozenset((author, a))
    row2 = a == sentinel and b == sentinel
    row3 = (a == sentinel) != (b == sentinel)
    row4 = (a == b and a not in (sentinel, author) and agreed_fail(author)
            and first.relations[pair] == "different" and second.relations[pair] == "different")
    row5 = not any(fit(c) for c in first.grades)
    early = [framing, row2, row3, row4, row5]
    late = not any(early)
    return {
        "возражение_держит_стадию": framing,
        "нет_годного_варианта": not framing and row2,
        "частичная_негодность": not framing and not row2 and row3,
        "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной":
            not framing and not row2 and not row3 and row4,
        "нет_консенсусно_годного": not framing and not row2 and not row3 and not row4 and row5,
        "подтверждён": late and a == b == author,
        "оба_предпочли_неавторскую": late and a == b and a != author,
        "расхождение": late and a != b and author in (a, b),
        "три_подхода_на_столе": late and a != b and author not in (a, b),
    }


def _critic_configs():
    for grades in itertools.product(["pass", "fail", "unknown"], repeat=3):
        graded = dict(zip(IDS, grades))
        passing = [c for c, g in graded.items() if g == "pass"]
        for selected in (passing or [SENTINEL]):
            yield graded, selected


def test_nine_outcomes_exclusive_and_complete_by_enumeration():
    configs = list(_critic_configs())
    assert len(configs) == 35
    reasons = set()
    for relation_a, relation_b in itertools.product(["same", "different", "unknown"], repeat=2):
        rel = lambda r: {frozenset(p): r for p in itertools.combinations(IDS, 2)}
        views = [(vc(IDS, g, s, rel(relation_a)), vc(IDS, g, s, rel(relation_b))) for g, s in configs]
        firsts = [(v[0], g, s) for v, (g, s) in zip(views, configs)]
        seconds = [(vc(IDS, g, s, rel(relation_b)), g, s) for g, s in configs]
        for (first, _, _), framing in itertools.product(firsts, [False, True]):
            for second, _, _ in seconds:
                outcome = C.decide_outcome(first, second, author_id="cand_a", framing_open=framing, tables=TABLES)
                spec = _spec(first, second, "cand_a", framing)
                assert sum(spec.values()) == 1, spec
                assert spec[outcome.reason], (outcome.reason, spec)
                assert outcome.verdict == "РЕШЕНИЕ_АНТОНА" and outcome.run_state == "ждёт_Антона"
                reasons.add(outcome.reason)
    assert reasons == set(REAL.raw["blocks"]["списки"]["исходы_идеи"])


def test_enhanced_requires_agreed_fail_on_a_criterion_not_two_different_ones():
    def grades(a_k1, a_k2):
        return {"cand_a": {"К1": a_k1, "К2": a_k2}, "cand_b": {"К1": "pass", "К2": "pass"},
                "cand_c": {"К1": "pass", "К2": "pass"}}
    rel = {frozenset(("cand_a", "cand_b")): "different"}

    def reason(first_grades, second_grades):
        first = vc(IDS, first_grades, "cand_b", rel, criteria=CRITERIA)
        second = vc(IDS, second_grades, "cand_b", rel, criteria=CRITERIA)
        return C.decide_outcome(first, second, author_id="cand_a", framing_open=False, tables=TABLES).reason

    enhanced = "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной"
    assert reason(grades("fail", "pass"), grades("fail", "pass")) == enhanced
    assert reason(grades("fail", "pass"), grades("pass", "fail")) == "оба_предпочли_неавторскую"
    assert reason(grades("fail", "fail"), grades("unknown", "fail")) == enhanced
    assert reason(grades("pass", "pass"), grades("pass", "pass")) == "оба_предпочли_неавторскую"


def test_enhanced_needs_both_critics_to_call_mechanisms_different():
    grades = {"cand_a": "fail", "cand_b": "pass", "cand_c": "pass"}
    for other in ("same", "unknown"):
        first = vc(IDS, grades, "cand_b", {frozenset(("cand_a", "cand_b")): "different"})
        second = vc(IDS, grades, "cand_b", {frozenset(("cand_a", "cand_b")): other})
        assert C.decide_outcome(first, second, author_id="cand_a", framing_open=False,
                                tables=TABLES).reason == "оба_предпочли_неавторскую"


def test_objection_row_wins_over_everything_and_never_approves(directory):
    sentinel_all = {"cand_a": "fail", "cand_b": "fail", "cand_c": "fail"}
    answer = cmp_answer(sentinel_all, SENTINEL)
    with locked(directory) as store:
        store.set_flag(C.OBJECTION_FLAG)
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask)
    assert result.outcome.reason == "возражение_держит_стадию" and result.outcome.priority is None
    assert result.verdict == "РЕШЕНИЕ_АНТОНА" and result.run_state == "ждёт_Антона"


def test_approved_verdict_is_impossible_on_idea_stage(monkeypatch):
    monkeypatch.setattr(C, "IDEA_VERDICT", "ОДОБРЕНО")
    first = vc(IDS, ALL_PASS, "cand_a")
    with pytest.raises(C.ContractError):
        C.decide_outcome(first, first, author_id="cand_a", framing_open=False, tables=TABLES)


def test_rules_come_only_through_outcome_rules():
    changed = copy.deepcopy(RULES)
    changed["рисунки"][0]["причина"] = "другая_причина"
    changed["рисунки"][0]["приоритет"] = 7
    first = vc(IDS, ALL_PASS, "cand_a")
    outcome = C.decide_outcome(first, first, author_id="cand_a", framing_open=False, tables=tables_with(changed))
    assert (outcome.reason, outcome.priority) == ("другая_причина", 7)


def test_real_rules_section_exists_and_matches_the_plan():
    section = C.outcome_rules(REAL)
    assert section == RULES                        # буквально §4.5 плана
    assert section == REAL.raw["stages"]["исходы_идеи"]
    reasons = [r["причина"] for r in section["строки"][:-1]] + [r["причина"] for r in section["рисунки"]]
    assert sorted(reasons) == sorted(REAL.raw["blocks"]["списки"]["исходы_идеи"])
    assert C._CHECKS == T.OUTCOME_CHECKS and C._PATTERNS == T.OUTCOME_PATTERNS


def test_missing_or_malformed_rules_section_is_contract_error():
    raw = copy.deepcopy(REAL.raw)
    del raw["stages"]["исходы_идеи"]
    with pytest.raises(C.ContractError):
        C.outcome_rules(T.Tables.from_raw(raw))
    bad = copy.deepcopy(RULES)
    bad["строки"].reverse()
    with pytest.raises(C.ContractError):
        C.outcome_rules(tables_with(bad))
    bad = copy.deepcopy(RULES)
    del bad["рисунки"][0]["приоритет"]
    with pytest.raises(C.ContractError):
        C.outcome_rules(tables_with(bad))


# --------------------------------------------------------------------------
# БИ-10 — бюджет повтора
# --------------------------------------------------------------------------

def _compare_ready(directory, claude_compare, codex_compare, tables=TABLES):
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): claude_compare, ("codex", "compare"): codex_compare})
    return ask, stage(directory, ask, tables=tables)


def test_both_comparisons_invalid_each_gets_one_retry_then_incomplete(directory):
    ask, result = _compare_ready(directory, ["мусор"], ["мусор"])
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and result.run_state == "неполный"
    assert ask.count("compare") == 4 and ask.count("blind") == 2
    assert sorted(c for c in ask.calls if c[1] == "compare") == [
        ("claude", "compare", 1), ("claude", "compare", 2), ("codex", "compare", 1), ("codex", "compare", 2)]
    # порядок повторов — по sha256(run_id) % 2
    retries = [c[0] for c in ask.calls if c[1] == "compare" and c[2] == 2]
    assert retries == C.retry_order("run-1", ["claude", "codex"])


def test_retry_order_alternates_by_run_id_parity():
    seen = {tuple(C.retry_order(f"run-{i}", ["a", "b"])) for i in range(20)}
    assert seen == {("a", "b"), ("b", "a")}
    assert C.retry_order("run-1", ["a", "b"]) == C.retry_order("run-1", ["a", "b"])


def test_valid_answer_is_never_asked_again(directory):
    answer = cmp_answer(ALL_PASS, "cand_a")
    ask, result = _compare_ready(directory, [answer], ["мусор", answer])
    assert result.outcome.reason == "подтверждён"
    assert [c for c in ask.calls if c[0] == "claude" and c[1] == "compare"] == [("claude", "compare", 1)]
    assert [c for c in ask.calls if c[0] == "codex" and c[1] == "compare"] == [
        ("codex", "compare", 1), ("codex", "compare", 2)]


def test_one_comparison_invalid_after_retry_is_incomplete(directory):
    answer = cmp_answer(ALL_PASS, "cand_a")
    ask, result = _compare_ready(directory, [answer], ["мусор"])
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and ask.count("compare") == 3


def test_retry_counter_survives_cold_load(directory):
    # первый вызов codex невалиден и записан; процесс «падает»; новый запуск находит счётчик в журнале
    answer = cmp_answer(ALL_PASS, "cand_a")

    class Crash(Exception):
        pass

    first = {"n": 0}

    def crashing(request):
        first["n"] += 1
        raise Crash

    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [crashing]})
    with pytest.raises(Crash):
        stage(directory, ask)
    cold = S.RunStore(directory, TABLES).load()
    assert C.calls_made(cold, C.COMPARE_STAGE, 1, "codex") == 1
    assert C.calls_made(cold, C.COMPARE_STAGE, 1, "claude") == 1

    again = Asker({("codex", "compare"): ["мусор"], ("claude", "compare"): [answer],
                   ("claude", "blind"): [], ("codex", "blind"): []})
    result = stage(directory, again, saved_comparisons={"claude": json.dumps(comparison(
        IDS, ALL_PASS, "cand_a"))}, new_id=None)
    # claude не переспрашивается. Вызов 1 codex оборван до ответа: в бюджет повтора он не идёт
    # (ответа не было), поэтому codex получает ответ (2) и свой ровно один повтор (3)
    assert [c for c in again.calls if c[0] == "claude"] == []
    assert [c for c in again.calls if c[0] == "codex"] == [("codex", "compare", 2), ("codex", "compare", 3)]
    assert S.RunStore(directory, TABLES).load().attempts[
        (cold.run_id, C.COMPARE_STAGE, 1, "codex", 1)].possible_duplicate
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН"


def test_budget_is_read_from_the_table(directory, tmp_path):
    zero = tables_with(повтор_невалидного_ответа={**REAL.vocabulary["повтор_невалидного_ответа"],
                                                  "максимум_на_ответ": 0})
    ask, result = _compare_ready(directory, ["мусор"], ["мусор"], tables=zero)
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and ask.count() == 4         # по одному вызову на фазу, без повторов
    other = started(tmp_path / "run2", "run-2")
    two = tables_with(повтор_невалидного_ответа={**REAL.vocabulary["повтор_невалидного_ответа"],
                                                 "максимум_на_ответ": 2})
    ask2 = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                  ("claude", "compare"): ["мусор"], ("codex", "compare"): ["мусор"]})
    result2 = stage(other, ask2, tables=two)
    assert result2.verdict == "НЕПОЛНЫЙ_ПРОГОН" and ask2.count("compare") == 6


def test_malformed_budget_is_contract_error():
    for patch in ({"максимум_на_ответ": -1}, {"максимум_на_ответ": "один"}, {"область": "на_ответ"}):
        bad = tables_with(повтор_невалидного_ответа={**REAL.vocabulary["повтор_невалидного_ответа"], **patch})
        with pytest.raises(C.ContractError):
            C.retry_budget(bad)
    assert C.retry_budget(REAL) == 1


# --------------------------------------------------------------------------
# БИ-13 — переход без ОК Антона
# --------------------------------------------------------------------------

def test_transition_without_anton_ok_refused_even_when_critics_agree(directory):
    answer = cmp_answer(ALL_PASS, "cand_a")
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask)
    assert result.outcome.reason == "подтверждён"          # полное согласие критиков
    with locked(directory) as store:
        with pytest.raises(C.AntonOkRequired) as refused:
            C.leave_idea_stage(store)
        assert refused.value.code == "НЕТ_ОК_АНТОНА"
        # положительный контроль: с записанным ОК тот же вызов проходит
        store.set_flag(C.ANTON_OK_FLAG)
        assert C.leave_idea_stage(store) is True


def test_other_flags_do_not_stand_in_for_anton_ok(directory):
    with locked(directory) as store:
        store.set_flag(C.OBJECTION_FLAG)
        with pytest.raises(C.AntonOkRequired):
            C.leave_idea_stage(store)


# --------------------------------------------------------------------------
# оракул: девять фикстур исходов через логику
# --------------------------------------------------------------------------

def test_outcome_fixtures_agree_with_oracle():
    files = sorted(FIXTURES.glob("outcome-*.json"))
    assert len(files) == 9
    reasons = set()
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        given, want = data["вход"], data["ожидается"]
        criteria = given["критерий_успеха"]
        parsed = C.validate_criteria(criteria)
        ids = [c["candidate_id"] if "candidate_id" in c else c["id"] for c in given["карточки"]]
        views = []
        for critic, answer in given["ответы_критиков"].items():
            raw = comparison(ids, {c: answer["оценки"][c] for c in ids}, answer["selected_candidate_id"],
                             {frozenset(r["pair"]): r["relation"] for r in answer["mechanism_relations"]},
                             criteria=criteria)
            views.append(C.validate_comparison(raw, candidate_ids=ids, criteria=parsed,
                                               critic=critic, tables=TABLES))
        outcome = C.decide_outcome(
            *views, author_id=given["автор_candidate_id"],
            framing_open=bool(given.get("есть_открытые_возражения_к_постановке")), tables=TABLES)
        assert outcome.reason == want["причина"], path.name
        assert outcome.priority == want["приоритет"], path.name
        assert outcome.verdict == want["вердикт"], path.name
        assert outcome.run_state == want["состояние_прогона"], path.name
        reasons.add(outcome.reason)
    assert reasons == set(REAL.raw["blocks"]["списки"]["исходы_идеи"])


# --------------------------------------------------------------------------
# круг 2
# --------------------------------------------------------------------------

def _blind_ask(compare_steps):
    return Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                  ("claude", "compare"): compare_steps, ("codex", "compare"): compare_steps})


def _from_request(grades, selected, relations=None):
    """Сравнение строится из запроса (id и критерии), а не из замыкания теста."""
    def build(request):
        ids = [c["candidate_id"] for c in request["candidates"]]
        mandatory = [c["id"] for c in request["criteria"] if c["mandatory"]]
        rows = [{"candidate_id": i, "criteria": [
            {"criterion_id": m, "grade": grades[i], "reason": "р"} for m in mandatory]} for i in ids]
        pairs = [{"pair": list(p), "relation": (relations or {}).get(frozenset(p), "unknown")}
                 for p in itertools.combinations(ids, 2)]
        return json.dumps({"assessments": rows, "selected_candidate_id": selected,
                           "mechanism_relations": pairs, "reasons": ["р"], "unknowns": [], "blockers": []})
    return build


# 1 — враждебные ответы
HOSTILE = {
    "глубина 100000": "[" * 100000 + "]" * 100000,
    "суррогат строкой": '"\\ud800"',
    "суррогат в объекте": json.dumps(proposal(ONE), ensure_ascii=False).replace('"вариант x"', '"\\ud800"'),
    "огромный": "[" + "0," * 400000 + "0]",
    "огромный объект": json.dumps({"variant": "я" * 400000}),
    "str с суррогатом": {**proposal(ONE), "variant": "\ud800"},
    "глубокий dict": None,
}


def _deep_dict(n=5000):
    node = {}
    for _ in range(n):
        node = {"a": node}
    return node


@pytest.mark.parametrize("name", list(HOSTILE))
def test_hostile_answer_is_answer_rejected_never_a_crash(name):
    raw = _deep_dict() if name == "глубокий dict" else HOSTILE[name]
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(raw, PARSED_ONE, TABLES)
    with pytest.raises(C.AnswerRejected):
        C.validate_comparison(raw, candidate_ids=IDS, criteria=PARSED_ONE, tables=TABLES)
    with pytest.raises(C.AuthorCardRefused):
        C.check_author_card(raw, ONE, TABLES)


def test_hostile_answer_gets_the_ordinary_retry(directory):
    ask = Asker({("claude", "blind"): ["[" * 100000, good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [cmp_answer(ALL_PASS, "cand_a")],
                 ("codex", "compare"): ['"\\ud800"', cmp_answer(ALL_PASS, "cand_a")]})
    result = stage(directory, ask)
    assert result.outcome.reason == "подтверждён" and ask.count() == 6


# 2 — сохранённые ответы проверяются
@pytest.mark.parametrize("bad", ["мусор", {"variant": "x"}, None, json.dumps({"x": 1})])
def test_saved_proposal_is_validated_and_breakage_is_ours(directory, bad):
    ask = _blind_ask([cmp_answer(ALL_PASS, "cand_a")])
    with pytest.raises(C.ContractError):
        stage(directory, ask, saved_proposals={"claude": bad})
    assert ask.count("compare") == 0


def test_saved_comparison_of_foreign_set_is_contract_error(directory):
    foreign = comparison(["x1", "x2", "x3"], {"x1": "pass", "x2": "pass", "x3": "pass"}, "x1")
    ask = _blind_ask([cmp_answer(ALL_PASS, "cand_a")])
    with pytest.raises(C.ContractError):
        stage(directory, ask, saved_comparisons={"claude": foreign})


def test_valid_saved_proposal_is_used_without_a_call(directory):
    ask = _blind_ask([cmp_answer(ALL_PASS, "cand_a")])
    stage(directory, ask, saved_proposals={"claude": proposal(ONE, "сохр")})
    assert ("claude", "blind", 1) not in ask.calls


# 3 — критерии в запросе сравнения
def test_comparison_is_built_from_the_request(directory):
    answer = _from_request(ALL_PASS, "cand_a")
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask, criteria=CRITERIA, author_card=proposal(CRITERIA, "а"))
    # ответы слепых по ONE не подходят к CRITERIA -> неполный; проверяем запрос отдельно на ONE
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН"


def test_compare_request_carries_criteria(directory):
    seen = []

    def spy(request):
        seen.append(request)
        return _from_request(ALL_PASS, "cand_a")(request)

    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [spy], ("codex", "compare"): [spy]})
    result = stage(directory, ask)
    assert result.outcome.reason == "подтверждён"
    assert seen[0]["criteria"] == [{"id": "К1", "text": "работает", "mandatory": True}]


# 4 — выход со стадии
def _done(directory, reason_grades=ALL_PASS, selected="cand_a", flag=False):
    if flag:
        with locked(directory) as store:
            store.set_flag(C.OBJECTION_FLAG)
    answer = _from_request(reason_grades, selected)
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    return stage(directory, ask)


def _leave(directory):
    with locked(directory) as store:
        return C.leave_idea_stage(store)


def test_gate_opens_only_for_ok_after_the_verdict(directory):
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)              # ОК до исхода
    _done(directory)
    with pytest.raises(C.AntonOkRequired):
        _leave(directory)
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)              # повторный ОК уже после вердикта
    assert _leave(directory) is True


def test_gate_closed_before_outcome(directory):
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)
    with pytest.raises(C.AntonOkRequired):
        _leave(directory)


def test_gate_closed_on_incomplete_run(directory):
    ask = Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]})
    assert stage(directory, ask).run_state == "неполный"
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)
    with pytest.raises(C.AntonOkRequired):
        _leave(directory)


def test_gate_closed_with_open_objection(directory):
    _done(directory, flag=True)
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)
    with pytest.raises(C.AntonOkRequired):
        _leave(directory)


def test_ok_does_not_survive_a_new_round_and_revoked_ok_closes_gate(directory):
    _done(directory)
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG)
        assert C.leave_idea_stage(store)
        store.start_round(2)
        with pytest.raises(C.AntonOkRequired):
            C.leave_idea_stage(store)
        store.set_flag(C.ANTON_OK_FLAG)              # ОК уже после нового круга, но вердикта нового нет
    # состояние прогона не менялось, вердикт прежний -> порядок событий: ОК после круга и после вердикта
    assert _leave(directory) is True
    with locked(directory) as store:
        store.set_flag(C.ANTON_OK_FLAG, False)
        with pytest.raises(C.AntonOkRequired):
            C.leave_idea_stage(store)


def test_critics_agree_parameter_is_gone():
    import inspect
    assert list(inspect.signature(C.leave_idea_stage).parameters) == ["store"]


# 5, 9 — неидентичная перестановка и пара автора
def test_shown_order_is_recorded_permutation_for_both_critics(directory):
    requests = []

    def spy(request):
        requests.append(request)
        return _from_request(ALL_PASS, "cand_a")(request)

    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [spy], ("codex", "compare"): [spy]})
    stage(directory, ask, shuffle=lambda order: order.reverse())
    state = S.RunStore(directory, TABLES).load()
    expected = [state.idea_candidates[i].candidate_id for i in state.idea_candidates_permutation]
    assert state.idea_candidates_permutation == (2, 1, 0) and expected == ["cand_c", "cand_b", "cand_a"]
    assert len(requests) == 2
    for request in requests:
        assert [c["candidate_id"] for c in request["candidates"]] == expected


def test_outcome_depends_on_author_pair_found_by_engine(directory, tmp_path):
    grades = {"cand_a": "fail", "cand_b": "pass", "cand_c": "pass"}
    reasons = {}
    for name, pair in (("автор-выбранный", ("cand_a", "cand_b")), ("другая", ("cand_b", "cand_c"))):
        path = started(tmp_path / name.replace("-", "_"), "run-" + name)
        answer = _from_request(grades, "cand_b", {frozenset(pair): "different"})
        ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                     ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
        reasons[name] = stage(path, ask, shuffle=lambda order: order.reverse()).outcome.reason
    assert reasons == {"автор-выбранный": "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной",
                       "другая": "оба_предпочли_неавторскую"}


# 6 — таблица порчи сравнения
def _comparison_corruptions():
    def at(mutator):
        def build():
            data = comparison(IDS, ALL_PASS, "cand_a")
            mutator(data)
            return data
        return build
    return {
        "корень лишнее": at(lambda d: d.update(x=1)),
        "assessment лишнее": at(lambda d: d["assessments"][0].update(x=1)),
        "criteria лишнее": at(lambda d: d["assessments"][0]["criteria"][0].update(x=1)),
        "relation лишнее": at(lambda d: d["mechanism_relations"][0].update(x=1)),
        "без assessments": at(lambda d: d.pop("assessments")),
        "без selected": at(lambda d: d.pop("selected_candidate_id")),
        "без relations": at(lambda d: d.pop("mechanism_relations")),
        "без reasons": at(lambda d: d.pop("reasons")),
        "без reason у критерия": at(lambda d: d["assessments"][0]["criteria"][0].pop("reason")),
        "пустой reason": at(lambda d: d["assessments"][0]["criteria"][0].update(reason="")),
        "невидимый reason": at(lambda d: d["assessments"][0]["criteria"][0].update(reason="\u200b\u2800")),
        "пустой selected": at(lambda d: d.update(selected_candidate_id="")),
        "пустые reasons": at(lambda d: d.update(reasons=[])),
        "grade Pass": at(lambda d: d["assessments"][0]["criteria"][0].update(grade="Pass")),
        "grade true": at(lambda d: d["assessments"][0]["criteria"][0].update(grade=True)),
        "relation вне словаря": at(lambda d: d["mechanism_relations"][0].update(relation="equal")),
        "reason не строка": at(lambda d: d["assessments"][0]["criteria"][0].update(reason=1)),
        "длинный reason": at(lambda d: d["assessments"][0]["criteria"][0].update(reason="я" * 5000)),
        "много reasons": at(lambda d: d.update(reasons=["р"] * 100)),
        "не объект": lambda: ["x"],
        "None": lambda: None,
    }


@pytest.mark.parametrize("name", list(_comparison_corruptions()))
def test_comparison_corruptions_rejected(name):
    with pytest.raises(C.AnswerRejected):
        C.validate_comparison(_comparison_corruptions()[name](), candidate_ids=IDS,
                              criteria=PARSED_ONE, tables=TABLES)


# 7 — порядок повторов на уровне стадии
def test_retry_order_differs_between_run_ids_of_different_parity(tmp_path):
    orders = {}
    for run_id in ("run-1", "run-2", "run-3", "run-4", "run-5", "run-6"):
        path = started(tmp_path / run_id, run_id)
        ask = Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]})
        stage(path, ask)
        orders[run_id] = tuple(c[0] for c in ask.calls if c[2] == 2)
    assert set(orders.values()) == {("claude", "codex"), ("codex", "claude")}
    for run_id, order in orders.items():
        assert list(order) == C.retry_order(run_id, ["claude", "codex"])


# 8 — отношения по каждой паре отдельно
def test_enumeration_varies_each_pair_relation_separately():
    pairs = [frozenset(p) for p in itertools.combinations(IDS, 2)]
    grades = {"cand_a": "fail", "cand_b": "pass", "cand_c": "pass"}
    enhanced = "оба_предпочли_неавторскую_и_назвали_авторскую_непроходной"
    for first_rel in itertools.product(["same", "different", "unknown"], repeat=3):
        for second_rel in itertools.product(["same", "different", "unknown"], repeat=3):
            one = vc(IDS, grades, "cand_b", dict(zip(pairs, first_rel)))
            two = vc(IDS, grades, "cand_b", dict(zip(pairs, second_rel)))
            author_pair = frozenset(("cand_a", "cand_b"))
            wanted = one.relations[author_pair] == two.relations[author_pair] == "different"
            got = C.decide_outcome(one, two, author_id="cand_a", framing_open=False, tables=TABLES).reason
            assert (got == enhanced) is wanted


# 10 — ровно два разных критика
@pytest.mark.parametrize("critics", [("claude",), ("claude", "claude"), ("a", "b", "c"), (), ("claude", ""), ("x", 1)])
def test_exactly_two_distinct_critics(directory, critics):
    ask = Asker({})
    with pytest.raises(C.ContractError):
        stage(directory, ask, critics=critics)
    assert ask.count() == 0


# 11 — одинаковая форма карточек
def test_cards_have_one_form_whatever_the_source(directory):
    author = proposal(CRITERIA[:2], "а")
    author["criteria_fit"].reverse()
    plain = proposal(CRITERIA[:2], "б")
    rich = {**proposal(CRITERIA[:2], "в"), "возражения_к_постановке": ["возражение"]}
    ask = Asker({("claude", "blind"): [json.dumps(plain)], ("codex", "blind"): [json.dumps(rich)],
                 ("claude", "compare"): ["x"], ("codex", "compare"): ["x"]})
    stage(directory, ask, criteria=CRITERIA[:2], author_card=author)
    cards = [json.loads(c.canonical_bytes) for c in S.RunStore(directory, TABLES).load().idea_candidates]
    assert len({tuple(sorted(c)) for c in cards}) == 1
    assert all([r["criterion_id"] for r in c["criteria_fit"]] == ["К1", "К2"] for c in cards)
    assert all("возражения_к_постановке" in c for c in cards)


# 13 — id критериев (смягчено, см. FORK в отчёте)
@pytest.mark.parametrize("bad_id", ["К 1", "К1 ", "", "\u200bК1", "я" * 33, "К\n1"])
def test_criterion_ids_with_spaces_or_invisibles_refused(bad_id):
    with pytest.raises(C.AuthorCardRefused):
        C.validate_criteria([{"id": bad_id, "текст": "т", "обязательный": True}])


# 14 — плохие shuffle/new_id
@pytest.mark.parametrize("shuffler", [
    lambda o: o.__setitem__(0, 1), lambda o: o.pop(), lambda o: o.append(9), lambda o: o.clear()])
def test_bad_permutation_is_contract_error(directory, shuffler):
    ask = _blind_ask(["x"])
    with pytest.raises(C.ContractError):
        stage(directory, ask, shuffle=shuffler)
    assert not S.RunStore(directory, TABLES).load().idea_candidates


@pytest.mark.parametrize("ids", [["a", "a", "b"], ["a", "", "b"], ["a", None, "b"], ["a", 1, "b"]])
def test_bad_ids_are_contract_error(directory, ids):
    ask = _blind_ask(["x"])
    with pytest.raises(C.ContractError):
        stage(directory, ask, new_id=iter(ids).__next__)


# 15 — повторный вход на завершённую стадию
def test_reentry_on_finished_stage_is_contract_error_with_zero_calls(directory, tmp_path):
    _done(directory)
    again = Asker({})
    with pytest.raises(C.ContractError, match="стадия завершена"):
        stage(directory, again)
    assert again.count() == 0
    other = started(tmp_path / "inc", "run-inc")
    stage(other, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}))
    again = Asker({})
    with pytest.raises(C.ContractError, match="стадия завершена"):
        stage(other, again)
    assert again.count() == 0


# 16 — значения критика в исключениях обрезаны
def test_participant_values_are_clipped_in_exceptions():
    long = "ы" * 5000
    data = comparison(IDS, ALL_PASS, long)
    with pytest.raises(C.AnswerRejected) as refused:
        C.validate_comparison(data, candidate_ids=IDS, criteria=PARSED_ONE, tables=TABLES)
    assert len(str(refused.value)) < 400 and long not in str(refused.value)
    extra = proposal(ONE)
    extra[long] = 1
    with pytest.raises(C.AnswerRejected) as refused:
        C.validate_proposal(extra, PARSED_ONE, TABLES)
    assert len(str(refused.value)) < 400


# 17 — невидимая «пустота»
@pytest.mark.parametrize("blank", ["\u200b", "\u2800", " \u200b ", "\u00ad", "\ufeff", "\t\n"])
def test_invisible_strings_count_as_empty(blank):
    broken = proposal(ONE)
    broken["variant"] = blank
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(broken, PARSED_ONE, TABLES)
    with pytest.raises(C.AuthorCardRefused):
        C.validate_criteria([{"id": "К1", "текст": blank, "обязательный": True}])


# 18 — явная ветка для рисунка_выбора, неизвестный код
def test_unknown_check_code_is_contract_error():
    rules = copy.deepcopy(RULES)
    rules["строки"][0]["проверка"] = "выдумка"
    with pytest.raises(C.ContractError):
        C.outcome_rules(tables_with(rules))


# 19 — порча словаря и схем
def test_vocabulary_corruption_is_contract_error():
    first = vc(IDS, ALL_PASS, "cand_a")
    for bad in ({"выбор_кандидата_sentinel": None}, {"выбор_кандидата_sentinel": ""}):
        with pytest.raises(C.ContractError):
            C.validate_comparison(comparison(IDS, ALL_PASS, "cand_a"), candidate_ids=IDS,
                                  criteria=PARSED_ONE, tables=tables_with(**bad))
        with pytest.raises(C.ContractError):
            C.decide_outcome(first, first, author_id="cand_a", framing_open=False, tables=tables_with(**bad))
    raw = copy.deepcopy(REAL.raw)
    raw["stages"]["исходы_идеи"] = copy.deepcopy(RULES)
    raw["vocabulary"].pop("выбор_кандидата_sentinel")
    with pytest.raises(C.ContractError):
        C.validate_comparison(comparison(IDS, ALL_PASS, "cand_a"), candidate_ids=IDS,
                              criteria=PARSED_ONE, tables=T.Tables.from_raw(raw))


def test_attempt_states_corruption_is_contract_error(directory):
    broken = tables_with(попытка={**REAL.vocabulary["попытка"], "состояния": ["запущена"]})
    state = S.RunStore(directory, TABLES).load()
    with pytest.raises(C.ContractError):
        C._valid_recorded(state, broken, "s", 1, "claude")


@pytest.mark.parametrize("schema", [
    {"type": "array", "minItems": "1"}, {"type": "array", "maxItems": -1}, {"type": "string", "minLength": True},
    {"type": "string", "maxLength": 1.5}, {"type": "array", "uniqueItems": "yes"},
    {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]},
])
def test_check_schema_types_numeric_keywords_and_required_subset(schema):
    with pytest.raises(C.ContractError):
        C.check_schema(schema)


@pytest.mark.parametrize("first,second", [("К1", "K1"), ("К1", "k1"), ("К1", "к1"), ("Е3", "E3"), ("КА", "KA"), ("ａ", "a")])
def test_criterion_ids_equal_after_homoglyph_folding_refused(first, second):
    rows = [{"id": first, "текст": "т", "обязательный": True}, {"id": second, "текст": "т", "обязательный": False}]
    with pytest.raises(C.AuthorCardRefused, match="свёртки"):
        C.validate_criteria(rows)


def test_criterion_ids_that_differ_stay_distinct():
    rows = [{"id": "К1", "текст": "т", "обязательный": True}, {"id": "К2", "текст": "т", "обязательный": True},
            {"id": "К3", "текст": "т", "обязательный": False}]
    assert len(C.validate_criteria(rows)) == 3
    assert len(C.validate_criteria([{"id": "Е3", "текст": "т", "обязательный": True},
                                    {"id": "Е8", "текст": "т", "обязательный": True}])) == 2
