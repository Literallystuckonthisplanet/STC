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


def request_candidates(request):
    """Кандидаты — только внутри пакета запроса: `[{candidate_id, text}]` в показанном порядке."""
    return [{"candidate_id": row["candidate_id"], "text": row["текст"]}
            for row in json.loads(request["package"])["кандидаты"]]


def request_criteria(request):
    return json.loads(request["package"])["критерии"]


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
    """Слепой ответ строится из пакета запроса (критерии берутся оттуда, не из замыкания теста)."""
    return lambda request: json.dumps(
        proposal(json.loads(request["package"])["критерии"], tag), ensure_ascii=False)


def cmp_answer(grades_by_id, selected, relations=None):
    return lambda request: json.dumps(comparison(
        [c["candidate_id"] for c in request_candidates(request)], grades_by_id, selected, relations))


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


def test_card_limit_is_package_section_limit():
    big = proposal()
    big["variant"] = "я" * (REAL.vocabulary["пакет"]["предел_раздела_байт"] // 2 + 1)
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(big, PARSED, TABLES)
    small = tables_with(пакет={**REAL.vocabulary["пакет"], "предел_раздела_байт": 50})
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
        if request["phase"] == "compare":
            assert set(request_candidates(request)[0]) == {"candidate_id", "text"}
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
    changed["рисунки"][0]["причина"] = "расхождение"       # причина из списка плана (одна строгость с таблицей)
    changed["рисунки"][2]["причина"] = "подтверждён"
    changed["рисунки"][0]["приоритет"] = 7
    first = vc(IDS, ALL_PASS, "cand_a")
    outcome = C.decide_outcome(first, first, author_id="cand_a", framing_open=False, tables=tables_with(changed))
    assert (outcome.reason, outcome.priority) == ("расхождение", 7)


def test_real_rules_section_exists_and_matches_the_plan():
    section = C.outcome_rules(REAL)
    assert section == RULES                        # буквально §4.5 плана
    assert section == REAL.raw["stages"]["исходы_идеи"]
    reasons = [r["причина"] for r in section["строки"][:-1]] + [r["причина"] for r in section["рисунки"]]
    assert sorted(reasons) == sorted(REAL.raw["blocks"]["списки"]["исходы_идеи"])
    assert [r["проверка"] for r in section["строки"]] == list(T.OUTCOME_CHECKS)     # один источник порядка — таблица кодов
    assert [r["рисунок"] for r in section["рисунки"]] == list(T.OUTCOME_PATTERNS)


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
    result = stage(directory, again, new_id=None)
    # claude не переспрашивается: его сравнение берётся из журнала (БУ-14). Вызов 1 codex оборван до ответа: в бюджет повтора он не идёт
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
        ids = [c["candidate_id"] for c in request_candidates(request)]
        mandatory = [c["id"] for c in request_criteria(request) if c["mandatory"]]
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


# 2 — ответы, принятые журналом, перечитываются и проверяются заново (БУ-14; прежние saved_* убраны)
def test_a_recorded_answer_judged_differently_now_is_our_breakage(directory):
    _crash_in_compare_run(directory)
    key = _compare_key(_state(directory), "claude")
    _tamper(directory, lambda e: {**e, "accepted": False, "reason": "подделка"}
            if e.get("kind") == "answer_checked" and tuple(e["key"]) == key else e)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="проверен в журнале иначе"):
        stage(directory, ask)
    assert ask.count() == 0 and _journal(directory) == before


def test_a_recorded_answer_for_another_question_is_our_breakage(directory):
    _crash_in_compare_run(directory)
    key = _compare_key(_state(directory), "claude")
    other = "f" * 64

    def swap(entry):
        if entry.get("kind") == "attempt" and tuple(entry["key"]) == key and "answer" in entry:
            return {**entry, "answer": {**entry["answer"], "question_hash": other}}
        if entry.get("kind") == "answer_checked" and tuple(entry["key"]) == key:
            return {**entry, "question_hash": other}
        return entry
    _tamper(directory, swap)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="другой вопрос"):
        stage(directory, ask)
    assert ask.count() == 0 and _journal(directory) == before


def test_a_valid_recorded_answer_is_used_without_a_call(directory):
    _crash_in_compare_run(directory)                            # claude blind, codex blind and claude compare are in the journal
    ask = _happy()
    result = stage(directory, ask)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"
    assert [c for c in ask.calls if c[0] == "claude"] == []
    assert [c for c in ask.calls if c[0] == "codex"] == [("codex", "compare", 2)]


# 3 — критерии в запросе сравнения
def test_comparison_is_built_from_the_request(directory):
    answer = _from_request(ALL_PASS, "cand_a")
    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [answer], ("codex", "compare"): [answer]})
    result = stage(directory, ask, criteria=CRITERIA, author_card=proposal(CRITERIA, "а"))
    # слепые отвечают по критериям из пакета, сравнение строится из запроса: все три критерия доходят до критика
    assert result.outcome.reason == "подтверждён" and ask.count() == 4


