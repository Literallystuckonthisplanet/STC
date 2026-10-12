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
outcomes are read through `outcome_rules(tables)` only, and the strictness of that
section lives in one place, `Tables._check_idea_outcomes` (the order of the codes is
fixed in `tables.OUTCOME_CHECKS`); the same goes for the abort limit
(`Tables._check_idea_execution`). The retry policy comes from
`vocabulary.повтор_невалидного_ответа`: the budget, the order, whether an answer spends
it, and the verdict after it runs out. This module owns only the predicates the check
codes name. The journal is touched only through the `RunStore` API (attempts, candidate
assignment, events, flags).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import secrets
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import tables as tables_module
from .context import (PackageRefused, build_comparison_package, build_package, canonical_json,
                      check_candidate_card, check_comparison_inputs, check_withheld, comparison_sections,
                      digest, fold_identifier, same_package)
from .state import CAUSE_INPUT_NOT_BUILT, IdeaCandidate, Refusal, ok_standing
from .tables import ContractError

__all__ = [
    "AnswerRejected", "AuthorCardRefused", "AntonOkRequired", "ContractError",
    "validate", "load_schema", "check_schema", "parse_answer", "criterion_verdict", "candidate_state",
    "validate_criteria", "validate_proposal", "validate_comparison", "check_author_card",
    "normalize_card", "card_bytes", "fits_package", "Criterion", "ValidatedComparison",
    "outcome_rules", "decide_outcome", "IdeaOutcome", "retry_budget", "retry_order", "abort_limit",
    "calls_made", "incomplete_verdict", "run_idea_stage", "StageResult",
    "require_anton_ok", "leave_idea_stage",
    "ResumeImpossible", "AntonOkRefused", "RefinementError", "CorrectionRefused", "RefinementCeiling",
    "submit_correction", "record_anton_ok", "ok_marker", "OBJECTION_FLAG", "PIN_INPUT", "PIN_PACKAGE", "AUTHOR_SOURCE", "BLIND_STAGE",
    "COMPARE_STAGE", "STAGE", "IDEA_VERDICT", "INCOMPLETE_VERDICT", "CRITERION_ID", "SCHEMAS_DIR",
]

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"

AUTHOR_SOURCE = "автор"
BLIND_STAGE = "идея:слепой"
COMPARE_STAGE = "идея:сравнение"
STAGE = "идея"
PIN_INPUT = "вход_закреплён"            # journal events (vocabulary.закрепление.события): the caller's inputs, pinned at the first entry
PIN_PACKAGE = "пакет_закреплён"         # ... and the second package, pinned before the first comparison call
OBJECTION_FLAG = "есть_открытые_возражения_к_постановке"
# БУ-15: Anton's OK is no flag any more -- it is a journal event tied to a reply in the transcript.

# Verdict of every valid «идея» outcome (§4.5: "любой валидный итог приходит в
# ждёт_Антона"). It is checked against the vocabulary and the run table below,
# never trusted: ОДОБРЕНО on this stage is a ContractError.
IDEA_VERDICT = "РЕШЕНИЕ_АНТОНА"
INCOMPLETE_VERDICT = "НЕПОЛНЫЙ_ПРОГОН"      # what the table's `после_исчерпания` must say; read from there


CLIP = 80
REASON_CLIP = 300                            # a rejection reason travels back to the critic: room for the cause
MAX_LISTED = 8                               # ids named in one exception text
# A closed alphabet: Cyrillic, ASCII Latin, digits and `.-_`. A letter outside it is a look-alike
# the fold cannot be trusted with (`İ`, `ԁ`, `ɡ`, `Ѵ`), so it is refused, not folded.
CRITERION_ID = re.compile(r"[A-Za-zА-Яа-яЁё0-9._\-]{1,32}")


def _clip(value, limit: int = CLIP) -> str:
    """A participant's value inside an exception text: never longer than `limit`."""
    text = value if isinstance(value, str) else repr(value)
    text = text.encode("utf-8", "replace").decode("utf-8", "replace")
    return text if len(text) <= limit else text[:limit] + "…"


def _listed(values) -> str:
    """A list of ids inside an exception text: a few of them, each clipped."""
    values = list(values)
    shown = ", ".join(_clip(v, 32) for v in values[:MAX_LISTED])
    return f"[{shown}{', …' if len(values) > MAX_LISTED else ''}]"


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


class ResumeImpossible(Exception):
    """БУ-13: an incomplete run has nothing left to continue with (the table's refusal code)."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class AntonOkRequired(Exception):
    """БИ-13: a transition was attempted with no recorded OK from Anton."""

    code = "НЕТ_ОК_АНТОНА"

    def __init__(self, detail: str = "", code: str | None = None):
        self.detail = detail
        if code is not None:
            self.code = code                 # the table's refusal (НЕТ_ОК_АНТОНА, ОК_УСТАРЕЛ, ЕСТЬ_ОТКРЫТОЕ_ВОЗРАЖЕНИЕ)
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class RefinementError(Exception):
    """The common base of the refinement cycle's named outcomes (`.code` is the table's code)."""

    code = ""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class CorrectionRefused(RefinementError):
    """БУ-1…БУ-8: a correction was offered and not taken -- NOTHING is written."""


class RefinementCeiling(RefinementError):
    """БУ-8: the turns of the cycle are used up -- the run was stopped for redesign (terminal), no agreement follows.

    Not a `CorrectionRefused`: that one means "nothing was written", here the stop IS written (on Anton's word).
    `history` is the journal's account of every turn, the stop included.
    """

    def __init__(self, detail: str = "", history: list | None = None):
        super().__init__("ПОТОЛОК_ОБОРОТОВ", detail)
        self.history = history or []


class AntonOkRefused(Exception):
    """БУ-15: a reply was offered as Anton's OK and was not counted (nothing is written)."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


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
                raise AnswerRejected("ответ длиннее предела пакет.предел_раздела_байт")
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            if limit is not None and len(text.encode("utf-8", "surrogatepass")) > limit:
                raise AnswerRejected("ответ длиннее предела пакет.предел_раздела_байт")
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
        raise AnswerRejected("ответ длиннее предела пакет.предел_раздела_байт")
    return value


# --------------------------------------------------------------------------
# tables, read lazily
# --------------------------------------------------------------------------

def _tables(tables=None):
    return tables if tables is not None else tables_module.load()


RETRY_ORDER = "детерминированное_чередование_вендоров"      # the only order `retry_order` implements


def _retry_policy(tables) -> dict:
    """`vocabulary.повтор_невалидного_ответа`, every field the behaviour depends on checked (БИ-10).

    `тратит_бюджет` — an answer spends the budget (the only mode the loop implements);
    `порядок` — the order of the retries; `после_исчерпания` — the verdict when it runs out.
    A value the code cannot honour is `ContractError`: a table that says something else
    must not be silently run as if it said this.
    """
    spec = tables.vocabulary.get("повтор_невалидного_ответа")
    if not isinstance(spec, dict):
        raise ContractError("vocabulary.повтор_невалидного_ответа отсутствует")
    maximum = spec.get("максимум_на_ответ")
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
        raise ContractError(f"повтор_невалидного_ответа.максимум_на_ответ: {maximum!r}")
    if spec.get("область") != "на_критика":
        raise ContractError("повтор_невалидного_ответа.область: ожидалось на_критика")
    if spec.get("тратит_бюджет") is not True:
        raise ContractError("повтор_невалидного_ответа.тратит_бюджет: движок считает бюджет по ответам (true)")
    if spec.get("порядок") != RETRY_ORDER:
        raise ContractError(f"повтор_невалидного_ответа.порядок: движок умеет только {RETRY_ORDER}")
    after = spec.get("после_исчерпания")
    if not isinstance(after, str) or after not in tables.vocabulary.get("вердикты", []):
        raise ContractError(f"повтор_невалидного_ответа.после_исчерпания: {_clip(after)!r} не вердикт")
    return spec


def retry_budget(tables=None) -> int:
    """Retries allowed per critic per answer — from the vocabulary (БИ-10)."""
    return _retry_policy(_tables(tables))["максимум_на_ответ"]


def incomplete_verdict(tables=None) -> str:
    """The verdict of a run whose retry budget ran out (`после_исчерпания`)."""
    return _retry_policy(_tables(tables))["после_исчерпания"]


def _sentinel(tables) -> str:
    value = tables.vocabulary.get("выбор_кандидата_sentinel")
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"vocabulary.выбор_кандидата_sentinel: {value!r}")
    return value


