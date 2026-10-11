#!/usr/bin/env python3
"""Б15 -- the programmatic precheck: mechanical checks of an artefact before round 1.

Zero network calls, zero model calls, zero subscription spend (§7.3) -- which is why
it can be repeated as often as the author likes.

The input is exactly two things:

* the artefact's **frontmatter** (the YAML text between the fences), validated by
  `schemas/precheck_frontmatter.json` with the same closed-subset validator as every
  other schema (`contracts.validate`);
* `PrecheckFacts` -- an immutable snapshot of what the package build established
  (manifest entries, the edition the TRUSTED caller set) or the build's refusal.
  The precheck reads no path from disk and parses no free text: the header's claims
  are compared against facts the artefact cannot write.

The result has four different outcomes (Б15-5). Only `чисто` allows going on; an
unusable input and a failed check are never an empty list of findings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import contracts
from . import tables as tables_module
from .context import ManifestEntry, Package, PackageRefused, check_revision, fold_name

__all__ = ["precheck", "split_frontmatter", "facts_from_package", "facts_from_refusal",
           "PrecheckFacts", "PrecheckResult", "Finding", "CLEAN", "FINDINGS", "BAD_INPUT",
           "CHECK_FAILED", "SCHEMA_NAME", "FRONTMATTER_LIMIT"]

CLEAN = "чисто"
FINDINGS = "находки"
BAD_INPUT = "недопустимый_вход"
CHECK_FAILED = "сбой_проверки"
STATUSES = (CLEAN, FINDINGS, BAD_INPUT, CHECK_FAILED)

SCHEMA_NAME = "precheck_frontmatter"
SCHEMA_DIR = contracts.SCHEMAS_DIR       # a test points it elsewhere to prove the failure path
FRONTMATTER_LIMIT = 64 * 1024
FENCE = "---"
MISSING_FILE_REFUSAL = "отсутствие_обязательного_файла"
REF_PREFIX = "ref:"
HIDDEN = "<значение скрыто>"
NAME_LIMIT = 120
NAME_EXTRA = frozenset("._:/+-")
DEPTH_LIMIT = 32             # flow brackets (`[`, `{`) nested deeper than this are refused before parsing
INDENT_LIMIT = 128           # columns of indentation incl. two per `- ` / `? ` marker
# The refusal reasons the builder can give (a test compares them with the literals in
# context.py): only these may be named in a result, any other refusal text is hidden.
KNOWN_REFUSALS = frozenset({
    "дубль_в_реестре", "жёсткая_ссылка", "запись_вне_схемы",
    "недопустимый_создатель_доказательства", "неизвестная_стадия", "неизвестный_вид_решения",
    "неизвестный_класс_файла", "неизвестный_тип_доказательства", "некорректный_вход",
    "неполное_доказательство", "отсутствие_обязательного_файла", "посторонний_знак",
    "посторонняя_письменность", "похоже_на_секрет", "превышение_размера", "путь_вне_корня",
    "путь_запрещён", "путь_не_канонический", "путь_с_родительским_переходом",
    "раздел_вне_пакета", "раздел_неизвестен", "реестры_не_полны", "симлинк",
    "слепой_вопрос_не_на_этой_стадии", "слепой_вопрос_показывает_лишнее",
    "слепой_пакет_неполон", "слепой_пакет_с_файлами", "слепой_пакет_след_скрытого",
    "слишком_много_файлов", "сравнение_не_на_этой_стадии", "файл_изменился", "файл_не_обычный",
    "файл_не_текст", "файл_нечитаем", "файл_объявлен_дважды"})
NON_STRING_HINT = " (число, дата, on/off, yes/no разбираются не как строка: возьми значение в кавычки)"


@dataclass(frozen=True)
class Finding:
    """One concrete finding: which code, where in the artefact, and why."""

    code: str
    where: str
    reason: str

    def as_tuple(self) -> tuple:
        return (self.code, self.where, self.reason)


@dataclass(frozen=True)
class PrecheckResult:
    """status + findings (ordered, without repeats) + the reason when the input/check is unusable."""

    status: str
    findings: tuple = ()
    reason: str = ""

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"предпроверка: неизвестный статус {self.status!r}")
        if self.status == CLEAN and (self.findings or self.reason):
            raise ValueError("предпроверка: «чисто» не может нести находки или причину")
        if self.status == FINDINGS and not self.findings:
            raise ValueError("предпроверка: «находки» без находок")
        if self.status in (BAD_INPUT, CHECK_FAILED) and (self.findings or not self.reason):
            raise ValueError("предпроверка: отказ без причины или с находками")

    @property
    def allows_continuation(self) -> bool:
        return self.status == CLEAN


@dataclass(frozen=True)
class PrecheckFacts:
    """Immutable facts of one package build.

    Exactly one of two shapes: a built package (`entries` + `revision`, `refusal` is None) or
    the builder's refusal (`refusal` = its reason, `refusal_detail`). A refusal is a fact too,
    but never a clean one.
    """

    entries: tuple = ()
    revision: str | None = None
    refusal: str | None = None
    refusal_detail: str = ""


def facts_from_package(package: Package) -> PrecheckFacts:
    if not isinstance(package, Package):
        raise TypeError("факты берутся только из собранного пакета")
    return PrecheckFacts(entries=tuple(package.manifest), revision=package.revision)


def facts_from_refusal(refused: PackageRefused) -> PrecheckFacts:
    if not isinstance(refused, PackageRefused):
        raise TypeError("отказ сборщика ожидался как PackageRefused")
    return PrecheckFacts(refusal=refused.reason, refusal_detail=refused.detail)


def split_frontmatter(document) -> str | None:
    """The text between the opening and the closing fence, or None when there is none.

    Only the fences are looked for; nothing of the body is read.
    """
    if not isinstance(document, str):
        return None
    lines = document.lstrip("﻿").split("\n")
    if not lines or lines[0].rstrip() != FENCE:
        return None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == FENCE:
            return "\n".join(lines[1:index])
    return None


class _Unusable(Exception):
    """The input cannot be checked (a defect of the input, not of the check)."""


def _bad(reason: str) -> PrecheckResult:
    return PrecheckResult(BAD_INPUT, (), reason)


def _name(value) -> str:
    """A value that may be shown in `where`/`reason`: a clipped name of a closed alphabet.

    Anything else (spaces, controls, invisible marks, a non-string) is replaced by a marker:
    the input is untrusted and its raw text must not travel into the result.
    """
    if (isinstance(value, str) and value and all(ch.isalnum() or ch in NAME_EXTRA for ch in value)):
        return value if len(value) <= NAME_LIMIT else value[:NAME_LIMIT] + "…"
    return HIDDEN


def _number(value) -> str:
    return str(value) if isinstance(value, int) and abs(value) < 10 ** 9 else "вне разумного предела"


def _too_deep(text: str) -> bool:
    """A cheap scan BEFORE the YAML parser: nested flow brackets or a deep indentation."""
    depth = 0
    for char in text:
        if char in "[{":
            depth += 1
            if depth > DEPTH_LIMIT:
                return True
        elif char in "]}" and depth:
            depth -= 1
    for line in text.split("\n"):
        rest = line.lstrip(" ")
        column = len(line) - len(rest)
        while rest[:2] in ("- ", "? "):
            column += 2
            rest = rest[2:].lstrip(" ")
        if column > INDENT_LIMIT:
            return True
    return False


def _parse(frontmatter_text) -> dict:
    if not isinstance(frontmatter_text, str):
        raise _Unusable("фронтматтер: нет текста")
    if not frontmatter_text.strip():
        raise _Unusable("фронтматтер: пусто")
    if len(frontmatter_text) > FRONTMATTER_LIMIT:
        raise _Unusable(f"фронтматтер: длиннее {FRONTMATTER_LIMIT} знаков")
    if _too_deep(frontmatter_text):
        raise _Unusable("фронтматтер: вложенность глубже допустимой")
    try:
        # Aliases are refused before loading: they are the way to make a small text expand.
        if any(isinstance(event, yaml.AliasEvent) for event in yaml.parse(frontmatter_text)):
            raise _Unusable("фронтматтер: ссылки-алиасы не допускаются")
        data = yaml.load(frontmatter_text, Loader=tables_module.StrictLoader)
    except yaml.YAMLError as error:
        raise _Unusable(f"фронтматтер: не разбирается — {type(error).__name__}") from None
    except RecursionError:
        raise _Unusable("фронтматтер: вложенность глубже допустимой") from None
    if not isinstance(data, dict):
        raise _Unusable("фронтматтер: ожидалась карта полей")
    return data


def _property_names(schema) -> set:
    names = set()
    for name, sub in (schema.get("properties") or {}).items():
        names.add(name)
        names |= _property_names(sub)
    if isinstance(schema.get("items"), dict):
        names |= _property_names(schema["items"])
    return names


def _schema_reason(message: str, schema) -> str:
    """Say what is wrong and where, using only names the schema itself knows."""
    known = _property_names(schema)
    place, _, kind = message.partition(": ")
    path = "".join(
        part if part.startswith("[") else "." + (part[1:] if part[1:] in known else HIDDEN)
        for part in re.findall(r"\[\d+\]|\.[^.\[\]]*", place[1:]))
    where = "$" + path
    found = re.match(r"нет поля '([^']*)'", kind)
    if found:
        what = f"нет обязательного поля {found.group(1) if found.group(1) in known else HIDDEN}"
    elif kind.startswith("лишнее поле"):
        what = "лишнее поле"
    elif kind.startswith("ожидался"):
        what = "неверный тип" + NON_STRING_HINT
    elif " не из " in kind:
        what = "значение вне перечня"
    else:
        what = "нарушен предел или форма"
    return f"фронтматтер не по схеме: {where}: {what}"


def _facts_shape(facts, classes) -> None:
    if not isinstance(facts, PrecheckFacts):
        raise _Unusable("факты: нужен PrecheckFacts из сборки пакета")
    if facts.refusal is not None:
        if not isinstance(facts.refusal, str) or not facts.refusal or facts.entries:
            raise _Unusable("факты: отказ сборщика записан неверно")
        return
    if not isinstance(facts.entries, tuple) or not isinstance(facts.revision, str) or not facts.revision:
        raise _Unusable("факты: у пакета нет редакции — её задаёт вызывающий при сборке")
    _revision_ok(facts.revision, "в фактах пакета")
    seen = set()
    for entry in facts.entries:
        if not isinstance(entry, ManifestEntry):
            raise _Unusable("факты: запись манифеста чужого вида")
        if entry.file_class not in classes:
            # An unknown class is neither planned_output nor silence.
            raise _Unusable(f"факты: неизвестный класс файла у {_name(entry.path)}")
        if entry.path in seen:
            raise _Unusable(f"факты: путь {_name(entry.path)} в манифесте дважды")
        seen.add(entry.path)


def _revision_ok(revision, side: str) -> None:
    """The edition obeys the very rule the package build applies to it."""
    try:
        check_revision(revision)
    except PackageRefused:
        raise _Unusable(f"редакция {side} вне допустимой длины или алфавита") from None


def _refusal_reason(refusal) -> str:
    return refusal if refusal in KNOWN_REFUSALS else "причина скрыта"


# -- the five codes ----------------------------------------------------------

def _broken_anchor(front, facts, found):
    declared = {anchor for section in front["sections"] for anchor in section["anchors"]}
    for reference in front["references"]:
        if not reference.startswith(REF_PREFIX) or len(reference) == len(REF_PREFIX):
            raise _Unusable("ссылка: ожидалось ref:<имя>")
    for reference in front["references"]:
        if reference not in declared:
            found.append(Finding("BROKEN_ANCHOR", _name(reference), "якорь не объявлен ни одним разделом"))


def _missing_evidence(front, facts, found):
    """The header answers for what it claimed: an `existing_evidence` of the manifest that the
    header does not mention is fine here -- the builder itself already required that file to
    exist and hashed it.
    """
    if facts.refusal is not None:
        if facts.refusal == MISSING_FILE_REFUSAL:
            found.append(Finding("MISSING_EXISTING_EVIDENCE", _name(facts.refusal_detail or "манифест"),
                                 "нет файла: сборщик отказал по отсутствию обязательного файла"))
            return
        raise _Unusable(f"пакет не собран: {_refusal_reason(facts.refusal)}")
    manifest = {entry.path: entry for entry in facts.entries}
    for claim in front["evidence"]:
        entry = manifest.get(claim["path"])
        if entry is None:
            found.append(Finding("MISSING_EXISTING_EVIDENCE", _name(claim["path"]), "нет файла: его нет в манифесте пакета"))
        elif entry.file_class != "existing_evidence":
            found.append(Finding("MISSING_EXISTING_EVIDENCE", _name(claim["path"]),
                                 f"нет файла как свидетельства: в манифесте он {_name(entry.file_class)}"))
        elif entry.sha256 is None:
            found.append(Finding("MISSING_EXISTING_EVIDENCE", _name(claim["path"]), "нет файла: у записи манифеста нет хеша"))
        elif entry.sha256.casefold() != claim["sha256"].strip().casefold():
            found.append(Finding("MISSING_EXISTING_EVIDENCE", _name(claim["path"]), "хеш не совпал с хешем из манифеста пакета"))


def _count_mismatch(front, facts, found):
    for row in front["lists"]:
        if len(row["items"]) != row["declared_count"]:
            found.append(Finding("DECLARED_COUNT_MISMATCH", _name(row["name"]),
                                 f"в списке {len(row['items'])}, объявлено {_number(row['declared_count'])}"))


def _revision_mismatch(front, facts, found):
    _revision_ok(front["revision"], "в шапке")
    if facts.refusal is not None:
        return                      # no package, no edition to compare; the refusal itself is reported
    if front["revision"] != facts.revision:
        found.append(Finding("REVISION_MISMATCH", "revision", "редакция в шапке не равна редакции пакета"))


def _forbidden_capability(front, facts, found):
    """Intersection of two sets of names under the package's own fold (look-alikes of other
    scripts, invisible marks and hyphens do not make a different name)."""
    def folded(name):
        key = fold_name(name)
        if not key:
            raise _Unusable("имя возможности без видимых знаков")
        return key
    forbidden = {folded(name) for name in front["forbidden_capabilities"]}
    seen = set()
    for name in front["active_capabilities"]:
        key = folded(name)
        if key in forbidden and key not in seen:
            seen.add(key)
            found.append(Finding("FORBIDDEN_CAPABILITY_PRESENT", _name(name),
                                 "возможность и активна, и запрещена одновременно"))


CHECKS = {
    "BROKEN_ANCHOR": _broken_anchor,
    "MISSING_EXISTING_EVIDENCE": _missing_evidence,
    "DECLARED_COUNT_MISMATCH": _count_mismatch,
    "REVISION_MISMATCH": _revision_mismatch,
    "FORBIDDEN_CAPABILITY_PRESENT": _forbidden_capability,
}


def _ordered(found, order) -> tuple:
    """Code order of precheck.yaml, then place, then reason; repeats dropped."""
    unique = {finding.as_tuple(): finding for finding in found}
    return tuple(sorted(unique.values(),
                        key=lambda f: (order.index(f.code), f.where, f.reason)))


def precheck(frontmatter_text, facts, tables=None) -> PrecheckResult:
    """Check one artefact. Never raises: a defect lands in the status."""
    try:
        tables = tables or tables_module.load()
        order = [row.code for row in tables.precheck_codes]
        if set(order) != set(CHECKS):
            raise contracts.ContractError("коды precheck.yaml и проверки precheck.py разошлись")
        schema = contracts.load_schema(SCHEMA_NAME, Path(SCHEMA_DIR))
        classes = set(tables.precheck["классы_файлов"])
    except Exception as error:      # the check itself cannot run: never "clean"
        return PrecheckResult(CHECK_FAILED, (), f"схема или таблицы недоступны: {type(error).__name__}")
    try:
        front = _parse(frontmatter_text)
        try:
            contracts.validate(schema, front)
        except contracts.AnswerRejected as error:
            return _bad(_schema_reason(str(error), schema))
        _facts_shape(facts, classes)
        found: list = []
        for code in order:
            CHECKS[code](front, facts, found)
        ordered = _ordered(found, order)
    except _Unusable as unusable:
        return _bad(str(unusable))
    except contracts.ContractError as error:
        return PrecheckResult(CHECK_FAILED, (), "схема не годна: ContractError")
    except Exception as error:      # a bug in a check is a failed check, not a pass
        return PrecheckResult(CHECK_FAILED, (), f"сбой проверки: {type(error).__name__}")
    return PrecheckResult(FINDINGS, ordered) if ordered else PrecheckResult(CLEAN)
