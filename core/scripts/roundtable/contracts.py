#!/usr/bin/env python3
"""БИ — executable contract of the «идея» stage: schemas, phases, outcomes.

Three things are load-bearing here:

**One validator, closed vocabulary.** Both idea schemas are checked by the same
small validator over a *closed* subset of JSON Schema. A keyword it does not
know is a `ContractError`, not silently ignored: a schema that says something
the validator cannot enforce would look protective and protect nothing.

**Three error classes, three owners.** `AnswerRejected` is a participant's bad
answer (retry budget applies); `AuthorCardRefused` is the author's bad card
(entry refused before any paid call, no verdict); `ContractError` is *our*
breakage — a corrupt table, a duplicated engine-made ID — and is never charged
to a participant.

**The rules come from the tables.** Order, reasons and priorities of the nine
outcomes are read through `outcome_rules(tables)` only; the retry budget comes
from `vocabulary.повтор_невалидного_ответа`. This module owns only the
predicates the table's check codes name. The journal is touched only through
the `RunStore` API (attempts, candidate assignment, events).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import tables as tables_module
from .context import (PackageRefused, build_comparison_package, canonical_json, check_candidate_card, digest,
                      check_comparison_inputs)
from .state import IdeaCandidate
from .tables import ContractError

__all__ = [
    "AnswerRejected", "AuthorCardRefused", "AntonOkRequired", "ContractError",
    "validate", "load_schema", "parse_answer", "criterion_verdict", "candidate_state",
    "validate_criteria", "validate_proposal", "validate_comparison", "check_author_card",
    "outcome_rules", "decide_outcome", "retry_budget", "retry_order", "calls_made",
    "run_idea_stage", "require_anton_ok", "leave_idea_stage", "ANTON_OK_FLAG",
]

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

AUTHOR_SOURCE = "автор"
BLIND_STAGE = "идея:слепой"
COMPARE_STAGE = "идея:сравнение"
STAGE = "идея"
PACKAGE_FLAG = "пакет_сравнения:"       # + sha256 of the second package: it is pinned once, in the journal
OBJECTION_FLAG = "есть_открытые_возражения_к_постановке"
# БИ-13: evidence of Anton's explicit OK. The real operation belongs to БУ;
# until it exists the evidence is a run flag, and the guard reads only that.
ANTON_OK_FLAG = "ок_антона_на_решение"

# Verdict of every valid «идея» outcome (§4.5: "любой валидный итог приходит в
# ждёт_Антона"). It is checked against the vocabulary and the run table below,
# never trusted: ОДОБРЕНО on this stage is a ContractError.
IDEA_VERDICT = "РЕШЕНИЕ_АНТОНА"
INCOMPLETE_VERDICT = "НЕПОЛНЫЙ_ПРОГОН"


CLIP = 80
CRITERION_ID = re.compile(r"[\w.\-]{1,32}")


def _clip(value) -> str:
    """A participant's value inside an exception text: never longer than CLIP."""
    text = value if isinstance(value, str) else repr(value)
    text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    return text if len(text) <= CLIP else text[:CLIP] + "…"


def _fold_id(text: str) -> str:
    """Identifier as a human sees it: NFKC, casefold, Latin look-alikes of Cyrillic folded
    (the same table the agreement engine uses)."""
    return unicodedata.normalize("NFKC", text).casefold().translate(tables_module._HOMOGLYPHS)


def _blank(text: str) -> bool:
    """Empty for a human: spaces, controls and invisible format characters only."""
    return all(ch.isspace() or ch == "\u2800" or unicodedata.category(ch) in ("Cf", "Cc", "Zs", "Zl", "Zp")
               for ch in text)


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------

class AnswerRejected(Exception):
    """A participant's answer broke the input contract (retry budget applies)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AuthorCardRefused(Exception):
    """The author's card is unfit: entry refused, no verdict, no paid call."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AntonOkRequired(Exception):
    """БИ-13: a transition was attempted with no recorded OK from Anton."""

    code = "НЕТ_ОК_АНТОНА"

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


# --------------------------------------------------------------------------
# the validator: a closed subset of JSON Schema
# --------------------------------------------------------------------------

_KEYWORDS = {
    "$schema", "title", "description", "type", "properties", "required",
    "additionalProperties", "items", "enum", "minItems", "maxItems",
    "minLength", "maxLength", "uniqueItems",
}
_TYPES = {"object", "array", "string", "boolean", "integer"}