def retry_order(run_id: str, critics) -> list:
    """Deterministic alternation of vendors between retries: sha256(run_id) % 2 (`RETRY_ORDER`)."""
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
            raise AuthorCardRefused(
                f"критерий_успеха: id вне алфавита (кириллица, латиница, цифры, . - _; 1-32 знака) {_clip(row['id'])!r}")
        if not isinstance(row["текст"], str) or _blank(row["текст"]):
            raise AuthorCardRefused(f"критерий_успеха {row['id']}: пустой текст")
        try:
            row["текст"].encode("utf-8")
        except UnicodeEncodeError:
            raise AuthorCardRefused(f"критерий_успеха {row['id']}: суррогаты в тексте") from None
        if not isinstance(row["обязательный"], bool):
            raise AuthorCardRefused(f"критерий_успеха {row['id']}: обязательный — не boolean")
        parsed.append(Criterion(row["id"], row["текст"], row["обязательный"]))
    ids = [c.id for c in parsed]
    if len(set(ids)) != len(ids):
        raise AuthorCardRefused(f"критерий_успеха: повторяющиеся id {_listed(ids)}")
    folded = [fold_identifier(i) for i in ids]
    if len(set(folded)) != len(folded):
        raise AuthorCardRefused(f"критерий_успеха: id совпадают после свёртки похожих букв {_listed(ids)}")
    if not any(c.mandatory for c in parsed):
        raise AuthorCardRefused("критерий_успеха: ни одного обязательного критерия")
    return tuple(parsed)


def _card_limit(tables) -> int:
    limit = tables.vocabulary.get("пакет", {}).get("предел_раздела_байт")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ContractError(f"пакет.предел_раздела_байт: {limit!r}")
    return limit


def validate_proposal(raw, criteria, tables=None) -> dict:
    """Validate one proposal (blind answer or author card); returns the parsed dict.

    Raises `AnswerRejected`. The card size limit is `пакет.предел_раздела_байт`
    (FORK-5, decided): one number for a card everywhere -- the answer validator, the author's
    card, the blind package (which hides the card as a section) and the second package.
    """
    tables = _tables(tables)
    schema = load_schema("idea_proposal")
    value = parse_answer(raw, _card_limit(tables))
    validate(schema, value)
    ids = [row["criterion_id"] for row in value["criteria_fit"]]
    wanted = [c.id for c in criteria]
    if len(set(ids)) != len(ids):
        raise AnswerRejected(f"criteria_fit: повторяющиеся критерии {_listed(ids)}")
    if sorted(ids) != sorted(wanted):
        raise AnswerRejected(
            f"criteria_fit: нужны ровно критерии {_listed(sorted(wanted))}, получено {_listed(sorted(ids))}")
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


def card_bytes(card: dict) -> bytes:
    """The card's canonical bytes in its one form: what is checked, stored and shown."""
    return canonical_json(normalize_card(card))


def _withheld_checked(tables, withheld, second: bool) -> None:
    """The hidden names as the build reads them; a wrong shape is the caller's, not a card's fault."""
    try:
        check_withheld(tables, withheld, second)
    except PackageRefused as refused:
        raise ContractError(f"withheld: {refused.reason}: {_clip(refused.detail)}") from None


def fits_package(card: dict, tables, withheld) -> None:
    """The card, in its final (normalised) bytes, passes what the second package will judge.

    One function of `context.py`, not a copy: a card that would be refused by the package
    after the set is written must be refused here, before it. A malformed `withheld` is
    `ContractError` (the caller's input), never a verdict on the card.
    """
    _withheld_checked(tables, withheld, True)
    try:
        check_candidate_card(card_bytes(card), STAGE, tables, withheld)
    except PackageRefused as refused:
        raise AnswerRejected(f"карточка не пройдёт пакет: {refused.reason}") from None