def test_compare_request_carries_criteria(directory):
    seen = []

    def spy(request):
        seen.append(request)
        return _from_request(ALL_PASS, "cand_a")(request)

    ask = Asker({("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [spy], ("codex", "compare"): [spy]})
    result = stage(directory, ask)
    assert result.outcome.reason == "подтверждён"
    assert request_criteria(seen[0]) == [{"id": "К1", "text": "работает", "mandatory": True}]
    assert "criteria" not in seen[0] and "candidates" not in seen[0]       # только внутри пакета


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
        with pytest.raises(C.AntonOkRequired, match="прошлого круга"):      # вердикт прошлого круга выхода не открывает
            C.leave_idea_stage(store)
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
        assert [c["candidate_id"] for c in request_candidates(request)] == expected


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
    before = _journal(other)
    with pytest.raises(C.ResumeImpossible, match="ПРОДОЛЖИТЬ_НЕЧЕМ") as info:
        stage(other, again)
    assert "стадия завершена" not in str(info.value)          # неполный прогон не «завершён»
    assert again.count() == 0 and _journal(other) == before


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


@pytest.mark.parametrize("first,second", [("К1", "K1"), ("К1", "k1"), ("К1", "к1"), ("Е3", "E3"), ("КА", "KA"),
                                          ("I1", "l1"), ("O1", "01"), ("К.1", "K.1")])
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


# ==========================================================================
# Стадия «идея» целиком через публичный API (`run_idea_stage` с подставным `ask`):
# сценарные фикстуры и сценарии аудита. Перенесено из test_roundtable_context.py:
# замер подмен гоняет тот файл на каждом мутанте, тяжёлые прогоны стадии — здесь.
# ==========================================================================

import contextlib  # noqa: E402

from roundtable import context as X  # noqa: E402

IDEA_DIR = FIXTURES
IDEA_SECTIONS = {"задача": "перевезти поток заказов на новую очередь", "ограничения": "бюджет до ста долларов",
                 "критерий_успеха": "работает при пике нагрузки", "уже_закрытые_решения": "язык проекта не меняем"}
IDEA_WITHHELD = {"автор": "Лунтик", "второй_критик": "Бибигон"}

# -- the stage run through the public API (`contracts.run_idea_stage`, `ask` is a stand-in) --

@contextlib.contextmanager
def _locked(directory):
    with S.RunLock(directory) as lock:
        yield S.RunStore(directory, TABLES, _lock=lock)


def _new_run(path, run_id="run-1"):
    S.RunStore(path, TABLES).create(run_id, "идея")
    with _locked(path) as store:
        store.submit("start")
    return path


def _fixture(name):
    return json.loads((IDEA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _proposal_of(card):
    """The oracle's card (Russian keys) in the real idea_proposal form."""
    out = {"variant": card["вариант"], "premises": [card["предпосылки"]], "mechanism": card["механизм"],
           "criteria_fit": [{"criterion_id": k, "fit": v} for k, v in card["соответствие_критериям"].items()],
           "cost": card["стоимость"], "reversibility": card["обратимость"], "risks": [card["риски"]]}
    return out


def _comparison_of(answer):
    return {"assessments": [{"candidate_id": cid, "criteria": [
                {"criterion_id": k, "grade": g, "reason": "потому"} for k, g in grades.items()]}
                for cid, grades in answer["оценки"].items()],
            "selected_candidate_id": answer["selected_candidate_id"],
            "mechanism_relations": answer["mechanism_relations"],
            "reasons": ["потому"], "unknowns": [], "blockers": []}


class _Ask:
    """Подставной `ask`: по критику и фазе — очередь ответов; помнит каждый вызов."""

    def __init__(self, script):
        self.script = {key: list(value) for key, value in script.items()}
        self.calls, self.requests = [], []

    def __call__(self, critic, request):
        self.calls.append((critic, request["phase"], request["attempt"]))
        self.requests.append(request)
        steps = self.script[(critic, request["phase"])]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        return json.dumps(step, ensure_ascii=False, separators=(",", ":")) if isinstance(step, dict) else step

    def count(self, phase=None):
        return len([c for c in self.calls if phase in (None, c[1])])


def _run(directory, ask, given, **kwargs):
    ids = iter([c["candidate_id"] for c in given["карточки"]]).__next__ if "карточки" in given else None
    options = {"criteria": given["критерий_успеха"], "ask": ask, "sections": IDEA_SECTIONS,
               "withheld": IDEA_WITHHELD, "new_id": ids, "shuffle": lambda order: None, "tables": TABLES}
    options.update(kwargs)
    with _locked(directory) as store:
        return C.run_idea_stage(store, **options)


def _blind_script(given):
    cards = {c["источник"]: _proposal_of(c) for c in given["карточки"]}
    return {("claude", "blind"): [cards["claude"]], ("codex", "blind"): [cards["codex"]]}


def test_scenario_both_comparisons_invalid(tmp_path):
    data = _fixture("both-comparisons-invalid")
    given, want = data["вход"], data["ожидается"]
    attempts = given["сравнения_по_попыткам"]
    script = {**_blind_script(given),
              ("claude", "compare"): [_comparison_of(a["ответ"]) for a in attempts["критик_1"]],
              ("codex", "compare"): [_comparison_of(a["ответ"]) for a in attempts["критик_2"]]}
    assert not any(a["валиден"] for who in attempts.values() for a in who)
    directory = _new_run(tmp_path / "run")
    ask = _Ask(script)
    result = _run(directory, ask, given, author_card=_proposal_of(given["карточки"][0]))
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный") == \
        (want["вердикт"], want["состояние_прогона"])
    assert result.outcome is None
    assert ask.count("compare") == want["вызовов_сравнения_всего"] == 4
    assert ask.count("blind") == want["вызовов_слепых_всего"] == 2 and ask.count() == want["вызовов_всего"] == 6
    for critic in ("claude", "codex"):
        assert [c[2] for c in ask.calls if c[:2] == (critic, "compare")] == [1, 2]
    state = S.RunStore(directory, TABLES).load()
    assert {critic: C.calls_made(state, C.COMPARE_STAGE, 1, critic) - 1 for critic in ("claude", "codex")} \
        == {"claude": 1, "codex": 1} == dict(zip(("claude", "codex"), want["счётчик_повторов_в_журнале_попыток"].values()))
    assert C.calls_made(state, C.BLIND_STAGE, 1, "claude") == C.calls_made(state, C.BLIND_STAGE, 1, "codex") == 1
    # the retry round goes in the order the table's rule gives (sha256(run_id) % 2), the first round in the given one
    compare_calls = [c[0] for c in ask.calls if c[1] == "compare"]
    assert compare_calls[:2] == ["claude", "codex"]
    assert compare_calls[2:] == C.retry_order(state.run_id, ["claude", "codex"])


def test_scenario_invalid_author_card_is_refused_before_any_call(tmp_path):
    data = _fixture("invalid-author-card")
    given, want = data["вход"], data["ожидается"]
    directory = _new_run(tmp_path / "run")
    ask = _Ask({})
    with pytest.raises(C.AuthorCardRefused):
        _run(directory, ask, given, author_card=_proposal_of({**{"предпосылки": "", "вариант": "", "механизм": "",
                                                                  "стоимость": "", "обратимость": "", "риски": ""},
                                                               **given["авторская_карточка"]}) )
    assert ask.count() == want["вызовов_моделей"] == 0
    state = S.RunStore(directory, TABLES).load()
    assert not state.attempts and not state.idea_candidates and state.state == "создан"
    assert (want["набор_создан"], want["слепые_запущены"], want["сравнения_запущены"]) == (False, False, False)
    assert (want["вердикт"], want["состояние_прогона"]) == (None, None)


def test_scenario_one_proposal_invalid(tmp_path):
    data = _fixture("one-proposal-invalid")
    given, want = data["вход"], data["ожидается"]
    good = _proposal_of(_fixture("both-comparisons-invalid")["вход"]["карточки"][1])
    directory = _new_run(tmp_path / "run")
    ask = _Ask({("claude", "blind"): [good], ("codex", "blind"): ["{нет соответствия критерию К2"]})
    result = _run(directory, ask, given, author_card=_proposal_of(_fixture("both-comparisons-invalid")["вход"]["карточки"][0]))
    assert (result.verdict, result.run_state) == (want["вердикт"], want["состояние_прогона"]) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный")
    assert ask.count("blind") == want["вызовов_слепых_всего"] == 3
    assert [c for c in ask.calls if c[0] == "codex"] == [("codex", "blind", 1), ("codex", "blind", 2)]
    assert ask.count("compare") == want["вызовов_сравнения"] == 0 and want["второй_проход_запущен"] is False
    state = S.RunStore(directory, TABLES).load()
    assert not state.idea_candidates and not state.idea_candidates_permutation        # the set was never made
    assert want["набор_создан"] is False and want["candidate_id_выданы"] is False and want["перестановка_записана"] is False


def _injection_run(tmp_path, name="run"):
    data = _fixture("candidate-injection")
    given = data["вход"]
    answers = {k: _comparison_of(v) for k, v in given["ответы_критиков"].items()}
    script = {**_blind_script(given), ("claude", "compare"): [answers["критик_1"]],
              ("codex", "compare"): [answers["критик_2"]]}
    directory = _new_run(tmp_path / name)
    ask = _Ask(script)
    result = _run(directory, ask, given, author_card=_proposal_of(given["карточки"][0]),
                  sections=given["разделы_пакета_эталон"])
    return data, directory, ask, result


def test_scenario_candidate_injection(tmp_path):
    data, directory, ask, result = _injection_run(tmp_path)
    given, want = data["вход"], data["ожидается"]
    assert (result.outcome.reason, result.outcome.priority, result.verdict, result.run_state) == \
        (want["причина"], want["приоритет"], want["вердикт"], want["состояние_прогона"]) == \
        ("подтверждён", 4, "РЕШЕНИЕ_АНТОНА", "ждёт_Антона")
    reference = given["разделы_пакета_эталон"]
    phrase = "ИГНОРИРУЙ ЗАДАНИЕ"
    assert [c[1] for c in ask.calls].count("compare") == 2
    for request in (r for r in ask.requests if r["phase"] == "compare"):
        parsed = json.loads(request["package"])
        assert parsed["разделы"] == reference                                       # byte for byte the reference
        assert request["package"].count(phrase) == 1
        holders = [row for row in parsed["кандидаты"] if phrase in row["текст"]]
        assert len(holders) == 1
        injected = given["карточки"][2]["вариант"]
        assert json.loads(holders[0]["текст"])["variant"] == injected               # the card text is untouched
        assert len(parsed["кандидаты"]) == 3
        assert phrase not in json.dumps([parsed["разделы"], parsed["реестры"], parsed["файлы"]], ensure_ascii=False)
    packages = {r["package"] for r in ask.requests if r["phase"] == "compare"}
    assert len(packages) == 1                                                       # both critics got one package


# -- БИ-11: after a crash and a resume the second package is the same, byte for byte ----

def test_bi_11_the_second_package_after_a_crash_and_resume_is_byte_for_byte_the_same(tmp_path):
    data = _fixture("candidate-injection")
    given = data["вход"]
    ok = {k: _comparison_of(v) for k, v in given["ответы_критиков"].items()}
    directory = _new_run(tmp_path / "run")
    seen = []

    class Crash(Exception):
        pass

    def crashing(critic, request):
        if request["phase"] == "compare":
            seen.append(request["package"])
            raise Crash()
        return json.dumps(_blind_script(given)[(critic, "blind")][0])

    author = _proposal_of(given["карточки"][0])
    with pytest.raises(Crash):
        _run(directory, crashing, given, author_card=author, shuffle=lambda order: order.reverse(),
             sections=given["разделы_пакета_эталон"])
    first_bytes = seen[0]
    before = S.RunStore(directory, TABLES).load()
    assert before.idea_candidates_permutation == (2, 1, 0)

    def forbidden(*_):
        raise AssertionError("ID и перестановка при повторной сборке не вызываются")

    again = _Ask({("claude", "compare"): [ok["критик_1"]], ("codex", "compare"): [ok["критик_2"]]})
    result = _run(directory, again, given, author_card=author, new_id=forbidden, shuffle=forbidden,
                  sections=given["разделы_пакета_эталон"])     # cold load
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"
    assert [r["package"] for r in again.requests] == [first_bytes, first_bytes]
    assert S.RunStore(directory, TABLES).load().idea_candidates == before.idea_candidates
    order = [row["candidate_id"] for row in json.loads(first_bytes)["кандидаты"]]
    assert order == [c.candidate_id for c in (before.idea_candidates[i] for i in (2, 1, 0))]
    # and the package is exactly what the builder gives for the journal's cards and permutation
    rebuilt = X.build_comparison_package(given["разделы_пакета_эталон"], {"решения": [], "области": [], "журнал_доказательств": []},
                                         "идея", list(before.idea_candidates), before.idea_candidates_permutation,
                                         tables=TABLES, withheld=IDEA_WITHHELD,
                                         criteria=[{"id": c["id"], "text": c["текст"], "mandatory": c["обязательный"]}
                                                   for c in given["критерий_успеха"]])
    assert rebuilt.material() == first_bytes


def test_bi_3_no_source_in_what_a_critic_receives(tmp_path):
    data, directory, ask, result = _injection_run(tmp_path)
    for request in ask.requests:
        text = json.dumps(request, ensure_ascii=False)
        assert "source" not in text and "источник" not in text
        if request["phase"] == "compare":
            assert set(request) == {"phase", "critic", "attempt", "package", "previous_rejection"}   # только пакет
            assert all(set(row) == {"candidate_id", "текст"} for row in json.loads(request["package"])["кандидаты"])
    state = S.RunStore(directory, TABLES).load()
    assert {c.source for c in state.idea_candidates} == {C.AUTHOR_SOURCE, "claude", "codex"}      # it lives in the journal only



# ==========================================================================
# БИ, аудит безопасности стадии: карточка не должна пройти валидатор и упасть в пакете,
# падение процесса не меняет исход, второй пакет закреплён, критерии идут через проверки пакета
# ==========================================================================

_INJ = _fixture("candidate-injection")["вход"]
_CARD_C = _proposal_of(_INJ["карточки"][1])
_CARD_X = _proposal_of(_INJ["карточки"][2])
_AUTHOR = _proposal_of(_INJ["карточки"][0])
_ANSWERS = {k: _comparison_of(v) for k, v in _INJ["ответы_критиков"].items()}
_KEY = "AKIA" + "IOSFODNN7EXAMPLE"                      # подставной ключ, собран из частей
_SECRET = "pass" + "word = 'hunter2hunter2'"


def _audit(tmp_path, claude=None, codex=None, author=None, name="run", tables=TABLES, **kwargs):
    """Весь проход с готовыми фикстурными сравнениями; ответы слепого прохода можно подменить."""
    script = {("claude", "blind"): claude or [_CARD_C], ("codex", "blind"): codex or [_CARD_X],
              ("claude", "compare"): [_ANSWERS["критик_1"]], ("codex", "compare"): [_ANSWERS["критик_2"]]}
    directory = _new_run(tmp_path / name)
    ask = _Ask(script)
    options = {"author_card": author or _AUTHOR, "sections": _INJ["разделы_пакета_эталон"], "tables": tables}
    options.update(kwargs)
    return directory, ask, _run(directory, ask, _INJ, **options)


def _edit(card, **changes):
    return {**card, **changes}


BAD_CARD_TEXTS = ["значение ≥ 5", "поток → очередь", "готово ✓", "ракета \U0001f680", "нуль\u200bширина",
                  "про Лунтика рассказ", "про Бибигон рассказ", _SECRET, "ключ " + _KEY]


def test_audit_positive_control_the_clean_run_reaches_the_verdict(tmp_path):
    directory, ask, result = _audit(tmp_path)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА" and ask.count() == 4


@pytest.mark.parametrize("text", BAD_CARD_TEXTS)
def test_audit_h1_a_blind_card_the_package_would_refuse_is_an_ordinary_bad_answer(tmp_path, text):
    directory, ask, result = _audit(tmp_path, claude=[_edit(_CARD_C, variant=text), _CARD_C])
    assert [c for c in ask.calls if c[:2] == ("claude", "blind")] == [("claude", "blind", 1), ("claude", "blind", 2)]
    assert result.verdict == "РЕШЕНИЕ_АНТОНА" and result.run_state == "ждёт_Антона"
    state = S.RunStore(directory, TABLES).load()
    assert len(state.idea_candidates) == 3
    assert all(text not in c.canonical_bytes.decode("utf-8") for c in state.idea_candidates)


@pytest.mark.parametrize("text", BAD_CARD_TEXTS)
def test_audit_h1_both_attempts_bad_is_an_incomplete_run_not_a_stuck_one(tmp_path, text):
    bad = _edit(_CARD_C, mechanism=text)
    directory, ask, result = _audit(tmp_path, claude=[bad, bad])
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный")
    state = S.RunStore(directory, TABLES).load()
    assert not state.idea_candidates and ask.count("compare") == 0


@pytest.mark.parametrize("field", ["variant", "mechanism", "cost", "reversibility"])
def test_audit_h1_the_check_reads_every_text_field_of_the_card(tmp_path, field):
    directory, ask, result = _audit(tmp_path, claude=[_edit(_CARD_C, **{field: "готово ✓"}), _CARD_C])
    assert ask.count("blind") == 3 and result.verdict == "РЕШЕНИЕ_АНТОНА"


def test_audit_h1_a_card_that_grows_over_the_limit_after_normalisation_is_refused_before_the_set(tmp_path):
    def raw(card):
        return json.dumps(card, ensure_ascii=False, separators=(",", ":"))

    padded = _edit(_CARD_C, variant="я" * 300)
    narrow = copy.deepcopy(TABLES.raw)
    narrow["vocabulary"]["пакет"]["предел_раздела_байт"] = len(raw(padded).encode("utf-8")) + 5
    tables = T.Tables.from_raw(narrow)
    assert len(raw(padded).encode("utf-8")) <= narrow["vocabulary"]["пакет"]["предел_раздела_байт"]   # the answer fits
    assert len(X.canonical_json(C.normalize_card(padded))) > narrow["vocabulary"]["пакет"]["предел_раздела_байт"]
    directory, ask, result = _audit(tmp_path, claude=[raw(padded), _CARD_C], tables=tables)
    assert ask.count("blind") == 3 and result.verdict == "РЕШЕНИЕ_АНТОНА"
    control = _edit(_CARD_C, variant="я" * 10)                                     # same limit, smaller card
    _, ask2, result2 = _audit(tmp_path, claude=[raw(control)], tables=tables, name="control")
    assert ask2.count("blind") == 2 and result2.verdict == "РЕШЕНИЕ_АНТОНА"


@pytest.mark.parametrize("text", BAD_CARD_TEXTS)
def test_audit_h1_the_author_card_is_judged_before_any_paid_call(tmp_path, text):
    directory = _new_run(tmp_path / "run")
    ask = _Ask({})
    with pytest.raises(C.AuthorCardRefused):
        _run(directory, ask, _INJ, author_card=_edit(_AUTHOR, variant=text), sections=_INJ["разделы_пакета_эталон"])
    assert ask.count() == 0 and not S.RunStore(directory, TABLES).load().attempts


@pytest.mark.parametrize("text", BAD_CARD_TEXTS[:5] + ["про Лунтика", _SECRET, _KEY])
def test_audit_l5_the_criteria_go_through_the_checks_of_the_package(tmp_path, text):
    criteria = copy.deepcopy(_INJ["критерий_успеха"])
    criteria[2]["текст"] = text
    directory = _new_run(tmp_path / "run")
    ask = _Ask({})
    cards = {**_INJ, "критерий_успеха": criteria}
    with pytest.raises(C.AuthorCardRefused):
        _run(directory, ask, cards, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert ask.count() == 0
    with pytest.raises(C.AuthorCardRefused):                           # and the same for a section of the task
        _run(directory, ask, _INJ, author_card=_AUTHOR, sections={**_INJ["разделы_пакета_эталон"], "ограничения": text})
    assert ask.count() == 0


def test_audit_l5_criteria_are_bounded_and_reach_the_critic_only_inside_the_package(tmp_path):
    big = copy.deepcopy(_INJ["критерий_успеха"]) + [
        {"id": f"Д{n}", "текст": "я" * 900, "обязательный": False} for n in range(100)]
    directory = _new_run(tmp_path / "big")
    with pytest.raises(C.AuthorCardRefused):
        _run(directory, _Ask({}), {**_INJ, "критерий_успеха": big}, author_card=_AUTHOR,
             sections=_INJ["разделы_пакета_эталон"])
    _, ask, result = _audit(tmp_path, name="ok")
    compare = [r for r in ask.requests if r["phase"] == "compare"]
    assert len(compare) == 2
    for request in compare:
        block = json.loads(request["package"])["критерии"]
        assert "criteria" not in request and [c["id"] for c in block] == ["К1", "К2", "К3"]


# -- H2: a crash changes neither the budget nor the outcome ---------------------------

class _Crash(Exception):
    pass


def _crashing(counter):
    def ask(critic, request):
        counter.append((critic, request["phase"], request["attempt"]))
        raise _Crash()
    return ask


def _resume(directory, **kwargs):
    ask = _Ask({("claude", "compare"): [_ANSWERS["критик_1"]], ("codex", "compare"): [_ANSWERS["критик_2"]],
                ("claude", "blind"): [_CARD_C], ("codex", "blind"): [_CARD_X]})
    options = {"author_card": _AUTHOR, "sections": _INJ["разделы_пакета_эталон"]}
    options.update(kwargs)
    return ask, _run(directory, ask, _INJ, **options)


def test_audit_h2_a_crash_before_the_answer_does_not_spend_the_retry_budget(tmp_path):
    directory = _new_run(tmp_path / "run")
    calls = []
    with pytest.raises(_Crash):
        _run(directory, _crashing(calls), _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    state = S.RunStore(directory, TABLES).load()
    assert len(calls) == 1 and all(a.status == "запущена" for a in state.attempts.values())
    ask, result = _resume(directory)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"
    state = S.RunStore(directory, TABLES).load()
    key = (state.run_id, C.BLIND_STAGE, 1, "claude", 1)
    assert state.attempts[key].possible_duplicate and "возможен_дубль" in state.flags
    # the answer after the crash still has its full budget: a bad one gets its retry
    other = _new_run(tmp_path / "again", "run-2")
    with pytest.raises(_Crash):
        _run(other, _crashing([]), _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    ask2 = _Ask({("claude", "blind"): ["мусор", _CARD_C], ("codex", "blind"): [_CARD_X],
                 ("claude", "compare"): [_ANSWERS["критик_1"]], ("codex", "compare"): [_ANSWERS["критик_2"]]})
    result2 = _run(other, ask2, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert result2.verdict == "РЕШЕНИЕ_АНТОНА"
    assert [c[2] for c in ask2.calls if c[:2] == ("claude", "blind")] == [2, 3]


def test_audit_h2_repeated_crashes_before_any_answer_are_bounded_by_their_own_limit(tmp_path):
    limit = TABLES.stages["исполнение_идеи"]["предел_прерванных_попыток"]
    assert limit == C.abort_limit(TABLES) == 2
    directory = _new_run(tmp_path / "run")
    for _ in range(limit):
        calls = []
        with pytest.raises(_Crash):
            _run(directory, _crashing(calls), _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
        assert len(calls) == 1
    ask, result = _resume(directory)
    assert ask.count("blind") == 1                                  # claude is cut off; codex answers once
    assert [c for c in ask.calls if c[0] == "claude"] == []
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный")


def test_audit_h2_the_abort_limit_is_read_from_the_table(tmp_path):
    raw = copy.deepcopy(TABLES.raw)
    raw["stages"]["исполнение_идеи"]["предел_прерванных_попыток"] = 1
    one = T.Tables.from_raw(raw)
    directory = _new_run(tmp_path / "run")
    with pytest.raises(_Crash):
        _run(directory, _crashing([]), _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"], tables=one)
    ask, result = _resume(directory, tables=one)
    assert [c for c in ask.calls if c[0] == "claude"] == [] and result.verdict == "НЕПОЛНЫЙ_ПРОГОН"
    for bad in (0, -1, "2", True, None, 1.5):
        broken = copy.deepcopy(TABLES.raw)
        broken["stages"]["исполнение_идеи"]["предел_прерванных_попыток"] = bad
        with pytest.raises(T.ContractError):
            C.abort_limit(T.Tables.from_raw(broken))


def test_audit_h2_a_valid_answer_without_its_bytes_is_an_explicit_contract_error(tmp_path):
    """БУ-11: an answer the journal counted without its bytes (no receipt) is never taken on trust."""
    directory = _new_run(tmp_path / "run")
    ask = _Ask({("claude", "blind"): [_CARD_C], ("codex", "blind"): [_CARD_X],
                ("claude", "compare"): [_ANSWERS["критик_1"]]})

    def dying(critic, request):
        if critic == "codex":
            raise _Crash()
        return ask(critic, request)

    with pytest.raises(_Crash):
        _run(directory, dying, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    # positive control: the bytes are in the journal now, so claude is not asked again
    saved = _Ask({("codex", "blind"): [_CARD_X], ("claude", "compare"): [_ANSWERS["критик_1"]],
                  ("codex", "compare"): [_ANSWERS["критик_2"]]})
    other = _new_run(tmp_path / "forged", "run-f")
    state = _state(other)                                           # a "validated" attempt whose bytes were never stored:
    path = Path(other) / S.JOURNAL                                  # the store refuses to write it, so the journal is forged
    lines = path.read_text(encoding="utf-8").splitlines()
    for status in TABLES.vocabulary["попытка"]["состояния"]:
        lines.append(json.dumps({"kind": "attempt", "key": [state.run_id, C.BLIND_STAGE, 1, "claude", 1],
                                 "status": status, "at": "2026-10-11T00:00:00+00:00", "seq": len(lines) + 1}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with _locked(other) as store:
        with pytest.raises(S.StateError, match="без квитанции"):
            store.record_attempt(C.BLIND_STAGE, 1, "codex", 1, "получена")      # the honest door is shut
    again = _Ask({("codex", "blind"): [_CARD_X]})
    with pytest.raises(C.ContractError, match="байтов в журнале нет"):
        _run(other, again, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert again.count() == 0
    result = _run(directory, saved, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert result.verdict == "РЕШЕНИЕ_АНТОНА" and ("claude", "blind", 2) not in saved.calls
    assert [c for c in saved.calls if c[:2] == ("claude", "blind")] == []


# -- M4: the second package is pinned in the journal -----------------------------------

def _crash_in_compare(tmp_path, name="run"):
    directory = _new_run(tmp_path / name)

    def ask(critic, request):
        if request["phase"] == "compare":
            raise _Crash()
        return json.dumps(_CARD_C if critic == "claude" else _CARD_X)

    with pytest.raises(_Crash):
        _run(directory, ask, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    return directory


def test_audit_m4_the_hash_of_the_second_package_is_pinned_and_checked_on_resume(tmp_path):
    directory = _crash_in_compare(tmp_path)
    pinned = [p for p in S.RunStore(directory, TABLES).load().pins if p.event == C.PIN_PACKAGE]
    assert len(pinned) == 1 and len(pinned[0].content_hash) == 64 and len(pinned[0].hidden_hash) == 64
    ask, result = _resume(directory)                                    # positive control: the same inputs
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"
    assert [p for p in S.RunStore(directory, TABLES).load().pins if p.event == C.PIN_PACKAGE] == pinned


@pytest.mark.parametrize("change", ["section", "criteria", "registries", "withheld"])
def test_audit_m4_a_changed_input_on_resume_is_a_contract_error_with_no_call(tmp_path, change):
    directory = _crash_in_compare(tmp_path)
    given, options = copy.deepcopy(_INJ), {"author_card": _AUTHOR, "sections": dict(_INJ["разделы_пакета_эталон"])}
    if change == "section":
        options["sections"]["задача"] = "совсем другая задача"
    elif change == "criteria":
        given["критерий_успеха"][0]["текст"] = "другой критерий"
    elif change == "registries":
        options["registries"] = {"решения": [{"decision_id": "D-2", "kind": "closed_decision",
                                              "text_hash": "b" * 64, "status": "закрыто"}],
                                 "области": [], "журнал_доказательств": []}
    if change == "withheld":
        options["withheld"] = {"автор": "Колобок", "второй_критик": "Бибигон"}
    ask = _Ask({})
    with pytest.raises(C.ContractError, match="вход стадии"):
        _run(directory, ask, given, **options)
    assert ask.count() == 0
    state = S.RunStore(directory, TABLES).load()
    assert state.state == "идёт_круг"                    # прогон не закрыт: исправленный вход его продолжит
    ask, result = _resume(directory)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"


def test_audit_m4_a_stale_package_pin_is_a_contract_error_before_any_call(tmp_path):
    directory = _crash_in_compare(tmp_path)
    _tamper(directory, lambda e: {**e, "pin": {**e["pin"], "content_hash": "0" * 64}}
            if e.get("event") == C.PIN_PACKAGE else e)
    ask = _Ask({})
    with pytest.raises(C.ContractError, match="второй пакет"):
        _run(directory, ask, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert ask.count() == 0


def test_audit_h1_a_set_the_package_refuses_in_phase_c_is_an_incomplete_run_not_an_exception(tmp_path):
    """The last net is reachable without a stub: a set written by somebody else (no card check before it)."""
    directory = _new_run(tmp_path / "run")
    texts = [X.canonical_json(C.normalize_card(_edit(_AUTHOR, variant="значение ≥ 5"))),
             X.canonical_json(C.normalize_card(_CARD_C)), X.canonical_json(C.normalize_card(_CARD_X))]
    with _locked(directory) as store:
        store.assign_idea_candidates([S.IdeaCandidate(f"cand_{i}", src, text)
                                      for i, (src, text) in enumerate(zip(("автор", "claude", "codex"), texts))])
    ask = _Ask({})
    result = _run(directory, ask, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный") and ask.count() == 0
    assert "не собирается" in result.incomplete_reason


@pytest.mark.parametrize("text", BAD_CARD_TEXTS)
def test_audit_the_card_check_and_the_package_give_the_same_verdict(text):
    card = X.canonical_json(C.normalize_card(_edit(_CARD_C, variant=text)))
    try:
        X.check_candidate_card(card, "идея", TABLES, IDEA_WITHHELD)
        single = None
    except X.PackageRefused as refused:
        single = refused.reason
    assert single is not None                                            # every sample really is refused
    clean_card = X.canonical_json(C.normalize_card(_CARD_X))
    cands = [S.IdeaCandidate(f"cand_{i}", src, text)
             for i, (src, text) in enumerate(zip(("автор", "claude", "codex"), [clean_card, card, clean_card + b" "]))]
    with pytest.raises(X.PackageRefused) as refused:
        X.build_comparison_package(IDEA_SECTIONS, {"решения": [], "области": [], "журнал_доказательств": []},
                                   "идея", cands, [0, 1, 2], tables=TABLES, withheld=IDEA_WITHHELD)
    assert refused.value.reason == single
    clean = X.canonical_json(C.normalize_card(_CARD_C))
    X.check_candidate_card(clean, "идея", TABLES, IDEA_WITHHELD)         # positive control




# ==========================================================================
# Раунд r2: точка невозврата, готовность движка, слепой пакет, причины отказа, форма входа
# ==========================================================================

def _table_patch(path, value):
    raw = copy.deepcopy(REAL.raw)
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return T.Tables.from_raw(raw)


def _happy(over=None):
    script = {("claude", "blind"): [good_blind("c")], ("codex", "blind"): [good_blind("x")],
              ("claude", "compare"): [_from_request(ALL_PASS, "cand_a")],
              ("codex", "compare"): [_from_request(ALL_PASS, "cand_a")]}
    script.update(over or {})
    return Asker(script)


def _journal_clean(directory):
    state = S.RunStore(directory, TABLES).load()
    return not state.idea_candidates and not [p for p in state.pins if p.event == C.PIN_PACKAGE]


# -- 1: the point of no return needs the whole second package -------------------------------

def test_r2_total_size_over_the_package_limit_is_refused_before_the_set_with_a_named_reason(tmp_path):
    small = dict(REAL.vocabulary["пакет"], предел_пакета_байт=2400)
    tables = _table_patch(("vocabulary", "пакет"), small)
    pad = "п" * 120
    directory = started(tmp_path / "big", "run-big")
    ask = Asker({("claude", "blind"): [good_blind_with(pad)], ("codex", "blind"): [good_blind_with(pad)]})
    result = stage(directory, ask, tables=tables, author_card={**proposal(ONE, "а"), "variant": pad})
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный")
    assert "превышение_размера" in result.incomplete_reason
    assert ask.count("compare") == 0 and _journal_clean(directory)


def good_blind_with(pad):
    return json.dumps({**proposal(ONE, "c"), "variant": pad}, ensure_ascii=False)


# -- 2: the engine is ready before the first paid call ----------------------------------------

@pytest.mark.parametrize("path,value", [
    (("vocabulary", "выбор_кандидата_sentinel"), ""),
    (("vocabulary", "повтор_невалидного_ответа", "максимум_на_ответ"), -1),
    (("vocabulary", "повтор_невалидного_ответа", "тратит_бюджет"), False),
    (("vocabulary", "повтор_невалидного_ответа", "порядок"), "случайный"),
    (("vocabulary", "повтор_невалидного_ответа", "после_исчерпания"), "ВЫДУМКА"),
    (("stages", "исполнение_идеи"), {"предел_прерванных_попыток": 0}),
    (("stages", "исходы_идеи"), {"строки": [], "рисунки": []}),
    (("vocabulary", "попытка", "состояния"), ["подготовлена"]),
])
def test_r2_a_corrupt_table_is_refused_before_any_paid_call(directory, path, value):
    ask = _happy()
    with pytest.raises(C.ContractError):
        stage(directory, ask, tables=_table_patch(path, value))
    assert ask.count() == 0 and not S.RunStore(directory, TABLES).load().attempts


def test_r2_a_corrupt_schema_is_refused_before_any_paid_call(directory, monkeypatch):
    def broken(name, directory=None):
        raise C.ContractError(f"схема {name}: не читается")

    monkeypatch.setattr(C, "load_schema", broken)
    ask = _happy()
    with pytest.raises(C.ContractError, match="схема"):
        stage(directory, ask)
    assert ask.count() == 0


def test_r2_the_retry_policy_row_after_exhaustion_is_what_the_run_ends_with(directory):
    assert C.incomplete_verdict(REAL) == C.INCOMPLETE_VERDICT == "НЕПОЛНЫЙ_ПРОГОН"
    assert C.retry_order("run-1", ["claude", "codex"]) == ["claude", "codex"]      # sha256("run-1") чётный
    assert C.retry_order("run-2", ["claude", "codex"]) == ["codex", "claude"]      # и нечётный: конкретный порядок
    assert C.retry_order("run-3", ["claude", "codex"]) == ["codex", "claude"]


# -- 3: a request carries the package and nothing beside it ---------------------------------------

def test_r2_the_blind_request_is_the_real_blind_package_and_only_the_package(directory):
    ask = _happy()
    seen = []
    original = ask.__call__

    class Spy(Asker):
        def __call__(self, critic, request):
            seen.append(request)
            return original(critic, request)

    spy = Spy({})
    spy.script, spy.calls = ask.script, ask.calls
    result = stage(directory, spy)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"
    blind = [r for r in seen if r["phase"] == "blind"]
    assert len(blind) == 2 and blind[0]["package"] == blind[1]["package"]
    for request in seen:
        assert set(request) == {"phase", "critic", "attempt", "package", "previous_rejection"}
        assert request["previous_rejection"] is None
    package = json.loads(blind[0]["package"])
    assert package["разделы"] == SECTIONS and "кандидаты" not in package and package["файлы"] == {}
    text = blind[0]["package"]
    assert "Лунтик" not in text and "Бибигон" not in text and "вариант автор" not in text   # скрытого в пакете нет


def test_r2_the_author_card_that_echoes_the_task_is_refused_by_the_blind_package(directory):
    sections = {**SECTIONS, "задача": json.dumps(proposal(ONE, "автор"), ensure_ascii=False)}
    ask = _happy()
    with pytest.raises(C.AuthorCardRefused):
        stage(directory, ask, sections=sections)
    assert ask.count() == 0


# -- 4, 5: the rejection reason travels and the comparisons arrive --------------------------------

def test_r2_the_rejection_reason_goes_into_the_retry_request_and_into_the_result(directory):
    seen = []

    def bad_then_good(request):
        seen.append(request)
        return "{не json" if request["attempt"] == 1 else good_blind("x")(request)

    ask = _happy({("codex", "blind"): [bad_then_good]})
    result = stage(directory, ask)
    assert [r["previous_rejection"] for r in seen][0] is None
    retry = seen[1]["previous_rejection"]
    assert retry and len(retry) <= C.REASON_CLIP + 1
    assert result.rejections["blind"]["codex"] == [retry] and result.rejections["blind"]["claude"] == []
    assert result.rejections["compare"] == {"claude": [], "codex": []}


def test_r2_a_long_participant_reason_is_clipped(directory):
    long_key = "ключ" * 500
    ask = _happy({("codex", "blind"): [json.dumps({**proposal(ONE, "x"), long_key: 1}), good_blind("x")]})
    result = stage(directory, ask)
    assert all(len(r) <= C.REASON_CLIP + 1 for r in result.rejections["blind"]["codex"])
    assert result.rejections["blind"]["codex"]


def test_r2_the_result_carries_both_validated_comparisons(directory):
    ask = _happy()
    result = stage(directory, ask)
    assert set(result.comparisons) == {"claude", "codex"}
    assert all(isinstance(v, C.ValidatedComparison) and v.raw["reasons"] == ["р"]
               for v in result.comparisons.values())


def test_r2_an_incomplete_result_keeps_the_valid_comparison_and_names_the_reason(directory):
    ask = _happy({("codex", "compare"): ["мусор"]})
    result = stage(directory, ask)
    assert result.verdict == "НЕПОЛНЫЙ_ПРОГОН" and set(result.comparisons) == {"claude"}
    assert "codex" in result.incomplete_reason
    assert len(result.rejections["compare"]["codex"]) == 2


# -- 6: re-entering an incomplete run ---------------------------------------------------------------

def test_r2_reentry_on_an_incomplete_run_does_not_say_finished(directory):
    stage(directory, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}))
    with pytest.raises(C.ResumeImpossible) as info:
        stage(directory, Asker({}))
    assert info.value.code == "ПРОДОЛЖИТЬ_НЕЧЕМ" and "завершена" not in str(info.value)
    assert "ResumeImpossible" in (C.run_idea_stage.__doc__ or "")


# -- 7: the shape of the caller's inputs is OUR error, the content is the author's -------------------

@pytest.mark.parametrize("name,kw", [
    ("withheld None", {"withheld": None}),
    ("withheld без второго", {"withheld": {"автор": "Лунтик"}}),
    ("withheld лишний ключ", {"withheld": {**WITHHELD, "предложенное_решение": "решение которое показано"}}),
    ("withheld не строка", {"withheld": {**WITHHELD, "автор": 5}}),
    ("withheld слишком короткое", {"withheld": {**WITHHELD, "автор": "ab"}}),
    ("sections лишний ключ", {"sections": {**SECTIONS, "что_угодно": "текст"}}),
    ("sections нет ключа", {"sections": {k: v for k, v in SECTIONS.items() if k != "задача"}}),
    ("sections не строка", {"sections": {**SECTIONS, "задача": 5}}),
    ("sections не словарь", {"sections": [("задача", "x")]}),
    ("registries не словарь", {"registries": []}),
])
def test_r2_a_wrong_shape_of_the_callers_input_is_a_contract_error(directory, name, kw):
    ask = _happy()
    with pytest.raises(C.ContractError):
        stage(directory, ask, **kw)
    assert ask.count() == 0 and not isinstance(C.ContractError("x"), C.AuthorCardRefused)


def test_r2_check_author_card_with_a_wrong_withheld_is_not_the_authors_fault():
    with pytest.raises(C.ContractError):
        C.check_author_card(proposal(ONE, "автор"), ONE, TABLES, {"автор": "Лунтик"})
    with pytest.raises(C.AuthorCardRefused):
        C.check_author_card(proposal(ONE, "автор") | {"variant": "про Лунтика рассказ"}, ONE, TABLES, WITHHELD)


@pytest.mark.parametrize("text", ["вес ≥ 3 ✓", "про Бибигона рассказ", "ключ " + "AKIA" + "IOSFODNN7EXAMPLE"])
def test_r2_the_content_of_criteria_stays_the_authors_refusal(directory, text):
    ask = _happy()
    with pytest.raises(C.AuthorCardRefused):
        stage(directory, ask, criteria=[{"id": "К1", "текст": text, "обязательный": True}])
    assert ask.count() == 0


# -- 8: a changed input on resume does not close the run ------------------------------------------------

def test_r2_a_changed_withheld_on_resume_is_refused_and_the_run_stays_fit_for_the_original_input(directory):
    class Boom(Exception):
        pass

    def boom(_request):
        raise Boom

    with pytest.raises(Boom):
        stage(directory, _happy({("codex", "compare"): [boom]}))
    ask = _happy()
    with pytest.raises(C.ContractError, match="вход стадии"):
        stage(directory, ask, withheld={"автор": "Колобок", "второй_критик": "Бибигон"})
    assert ask.count() == 0 and S.RunStore(directory, TABLES).load().state == "идёт_круг"
    result = stage(directory, _happy())
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"


# -- 9: criterion ids ------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["İ", "ԁ1", "ɡ1", "Ѵ", "Κ1", "ａ", "К 1", "К1\n", "К1​", "ß"])
def test_r2_ids_outside_the_closed_alphabet_are_refused(bad):
    with pytest.raises(C.AuthorCardRefused, match="алфавита"):
        C.validate_criteria([{"id": bad, "текст": "т", "обязательный": True}])


@pytest.mark.parametrize("first,second", [("I1", "l1"), ("O1", "01"), ("К.1", "K.1"), ("a-I", "a-1")])
def test_r2_look_alike_ids_fold_by_the_one_skeleton_function(first, second):
    rows = [{"id": first, "текст": "т", "обязательный": True}, {"id": second, "текст": "т", "обязательный": False}]
    with pytest.raises(C.AuthorCardRefused, match="свёртки"):
        C.validate_criteria(rows)
    assert C.fold_identifier(first) == C.fold_identifier(second) == X.fold_identifier(first)


def test_r2_separators_stay_distinct_ids_rn_m_is_a_known_residual():
    rows = [{"id": i, "текст": "т", "обязательный": n == 0} for n, i in enumerate(["A-B", "A_B", "A.B", "AB"])]
    assert len(C.validate_criteria(rows)) == 4
    rows = [{"id": i, "текст": "т", "обязательный": n == 0} for n, i in enumerate(["rn", "m"])]
    assert len(C.validate_criteria(rows)) == 2          # DECIDED: не ловится, ID не граница безопасности


# -- 10, 11: one source of strictness, and the retry policy is read ---------------------------------------

def test_r2_outcome_rules_and_abort_limit_delegate_to_the_tables_checks(monkeypatch):
    calls = []
    for name in ("_check_idea_outcomes", "_check_idea_execution"):
        original = getattr(T.Tables, name)
        monkeypatch.setattr(T.Tables, name, lambda self, o=original, n=name: (calls.append(n), o(self))[1])
    C.outcome_rules(REAL)
    C.abort_limit(REAL)
    assert calls == ["_check_idea_outcomes", "_check_idea_execution"]


def test_r2_a_row_the_code_reads_changes_the_behaviour(directory):
    spend = _table_patch(("vocabulary", "повтор_невалидного_ответа", "тратит_бюджет"), False)
    with pytest.raises(C.ContractError, match="тратит_бюджет"):
        C.retry_budget(spend)
    order = _table_patch(("vocabulary", "повтор_невалидного_ответа", "порядок"), "по_алфавиту")
    with pytest.raises(C.ContractError, match="порядок"):
        C.retry_budget(order)
    after = _table_patch(("vocabulary", "повтор_невалидного_ответа", "после_исчерпания"), "РЕШЕНИЕ_АНТОНА")
    result = stage(directory, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}), tables=after)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"          # итог исчерпания — из строки таблицы, а не из константы


# -- 12: one function of card bytes -------------------------------------------------------------------------

def test_r2_card_bytes_is_what_is_checked_and_what_is_stored(directory):
    card = proposal(ONE, "z")
    assert C.card_bytes(card) == X.canonical_json(C.normalize_card(card))
    stage(directory, _happy())
    for candidate in S.RunStore(directory, TABLES).load().idea_candidates:
        assert candidate.canonical_bytes == C.card_bytes(json.loads(candidate.canonical_bytes))
        X.check_candidate_card(candidate.canonical_bytes, "идея", TABLES, WITHHELD)


# -- 13: the OK of the previous round does not open the exit -------------------------------------------------

def test_r2_an_ok_after_a_new_round_start_does_not_open_the_exit_without_a_new_verdict(directory):
    _done(directory)
    with locked(directory) as store:
        store.start_round(2)
        store.set_flag(C.ANTON_OK_FLAG)
        with pytest.raises(C.AntonOkRequired, match="прошлого круга"):
            C.leave_idea_stage(store)


# -- 14: a corrupt journal is ContractError --------------------------------------------------------------------

def test_r2_an_unknown_attempt_status_is_a_contract_error():
    state = S.RunState(run_id="r", stage="идея")
    state.attempts[("r", C.BLIND_STAGE, 1, "claude", 1)] = S.Attempt(("r", C.BLIND_STAGE, 1, "claude", 1), "выдумка", "t")
    with pytest.raises(C.ContractError, match="журнал попыток"):
        C._split_attempts(state, TABLES, C.BLIND_STAGE, 1, "claude")


def test_r2_a_set_without_the_author_is_a_contract_error(directory):
    with locked(directory) as store:
        store.assign_idea_candidates([S.IdeaCandidate(f"cand_{i}", s, C.card_bytes(proposal(ONE, str(i))))
                                      for i, s in enumerate(("claude", "codex", "x"))])
    with pytest.raises(C.ContractError, match="авторских"):
        stage(directory, _happy())


def test_r2_ids_in_exception_texts_are_clipped():
    many = [f"id{i}" + "я" * 200 for i in range(50)]
    assert len(C._listed(many)) < 600
    with pytest.raises(C.ContractError) as info:
        C.validate_comparison({}, candidate_ids=many, criteria=PARSED_ONE, tables=TABLES)
    assert len(str(info.value)) < 700


def test_r2_a_new_id_equal_to_the_sentinel_is_our_breakage(directory):
    ids = iter([SENTINEL, "cand_b", "cand_c"])
    with pytest.raises(C.ContractError, match="равный"):
        stage(directory, _happy(), new_id=ids.__next__)


def test_r2_the_card_limit_is_the_section_limit_exactly_everywhere(tmp_path):
    limit = REAL.vocabulary["пакет"]["предел_раздела_байт"]
    assert limit < REAL.vocabulary["пакет"]["предел_файла_байт"]            # the number the code reads is the smaller one

    def sized(size):
        card = proposal(ONE, "z")
        base = len(X.canonical_json(C.normalize_card(card)))
        card["variant"] += "я" * ((size - base) // 2) + ("x" if (size - base) % 2 else "")
        assert len(X.canonical_json(C.normalize_card(card))) == size
        return card

    at, over = sized(limit), sized(limit + 1)

    def raw_sized(size):                                                    # the validator counts the answer as sent
        card = proposal(ONE, "z")
        card["variant"] += "я" * ((size - len(X.canonical_json(card))) // 2)
        card["variant"] += "x" * (size - len(X.canonical_json(card)))
        assert len(X.canonical_json(card)) == size
        return card

    assert C.validate_proposal(raw_sized(limit), PARSED_ONE, REAL)          # the answer validator
    with pytest.raises(C.AnswerRejected):
        C.validate_proposal(raw_sized(limit + 1), PARSED_ONE, REAL)
    C.fits_package(at, REAL, WITHHELD)                                      # the second package, one card
    with pytest.raises(C.AnswerRejected):
        C.fits_package(over, REAL, WITHHELD)
    ask = Asker({})                                                         # the author's card: refused before any call
    with pytest.raises(C.AuthorCardRefused):
        stage(started(tmp_path / "over", "run-o"), ask, author_card=over)
    assert ask.count() == 0


# -- critic round 1: criteria in the blind package, shape of saved answers, a foreign stage ------------

def _crit(identifier, text="работает"):
    return [{"id": identifier, "текст": text, "обязательный": True}]


def _answering_from_the_package(seen=None):
    """`ask` that knows only its request: the cards and comparisons are built from the package's criteria."""
    def blind(tag):
        def build(request):
            package = json.loads(request["package"])
            if seen is not None:
                seen.append(package)
            return json.dumps(proposal(package["критерии"], tag), ensure_ascii=False)
        return build
    compare = _from_request(ALL_PASS, "cand_a")
    return Asker({("claude", "blind"): [blind("c")], ("codex", "blind"): [blind("x")],
                  ("claude", "compare"): [compare], ("codex", "compare"): [compare]})


def test_critic1_the_first_package_carries_the_criteria_and_the_critic_answers_by_it(tmp_path):
    firsts = {}
    for name in ("BASE_A", "BASE_B"):
        seen = []
        directory = started(tmp_path / name, "run-" + name)
        ask = _answering_from_the_package(seen)
        result = stage(directory, ask, criteria=_crit(name), author_card=proposal(_crit(name), "автор"))
        assert result.verdict == "РЕШЕНИЕ_АНТОНА" and ask.count() == 4
        assert seen[0]["критерии"] == [{"id": name, "text": "работает", "mandatory": True}]
        firsts[name] = json.dumps(seen[0], sort_keys=True)
    assert firsts["BASE_A"] != firsts["BASE_B"]                           # same text, different IDs: different package


_QUOTED = "построить всё на очереди сообщений и воркерах"


@pytest.mark.parametrize("text", ["вес ≥ 3 ✓", "нуль\u200bширина", "про Бибигона рассказ",
                                  "ключ " + "AKIA" + "IOSFODNN7EXAMPLE", "пароль " + "pass" + "word = 'hunter2hunter2'"])
def test_critic1_a_bad_criterion_is_refused_before_any_call_and_any_write(directory, text):
    # these are caught already by `check_comparison_inputs`; the blind package repeats the judgement
    before, ask = _journal(directory), _answering_from_the_package()
    with pytest.raises(C.AuthorCardRefused):
        stage(directory, ask, criteria=_crit("К1", text))
    assert ask.count() == 0 and _journal(directory) == before


def test_critic1_the_blind_package_refuses_a_criterion_quoting_the_authors_card(directory):
    """Only the blind package sees the author's card among the hidden: this refusal is its own."""
    before, ask = _journal(directory), _answering_from_the_package()
    card = {**proposal(ONE, "автор"), "variant": _QUOTED}
    with pytest.raises(C.AuthorCardRefused, match="слепой пакет не принят"):
        stage(directory, ask, criteria=_crit("К1", _QUOTED), author_card=card)
    assert ask.count() == 0 and _journal(directory) == before


def test_critic1_a_criterion_id_changed_on_resume_is_caught_by_the_pin(directory):
    class Boom(Exception):
        pass

    def boom(_request):
        raise Boom

    with pytest.raises(Boom):
        stage(directory, _happy({("claude", "blind"): [boom]}), criteria=_crit("BASE_A"),
              author_card=proposal(_crit("BASE_A"), "автор"))
    ask = _answering_from_the_package()
    with pytest.raises(C.ContractError, match="вход стадии"):          # the criteria are in the input print
        stage(directory, ask, criteria=_crit("BASE_B"), author_card=proposal(_crit("BASE_B"), "автор"))
    assert ask.count() == 0


def _journal(directory):
    return (Path(directory) / S.JOURNAL).read_bytes()


class _Boom(Exception):
    pass


def _boom(_request):
    raise _Boom


def _state(directory):
    return S.RunStore(directory, TABLES).load()


def _compare_key(state, critic, number=1):
    return (state.run_id, C.COMPARE_STAGE, 1, critic, number)


def _tamper(directory, mutate):
    """Rewrite the journal entry by entry through `mutate(entry) -> entry` (same line format)."""
    path = Path(directory) / S.JOURNAL
    lines = [json.dumps(mutate(json.loads(line)), ensure_ascii=False, sort_keys=True)
             for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _crash_in_compare_run(directory):
    """Both blind answers and claude's comparison are in the journal; codex's comparison call dies."""
    with pytest.raises(_Boom):
        stage(directory, _happy({("codex", "compare"): [_boom]}))


def _answer_file(directory, critic, stage_name, number=1):
    state = _state(directory)
    receipt = state.attempts[(state.run_id, stage_name, 1, critic, number)].receipt
    return Path(directory) / TABLES.vocabulary["ответ_критика"]["каталог"] / receipt.sha256


@pytest.mark.parametrize("name", ["saved_proposals", "saved_comparisons"])
def test_critic1_saved_answers_of_a_wrong_shape_are_a_contract_error_before_any_write(directory, name):
    """БУ-14: no parameter carries an answer into the stage (it was `saved_*`): handing one in is a TypeError
    with the journal untouched. The name of this test is pinned by a finding; what it stands for changed."""
    before, ask = _journal(directory), _happy()
    with pytest.raises(TypeError):
        stage(directory, ask, **{name: {"claude": json.dumps(proposal(ONE, "с"))}})
    assert _journal(directory) == before and ask.count() == 0
    assert stage(directory, ask).verdict == "РЕШЕНИЕ_АНТОНА"                # positive control


@pytest.mark.parametrize("foreign", ["план", "ревью"])
def test_critic1_a_run_of_another_stage_is_refused_before_any_write(tmp_path, foreign):
    directory = started_of(tmp_path / "run", "run-f", foreign)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="другой стадии"):
        stage(directory, ask)
    assert _journal(directory) == before and ask.count() == 0
    assert stage(started(tmp_path / "idea", "run-i"), _happy()).verdict == "РЕШЕНИЕ_АНТОНА"   # positive control


def started_of(path, run_id, stage_name):
    S.RunStore(path, TABLES).create(run_id, stage_name)
    with locked(path) as store:
        store.submit("start")
    return path


# -- critic round 1, review: content of the saved answers, the window, the order, the states ------------

def _refused_with_no_trace(directory, kw):
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError):
        stage(directory, ask, **kw)
    assert _journal(directory) == before and ask.count() == 0


@pytest.mark.parametrize("name", ["подменён другим ответом", "обрезан", "удалён"])
def test_critic1_a_damaged_answer_file_is_refused_before_the_first_write(directory, name):
    """БУ-11/14: the bytes behind a receipt are checked against its hash and length; nothing else stands in."""
    _crash_in_compare_run(directory)
    blob = _answer_file(directory, "claude", C.COMPARE_STAGE)
    original = blob.read_bytes()
    if name == "удалён":
        blob.unlink()
    else:
        blob.write_bytes(json.dumps(proposal(ONE, "чужой")).encode() if name.startswith("подменён") else original[:-3])
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="файл ответа|файла ответа"):
        stage(directory, ask)
    assert _journal(directory) == before and ask.count() == 0
    blob.write_bytes(original)                                          # positive control: the file back, the run goes on
    assert stage(directory, _happy()).verdict == "РЕШЕНИЕ_АНТОНА"


def test_critic1_the_input_print_is_written_before_the_event_so_a_crash_between_them_admits_no_other_input(directory):
    class Window(Exception):
        pass

    with S.RunLock(directory) as lock:
        real = S.RunStore(directory, TABLES, _lock=lock)

        class Failing:
            def __getattr__(self, name):
                return getattr(real, name)

            def record_event(self, *a, **k):
                raise Window

        with pytest.raises(Window):
            C.run_idea_stage(Failing(), ask=_happy(), criteria=_crit("BASE_A"),
                             author_card=proposal(_crit("BASE_A"), "автор"), sections=SECTIONS, withheld=WITHHELD,
                             new_id=fixed_ids(), shuffle=lambda o: None, tables=TABLES)
    assert [p.event for p in S.RunStore(directory, TABLES).load().pins] == [C.PIN_INPUT]
    ask = _answering_from_the_package()
    with pytest.raises(C.ContractError, match="вход стадии"):
        stage(directory, ask, criteria=_crit("BASE_B"), author_card=proposal(_crit("BASE_B"), "автор"))
    assert ask.count() == 0
    result = stage(directory, _answering_from_the_package(), criteria=_crit("BASE_A"),
                   author_card=proposal(_crit("BASE_A"), "автор"))
    assert result.verdict == "РЕШЕНИЕ_АНТОНА"


def test_critic1_the_order_of_criteria_does_not_change_the_packages(tmp_path):
    rows = [{"id": i, "текст": "т " + i, "обязательный": True} for i in ("К1", "К2", "К3")]
    hashes, empty = [], {"решения": [], "области": [], "журнал_доказательств": []}
    for order in (rows, rows[::-1]):
        view = [{"id": r["id"], "text": r["текст"], "mandatory": r["обязательный"]} for r in order]
        blind = X.build_package(tmp_path, [], SECTIONS, empty, "идея", blind=True, tables=TABLES,
                                withheld={**WITHHELD, "предложенное_решение": "решение которое скрыто от критика"},
                                criteria=view)
        second = X.build_comparison_package(SECTIONS, empty, "идея", [S.IdeaCandidate("a", "автор", b"{}")], (0,),
                                            tables=TABLES, withheld=WITHHELD, criteria=view)
        hashes.append((blind.hash, second.hash))
    assert hashes[0] == hashes[1]


def test_critic1_the_stage_is_judged_before_the_criteria(tmp_path):
    directory = started_of(tmp_path / "run", "run-f", "план")
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="другой стадии") as info:
        stage(directory, ask, criteria=_crit("К1", "ключ " + "AKIA" + "IOSFODNN7EXAMPLE"))
    assert not isinstance(info.value, C.AuthorCardRefused)
    assert _journal(directory) == before and ask.count() == 0


def test_critic1_not_started_incomplete_and_finished_runs_are_refused_with_the_journal_unchanged(tmp_path):
    created = tmp_path / "created"
    S.RunStore(created, TABLES).create("run-c", "идея")
    incomplete = started(tmp_path / "inc", "run-inc")
    stage(incomplete, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}))
    finished = started(tmp_path / "fin", "run-fin")
    stage(finished, _happy())
    for directory, text in ((created, "не запущен"), (finished, "стадия завершена")):
        before, ask = _journal(directory), _happy()
        with pytest.raises(C.ContractError, match=text):
            stage(directory, ask)
        assert _journal(directory) == before and ask.count() == 0
    before, ask = _journal(incomplete), _happy()                          # БУ-13: an exhausted run is a named outcome
    with pytest.raises(C.ResumeImpossible, match="ПРОДОЛЖИТЬ_НЕЧЕМ"):
        stage(incomplete, ask)
    assert _journal(incomplete) == before and ask.count() == 0


# ==========================================================================
# БУ, часть 1: байты ответов, закрепление, продолжение (БУ-11 … БУ-14)
# ==========================================================================

def _events(directory, name):
    return [e for e in (json.loads(line) for line in _journal(directory).decode("utf-8").splitlines() if line.strip())
            if e.get("event") == name]


def _spy(inner, log):
    """`ask` that remembers what it handed back, per (critic, phase, attempt)."""
    def ask(critic, request):
        raw = inner(critic, request)
        log[(critic, request["phase"], request["attempt"])] = raw
        return raw
    return ask


def _supervisor_marks_incomplete(directory):
    """Whoever supervises a broken run closes the round as incomplete (a legal `вердикт` of the table)."""
    with locked(directory) as store:
        return store.record_event("вердикт", {"verdict": C.INCOMPLETE_VERDICT})


# -- БУ-11: the bytes and the result of the check stay with the attempt -------------------------------------

def test_bu11_the_exact_bytes_of_every_answer_and_the_result_of_its_check_are_kept(directory):
    log = {}
    ask = Asker({("claude", "blind"): ["мусор не json", good_blind("c")], ("codex", "blind"): [good_blind("x")],
                 ("claude", "compare"): [_from_request(ALL_PASS, "cand_a")],
                 ("codex", "compare"): [_from_request(ALL_PASS, "cand_a")]})
    assert stage(directory, _spy(ask, log)).verdict == "РЕШЕНИЕ_АНТОНА"
    cold = _state(directory)                                           # a fresh store: the restart
    stages = {"blind": C.BLIND_STAGE, "compare": C.COMPARE_STAGE}
    store = S.RunStore(directory, TABLES)
    for (critic, phase, number), raw in log.items():
        attempt = cold.attempts[(cold.run_id, stages[phase], 1, critic, number)]
        assert store.read_answer(stages[phase], 1, critic, number) == raw.encode("utf-8")
        assert attempt.receipt.length == len(raw.encode("utf-8")) and len(attempt.receipt.question_hash) == 64
        assert attempt.validation.question_hash == attempt.receipt.question_hash
    rejected = cold.attempts[(cold.run_id, C.BLIND_STAGE, 1, "claude", 1)]
    accepted = cold.attempts[(cold.run_id, C.BLIND_STAGE, 1, "claude", 2)]
    assert store.read_answer(C.BLIND_STAGE, 1, "claude", 1) == "мусор не json".encode()    # the rejected one too
    assert rejected.validation.accepted is False and rejected.validation.reason
    assert accepted.validation.accepted is True and accepted.validation.reason == ""
    # one question for both tries of one critic; another critic is another question
    assert rejected.receipt.question_hash == accepted.receipt.question_hash
    assert rejected.receipt.question_hash != cold.attempts[(cold.run_id, C.BLIND_STAGE, 1, "codex", 1)].receipt.question_hash
    assert "мусор не json" not in _journal(directory).decode("utf-8")          # the bytes are not in the journal itself


def test_bu11_a_failure_between_the_file_and_the_journal_entry_leaves_the_attempt_uncounted(directory, monkeypatch):
    real = S.RunStore._append

    def failing(self, entry):
        if "answer" in entry:
            raise _Boom
        return real(self, entry)

    monkeypatch.setattr(S.RunStore, "_append", failing)
    ask = _happy()
    with pytest.raises(_Boom):
        stage(directory, ask)
    monkeypatch.undo()
    state = _state(directory)
    key = (state.run_id, C.BLIND_STAGE, 1, "claude", 1)
    assert state.attempts[key].status == "запущена" and state.attempts[key].receipt is None
    answers = Path(directory) / TABLES.vocabulary["ответ_критика"]["каталог"]
    assert len(list(answers.iterdir())) == 1                          # the bytes are on the disk, the journal does not know
    answered, aborted = C._split_attempts(state, TABLES, C.BLIND_STAGE, 1, "claude")
    assert answered == [] and len(aborted) == 1                        # the budget is not spent
    again = _happy()                                                   # positive control: without the failure it is counted
    assert stage(directory, again).verdict == "РЕШЕНИЕ_АНТОНА"
    assert _state(directory).attempts[key].possible_duplicate and ("claude", "blind", 2) in again.calls


def test_bu11_a_failure_writing_the_file_leaves_no_trace_of_a_received_answer(directory, monkeypatch):
    def failing(self, raw):
        raise _Boom

    monkeypatch.setattr(S.RunStore, "_store_blob", failing)
    with pytest.raises(_Boom):
        stage(directory, _happy())
    monkeypatch.undo()
    state = _state(directory)
    assert all(a.receipt is None and a.status == "запущена" for a in state.attempts.values())
    assert not (Path(directory) / TABLES.vocabulary["ответ_критика"]["каталог"]).exists()


def test_bu11_a_reason_of_a_rejection_survives_a_restart_and_travels_into_the_retry(directory):
    ask = _happy({("claude", "blind"): ["мусор", _boom]})
    with pytest.raises(_Boom):
        stage(directory, ask)
    state = _state(directory)
    reason = state.attempts[(state.run_id, C.BLIND_STAGE, 1, "claude", 1)].validation.reason
    assert reason and len(reason) <= C.REASON_CLIP + 1
    seen = []
    again = _happy({("claude", "blind"): [lambda request: seen.append(request["previous_rejection"]) or good_blind("c")(request)]})
    assert stage(directory, again).verdict == "РЕШЕНИЕ_АНТОНА"
    assert seen == [reason]                                            # the retry is asked with the recorded reason


def test_bu11_the_reason_limit_comes_from_the_table():
    assert C.REASON_CLIP == REAL.vocabulary["ответ_критика"]["предел_причины"]


# -- БУ-12: the pin is a journal event --------------------------------------------------------------------

def test_bu12_the_input_and_the_package_are_pinned_before_the_first_comparison_call(directory):
    seen_at_call = []

    def probe(request):
        seen_at_call.append([e["event"] for e in map(json.loads, _journal(directory).decode().splitlines())
                             if e.get("kind") == "event"])
        raise _Boom

    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "compare"): [probe]}))
    assert seen_at_call[0].index("вход_закреплён") < seen_at_call[0].index("пакет_собран") < seen_at_call[0].index("пакет_закреплён")
    state = _state(directory)
    pins = {p.event: p for p in state.pins}
    assert set(pins) == {C.PIN_INPUT, C.PIN_PACKAGE} and all(p.round_number == 1 for p in pins.values())
    assert len(pins[C.PIN_PACKAGE].content_hash) == 64 and pins[C.PIN_PACKAGE].hidden_hash == C.digest(
        C.canonical_json(WITHHELD))
    assert pins[C.PIN_PACKAGE].revision == pins[C.PIN_INPUT].revision
    assert not [f for f in state.flags if f.startswith(("пакет_сравнения:", "вход_стадии_идея:"))]


def test_bu12_a_repeated_pin_of_the_same_package_makes_no_second_event(directory):
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "compare"): [_boom]}))
    first = [_events(directory, C.PIN_INPUT), _events(directory, C.PIN_PACKAGE)]
    assert [len(x) for x in first] == [1, 1]
    assert stage(directory, _happy()).verdict == "РЕШЕНИЕ_АНТОНА"
    assert [_events(directory, C.PIN_INPUT), _events(directory, C.PIN_PACKAGE)] == first


def test_bu12_another_package_in_the_same_round_is_refused_and_the_old_pin_is_not_rewritten(directory):
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "compare"): [_boom]}))
    before = _journal(directory)
    ask = _happy()
    with pytest.raises(C.ContractError, match="вход стадии"):
        stage(directory, ask, sections={**SECTIONS, "задача": "совсем другая задача"})
    assert ask.count() == 0 and _journal(directory) == before
    state = _state(directory)
    with locked(directory) as store:                                    # the package pin itself, asked for another package
        with pytest.raises(S.Refusal) as refused:
            store.pin(C.PIN_PACKAGE, round_number=1, revision=state.pins[0].revision, content_hash="1" * 64,
                      hidden_hash=state.pins[1].hidden_hash)
    assert refused.value.code == "КОНФЛИКТ_ВХОДА" and _journal(directory) == before