def check_schema(schema, where: str = "$") -> None:
    """Refuse a schema that uses anything outside the closed subset."""
    if not isinstance(schema, dict):
        raise ContractError(f"схема {where}: ожидалась карта")
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise ContractError(f"схема {where}: неизвестные ключевые слова {sorted(unknown)}")
    kind = schema.get("type")
    if kind is not None and kind not in _TYPES:
        raise ContractError(f"схема {where}: неизвестный тип {kind!r}")
    if "properties" in schema and not isinstance(schema["properties"], dict):
        raise ContractError(f"схема {where}.properties: ожидалась карта")
    for name, sub in (schema.get("properties") or {}).items():
        check_schema(sub, f"{where}.{name}")
    if "items" in schema:
        check_schema(schema["items"], f"{where}[]")
    extra = schema.get("additionalProperties")
    if isinstance(extra, dict):
        check_schema(extra, f"{where}.*")
    elif extra is not None and not isinstance(extra, bool):
        raise ContractError(f"схема {where}: additionalProperties — не boolean и не схема")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ContractError(f"схема {where}: enum — непустой список")
    if "required" in schema and (not isinstance(schema["required"], list) or not all(
            isinstance(x, str) for x in schema["required"])):
        raise ContractError(f"схема {where}: required — список строк")
    for name in ("minItems", "maxItems", "minLength", "maxLength"):
        if name in schema and (not isinstance(schema[name], int) or isinstance(schema[name], bool)
                               or schema[name] < 0):
            raise ContractError(f"схема {where}: {name} — неотрицательное целое")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise ContractError(f"схема {where}: uniqueItems — boolean")
    if "required" in schema and "properties" in schema:
        missing = set(schema["required"]) - set(schema["properties"])
        if missing:
            raise ContractError(f"схема {where}: required без описания в properties {sorted(missing)}")


def load_schema(name: str, directory: Path = SCHEMAS_DIR) -> dict:
    path = Path(directory) / f"{name}.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContractError(f"схема {name}: не читается — {error}") from None
    check_schema(schema)
    return schema


def _type_ok(kind: str, value) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    return isinstance(value, int) and not isinstance(value, bool)


def validate(schema: dict, value, where: str = "$") -> None:
    """Raise `AnswerRejected` unless `value` fits `schema`.

    A schema outside the closed subset raises `ContractError` first, so the
    answer is never blamed for a defect that is ours.
    """
    check_schema(schema, where)
    _validate(schema, value, where)