def check_author_card(card, criteria_raw, tables=None, withheld=None) -> dict:
    """Phase 0 (БИ-6): pure checking, no store and no `ask` — nothing paid can precede it.

    With `withheld` the card must also pass the package checks of its normalised bytes.
    `AuthorCardRefused` is only about the content of the card and the criteria; a malformed
    `withheld` is `ContractError`.
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
        raise ContractError(f"набор должен быть из трёх разных ID: {_listed(candidate_ids)}")
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
                raise AnswerRejected(
                    f"assessments: критерий {_clip(row['criterion_id'])!r} оценён дважды у {_clip(cid)!r}")
            seen[row["criterion_id"]] = row["grade"]
        missing = [m for m in mandatory if m not in seen]
        if missing:
            raise AnswerRejected(f"assessments: у {_clip(cid)!r} нет оценки обязательных {_listed(missing)}")
        grades[cid] = {m: seen[m] for m in mandatory}
    if set(grades) != set(candidate_ids):
        raise AnswerRejected(f"assessments: нужны ровно кандидаты {_listed(sorted(candidate_ids))}")

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
            raise AnswerRejected(f"selected_candidate_id: {sentinel}, хотя проходят {_listed(sorted(passing))}")
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


def outcome_rules(tables=None) -> dict:
    """The only door to the outcome rules: `stages.исходы_идеи` (FORK-1).

    Form: {строки: [{проверка, причина, приоритет}], рисунки: [{рисунок, причина,
    приоритет}]}. Order is the order of evaluation; the order of the codes is fixed in
    `tables.OUTCOME_CHECKS` / `OUTCOME_PATTERNS`. The section is judged by the one check
    the table owns (`Tables._check_idea_outcomes`), not by a second copy of it here.
    """
    tables = _tables(tables)
    tables._check_idea_outcomes()
    return tables.stages["исходы_идеи"]


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
    if any(set(first.grades[c]) != set(second.grades[c]) for c in first.grades):
        raise ContractError("сравнения оценили разные обязательные критерии")
    pairs = {frozenset(p) for p in itertools.combinations(first.grades, 2)}
    if set(first.relations) != pairs or set(second.relations) != pairs:
        raise ContractError("сравнения не покрывают все пары кандидатов")
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
        result = next((r for r in rules["рисунки"] if r["рисунок"] == pattern), None)
        if result is None:
            raise ContractError(f"исход: в таблице нет рисунка {pattern!r}")

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


def _rank(order: list, attempt) -> int:
    """Position of an attempt's status in the table's order; a status the table lacks is a corrupt journal."""
    if attempt.status not in order:
        raise ContractError(f"журнал попыток: состояние {_clip(attempt.status)!r} не из vocabulary.попытка.состояния")
    return order.index(attempt.status)


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
            (answered if _rank(order, attempt) >= floor else aborted).append(attempt)
    return answered, aborted


def abort_limit(tables=None) -> int:
    """Aborted calls allowed per critic per phase — from `stages.исполнение_идеи`.

    The section is judged by the one check the table owns (`Tables._check_idea_execution`).
    """
    tables = _tables(tables)
    tables._check_idea_execution()
    return tables.stages["исполнение_идеи"]["предел_прерванных_попыток"]


def _valid_recorded(state, tables, stage: str, round_number: int, critic: str) -> bool:
    order = _attempt_states(tables)
    floor = order.index("провалидирована")
    return any(_rank(order, a) >= floor for k, a in state.attempts.items()
               if k[1] == stage and k[2] == round_number and k[3] == critic)


@dataclass(frozen=True)
class _Run:
    """What every phase of one `run_idea_stage` call shares (all of it already checked)."""

    store: object
    ask: object
    tables: object
    critics: tuple
    criteria: tuple               # parsed `Criterion`s
    criteria_view: list           # {id, text, mandatory}: the form the package carries
    sections: dict
    registries: dict
    withheld: dict
    round_number: int
    revision: str                 # the author's card hash: the identity of the revision this round judges
    snapshot: dict = field(default_factory=dict)   # phase 0's one reading of the journal's answers: (stage, critic) -> [_Seen]


def _answer_bytes(raw, tables) -> bytes:
    """The bytes the journal keeps for an answer: what came, or its canonical JSON when it came as a value.

    A text is kept as UTF-8, bytes as they are; a dict or a list has no bytes of its own, so its
    canonical form stands in. Anything else (or a value that does not serialise) is kept as nothing:
    the check of the stored bytes then rejects it, on the first call and on every resume alike.
    What is kept is cut to `ответ_критика.предел_байтов + 1` bytes: the check refuses an over-long answer
    by its length either way, and the disk does not grow with a hostile answer.
    """
    if isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
    elif isinstance(raw, str):
        data = raw.encode("utf-8", "surrogatepass")
    elif isinstance(raw, (dict, list)):
        try:
            data = canonical_json(raw)
        except _HOSTILE:
            data = b""
    else:
        data = b""
    return data[:tables.vocabulary["ответ_критика"]["предел_байтов"] + 1]


def _question(phase: str, critic: str, package: str) -> str:
    """The hash of what was asked: phase, critic and the package. The attempt number and the
    previous rejection are not in it -- they are the retry, not the question."""
    return digest(canonical_json({"phase": phase, "critic": critic, "package": package}))


def _reason(error: AnswerRejected) -> str:
    """The clipped reason of a rejected answer; the journal does not take a refusal without one."""
    return _clip(error.reason, REASON_CLIP).strip() or "ответ отвергнут без названной причины"


@dataclass(frozen=True)
class _Seen:
    """An answer the journal holds, judged again from its stored bytes."""

    number: int
    accepted: bool
    value: object
    reason: str


def _recorded(store, state, tables, stage: str, round_number: int, critic: str, check, question: str) -> list:
    """БУ-14: the answers the journal has for one critic in one phase, read back from their receipts.

    Only an attempt the journal counted as received (the receipt written after the bytes) is
    read. Its bytes come from the store with the hash and length checked; the receipt must name
    THIS question; the bytes are judged again by the same check, and the result must agree with the
    recorded one. Whatever disagrees is our breakage (`ContractError`) -- never silently accepted,
    never replaced by anything the caller hands in. Writes nothing.
    """
    order = _attempt_states(tables)
    floor = order.index("получена")
    seen = []
    for key in sorted((k for k in state.attempts if k[1] == stage and k[2] == round_number and k[3] == critic),
                      key=lambda k: k[4]):
        attempt = state.attempts[key]
        if _rank(order, attempt) < floor:
            continue
        number = key[4]
        if attempt.receipt is None:
            raise ContractError(f"{critic}: ответ попытки {number} учтён, а его байтов в журнале нет")
        if attempt.receipt.question_hash != question:
            raise ContractError(f"{critic}: ответ попытки {number} записан на другой вопрос")
        data = store.read_answer(stage, round_number, critic, number)
        try:
            judged = _Seen(number, True, check(data, critic), "")
        except AnswerRejected as error:
            judged = _Seen(number, False, None, _reason(error))
        recorded = attempt.validation
        if recorded is not None:
            if recorded.accepted != judged.accepted:
                raise ContractError(f"{critic}: ответ попытки {number} проверен в журнале иначе, чем проверяется сейчас")
            if not judged.accepted:
                if recorded.reason != judged.reason:
                    raise ContractError(f"{critic}: причина отказа ответа попытки {number} расходится с записанной")
                judged = _Seen(number, False, None, recorded.reason)          # the recorded one is what travels on
        seen.append(judged)
    return seen


def _settle(store, tables, stage: str, round_number: int, critic: str, seen) -> None:
    """Bring the journal up to what the saved answers say: the missing result of the check, the missing states."""
    order = _attempt_states(tables)
    for item in seen:
        state = store.load()
        key = (state.run_id, stage, round_number, critic, item.number)
        if state.attempts[key].validation is None:
            store.record_validation(stage, round_number, critic, item.number, item.accepted, item.reason)
        if item.accepted:
            for status in ("провалидирована", "зафиксирована"):
                if _rank(order, store.load().attempts[key]) < order.index(status):
                    store.record_attempt(stage, round_number, critic, item.number, status)


def _collect(run: _Run, *, stage: str, phase: str, package: str, check) -> tuple:
    """Ask every critic once, then retry invalid answers within the table budget.

    A valid answer is never re-requested: it is read back from the journal (БУ-11, БУ-14) --
    the answer the critic gave, byte for byte, with the attempt, the question and the result of
    the check. Only an ANSWER spends the retry budget; a call cut off before its answer is marked a
    possible duplicate and bounded by its own limit. A rejected answer's reason (clipped) goes into
    the retry's request as `previous_rejection`; the journal keeps it too, so a resumed run
    asks the retry with the same reason.

    A received answer is stored (bytes on the disk, then the journal entry) BEFORE it is judged.

    Returns `(results, rejections)`: critic -> validated value or None (budget exhausted),
    and critic -> the reasons of the rejected answers of this phase, those of earlier calls included.
    """
    store, tables, critics = run.store, run.tables, run.critics
    round_number = run.round_number
    limit = 1 + retry_budget(tables)
    cutoff = abort_limit(tables)
    results: dict = {}
    rejections = {c: [] for c in critics}
    state = store.load()
    for critic in critics:
        seen = run.snapshot.get((stage, critic))
        if seen is None:
            seen = _recorded(store, state, tables, stage, round_number, critic, check,
                             _question(phase, critic, package))
        _settle(store, tables, stage, round_number, critic, seen)
        rejections[critic] = [item.reason for item in seen if not item.accepted]
        valid = [item for item in seen if item.accepted]
        if valid:
            results[critic] = valid[0].value
        state = store.load()
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
            request = {"phase": phase, "critic": critic, "attempt": number, "package": package,
                       "previous_rejection": rejections[critic][-1] if rejections[critic] else None}
            data = _answer_bytes(run.ask(critic, request), tables)
            store.record_received(stage, round_number, critic, number, data, _question(phase, critic, package))
            try:
                value = check(data, critic)
            except AnswerRejected as error:
                reason = _reason(error)
                store.record_validation(stage, round_number, critic, number, False, reason)
                rejections[critic].append(reason)
            else:
                store.record_validation(stage, round_number, critic, number, True)
                store.record_attempt(stage, round_number, critic, number, "провалидирована")
                store.record_attempt(stage, round_number, critic, number, "зафиксирована")
                results[critic] = value
            progressed = True
        iteration += 1
        if not progressed:
            break
    return {c: results.get(c) for c in critics}, rejections


# --------------------------------------------------------------------------
# the stage: phases 0, A, B, C
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StageResult:
    """What the stage hands on. `comparisons` and `rejections` are what Anton reads.

    `comparisons`: critic -> validated comparison (reasons, unknowns, blockers in `.raw`);
    only the critics whose answer is valid. `rejections`: phase -> critic -> reasons of
    the answers rejected in this call. `incomplete_reason`: why the run is incomplete
    (None for a verdict). There is no journal place for the reasons yet: БУ.
    """

    verdict: str
    outcome: IdeaOutcome | None
    run_state: str
    proposals: dict
    comparisons: dict = field(default_factory=dict)
    rejections: dict = field(default_factory=dict)
    incomplete_reason: str | None = None
    turns: list = field(default_factory=list)       # БУ-6: the refinement history at the moment of the result


def _finish(run: _Run, outcome, proposals, comparisons, rejections, incomplete_reason=None,
            cause=None) -> StageResult:
    """`cause`: why a run is incomplete when it is not the budget (the input does not build) -- kept with the verdict."""
    verdict = outcome.verdict if outcome is not None else incomplete_verdict(run.tables)
    state = run.store.record_event("вердикт", {"verdict": verdict}, {"cause": cause} if cause else None)
    return StageResult(verdict, outcome, state.state, proposals, comparisons, rejections, incomplete_reason,
                       run.store.refinement_history())


def _package_pin(run_round: int, revision: str, package, withheld) -> dict:
    """What the second package is pinned by: its hash and the hash of the hidden names (never the names)."""
    return dict(round_number=run_round, revision=revision, content_hash=package.hash,
                hidden_hash=digest(canonical_json(withheld)))


def _pin_package(store, round_number: int, revision: str, package, withheld) -> None:
    """БУ-12: the second package is pinned in the journal before the first comparison call.

    The same package again (a resume) comes back as the same event, with no second one; another
    package in the same round is refused; a changed hidden name is not passed over silently.
    """
    try:
        store.pin(PIN_PACKAGE, **_package_pin(round_number, revision, package, withheld))
    except Refusal:
        raise ContractError("второй пакет при возобновлении не совпал с записанным в журнале "
                            "(изменились разделы, критерии, имена скрытого или карточки)") from None


def _permutation_ok(order, size: int) -> bool:
    return (isinstance(order, (list, tuple)) and len(order) == size
            and all(isinstance(i, int) and not isinstance(i, bool) for i in order)
            and sorted(order) == list(range(size)))


def _check_critics(critics) -> tuple:
    critics = list(critics)
    if len(critics) != 2 or len(set(critics)) != 2 or not all(
            isinstance(c, str) and c.strip() for c in critics):
        raise ContractError(f"нужны ровно два разных критика: {_listed(critics)}")
    return tuple(critics)


def _check_engine(tables) -> None:
    """Phase 0, the engine's own readiness: a corrupt schema or table is found before a paid call."""
    load_schema("idea_proposal")
    load_schema("idea_comparison")
    _sentinel(tables)
    outcome_rules(tables)
    retry_budget(tables)
    abort_limit(tables)
    _attempt_states(tables)