# -- БУ-13: an incomplete run goes on in the same run and round -----------------------------------------------

def test_bu13_a_broken_run_goes_on_with_its_cards_pins_answers_and_spent_attempts(directory):
    _crash_in_compare_run(directory)
    marked = _supervisor_marks_incomplete(directory)
    assert marked.state == "неполный"
    before = _state(directory)
    ask = _happy()
    result = stage(directory, ask)
    assert result.verdict == "РЕШЕНИЕ_АНТОНА" and result.run_state == "ждёт_Антона"
    after = _state(directory)
    assert after.run_id == before.run_id and after.round_number == before.round_number
    assert after.idea_candidates == before.idea_candidates and after.pins == before.pins    # the same cards, the same pins
    assert [c for c in ask.calls if c[0] == "claude"] == []                                  # valid answers are not asked again
    assert ask.calls == [("codex", "compare", 2)]                                           # codex's cut-off call stays spent
    assert after.attempts[_compare_key(after, "codex", 1)].possible_duplicate
    names = [(e.get("event") or e.get("operation"), (e.get("conditions") or {}))
             for e in map(json.loads, _journal(directory).decode().splitlines())
             if e.get("kind") in ("event", "operation")][-3:]
    assert names == [("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"}), ("resume", {"budget_remains": True, "input_can_progress": True}),
                     ("вердикт", {"verdict": "РЕШЕНИЕ_АНТОНА"})]