def _validate(schema: dict, value, where: str) -> None:
    kind = schema.get("type")
    if kind is not None and not _type_ok(kind, value):
        raise AnswerRejected(f"{where}: ожидался {kind}, получено {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise AnswerRejected(f"{where}: {_clip(value)!r} не из {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and schema["minLength"] > 0 and (
                _blank(value) or len(value) < schema["minLength"]):
            raise AnswerRejected(f"{where}: пустая строка")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise AnswerRejected(f"{where}: строка длиннее {schema['maxLength']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise AnswerRejected(f"{where}: элементов меньше {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise AnswerRejected(f"{where}: элементов больше {schema['maxItems']}")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise AnswerRejected(f"{where}: повторяющиеся элементы")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(schema["items"], item, f"{where}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                raise AnswerRejected(f"{where}: нет поля {name!r}")
        extra = schema.get("additionalProperties", True)
        for name, sub in value.items():
            if name in properties:
                _validate(properties[name], sub, f"{where}.{name}")
            elif extra is False:
                raise AnswerRejected(f"{where}: лишнее поле {_clip(name)!r}")
            elif isinstance(extra, dict):
                _validate(extra, sub, f"{where}.{name}")


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"повтор ключа {_clip(key)!r}")
        seen[key] = value
    return seen


def _no_constant(name):
    raise ValueError(f"недопустимая константа {name}")


_HOSTILE = (RecursionError, ValueError, TypeError, UnicodeError, OverflowError, MemoryError,
            PackageRefused)


def parse_answer(raw, limit: int | None = None) -> object:
    """Text or bytes of a critic's answer → JSON value, or `AnswerRejected`.

    The raw size is bounded *before* parsing, and anything the parser or the
    serialiser can throw at hostile input (deep nesting, lone surrogates)
    becomes a rejection of the answer, not a crash of the stage.
    """
    try:
        if isinstance(raw, (bytes, bytearray, str)):
            if limit is not None and len(raw) > limit:
                raise AnswerRejected("ответ длиннее предела пакет.предел_файла_байт")
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if limit is not None and len(text.encode("utf-8", "surrogatepass")) > limit:
                raise AnswerRejected("ответ длиннее предела пакет.предел_файла_байт")
            value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
        elif isinstance(raw, (dict, list)):
            value = raw
        else:
            raise AnswerRejected(f"ответ не JSON: {type(raw).__name__}")
        size = len(canonical_json(value))                  # fails on surrogates and on depth
    except AnswerRejected:
        raise
    except _HOSTILE as error:
        raise AnswerRejected(f"ответ не разобран: {type(error).__name__}: {_clip(str(error))}") from None
    if limit is not None and size > limit:
        raise AnswerRejected("ответ длиннее предела пакет.предел_файла_байт")
    return value


# --------------------------------------------------------------------------
# tables, read lazily
# --------------------------------------------------------------------------

def _tables(tables=None):
    return tables if tables is not None else tables_module.load()


def retry_budget(tables=None) -> int:
    """Retries allowed per critic per answer — from the vocabulary (БИ-10)."""
    spec = _tables(tables).vocabulary.get("повтор_невалидного_ответа")
    if not isinstance(spec, dict):
        raise ContractError("vocabulary.повтор_невалидного_ответа отсутствует")
    maximum = spec.get("максимум_на_ответ")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise ContractError(f"повтор_невалидного_ответа.максимум_на_ответ: {maximum!r}")
    if spec.get("область") != "на_критика":
        raise ContractError("повтор_невалидного_ответа.область: ожидалось на_критика")
    return maximum


def _sentinel(tables) -> str:
    value = tables.vocabulary.get("выбор_кандидата_sentinel")
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"vocabulary.выбор_кандидата_sentinel: {value!r}")
    return value


def retry_order(run_id: str, critics) -> list:
    """Deterministic alternation of vendors between retries: sha256(run_id) % 2."""
    critics = list(critics)
    parity = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest(), 16) % 2
    return critics[parity:] + critics[:parity]


# --------------------------------------------------------------------------
# truth table (§4.3)
# --------------------------------------------------------------------------

def criterion_verdict(first: str, second: str) -> str:
    """pass/pass → pass, fail/fail → fail, anything else → unknown."""
    if first == "pass" and second == "pass":
        return "pass"
    if first == "fail" and second == "fail":
        return "fail"
    return "unknown"


def candidate_state(verdicts) -> str:
    """First match: непроходной (any agreed fail), годен (all pass), else неясен."""
    verdicts = list(verdicts)
    if any(v == "fail" for v in verdicts):
        return "непроходной"
    if verdicts and all(v == "pass" for v in verdicts):
        return "годен"
    return "неясен"


# --------------------------------------------------------------------------
# criteria and proposals (phases 0 and A)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Criterion:
    id: str
    text: str
    mandatory: bool


def validate_criteria(criteria) -> tuple:
    """FORK-3: list of {id, текст, обязательный}; at least one mandatory."""
    if not isinstance(criteria, list) or not criteria:
        raise AuthorCardRefused("критерий_успеха: ожидался непустой список")
    parsed = []
    for row in criteria:
        if not isinstance(row, dict) or set(row) != {"id", "текст", "обязательный"}:
            raise AuthorCardRefused(f"критерий_успеха: плохая запись {_clip(row)}")
        if not isinstance(row["id"], str) or not CRITERION_ID.fullmatch(row["id"]):
            raise AuthorCardRefused(f"критерий_успеха: id вне [\\w.-]{{1,32}} {_clip(row['id'])!r}")
        if not isinstance(row["текст"], str) or _blank(row["текст"]):
            raise AuthorCardRefused(f"критерий_успеха {row['id']}: пустой текст")
        if not isinstance(row["обязательный"], bool):
            raise AuthorCardRefused(f"критерий_успеха {row['id']}: обязательный — не boolean")
        parsed.append(Criterion(row["id"], row["текст"], row["обязательный"]))
    ids = [c.id for c in parsed]
    if len(set(ids)) != len(ids):
        raise AuthorCardRefused(f"критерий_успеха: повторяющиеся id {ids}")
    folded = [_fold_id(i) for i in ids]
    if len(set(folded)) != len(folded):
        raise AuthorCardRefused(f"критерий_успеха: id совпадают после свёртки похожих букв {_clip(ids)}")
    if not any(c.mandatory for c in parsed):
        raise AuthorCardRefused("критерий_успеха: ни одного обязательного критерия")
    return tuple(parsed)


def _card_limit(tables) -> int:
    limit = tables.vocabulary.get("пакет", {}).get("предел_файла_байт")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ContractError(f"пакет.предел_файла_байт: {limit!r}")
    return limit


def validate_proposal(raw, criteria, tables=None) -> dict:
    """Validate one proposal (blind answer or author card); returns the parsed dict.

    Raises `AnswerRejected`. The card size limit is `пакет.предел_файла_байт`
    (FORK-5): all three cards must fit the same ceiling.
    """
    tables = _tables(tables)
    schema = load_schema("idea_proposal")
    value = parse_answer(raw, _card_limit(tables))
    validate(schema, value)
    ids = [row["criterion_id"] for row in value["criteria_fit"]]
    wanted = [c.id for c in criteria]
    if len(set(ids)) != len(ids):
        raise AnswerRejected(f"criteria_fit: повторяющиеся критерии {ids}")
    if sorted(ids) != sorted(wanted):
        raise AnswerRejected(
            f"criteria_fit: нужны ровно критерии {sorted(wanted)}, получено {_clip(sorted(ids))}")
    return value


def normalize_card(card: dict) -> dict:
    """§4.8: one form for all three cards, so the field set cannot reveal the source.

    `criteria_fit` goes by criterion id; optional fields are always present
    (as an empty list).
    """
    form = dict(card)
    form["criteria_fit"] = sorted(card["criteria_fit"], key=lambda row: row["criterion_id"])
    form.setdefault("возражения_к_постановке", [])
    return form


def fits_package(card: dict, tables, withheld) -> None:
    """The card, in its final (normalised) bytes, passes what the second package will judge.

    One function of `context.py`, not a copy: a card that would be refused by the package
    after the set is written must be refused here, before it.
    """
    try:
        check_candidate_card(canonical_json(normalize_card(card)), STAGE, tables, withheld)
    except PackageRefused as refused:
        raise AnswerRejected(f"карточка не пройдёт пакет: {refused.reason}") from None


def check_author_card(card, criteria_raw, tables=None, withheld=None) -> dict:
    """Phase 0 (БИ-6): pure checking, no store and no `ask` — nothing paid can precede it.

    With `withheld` the card must also pass the package checks of its normalised bytes.
    """
    criteria = validate_criteria(criteria_raw)
    try:
        value = validate_proposal(card, criteria, tables)
        if withheld is not None:
            fits_package(value, _tables(tables), withheld)
        return value
    except AnswerRejected as error:
        raise AuthorCardRefused(f"авторская карточка негодна: {error.reason}") from None
    except _HOSTILE as error:                       # pragma: no cover - parse_answer already converts
        raise AuthorCardRefused(f"авторская карточка негодна: {type(error).__name__}") from None


# --------------------------------------------------------------------------
# comparisons (phase C)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidatedComparison:
    critic: str
    grades: dict          # candidate_id -> {mandatory criterion_id -> grade}
    selected: str
    relations: dict       # frozenset({id, id}) -> relation
    raw: dict

    def passing(self) -> list:
        return [c for c, g in self.grades.items() if g and all(v == "pass" for v in g.values())]


def validate_comparison(raw, *, candidate_ids, criteria, critic: str = "", tables=None) -> ValidatedComparison:
    """Validate a comparison, including the two-sided selection invariant (§4.4)."""
    tables = _tables(tables)
    sentinel = _sentinel(tables)
    candidate_ids = list(candidate_ids)
    if len(candidate_ids) != 3 or len(set(candidate_ids)) != 3:
        raise ContractError(f"набор должен быть из трёх разных ID: {candidate_ids}")
    value = parse_answer(raw, _card_limit(tables))
    validate(load_schema("idea_comparison"), value)

    known = {c.id for c in criteria}
    mandatory = [c.id for c in criteria if c.mandatory]
    grades: dict = {}
    for entry in value["assessments"]:
        cid = entry["candidate_id"]
        if cid not in candidate_ids:
            raise AnswerRejected(f"assessments: чужой candidate_id {_clip(cid)!r}")
        if cid in grades:
            raise AnswerRejected(f"assessments: кандидат {_clip(cid)!r} оценён дважды")
        seen = {}
        for row in entry["criteria"]:
            if row["criterion_id"] not in known:
                raise AnswerRejected(f"assessments: чужой критерий {_clip(row['criterion_id'])!r}")
            if row["criterion_id"] in seen:
                raise AnswerRejected(f"assessments: критерий {_clip(row['criterion_id'])!r} оценён дважды у {cid!r}")
            seen[row["criterion_id"]] = row["grade"]
        missing = [m for m in mandatory if m not in seen]
        if missing:
            raise AnswerRejected(f"assessments: у {cid!r} нет оценки обязательных {missing}")
        grades[cid] = {m: seen[m] for m in mandatory}
    if set(grades) != set(candidate_ids):
        raise AnswerRejected(f"assessments: нужны ровно кандидаты {sorted(candidate_ids)}")

    relations: dict = {}
    for row in value["mechanism_relations"]:
        pair = row["pair"]
        if pair[0] == pair[1]:
            raise AnswerRejected(f"mechanism_relations: пара из одного ID {_clip(pair[0])!r}")
        if any(x not in candidate_ids for x in pair):
            raise AnswerRejected(f"mechanism_relations: чужой ID в паре {_clip(pair)}")
        key = frozenset(pair)
        if key in relations:
            raise AnswerRejected(f"mechanism_relations: пара {_clip(sorted(pair))} повторена")
        relations[key] = row["relation"]
    expected = {frozenset(p) for p in itertools.combinations(candidate_ids, 2)}
    if set(relations) != expected:
        raise AnswerRejected("mechanism_relations: нужны ровно три неупорядоченные пары")

    comparison = ValidatedComparison(critic, grades, value["selected_candidate_id"], relations, value)
    passing = comparison.passing()
    selected = comparison.selected
    if selected == sentinel:
        if passing:
            raise AnswerRejected(f"selected_candidate_id: {sentinel}, хотя проходят {sorted(passing)}")
    else:
        if selected not in candidate_ids:
            raise AnswerRejected(f"selected_candidate_id: чужой ID {_clip(selected)!r}")
        if selected not in passing:
            raise AnswerRejected(
                f"selected_candidate_id: {_clip(selected)!r} не проходит по всем обязательным у этого критика")
    return comparison


# --------------------------------------------------------------------------
# outcomes (§4.5)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class IdeaOutcome:
    reason: str
    priority: int | None
    verdict: str
    run_state: str
    row: int


_CHECKS = tables_module.OUTCOME_CHECKS
_PATTERNS = tables_module.OUTCOME_PATTERNS


def outcome_rules(tables=None) -> dict:
    """The only door to the outcome rules: `stages.исходы_идеи` (FORK-1).

    Form: {строки: [{проверка, причина, приоритет}], рисунки: [{рисунок, причина,
    приоритет}]}. Order is the order of evaluation; the code owns only the
    predicates the check codes name.
    """
    section = _tables(tables).raw.get("stages", {}).get("исходы_идеи")
    if not isinstance(section, dict) or set(section) != {"строки", "рисунки"}:
        raise ContractError("stages.исходы_идеи: нет раздела правил исходов нужной формы")
    for name, codes, key in (("строки", _CHECKS, "проверка"), ("рисунки", _PATTERNS, "рисунок")):
        rows = section[name]
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows) or [
                r.get(key) for r in rows] != list(codes):
            raise ContractError(f"stages.исходы_идеи.{name}: ожидался порядок {list(codes)}")
        for row in rows:
            if set(row) != {key, "причина", "приоритет"}:
                raise ContractError(f"stages.исходы_идеи.{name}: плохая строка {row!r}")
            if not isinstance(row["причина"], str) or not row["причина"]:
                raise ContractError(f"stages.исходы_идеи.{name}: пустая причина {row!r}")
            if row["приоритет"] is not None and (
                    not isinstance(row["приоритет"], int) or isinstance(row["приоритет"], bool)):
                raise ContractError(f"stages.исходы_идеи.{name}: приоритет {row!r}")
    return section


def _combined(first: ValidatedComparison, second: ValidatedComparison, candidate: str) -> dict:
    return {c: criterion_verdict(first.grades[candidate][c], second.grades[candidate][c])
            for c in first.grades[candidate]}


def _enhanced(first, second, author_id: str, sentinel: str) -> bool:
    """§4.6: three converging testimonies; the name describes testimony, not a conclusion."""
    if first.selected != second.selected or first.selected in (sentinel, author_id):
        return False
    if not any(v == "fail" for v in _combined(first, second, author_id).values()):
        return False
    pair = frozenset((author_id, first.selected))
    return first.relations[pair] == "different" and second.relations[pair] == "different"


def _pattern(first, second, author_id: str) -> str:
    a, b = first.selected, second.selected
    if a == b == author_id:
        return "обе_одну_авторскую"
    if a == b:
        return "обе_одну_неавторскую"
    if author_id in (a, b):
        return "авторская_и_неавторская"
    return "разные_неавторские"


def decide_outcome(first: ValidatedComparison, second: ValidatedComparison, *, author_id: str,
                   framing_open: bool, tables=None) -> IdeaOutcome:
    """First matching row of §4.5; one of nine outcomes, always to ждёт_Антона."""
    tables = _tables(tables)
    rules = outcome_rules(tables)
    sentinel = _sentinel(tables)
    if set(first.grades) != set(second.grades) or author_id not in first.grades:
        raise ContractError("сравнения построены на разных наборах кандидатов")
    states = {c: candidate_state(_combined(first, second, c).values()) for c in first.grades}
    sentinels = [first.selected == sentinel, second.selected == sentinel]

    def holds(code: str) -> bool:
        if code == "открытое_возражение":
            return framing_open
        if code == "оба_нет_проходящего":
            return all(sentinels)
        if code == "один_нет_проходящего":
            return any(sentinels)
        if code == "усиленный_случай":
            return _enhanced(first, second, author_id, sentinel)
        if code == "нет_совокупно_годного":
            return not any(s == "годен" for s in states.values())
        if code == "рисунок_выбора":
            return True                               # последняя строка: решает рисунок
        raise ContractError(f"исход: неизвестный код проверки {code!r}")

    for matched_row, matched in enumerate(rules["строки"], start=1):
        if holds(matched["проверка"]):
            break
    else:
        raise ContractError("исход: ни одна строка не подошла")
    result = matched
    if matched["проверка"] == "рисунок_выбора":
        pattern = _pattern(first, second, author_id)
        result = next(r for r in rules["рисунки"] if r["рисунок"] == pattern)

    verdict = IDEA_VERDICT
    if verdict == "ОДОБРЕНО" or verdict not in tables.vocabulary.get("вердикты", []):
        raise ContractError(f"вердикт {verdict!r} недопустим на стадии идея")
    run_state = tables.decide("идёт_круг", "вердикт", {"verdict": verdict}).to
    return IdeaOutcome(result["причина"], result["приоритет"], verdict, run_state, matched_row)


# --------------------------------------------------------------------------
# attempts and the retry budget (БИ-10)
# --------------------------------------------------------------------------

def calls_made(state, stage: str, round_number: int, critic: str) -> int:
    """Calls already made for this critic in this phase (all of them) — read from the attempt journal."""
    return len({k[4] for k in state.attempts
                if k[1] == stage and k[2] == round_number and k[3] == critic})


def _attempt_states(tables) -> list:
    order = tables.vocabulary.get("попытка", {}).get("состояния")
    if not isinstance(order, list) or "получена" not in order or "провалидирована" not in order:
        raise ContractError("vocabulary.попытка.состояния: нет состояний получена и провалидирована")
    return order


def _split_attempts(state, tables, stage: str, round_number: int, critic: str) -> tuple:
    """`(answered, aborted)` attempts of one critic in one phase.

    Answered: the status is not below `получена` — the vendor's answer exists, the budget
    is spent. Aborted: cut off before the answer (the process died) — no answer, no spend.
    """
    order = _attempt_states(tables)
    floor = order.index("получена")
    answered, aborted = [], []
    for key, attempt in state.attempts.items():
        if key[1] == stage and key[2] == round_number and key[3] == critic:
            (answered if order.index(attempt.status) >= floor else aborted).append(attempt)
    return answered, aborted


def abort_limit(tables=None) -> int:
    """Aborted calls allowed per critic per phase — from `stages.исполнение_идеи`."""
    section = _tables(tables).stages.get("исполнение_идеи")
    limit = section.get("предел_прерванных_попыток") if isinstance(section, dict) else None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ContractError(f"stages.исполнение_идеи.предел_прерванных_попыток: {limit!r}")
    return limit


def _valid_recorded(state, tables, stage: str, round_number: int, critic: str) -> bool:
    order = _attempt_states(tables)
    floor = order.index("провалидирована")
    return any(order.index(a.status) >= floor for k, a in state.attempts.items()
               if k[1] == stage and k[2] == round_number and k[3] == critic)


def _collect(store, ask, critics, *, stage: str, round_number: int, request, check, saved, tables) -> dict:
    """Ask every critic once, then retry invalid answers within the table budget.

    A valid answer is never re-requested: it comes from `saved` (the caller's
    own durable copy — the journal records that an answer was valid, not its
    bytes). Only an ANSWER spends the retry budget; a call cut off before its answer
    is marked a possible duplicate and bounded by its own limit. Returns critic ->
    validated value or None (budget exhausted).
    """
    limit = 1 + retry_budget(tables)
    cutoff = abort_limit(tables)
    results = {c: saved[c] for c in critics if c in saved}
    state = store.load()
    for critic in critics:
        if critic not in results and _valid_recorded(state, tables, stage, round_number, critic):
            raise ContractError(f"{critic}: в журнале валидный ответ, а его байтов нет")
        for attempt in _split_attempts(state, tables, stage, round_number, critic)[1]:
            if not attempt.possible_duplicate:
                store.mark_possible_duplicate(stage, round_number, critic, attempt.key[4])
    iteration = 0
    while True:
        order = list(critics) if iteration == 0 else retry_order(state.run_id, critics)
        progressed = False
        for critic in order:
            state = store.load()
            answered, aborted = _split_attempts(state, tables, stage, round_number, critic)
            if critic in results or len(answered) >= limit or len(aborted) >= cutoff:
                continue
            number = calls_made(state, stage, round_number, critic) + 1
            store.record_attempt(stage, round_number, critic, number, "подготовлена")
            store.record_attempt(stage, round_number, critic, number, "запущена")
            raw = ask(critic, request(critic, number))
            store.record_attempt(stage, round_number, critic, number, "получена")
            try:
                results[critic] = check(raw, critic)
            except AnswerRejected:
                pass
            else:
                store.record_attempt(stage, round_number, critic, number, "провалидирована")
                store.record_attempt(stage, round_number, critic, number, "зафиксирована")
            progressed = True
        iteration += 1
        if not progressed:
            break
    return {c: results.get(c) for c in critics}


# --------------------------------------------------------------------------
# the stage: phases 0, A, B, C
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StageResult:
    verdict: str
    outcome: IdeaOutcome | None
    run_state: str
    proposals: dict


def _finish(store, verdict: str, outcome, proposals) -> StageResult:
    state = store.record_event("вердикт", {"verdict": verdict})
    return StageResult(verdict, outcome, state.state, proposals)


def _trusted(check, raw, who: str):
    """A saved answer is our own input: if it no longer fits, that is our breakage."""
    try:
        return check(raw)
    except AnswerRejected as error:
        raise ContractError(f"сохранённый ответ {who} не проходит проверку: {error.reason}") from None


def _pin_package(store, package, withheld) -> None:
    """The second package is pinned in the journal once; a resumed run must rebuild the same print.

    The print is sha256 over the package hash and the sha256 of the canonical `withheld`
    (the hash only, never the text): a changed hidden name is not passed over silently.
    """
    print_ = digest(canonical_json({"пакет": package.hash, "withheld": digest(canonical_json(withheld))}))
    state = store.load()
    pinned = sorted(f for f in state.flags if f.startswith(PACKAGE_FLAG))
    if not pinned:
        store.set_flag(PACKAGE_FLAG + print_)
    elif pinned != [PACKAGE_FLAG + print_]:
        raise ContractError("второй пакет при возобновлении не совпал с записанным в журнале "
                            "(изменились разделы, критерии, имена скрытого или карточки)")


def _permutation_ok(order, size: int) -> bool:
    return (isinstance(order, list) and len(order) == size
            and all(isinstance(i, int) and not isinstance(i, bool) for i in order)
            and sorted(order) == list(range(size)))


def run_idea_stage(store, *, criteria, author_card, ask, sections, withheld, registries=None,
                   critics=("claude", "codex"), saved_proposals=None, saved_comparisons=None,
                   new_id=None, shuffle=None, tables=None) -> StageResult:
    """Run the «идея» stage end to end against a locked `RunStore`.

    `ask(critic, request)` is the only paid call. Phase 0 runs before it can be
    reached. `new_id` / `shuffle` are injection points for tests; by default
    IDs and the permutation come from `secrets` (identity permutation allowed).

    `sections` (the shown task sections), `registries` (default: empty) and
    `withheld` (the author and the second critic) feed the second package, which
    is built by `context.build_comparison_package` from the journal's cards and
    permutation only -- so a resumed run builds the same bytes.
    """
    tables = _tables(tables)
    critics = list(critics)
    if len(critics) != 2 or len(set(critics)) != 2 or not all(
            isinstance(c, str) and c.strip() for c in critics):
        raise ContractError(f"нужны ровно два разных критика: {_clip(critics)}")
    parsed_criteria = validate_criteria(criteria)                      # phase 0
    criteria_view = [{"id": c.id, "text": c.text, "mandatory": c.mandatory} for c in parsed_criteria]
    empty = {"решения": [], "области": [], "журнал_доказательств": []}
    registries = empty if registries is None else registries
    try:                       # the task, criteria and hidden names go through the package's own checks first
        check_comparison_inputs(sections, registries, STAGE, tables, withheld, criteria_view)
    except PackageRefused as refused:
        raise AuthorCardRefused(f"вход пакета не принят: {refused.reason}") from None
    author = check_author_card(author_card, criteria, tables, withheld)
    state = store.load()
    if state.state is None:
        raise ContractError("прогон не запущен: сначала операция start")
    if state.state not in ("создан", "идёт_круг"):
        raise ContractError(f"стадия завершена: прогон в состоянии {state.state!r}")
    if state.state == "создан":
        state = store.record_event("пакет_собран")
    round_number = max(state.round_number, 1)
    for owner, saved in (("предложения", saved_proposals), ("сравнения", saved_comparisons)):
        if set(saved or {}) - set(critics):
            raise ContractError(f"сохранённые {owner}: чужие критики {sorted(set(saved) - set(critics))}")

    # -- phase A: blind proposals --------------------------------------------
    proposals: dict = {}

    def blind_card(raw, critic=None):
        card = validate_proposal(raw, parsed_criteria, tables)
        fits_package(card, tables, withheld)          # what the package will judge, before the set exists
        return card

    if not state.idea_candidates:
        proposals = _collect(
            store, ask, critics, stage=BLIND_STAGE, round_number=round_number,
            request=lambda critic, n: {"phase": "blind", "critic": critic, "attempt": n,
                                       "criteria": criteria_view},
            check=lambda raw, critic: blind_card(raw),
            saved={c: _trusted(blind_card, raw, c) for c, raw in (saved_proposals or {}).items()},
            tables=tables)
        if sum(v is not None for v in proposals.values()) < 2:
            return _finish(store, INCOMPLETE_VERDICT, None, proposals)

        # -- phase B: the engine makes the set -----------------------------------
        make_id = new_id or (lambda: "cand_" + secrets.token_hex(4))
        cards = [(AUTHOR_SOURCE, author)] + [(c, proposals[c]) for c in critics]
        ids = [make_id() for _ in cards]
        if not all(isinstance(i, str) and i.strip() for i in ids):
            raise ContractError(f"движок выдал пустой candidate_id: {ids}")
        if len(set(ids)) != len(ids):
            raise ContractError(f"движок выдал повторяющиеся candidate_id: {ids}")
        order = list(range(len(cards)))
        (shuffle or secrets.SystemRandom().shuffle)(order)
        if not _permutation_ok(order, len(cards)):
            raise ContractError(f"перестановка {order} не из {len(cards)} карточек")
        store.assign_idea_candidates(
            [IdeaCandidate(i, source, canonical_json(normalize_card(card)))
             for i, (source, card) in zip(ids, cards)],
            order)
        state = store.load()

    # -- phase C: comparisons -------------------------------------------------
    candidates = state.idea_candidates
    author_id = next(c.candidate_id for c in candidates if c.source == AUTHOR_SOURCE)
    ordered = [candidates[i] for i in state.idea_candidates_permutation]
    ids = [c.candidate_id for c in ordered]
    try:
        package = build_comparison_package(
            sections, registries, STAGE, candidates, state.idea_candidates_permutation,
            tables=tables, withheld=withheld, criteria=criteria_view)
    except PackageRefused:                  # the cards were checked before the set; this is the last net
        return _finish(store, INCOMPLETE_VERDICT, None, proposals)
    _pin_package(store, package, withheld)
    shown = [{"candidate_id": row["candidate_id"], "text": row["текст"]} for row in package.candidates]

    def compare(raw, critic):
        return validate_comparison(raw, candidate_ids=ids, criteria=parsed_criteria,
                                   critic=critic, tables=tables)

    comparisons = _collect(
        store, ask, critics, stage=COMPARE_STAGE, round_number=round_number,
        request=lambda critic, n: {"phase": "compare", "critic": critic, "attempt": n,
                                   "criteria": package.criteria, "candidates": shown,
                                   "package": package.material()},
        check=compare,
        saved={c: _trusted(lambda r: compare(r, c), raw, c) for c, raw in (saved_comparisons or {}).items()},
        tables=tables)
    if any(v is None for v in comparisons.values()):
        return _finish(store, INCOMPLETE_VERDICT, None, proposals)
    first, second = (comparisons[c] for c in critics)
    outcome = decide_outcome(first, second, author_id=author_id,
                             framing_open=OBJECTION_FLAG in state.flags, tables=tables)
    return _finish(store, outcome.verdict, outcome, proposals)


# --------------------------------------------------------------------------
# БИ-13: no transition without Anton's recorded OK
# --------------------------------------------------------------------------

def require_anton_ok(store) -> None:
    """Refuse unless the stage is finished and Anton's OK follows its last verdict.

    The OK counts only when (by journal order) the run waits for Anton, the last
    verdict is the idea one, no framing objection is open, the OK flag is still
    on, and it was recorded after the last verdict and after the last round start.
    """
    state = store.load()
    if state.state != "ждёт_Антона":
        raise AntonOkRequired(f"прогон в состоянии {state.state!r}, ждать ОК нечего")
    if OBJECTION_FLAG in state.flags:
        raise AntonOkRequired("открыто возражение к постановке — оно держит стадию")
    if ANTON_OK_FLAG not in state.flags:
        raise AntonOkRequired("нет записанного ОК Антона на решение")
    position = {"verdict": -1, "round": -1, "ok": -1}
    last_verdict = None
    for index, entry in enumerate(store._entries()):    # временно: до публичного чтения журнала в state.py (блок БУ)
        kind = entry.get("kind")
        if kind == "event" and entry.get("event") == "вердикт" and (entry.get("outcome") or {}).get("moved"):
            position["verdict"] = index
            last_verdict = (entry.get("conditions") or {}).get("verdict")
        elif kind == "round_started":
            position["round"] = index
        elif kind == "flag" and entry.get("flag") == ANTON_OK_FLAG:
            position["ok"] = index if entry.get("on") else -1
    if last_verdict != IDEA_VERDICT:
        raise AntonOkRequired(f"последний вердикт {last_verdict!r}, а не {IDEA_VERDICT}")
    if position["ok"] < 0 or position["ok"] < position["verdict"] or position["ok"] < position["round"]:
        raise AntonOkRequired("ОК Антона дан не после последнего вердикта текущего круга")


def leave_idea_stage(store) -> bool:
    """A PREDICATE: True only when Anton's OK is recorded after the last verdict.

    It is not wired to a run transition and the OK flag is not a protected write — both
    belong to the БУ block; until then nothing in the engine calls it on a transition.
    The critics' agreement never substitutes for the OK."""
    require_anton_ok(store)
    return True