def _check_shape(sections, registries, withheld, tables) -> None:
    """The caller's inputs are the right shape — `ContractError` otherwise (never the author's fault)."""
    shown = comparison_sections(tables, STAGE)
    if not isinstance(sections, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in sections.items()):
        raise ContractError("sections: нужен словарь строка -> строка")
    if set(sections) != shown:
        raise ContractError(f"sections: нужны ровно разделы {sorted(shown)}")
    if not isinstance(registries, dict):
        raise ContractError("registries: нужен словарь")
    _withheld_checked(tables, withheld, True)


def _blind_checker(criteria, tables, withheld):
    """The check of a blind card: the answer's own validation and what the second package will judge."""
    def blind_card(raw, critic=None):
        card = validate_proposal(raw, criteria, tables)
        fits_package(card, tables, withheld)    # what the package will judge, before the set exists
        return card
    return blind_card


def _compare_checker(ids, criteria, tables):
    def compare(raw, critic):
        return validate_comparison(raw, candidate_ids=ids, criteria=criteria, critic=critic, tables=tables)
    return compare


def _check_recorded(store, state, run: "_Run", blind_package, tables) -> dict:
    """Phase 0: whatever the journal already holds for the phase that is open is read back and judged
    -- hash, receipt, question, content -- before the first write or call (БУ-14).

    Blind answers are read only while the set of cards does not exist; once it does, only the
    comparisons are (against the recorded candidates in the recorded order). A second package that
    does not build here is left to the phase itself, which closes the run as incomplete.

    Returns the one reading: (stage, critic) -> the judged answers of the open phase (empty if the phase never
    reads the journal). The phase and the resume decision use it; the bytes are not judged again.
    """
    round_number = run.round_number
    if not state.idea_candidates:
        check = _blind_checker(run.criteria, tables, run.withheld)
        return {(BLIND_STAGE, critic): _recorded(store, state, tables, BLIND_STAGE, round_number, critic, check,
                                                 _question("blind", critic, blind_package.material()))
                for critic in run.critics}
    permutation = state.idea_candidates_permutation
    if not _permutation_ok(permutation, len(state.idea_candidates)):
        raise ContractError("журнал: перестановка не соответствует записанному набору")
    ids = [state.idea_candidates[i].candidate_id for i in permutation]
    try:
        package = _second_package(run, state.idea_candidates, permutation)
    except PackageRefused:
        return {}
    compare = _compare_checker(ids, run.criteria, tables)
    return {(COMPARE_STAGE, critic): _recorded(store, state, tables, COMPARE_STAGE, round_number, critic, compare,
                                               _question("compare", critic, package.material()))
            for critic in run.critics}


def _check_state(store, tables):
    """The journal is a run of THIS stage, started and still open for it; returns the loaded state."""
    state = store.load()
    if state.stage != STAGE:
        raise ContractError(f"прогон другой стадии: {state.stage!r}, нужна {STAGE!r}")
    if state.state is None:
        raise ContractError("прогон не запущен: сначала операция start")
    incomplete = tables.decide("идёт_круг", "вердикт", {"verdict": incomplete_verdict(tables)}).to
    if state.state not in ("создан", "идёт_круг", incomplete):
        raise ContractError(f"стадия завершена: прогон в состоянии {state.state!r}")
    return state


def _card_checks(tables, sections, registries, withheld, criteria, criteria_view, author_card) -> tuple:
    """The checks of the author's card and of the input around it -- phase 0 of the stage AND of a correction.

    The task, criteria and hidden names go through the package's own checks first; a card the package
    refuses is `AuthorCardRefused`, a shape it cannot read is `ContractError`. Returns `(author, blind_package)`.
    """
    try:
        check_comparison_inputs(sections, registries, STAGE, tables, withheld, criteria_view)
    except PackageRefused as refused:
        if refused.reason == "некорректный_вход":              # a shape the package cannot read: the caller's
            raise ContractError(f"вход пакета: {refused.reason}: {_clip(refused.detail)}") from None
        raise AuthorCardRefused(f"вход пакета не принят: {refused.reason}") from None
    author = check_author_card(author_card, criteria, tables, withheld)
    return author, _blind_package((sections, registries, withheld, criteria_view), author, tables)


def _revision_of(card) -> str | None:
    """The revision of an author's card: the sha256 of its canonical bytes (`card_bytes`) -- or None for a card that does not read."""
    try:
        return digest(card_bytes(parse_answer(card)))
    except (AnswerRejected, PackageRefused, KeyError, TypeError, ValueError, AttributeError):
        return None


def _frame(sections, registries, criteria_view, critics, withheld) -> dict:
    """The input of the stage WITHOUT the author's card: task, registries, criteria, critics, hidden names (as a hash).

    A correction changes the card only; the frame is what stays, and its hash is kept with every input pin.
    """
    return {"разделы": sections, "реестры": registries, "критерии": criteria_view, "критики": list(critics),
            "withheld": digest(canonical_json(withheld))}


def _input_pin(round_number: int, revision: str, run_inputs: dict, frame: dict) -> dict:
    return dict(round_number=round_number, revision=revision, content_hash=digest(canonical_json(run_inputs)),
                frame_hash=digest(canonical_json(frame)))


def _pin_inputs(store, pin: dict, *, write: bool) -> None:
    """The caller's inputs are pinned at the first entry; a resumed run with other inputs is refused.

    Compared BEFORE the package is rebuilt: a changed input must not close the run as
    incomplete -- the run stays fit for the corrected input. With `write=False` only the comparison
    is made; the event is written by the second call.
    """
    if write:
        try:
            store.pin(PIN_INPUT, **pin)
        except Refusal:
            raise ContractError(_INPUT_CHANGED) from None
        return
    if isinstance(store.pin_status(store.load(), PIN_INPUT, **pin), str):
        raise ContractError(_INPUT_CHANGED)


_INPUT_CHANGED = ("вход стадии при возобновлении не совпал с записанным в журнале "
                  "(изменились разделы, реестры, критерии, карточка автора или имена скрытого)")