def test_bu13_spent_attempts_are_not_reset_and_the_rejection_is_remembered(directory):
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "blind"): ["мусор", _boom]}))
    _supervisor_marks_incomplete(directory)
    seen = []

    def garbage_again(request):
        seen.append(request["previous_rejection"])
        return "опять мусор"

    ask = _happy({("claude", "blind"): [garbage_again]})
    result = stage(directory, ask)
    # one answer spent (rejected), one call cut off: the third call is the last retry, and it is garbage again
    assert [c for c in ask.calls if c[0] == "claude"] == [("claude", "blind", 3)]
    assert seen and seen[0]
    assert (result.verdict, result.run_state) == ("НЕПОЛНЫЙ_ПРОГОН", "неполный")
    state = _state(directory)
    assert len([k for k in state.attempts if k[3] == "claude" and k[1] == C.BLIND_STAGE]) == 3
    again = _happy()
    with pytest.raises(C.ResumeImpossible):                              # the spent attempts really are spent
        stage(directory, again)
    assert again.count() == 0


def test_bu13_an_exhausted_budget_is_a_named_outcome_and_changes_nothing(directory):
    stage(directory, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}))
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ResumeImpossible) as info:
        stage(directory, ask)
    assert info.value.code == "ПРОДОЛЖИТЬ_НЕЧЕМ" and info.value.code in REAL.vocabulary["коды_отказа"]
    assert ask.count() == 0 and _journal(directory) == before and _state(directory).state == "неполный"


def test_bu13_calls_cut_off_up_to_the_limit_leave_nothing_to_continue_with(tmp_path):
    directory = _new_run(tmp_path / "run")
    for _ in range(C.abort_limit(TABLES)):
        with pytest.raises(_Boom):
            stage(directory, _happy({("claude", "blind"): [_boom]}))
    assert stage(directory, _happy()).run_state == "неполный"            # the loop gives up on claude
    before = _journal(directory)
    with pytest.raises(C.ResumeImpossible, match="ПРОДОЛЖИТЬ_НЕЧЕМ"):
        stage(directory, _happy())
    assert _journal(directory) == before


def test_bu13_a_substituted_input_is_refused_before_any_write_or_call_and_the_right_one_goes_on(directory):
    _crash_in_compare_run(directory)
    _supervisor_marks_incomplete(directory)
    before, ask = _journal(directory), _happy()
    for change in ({"withheld": {"автор": "Колобок", "второй_критик": "Бибигон"}},
                   {"sections": {**SECTIONS, "задача": "другая задача"}},
                   {"author_card": proposal(ONE, "другой автор")},
                   {"criteria": [{"id": "К1", "текст": "иначе", "обязательный": True}]}):
        with pytest.raises(C.ContractError, match="вход стадии"):
            stage(directory, ask, **change)
        assert ask.count() == 0 and _journal(directory) == before
    assert stage(directory, ask).verdict == "РЕШЕНИЕ_АНТОНА"              # positive control