def _blind_package(run_inputs: tuple, author: dict, tables):
    """The real blind package the first-phase critic gets: the task, with the author's card hidden.

    `предложенное_решение` is the author's card text; the author and the second critic come
    from `withheld`. The criteria go in as the package's own `критерии` block (the critic answers by
    their IDs). A refusal by the content (the card's trace, a criterion) is `AuthorCardRefused`; one
    about the build root or a shape is ours.
    """
    sections, registries, withheld, criteria_view = run_inputs
    hidden = {**withheld, "предложенное_решение": card_bytes(author).decode("utf-8")}
    try:
        with tempfile.TemporaryDirectory() as root:
            return build_package(root, [], sections, registries, STAGE, blind=True, tables=tables,
                                 withheld=hidden,
                                 criteria=criteria_view)
    except PackageRefused as refused:
        if refused.reason in ("путь_запрещён", "файл_нечитаем", "некорректный_вход"):
            raise ContractError(f"слепой пакет не собирается: {refused.reason}: {_clip(refused.detail)}") from None
        raise AuthorCardRefused(f"слепой пакет не принят: {refused.reason}") from None


def _second_package(run: _Run, candidates, permutation):
    return build_comparison_package(
        run.sections, run.registries, STAGE, candidates, permutation,
        tables=run.tables, withheld=run.withheld, criteria=run.criteria_view)


def _author_id(candidates) -> str:
    authors = [c.candidate_id for c in candidates if c.source == AUTHOR_SOURCE]
    if len(authors) != 1:
        raise ContractError(f"в записанном наборе авторских карточек {len(authors)}, нужна одна")
    return authors[0]


def _phase_blind(run: _Run, blind_package) -> tuple:
    """Phase A: each critic proposes blind; a card the second package would refuse is a bad answer."""
    blind_card = _blind_checker(run.criteria, run.tables, run.withheld)
    return _collect(
        run, stage=BLIND_STAGE, phase="blind", package=blind_package.material(), check=blind_card)


def _draw_set(run: _Run, cards: list, new_id, shuffle) -> tuple:
    """The engine makes the IDs and the order of a set and builds the whole second package as a trial.

    `cards`: `[(source, canonical bytes)]`. Returns `(candidates, order, package, None)` or, when the
    package would not build, `(None, None, None, reason)`. Nothing is written: the caller decides.
    Phase B and the correction (a new round) draw their sets here, by the same rules.
    """
    sentinel = _sentinel(run.tables)
    make_id = new_id or (lambda: "cand_" + secrets.token_hex(4))
    ids = [make_id() for _ in cards]
    if not all(isinstance(i, str) and i.strip() for i in ids):
        raise ContractError(f"движок выдал пустой candidate_id: {_listed(ids)}")
    if len(set(ids)) != len(ids):
        raise ContractError(f"движок выдал повторяющиеся candidate_id: {_listed(ids)}")
    if sentinel in ids:
        raise ContractError("движок выдал candidate_id, равный выбору «нет подходящего»")
    order = list(range(len(cards)))
    (shuffle or secrets.SystemRandom().shuffle)(order)
    if not _permutation_ok(order, len(cards)):
        raise ContractError(f"перестановка {_clip(order)} не из {len(cards)} карточек")
    candidates = [IdeaCandidate(i, source, data) for i, (source, data) in zip(ids, cards)]
    try:
        package = _second_package(run, candidates, order)
    except PackageRefused as refused:
        return None, None, None, f"второй пакет из этих карточек не собирается: {refused.reason}"
    return candidates, order, package, None


def _phase_set(run: _Run, author: dict, proposals: dict, new_id, shuffle) -> tuple:
    """Phase B: the engine makes the IDs and the order, builds the whole second package, and only then writes.

    The write of the set is the point of no return, so the second package is built in full first
    (`_draw_set`): total size, grams and hashes across card borders. A refusal leaves the journal clean.
    Returns `(package, None)` or `(None, reason)`.
    """
    cards = [(AUTHOR_SOURCE, card_bytes(author))] + [(c, card_bytes(proposals[c])) for c in run.critics]
    candidates, order, package, reason = _draw_set(run, cards, new_id, shuffle)
    if package is None:
        return None, reason
    run.store.assign_idea_candidates(candidates, order)
    return package, None


def _phase_compare(run: _Run, state, expected, proposals, rejections) -> StageResult:
    """Phase C: both critics compare the same package; the outcome is the table's."""
    candidates = state.idea_candidates
    permutation = state.idea_candidates_permutation
    if not _permutation_ok(permutation, len(candidates)):
        raise ContractError("журнал: перестановка не соответствует записанному набору")
    author_id = _author_id(candidates)
    ids = [candidates[i].candidate_id for i in permutation]
    try:
        package = _second_package(run, candidates, permutation)
    except PackageRefused as refused:         # a set written by somebody else, or a table that changed: the last net
        return _finish(run, None, proposals, {}, rejections,
                       f"второй пакет из записанного набора не собирается: {refused.reason}",
                       cause=CAUSE_INPUT_NOT_BUILT)
    if expected is not None and not same_package(expected, package):
        raise ContractError("второй пакет, собранный из журнала, не равен собранному до записи набора")
    _pin_package(run.store, run.round_number, run.revision, package, run.withheld)

    compare = _compare_checker(ids, run.criteria, run.tables)
    comparisons, compare_rejections = _collect(
        run, stage=COMPARE_STAGE, phase="compare", package=package.material(), check=compare)
    rejections = {**rejections, "compare": compare_rejections}
    valid = {c: v for c, v in comparisons.items() if v is not None}
    if len(valid) < len(run.critics):
        missing = [c for c in run.critics if c not in valid]
        return _finish(run, None, proposals, valid, rejections,
                       f"сравнение: нет валидного ответа у {_listed(missing)}")
    first, second = (comparisons[c] for c in run.critics)
    outcome = decide_outcome(first, second, author_id=author_id,
                             framing_open=OBJECTION_FLAG in state.flags, tables=run.tables)
    return _finish(run, outcome, proposals, valid, rejections)


_RESUME_REFUSALS = {
    "ПРОДОЛЖИТЬ_НЕЧЕМ": "у критиков без валидного ответа не осталось ни повтора, ни вызова",
    "НУЖНА_КОРРЕКЦИЯ_ВХОДА": "вход не ведёт вперёд (второй пакет не собирается либо новый круг без закреплённого "
                             "входа): нужна коррекция входа, а не продолжение",
}


def _resume_open(store, run: _Run, state, tables) -> tuple:
    """БУ-13: the table's decision on continuing an incomplete run, before any write.

    The conditions are counted by the store from its journal; the one thing the caller's reading adds is
    which received-but-unjudged answers it found invalid (it can only take budget away). A refusal is
    raised as `ResumeImpossible` and writes nothing. Returns what `_resume` needs.
    """
    stage = COMPARE_STAGE if state.idea_candidates else BLIND_STAGE
    invalid = tuple((state.run_id, stage, run.round_number, critic, item.number)
                    for (_, critic), seen in run.snapshot.items() for item in seen
                    if not item.accepted and state.attempts[(state.run_id, stage, run.round_number, critic,
                                                             item.number)].validation is None)
    conditions = store.resume_conditions(invalid)
    refusal = tables.decide(state.state, "resume", conditions).refusal
    if refusal is not None:
        raise ResumeImpossible(refusal, _RESUME_REFUSALS.get(refusal, ""))
    return invalid


def _resume(store, invalid: tuple) -> None:
    """Apply the continuation as the operation `resume` (the store recounts the conditions itself)."""
    try:
        operation = store.submit("resume", body={"reason": "продолжение неполного прогона"}, invalid_attempts=invalid)
    except Refusal as refusal:
        raise ContractError(f"продолжение отвергнуто: {refusal}") from None
    if operation.refusal is not None:
        raise ResumeImpossible(operation.refusal, _RESUME_REFUSALS.get(operation.refusal, ""))