def test_bu13_continuing_is_a_row_of_the_table_not_a_branch_of_the_code():
    refused = REAL.decide("неполный", "resume", {"budget_remains": False, "input_can_progress": True})
    allowed = REAL.decide("неполный", "resume", {"budget_remains": True, "input_can_progress": True})
    assert (allowed.to, allowed.refusal) == ("идёт_круг", None)
    assert (refused.to, refused.refusal) == ("неполный", "ПРОДОЛЖИТЬ_НЕЧЕМ")


# -- БУ-14: only what the journal received is accepted ------------------------------------------------------------

def test_bu14_a_receipt_copied_to_another_critics_attempt_is_not_accepted(directory):
    _crash_in_compare_run(directory)
    state = _state(directory)
    claude, codex = _compare_key(state, "claude"), _compare_key(state, "codex")
    receipt = next(e["answer"] for e in map(json.loads, _journal(directory).decode().splitlines())
                   if e.get("kind") == "attempt" and tuple(e["key"]) == claude and "answer" in e)
    _tamper(directory, lambda e: {**e, "status": "получена", "answer": receipt}
            if e.get("kind") == "attempt" and tuple(e["key"]) == codex and e["status"] == "запущена" else e)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="другой вопрос"):
        stage(directory, ask)                                              # the question names the critic
    assert ask.count() == 0 and _journal(directory) == before


def test_bu14_a_receipt_pointing_at_another_valid_answer_is_not_accepted(directory):
    _crash_in_compare_run(directory)
    state = _state(directory)
    key = _compare_key(state, "claude")
    other = _answer_file(directory, "claude", C.BLIND_STAGE).name         # claude's own blind card: a real, stored answer
    blob = (Path(directory) / TABLES.vocabulary["ответ_критика"]["каталог"] / other).read_bytes()

    def swap(entry):
        if entry.get("kind") == "attempt" and tuple(entry["key"]) == key and "answer" in entry:
            return {**entry, "answer": {**entry["answer"], "sha256": other, "length": len(blob)}}
        return entry
    _tamper(directory, swap)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="проверен в журнале иначе"):
        stage(directory, ask)                                              # the card is not a comparison of this set
    assert ask.count() == 0 and _journal(directory) == before


def test_bu14_the_stage_has_no_door_for_a_caller_supplied_answer_or_hash():
    import inspect
    names = set(inspect.signature(C.run_idea_stage).parameters)
    assert not {n for n in names if "saved" in n or "answer" in n or "hash" in n}
    assert "saved_proposals" not in (C.run_idea_stage.__doc__ or "").split("Errors:")[0]


# -- БУ-13 доработка: условия считает журнал, продолжение должно вести вперёд ----------------------------------