def run_idea_stage(store, *, criteria, author_card, ask, sections, withheld, registries=None,
                   critics=("claude", "codex"),
                   new_id=None, shuffle=None, tables=None) -> StageResult:
    """Run the «идея» stage end to end against a locked `RunStore`.

    `ask(critic, request)` is the only paid call. Phase 0 runs before it can be
    reached. `new_id` / `shuffle` are injection points for tests; by default
    IDs and the permutation come from `secrets` (identity permutation allowed).

    A request is `{phase, critic, attempt, package, previous_rejection}`: the task, the
    criteria and (in the second phase) the candidates reach the critic only inside `package`.

    `sections` (exactly the shown task sections), `registries` (default: empty) and `withheld`
    (the NAMES of both critics: `{"автор": ..., "второй_критик": ...}`; the proposed solution
    is the author's card and is added here) feed both packages. The second one is built by
    `context.build_comparison_package` from the journal's cards and permutation only -- so a
    resumed run builds the same bytes.

    Errors: a wrong shape of the caller's inputs, a corrupt table or journal, a changed input on
    resume -- `ContractError`; the content of the author's card, the criteria or the sections
    -- `AuthorCardRefused`. An incomplete run (`НЕПОЛНЫЙ_ПРОГОН`) is a result, not an error.

    Resuming (БУ-13, БУ-14): entering a run again -- after a break, or an incomplete verdict --
    continues it in the same run and round. The answers come ONLY from the journal: the bytes of
    each received answer, read back with their hash, attempt and question checked, then judged again;
    nothing the caller hands in can stand in for one (there is no parameter for it). A valid answer is
    not asked for again, spent attempts stay spent, a changed input is refused before any write or
    call. An incomplete run is continued by the table's row `resume`; when the critics without a
    valid answer have no attempts left (retries or cut-off calls used up) the row's refusal is raised
    as `ResumeImpossible` (`ПРОДОЛЖИТЬ_НЕЧЕМ`) and the run stays as it was -- a changed input then goes
    through the correction of the clarification block (БУ, part 2), not through this call.

    Phase 0 refuses in this order: the shape of the inputs, the run's stage, its state, then the
    cards and criteria, then what the journal already holds (read back and judged), then the
    exhausted budget of an incomplete run. Writing the input pin before the `пакет_собран` event
    closes the window in which a crash would leave the run started but not pinned. If the `fit` of
    the author's card repeats a criterion's text word for word, the author is refused by the trace of
    the hidden: retell it in your own words (the check is not loosened).
    """
    tables = _tables(tables)
    critics = _check_critics(critics)
    _check_engine(tables)                                                  # phase 0
    _check_shape(sections, {} if registries is None else registries, withheld, tables)
    state = _check_state(store, tables)                                    # the stage, then the state
    registries = {"решения": [], "области": [], "журнал_доказательств": []} if registries is None else registries
    parsed_criteria = validate_criteria(criteria)
    criteria_view = [{"id": c.id, "text": c.text, "mandatory": c.mandatory} for c in parsed_criteria]
    card_print = _revision_of(author_card)                                # None: refused below, by the card's own check
    round_number = max(state.round_number, 1)
    revision = card_print or "карточка_не_разобрана"
    frame = _frame(sections, registries, criteria_view, critics, withheld)
    input_pin = _input_pin(round_number, revision, {**frame, "карточка": card_print}, frame)
    _pin_inputs(store, input_pin, write=False)                             # before anything is rebuilt
    author, blind_package = _card_checks(tables, sections, registries, withheld, criteria, criteria_view, author_card)
    if digest(card_bytes(author)) != card_print:
        raise ContractError("редакция карточки не сходится с хешем её канонических байтов")

    run = _Run(store, ask, tables, critics, parsed_criteria, criteria_view, sections, registries, withheld,
               round_number, revision)
    run = replace(run, snapshot=_check_recorded(store, state, run, blind_package, tables))
    incomplete = state.state == tables.decide(
        "идёт_круг", "вердикт", {"verdict": incomplete_verdict(tables)}).to
    if incomplete:                                   # БУ-13: the journal counts the conditions, the table decides
        resume_open = _resume_open(store, run, state, tables)
    _pin_inputs(store, input_pin, write=True)        # the pin first: a crash after it cannot admit other inputs
    if incomplete:
        _resume(store, resume_open)
        state = store.load()
    elif state.state == "создан":
        state = store.record_event("пакет_собран")

    proposals: dict = {}
    rejections: dict = {}
    expected = None
    if not state.idea_candidates:
        proposals, blind_rejections = _phase_blind(run, blind_package)     # phase A
        rejections["blind"] = blind_rejections
        if sum(v is not None for v in proposals.values()) < len(critics):
            missing = [c for c in critics if proposals[c] is None]
            return _finish(run, None, proposals, {}, rejections,
                           f"слепая фаза: нет валидного предложения у {_listed(missing)}")
        expected, reason = _phase_set(run, author, proposals, new_id, shuffle)             # phase B
        if expected is None:
            return _finish(run, None, proposals, {}, rejections, reason, cause=CAUSE_INPUT_NOT_BUILT)
        state = store.load()
    return _phase_compare(run, state, expected, proposals, rejections)  # phase C


# --------------------------------------------------------------------------
# БУ-15, БУ-9, БУ-5, БУ-10: Anton's OK -- a trusted source, a record, a real transition
# --------------------------------------------------------------------------

def ok_marker(run_id: str, revision: str, tables=None) -> str:
    """The line the assistant prints before asking for the OK: the run and the short hash of the revision.

    The form is `vocabulary.ок_антона.маркер`. An OK counts for the revision whose marker stood in the
    answer right before the reply -- the engine does not take the hash from the reply itself.
    """
    spec = _tables(tables).vocabulary["ок_антона"]
    return spec["маркер"].replace("{прогон}", run_id).replace("{хеш}", revision[:spec["длина_хеша"]])


def _markers_shown(turn: str, spec: dict) -> set:
    head, tail = spec["маркер"].split("{прогон}")
    middle, end = tail.split("{хеш}")
    pattern = re.escape(head) + r"([^\s,]+)" + re.escape(middle) + r"([0-9a-f]{%d})(?![0-9a-f])" % spec["длина_хеша"] + re.escape(end)
    return set(re.findall(pattern, turn))


def _parse_time(value):
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _shown_problem(state, revision: str, found: dict, spec: dict, tables) -> tuple:
    """`(problem, fork)`: the marker of this run and of the current revision stands in the LAST text block of the assistant
    before the reply (in fork mode inside the card after 🗳). One check for the OK and for Anton's correction."""
    block = found["last_text"]
    if block is None:
        return "перед репликой нет текстового блока ассистента: вопроса, на который она отвечает, нет", False
    fork = "🗳" in block
    shown = _markers_shown(block[block.rindex("🗳"):] if fork else block, spec)
    if shown != {(state.run_id, revision[:spec["длина_хеша"]])}:
        return ("в последнем блоке ассистента перед репликой" + (" (в карточке после 🗳)" if fork else "")
                + f" нет строки с этим прогоном и текущей редакцией ({ok_marker(state.run_id, revision, tables)})"
                  " или есть строка с другими"), fork
    return None, fork


def _after_verdict_problem(state, found: dict) -> str | None:
    """The reply and the block of the assistant are not older than the last verdict of the current round."""
    verdict_at = _parse_time(state.last_verdict_at)
    for what, stamp in (("реплика", found["timestamp"]), ("блок ассистента с вопросом", found["last_text_at"])):
        moment = _parse_time(stamp)
        if moment is None:
            return f"у записи «{what}» нет времени в переписке: порядок относительно вердикта не доказать"
        if verdict_at is None or moment < verdict_at:
            return f"{what} раньше последнего вердикта текущего круга"
    return None


def _ok_problem(store, state, spec: dict, basis, home) -> tuple:
    """`(fields, None)` for an OK that is counted, `(None, problem)` for one that is not.

    Judged first by the journal (`RunStore.ok_journal_problem`: a revision is pinned, the critics judged it,
    the verdict is of this round, the session is the run's own). Then by the transcript, read ONCE:
    * the reply is a human's (`tables.transcript_reply`), and it is ONLY the bare word of consent
      (`ок`, `да`, `согласен`…) or, when the question was a fork card, a verbatim copy of its «yes» option
      (`resolve_basis(consent=True)`); «ОК на <что угодно>» is not an OK -- what is approved is held by the marker;
    * the marker line (this run, the whole hash of the current revision's first `длина_хеша` signs) stands in
      the LAST text block of the assistant -- the parent of the reply -- and in fork mode inside the card after 🗳;
    * that block and the reply are not older than the last verdict of the current round.
    """
    problem = store.ok_journal_problem(state, basis["сессия"])
    if problem:
        return None, problem
    revision = state.input_revision
    found = tables_module.transcript_reply(basis["сессия"], basis["native_uuid"], home)
    if isinstance(found, str):
        return None, found
    own = found["own"]
    if not found["human_prompt"]:
        return None, "основание — не реплика человека (служебная запись или результат инструмента)"
    if found["inserted"]:
        # a cut-out insertion next to the word is not "the human's words alone": decided BEFORE either branch
        return None, ("в реплике есть вставка (служебный или вставленный чужой текст): ОК даёт реплика, в которой "
                      "нет ничего, кроме слов человека")
    problem, fork = _shown_problem(state, revision, found, spec, store.tables)
    if problem:
        return None, problem
    if fork:
        quote = own.strip(" \t\r\n\x00")
        problem = tables_module.resolve_basis(
            {"вид": "событие_транскрипта", "сессия": basis["сессия"], "native_uuid": basis["native_uuid"],
             "цитата": quote, "подвид": "выбор_варианта"}, home, consent=True, records=found["records"])
    else:
        problem = tables_module.bare_consent_problem(own)
    if problem:
        return None, problem
    problem = _after_verdict_problem(state, found)
    if problem:
        return None, problem
    return {"session": basis["сессия"], "native_uuid": basis["native_uuid"], "reply_at": found["timestamp"],
            "run_id": state.run_id, "stage": state.stage, "artifact": spec["артефакт"], "revision": revision,
            "round_number": max(state.round_number, 1)}, None


def record_anton_ok(store, basis, home=None):
    """Record Anton's OK on the current revision -- only from a reply in the transcript (БУ-15).

    `basis` is a reference to a record of the session, `{"сессия": ..., "native_uuid": ...}` and nothing
    else: no `actor`, no text, no hash. The record ties the source (session, uuid, time of the reply),
    the run, the stage, the artifact and the hash of the revision (БУ-9). Not counted -> `AntonOkRefused`
    with the table's code, nothing written. The same reply again is the same record; another reply
    makes a new one (before the exit); none of them makes a transition (that is `leave_idea_stage`).
    """
    tables = store.tables
    spec = tables.vocabulary["ок_антона"]
    if not isinstance(basis, Mapping) or set(basis) != {"сессия", "native_uuid"}:
        raise ContractError("основание ОК: только ссылка на запись переписки {сессия, native_uuid}")
    state = store.load()
    if state.stage != spec["этап"]:
        raise ContractError(f"прогон другой стадии: {state.stage!r}, ОК даётся на {spec['этап']!r}")
    if state.state == "завершён" and state.stage_exit_position >= 0:
        # the exit is made and `завершён` has no way out: the same reply is the record already kept, a new one is not needed
        for old in state.anton_oks:
            if (old.session, old.native_uuid) == (basis["сессия"], basis["native_uuid"]):
                return old
        raise AntonOkRefused("ОК_НЕ_ЗАСЧИТАН", "переход со стадии уже совершён: новый ОК не нужен")
    if state.state != "ждёт_Антона":
        raise AntonOkRefused("ОК_НЕ_ЗАСЧИТАН", f"прогон в состоянии {state.state!r}: ОК давать не на что")
    fields, problem = _ok_problem(store, state, spec, basis, home)
    refusal = tables.decide(state.state, spec["событие"], {"ok_binding": problem is None}).refusal
    if refusal is not None:
        raise AntonOkRefused(refusal, problem or "")
    try:
        return store._record_anton_ok(**fields)
    except Refusal as refused:
        if refused.code == "ОК_НЕ_ЗАСЧИТАН":
            raise AntonOkRefused(refused.code, refused.detail) from None
        raise ContractError(f"запись ОК отвергнута: {refused}") from None


def require_anton_ok(store) -> None:
    """Refuse unless the exit is open: an OK on the current revision after the current verdict, no open objection.

    The answer is the table's (`run.yaml`, `этап_пройден`): the code of the refusal, never an invented one.
    A read of the journal; the transcript is looked at again by `leave_idea_stage`.
    """
    state = store.load()
    if state.state != "ждёт_Антона":
        raise AntonOkRequired(f"прогон в состоянии {state.state!r}, ждать ОК нечего")
    spec = store.tables.vocabulary["ок_антона"]
    flag = store.tables.framing["флаг_прогона"]
    standing, detail = ok_standing(state, spec)
    outcome = store.tables.decide(state.state, spec["переход"], {
        "anton_ok": standing, "framing_objection": flag in state.flags})
    if outcome.refusal is not None:
        raise AntonOkRequired(detail or "открыто возражение к постановке — оно держит стадию", code=outcome.refusal)


def leave_idea_stage(store, home=None) -> bool:
    """БУ-5, БУ-10: leave the stage through the table, only on Anton's recorded OK.

    Checks the journal (the last verdict of the current round, an OK on the current revision after it, the
    revision judged, no open objection to the framing), then looks at the transcript AGAIN: the reply of the
    last counted OK must still be there and still be what it was (a vanished or changed reply shuts the exit,
    `ОК_УСТАРЕЛ`). Then the store makes the transition `этап_пройден` and counts the conditions itself.
    Without the OK -- the table's refusal code, however much the critics agree. A repeat (or a restart) finds
    the exit already made: `True` again, no second transition.
    """
    state = store.load()
    spec = store.tables.vocabulary["ок_антона"]
    if state.stage != spec["этап"]:
        raise ContractError(f"прогон другой стадии: {state.stage!r}, выходим со стадии {spec['этап']!r}")
    if state.stage_exit_position >= 0:
        return True
    require_anton_ok(store)
    last = [o for o in state.anton_oks
            if o.revision == state.input_revision and o.position > state.last_verdict_position][-1]
    fields, problem = _ok_problem(store, state, spec, {"сессия": last.session, "native_uuid": last.native_uuid}, home)
    if problem is None and (fields["reply_at"], fields["revision"]) != (last.reply_at, last.revision):
        problem = "реплика ОК в переписке изменилась"
    if problem is not None:
        raise AntonOkRequired(f"реплика последнего ОК больше не подтверждается: {problem}", code="ОК_УСТАРЕЛ")
    try:
        store._record_stage_exit()
    except Refusal as refused:
        raise AntonOkRequired(refused.detail, code=refused.code) from None
    return True


# --------------------------------------------------------------------------
# БУ-1 … БУ-8, БУ-16: the correction -- one turn of the refinement cycle
# --------------------------------------------------------------------------

def _correction_reply_problem(state, spec_ok: dict, found, tables) -> str | None:
    """Anton's word behind a correction, judged on the ONE reading of the transcript (`found`).

    Required for ANY correction, whoever composed the card: his human reply (no service record, no tool result,
    no plan approval), without inserted text, words and not a consent in any form (a formula, a «yes» option, a
    reply that begins with a word of consent), no negation, no question; after the answer that shows the
    current revision (the marker in the last text block) and not older than the last verdict.
    """
    if isinstance(found, str):
        return found
    if not found["human_prompt"]:
        return "основание — не реплика человека (служебная запись или результат инструмента)"
    if found["inserted"]:
        return "в реплике есть вставка (служебный или вставленный чужой текст): основанием годятся только слова человека"
    problem = tables_module.correction_reply_problem(found["own"], found["chose_yes"])
    if problem:
        return problem
    problem, _ = _shown_problem(state, state.input_revision, found, spec_ok, tables)
    return problem or _after_verdict_problem(state, found)