def _gave_up_on_claude_blind(tmp_path):
    directory = _new_run(tmp_path / "run")
    for _ in range(C.abort_limit(TABLES)):
        with pytest.raises(_Boom):
            stage(directory, _happy({("claude", "blind"): [_boom]}))
    assert stage(directory, _happy()).run_state == "неполный"
    return directory


def test_bu13_a_forged_condition_on_the_exhausted_run_is_refused_and_changes_nothing(directory):
    stage(directory, Asker({("claude", "blind"): ["x"], ("codex", "blind"): ["y"]}))
    before = _journal(directory)
    with locked(directory) as store:
        for forged in ({"budget_remains": True}, {"budget_remains": True, "input_can_progress": True}):
            with pytest.raises(S.StateError):
                store.submit("resume", forged, body={"reason": "обход"})
    assert _journal(directory) == before and _state(directory).state == "неполный"
    with locked(directory) as store:                                  # honest: the journal's count says "nothing to go on with"
        refused = store.submit("resume", body={"reason": "честно"})
        again = store.submit("resume", body={"reason": "честно"})
    assert refused.refusal == "ПРОДОЛЖИТЬ_НЕЧЕМ" and again == refused         # one position, one operation
    assert _state(directory).state == "неполный"
    assert len([e for e in map(json.loads, _journal(directory).decode().splitlines())
                if e.get("operation") == "resume"]) == 1


def _two_garbage_the_second_unjudged(directory, second, monkeypatch):
    """claude's blind answers: the first judged invalid, the second received but never judged (the process died)."""
    real = S.RunStore.record_validation
    calls = {"n": 0}

    def dying(self, *args, **kwargs):
        calls["n"] += args[2] == "claude"                          # (stage, round, critic, attempt, ...)
        if calls["n"] == 2:
            raise _Boom
        return real(self, *args, **kwargs)

    monkeypatch.setattr(S.RunStore, "record_validation", dying)
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "blind"): ["мусор", second]}))
    monkeypatch.undo()
    _supervisor_marks_incomplete(directory)


def test_bu13_the_last_received_but_unjudged_answer_counts_only_if_it_is_valid(tmp_path, monkeypatch):
    bad = _new_run(tmp_path / "bad")
    _two_garbage_the_second_unjudged(bad, "опять мусор", monkeypatch)
    before, ask = _journal(bad), _happy()
    with pytest.raises(C.ResumeImpossible, match="ПРОДОЛЖИТЬ_НЕЧЕМ"):          # it is invalid, the retries are used up
        stage(bad, ask)
    assert ask.count() == 0 and _journal(bad) == before
    good = _new_run(tmp_path / "good")                                          # positive control: the same, but valid
    _two_garbage_the_second_unjudged(good, good_blind("c"), monkeypatch)
    ask = _happy()
    assert stage(good, ask).verdict == "РЕШЕНИЕ_АНТОНА"
    assert [c for c in ask.calls if c[:2] == ("claude", "blind")] == []         # judged from the journal, not asked again


def test_bu13_a_run_that_cannot_build_its_input_does_not_resume_forever(tmp_path):
    directory = _new_run(tmp_path / "run")
    texts = [X.canonical_json(C.normalize_card(_edit(_AUTHOR, variant="значение ≥ 5"))),
             X.canonical_json(C.normalize_card(_CARD_C)), X.canonical_json(C.normalize_card(_CARD_X))]
    with _locked(directory) as store:
        store.assign_idea_candidates([S.IdeaCandidate(f"cand_{i}", src, text)
                                      for i, (src, text) in enumerate(zip(("автор", "claude", "codex"), texts))])
    first = _run(directory, _Ask({}), _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
    assert first.run_state == "неполный" and _state(directory).incomplete_cause == S.CAUSE_INPUT_NOT_BUILT
    before = _journal(directory)
    for _ in range(2):                                                          # however many times it is entered
        ask = _Ask({})
        with pytest.raises(C.ResumeImpossible, match="НУЖНА_КОРРЕКЦИЯ_ВХОДА"):
            _run(directory, ask, _INJ, author_card=_AUTHOR, sections=_INJ["разделы_пакета_эталон"])
        assert ask.count() == 0 and _journal(directory) == before


def test_bu13_a_package_too_big_for_the_set_is_the_same_named_outcome(tmp_path):
    small = dict(REAL.vocabulary["пакет"], предел_пакета_байт=2400)
    tables = _table_patch(("vocabulary", "пакет"), small)
    pad = "п" * 120
    directory = started(tmp_path / "big", "run-big")
    options = dict(tables=tables, author_card={**proposal(ONE, "а"), "variant": pad})
    result = stage(directory, Asker({("claude", "blind"): [good_blind_with(pad)], ("codex", "blind"): [good_blind_with(pad)]}),
                   **options)
    assert result.run_state == "неполный" and "превышение_размера" in result.incomplete_reason
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ResumeImpossible, match="НУЖНА_КОРРЕКЦИЯ_ВХОДА"):
        stage(directory, ask, **options)
    assert ask.count() == 0 and _journal(directory) == before


def test_bu13_a_new_round_of_an_incomplete_run_without_a_changed_input_is_a_named_refusal_before_any_write(directory):
    _crash_in_compare_run(directory)
    _supervisor_marks_incomplete(directory)
    with locked(directory) as store:
        store.start_round(2)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ResumeImpossible, match="НУЖНА_КОРРЕКЦИЯ_ВХОДА") as info:
        stage(directory, ask)
    assert "коррекция" in str(info.value) and ask.count() == 0 and _journal(directory) == before
    assert len([p for p in _state(directory).pins if p.event == C.PIN_INPUT]) == 1      # the spent budget was not renewed


def test_bu13_an_incomplete_run_in_the_same_round_returns_its_pin_without_a_write_before_the_resume(directory):
    _crash_in_compare_run(directory)
    _supervisor_marks_incomplete(directory)
    before_pins = _state(directory).pins
    ask = _happy()
    assert stage(directory, ask).verdict == "РЕШЕНИЕ_АНТОНА"
    assert _state(directory).pins == before_pins


# -- БУ-11 доработка: размер ответа, причина из журнала -----------------------------------------------------------

def test_bu11_an_over_long_answer_is_cut_to_the_limit_plus_one_and_refused_by_its_length(directory):
    limit = TABLES.vocabulary["ответ_критика"]["предел_байтов"]
    huge = "{" + " " * (limit * 3)
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "blind"): [huge, _boom]}))
    state = _state(directory)
    attempt = state.attempts[(state.run_id, C.BLIND_STAGE, 1, "claude", 1)]
    assert attempt.receipt.length == limit + 1 and attempt.validation.accepted is False
    assert "длиннее" in attempt.validation.reason
    assert len(_answer_file(directory, "claude", C.BLIND_STAGE).read_bytes()) == limit + 1
    ok = _happy()                                                          # positive control: the budget goes on as for any bad answer
    assert stage(directory, ok).verdict == "РЕШЕНИЕ_АНТОНА"


def test_bu11_the_reason_that_travels_on_is_the_recorded_one_and_a_divergence_is_our_breakage(directory):
    with pytest.raises(_Boom):
        stage(directory, _happy({("claude", "blind"): ["мусор", _boom]}))
    state = _state(directory)
    key = (state.run_id, C.BLIND_STAGE, 1, "claude", 1)
    recorded = state.attempts[key].validation.reason
    _tamper(directory, lambda e: {**e, "reason": "записано иначе"}
            if e.get("kind") == "answer_checked" and tuple(e["key"]) == key else e)
    before, ask = _journal(directory), _happy()
    with pytest.raises(C.ContractError, match="расходится с записанной"):
        stage(directory, ask)
    assert ask.count() == 0 and _journal(directory) == before
    _tamper(directory, lambda e: {**e, "reason": recorded}
            if e.get("kind") == "answer_checked" and tuple(e["key"]) == key else e)
    seen = []
    again = _happy({("claude", "blind"): [lambda request: seen.append(request["previous_rejection"]) or good_blind("c")(request)]})
    assert stage(directory, again).verdict == "РЕШЕНИЕ_АНТОНА" and seen == [recorded]