def _correction_arguments(store, tables, new_card, source, basis, criteria, sections, withheld, registries, critics):
    """Step 1: the shape of the arguments and the state of the run; returns `(critics, registries, state)`."""
    spec_c = tables.vocabulary["цикл_уточнений"]
    critics = _check_critics(critics)
    _check_engine(tables)
    registries = {"решения": [], "области": [], "журнал_доказательств": []} if registries is None else registries
    _check_shape(sections, registries, withheld, tables)
    state = store.load()
    if state.stage != STAGE:
        raise ContractError(f"прогон другой стадии: {state.stage!r}, нужна {STAGE!r}")
    if state.state not in ("ждёт_Антона", "неполный"):
        raise CorrectionRefused("ПОПРАВКА_НЕВОЗМОЖНА", f"прогон в состоянии {state.state!r}: поправка возможна после показа "
                                                       "Антону или в неполном прогоне")
    if source not in spec_c["источники"]:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", f"источник поправки {source!r}: нужен один из {spec_c['источники']}")
    return critics, registries, state


def _correction_basis_shape(basis) -> None:
    """Step 2b: a correction without a reference to Anton's reply is not counted -- whoever composed the card."""
    if not isinstance(basis, Mapping) or set(basis) != {"сессия", "native_uuid"}:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", "поправка без слова Антона не засчитывается: нужна ссылка "
                                                         "{сессия, native_uuid} на его реплику")


def _correction_card(state, tables, new_card, criteria, sections, registries, withheld, critics) -> tuple:
    """Step 2: the new card passes the checks of phase 0 and is a revision the run has never judged.

    Returns `(author bytes, blind package, revision, input pin)`. Refused with nothing written: the same
    revision as now or as ANY earlier one of the run (a return to an old card), a copy of a critic's card.
    """
    parsed = validate_criteria(criteria)
    criteria_view = [{"id": c.id, "text": c.text, "mandatory": c.mandatory} for c in parsed]
    revision = _revision_of(new_card)
    author, blind_package = _card_checks(tables, sections, registries, withheld, criteria, criteria_view, new_card)
    data = card_bytes(author)
    if revision is None or digest(data) != revision:
        raise ContractError("редакция карточки не сходится с хешем её канонических байтов")
    if revision == state.input_revision:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", "та же редакция, что текущая: поправка без изменения")
    if revision in {p.revision for p in state.pins if p.event == PIN_INPUT}:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", "возврат к прежней редакции прогона: она уже была судима, оборот не тратится")
    if any(c.source != AUTHOR_SOURCE and c.canonical_bytes == data for c in state.idea_candidates):
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", "карточка автора побайтово равна карточке критика: дубль в наборе "
                                                         "для сравнения бессмыслен")
    frame = _frame(sections, registries, criteria_view, critics, withheld)
    pin = _input_pin(max(state.round_number, 1) + 1, revision, {**frame, "карточка": revision}, frame)
    first = next((p for p in state.pins if p.event == PIN_INPUT), None)
    if first is not None and first.frame_hash is not None and pin["frame_hash"] != first.frame_hash:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", "изменилась рамка входа (задача, ограничения, критерии, критики, "
                                                         "скрытые имена): это новый прогон, а не поправка")
    return data, blind_package, revision, pin, parsed, criteria_view


def _correction_proof(store, state, tables, basis, home) -> dict:
    """Step 3: Anton's word. The transcript is read ONCE; returns the basis as the journal keeps it."""
    spec_ok = tables.vocabulary["ок_антона"]
    found = tables_module.transcript_reply(basis["сессия"], basis["native_uuid"], home)
    problem = _correction_reply_problem(state, spec_ok, found, tables)
    if problem:
        raise CorrectionRefused("ПОПРАВКА_НЕ_ЗАСЧИТАНА", problem)
    words = found["own"].strip()
    return {"session": basis["сессия"], "native_uuid": basis["native_uuid"], "reply_at": found["timestamp"],
            "words_hash": digest(words.encode("utf-8")), "words_clip": words[:200]}


def _correction_kept_cards(store, state, tables, critics, parsed_criteria, withheld, blind_package) -> list:
    """The critics' cards that stay: those of the past set byte for byte, or -- if no set was ever made -- their valid blind proposals."""
    if state.idea_candidates:
        return [(c.source, c.canonical_bytes) for c in state.idea_candidates if c.source != AUTHOR_SOURCE]
    check = _blind_checker(parsed_criteria, tables, withheld)
    kept = []
    for critic in critics:
        seen = _recorded(store, state, tables, BLIND_STAGE, max(state.round_number, 1), critic, check,
                         _question("blind", critic, blind_package.material()))
        valid = [item for item in seen if item.accepted]
        if not valid:                                   # the dead end has its own row in the table
            refusal = tables.decide("неполный", "поправка", {"blind_cards_ready": False}).refusal
            raise CorrectionRefused(refusal, f"у критика {critic} нет валидного слепого предложения: слепая фаза не повторяется")
        kept.append((critic, card_bytes(valid[0].value)))
    return kept


def submit_correction(store, *, new_card, source, basis, criteria, sections, withheld, from_candidate=None,
                      home=None, registries=None, critics=("claude", "codex"), new_id=None, shuffle=None,
                      tables=None):
    """One turn of the cycle: a corrected card of the author opens a NEW comparison round (БУ-1 … БУ-8, БУ-16).

    NO correction is counted without Anton's word: `basis` is the reference `{сессия, native_uuid}` to his reply
    in the transcript, proven here -- for any `source`. `source` says who COMPOSED the card: `антон` (by his
    words) or `автор` (by the critics' findings, with his consent). So neither a turn, nor a paid call, nor the stop
    at the ceiling can happen without him. His words are kept as a hash and a clip of 200 signs; one reply serves once.

    From `ждёт_Антона` (after the show) or an incomplete run that cannot go on by itself. Only the author's
    card changes; the frame (task, constraints, criteria, critics, hidden names) is the pinned one -- another
    frame is a new run. The new card passes the checks of phase 0 before any write; the same card as now, a
    return to any earlier card of the run and a copy of a critic's card are refused. `from_candidate` names a
    candidate of a past round the revision grew from; its source is the journal's, the critics' cards stay as they
    are. One journal entry carries the whole turn (new revision, new set with new IDs and order, the pins of the new
    round, the stale mark for the old scores). The comparison is then run by `run_idea_stage` with the new card:
    only the second phase, with the budget of the new round. The call itself makes no paid call.

    Returns the new state. Raises: `CorrectionRefused` (a named code, nothing written: wrong state, no basis,
    the reply is no correction, same/earlier revision, a copy, another frame, the run can go on without it, no blind
    cards); `RefinementCeiling` (the stop IS written: the run is terminal, `.history` has every turn);
    `AuthorCardRefused` (the new card is unfit, or the second package would not build); `ContractError` (a wrong
    shape of the inputs, a corrupt table or journal, a run of another stage); `TypeError` (an unknown argument).
    """
    tables = tables or store.tables
    spec_c = tables.vocabulary["цикл_уточнений"]
    critics, registries, state = _correction_arguments(store, tables, new_card, source, basis, criteria, sections,
                                                       withheld, registries, critics)
    data, blind_package, revision, input_pin, parsed, criteria_view = _correction_card(
        state, tables, new_card, criteria, sections, registries, withheld, critics)
    _correction_basis_shape(basis)
    wire = _correction_proof(store, state, tables, basis, home)
    run = _Run(store, None, tables, critics, parsed, criteria_view, sections, registries, withheld,
               max(state.round_number, 1) + 1, revision)
    kept = _correction_kept_cards(store, state, tables, critics, parsed, withheld, blind_package)
    candidates, order, package, reason = _draw_set(run, [(AUTHOR_SOURCE, data)] + kept, new_id, shuffle)
    if package is None:
        raise AuthorCardRefused(reason)
    try:
        after = store._record_correction(
            source=source, basis=wire, from_candidate=from_candidate, to_revision=revision, candidates=candidates,
            permutation=order, input_pin=input_pin,
            package_pin={"content_hash": package.hash, "hidden_hash": digest(canonical_json(withheld))})
    except Refusal as refused:
        raise CorrectionRefused(refused.code, refused.detail) from None
    if after.state == spec_c["терминальное"]:
        raise RefinementCeiling("обороты исчерпаны: прогон остановлен для перепроектирования, согласия не будет",
                                store.refinement_history())
    return after
