#!/usr/bin/env python3
"""Roundtable — the tables, made executable.

Review round 11 landed the finding this module answers: YAML on its own does
not make prose executable. A rule written as `условие: "первая смена за стадию"`
still has to be re-expressed in Python, and then there are two sources again —
which is the exact failure the tables were introduced to end.

So the tables get one reader, and it is this module:

* **one strict loader** for the suite and for the engine — duplicate keys,
  unregistered top-level sections and a foreign contract version are refused,
  because `yaml.safe_load` accepts all three without a word;
* **typed rows**, so a mistyped field name fails at load instead of at the
  first attribute access;
* **`decide`**, which returns exactly one outcome for any combination of
  condition codes — zero matches or two are a contract error, never "take the
  first one". This is what makes the engine call the table rather than restate
  it;
* **generation of the normative sections of docs/roundtable.md**, because those
  tables lived in two places and drifted apart twice.

    python3 core/scripts/roundtable/tables.py check
    python3 core/scripts/roundtable/tables.py render [--check]
    python3 core/scripts/roundtable/tables.py decide \
        --state ждёт_Антона --event submit-decision \
        --condition decision=принять_риск --condition all_verdict_blocking_resolved=true

The same entry points work as `python3 -m roundtable.tables …` when
`core/scripts` is on PYTHONPATH.
"""

from __future__ import annotations

import argparse
import contextvars
import functools
import hashlib
import itertools
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
# The mutation ratchet points this at a scratch copy. It used to write the
# canonical YAML in place and restore it in `finally`: a `kill -9` mid-run left
# the repository holding a corrupted table.
TABLES_DIR = Path(os.environ.get("ROUNDTABLE_TABLES_DIR") or (HERE.parent / "tables"))
DOCUMENT = HERE.parents[3] / "docs" / "roundtable.md"

# Версия формы КАЖДОЙ таблицы отдельно. Одна глобальная константа не давала
# поднять версию одной таблицы: отвергалась бы либо она, либо все остальные.
# Bumped when the *shape* of the scope record changes, so a moved hash is
# explainable: scope/2 added the exact position in the order and the full
# executable content of every gate touching the block — both could be changed
# before without disturbing the fingerprint.
SCOPE_ALGORITHM = "scope/2"
# Короткая цитата ничего не доказывает, пустая — «находится» в любой реплике.
MIN_QUOTE = 12

CONTRACT_VERSIONS = {
    "vocabulary": 1, "run": 1, "issues": 1, "framing": 1,
    "precheck": 1, "blocks": 2, "stages": 1, "findings": 1,
}

TABLE_NAMES = ("vocabulary", "run", "issues", "framing", "precheck", "blocks",
               "stages", "findings")

# Top-level sections each table may carry. The point is not documentation: an
# unregistered key is refused, so `переходи:` instead of `переходы:` becomes a
# load error rather than a table that silently lost its rules.
TOP_LEVEL = {
    "vocabulary": {
        "состояния_прогона", "действительность_прогона", "статусы_issue",
        "классы_находки", "устранимость", "существенность", "уверенность",
        "решения_по_issue", "решения_по_возражению", "статусы_возражения",
        "вердикты", "стадии", "типы_доказательства", "отпечаток",
        "создатели_доказательства", "пакет", "попытка",
        "состояния_блока", "внешние_действия",
        "оценка_критерия", "состояния_кандидата", "выбор_кандидата_sentinel",
        "отношение_механизмов", "повтор_невалидного_ответа",
        "операции", "операции_без_бюджета",
        "коды_условий", "коды_действий", "коды_отказа",
        "схемы_контрактов", "схемы_вне_контрактов",
    },
    "run": {"переходы", "действия", "revoke_operation"},
    "issues": {
        "переходы", "кто_завершает", "допустимые_решения", "вердикт",
        "вердикт_вне_таблицы", "обязательства", "валидация",
        # БТ2: закрытые коды-различители ЭТОГО автомата (R21-5 → БТ2-1). Не в
        # vocabulary.yaml — эти значения не статус, не класс и не решение
        # общего канала, а ответ конкретной роли в конкретном переходе.
        "коды_условий",
    },
    "framing": {
        "операция", "цель", "переходы", "влияние_по_стадиям", "флаг_прогона",
        "флаг_обязателен_в", "права_по_стадиям", "критерии_решения",
        "критерии_постановки", "считает_движок_без_права_поднимать",
        "ограничитель_смены_решения", "хранение",
    },
    "precheck": {
        "схема_входа", "зависимость_блока", "коды", "вне_возможностей",
        "почему", "классы_файлов", "фикстуры", "общий_резолвер",
    },
    "blocks": {
        "порядок", "вне_порядка", "блоки", "списки",
        "заключения_ревью", "разрешения_исполнения", "история_разрешений", "шлюзы",
        "отпечаток_изоляции", "проверки_источников", "проверка_памяти", "согласия",
        "порядок_критики", "сверка_записи", "исполнение",
    },
    "stages": {
        "стадии", "слепой_вопрос", "сигнал_нежизнеспособности",
        "метрика_цены_понимания", "приоритет_расхода",
    },
    "findings": {"находки"},
}


class ContractError(Exception):
    """A table says something the contract does not allow it to say."""


# --------------------------------------------------------------------------
# the one strict loader
# --------------------------------------------------------------------------

class StrictLoader(yaml.SafeLoader):
    """A SafeLoader that refuses duplicate keys instead of keeping the last.

    Round 11: `yaml.safe_load` accepts a repeated key silently, so a table
    could carry two different values for one rule and look perfectly fine.
    """


def _no_duplicate_keys(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def load_table(name: str, directory: Path = TABLES_DIR) -> dict:
    """Load one table, refusing anything the contract does not recognise."""
    if name not in TABLE_NAMES:
        raise ContractError(f"unknown table {name!r}")
    path = Path(directory) / f"{name}.yaml"
    with open(path, encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=StrictLoader)
    if not isinstance(data, dict):
        raise ContractError(f"{path}: a table must be a mapping")

    expected = CONTRACT_VERSIONS[name]
    version = data.get("версия_контракта")
    if version != expected:
        raise ContractError(
            f"{path}: contract version {version!r}, this engine speaks {expected}")

    unknown = set(data) - TOP_LEVEL[name] - {"версия_контракта"}
    if unknown:
        raise ContractError(f"{path}: unregistered top-level sections {sorted(unknown)}")
    return data


# --------------------------------------------------------------------------
# typed rows — a mistyped field fails here, not at first use
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Transition:
    """One row of the run automaton (run.yaml)."""

    source: str | None
    event: str
    conditions: dict
    target: str
    actions: tuple[str, ...] = ()
    refusal: str | None = None

    @classmethod
    def parse(cls, row: dict) -> "Transition":
        _require(row, {"из", "событие", "в"}, {"условия", "действия", "отказ"}, "run.переходы")
        return cls(
            source=row["из"],
            event=row["событие"],
            conditions=dict(row.get("условия") or {}),
            target=row["в"],
            actions=tuple(row.get("действия") or ()),
            refusal=row.get("отказ"),
        )

    def matches(self, conditions: dict) -> bool:
        return all(conditions.get(key, _MISSING) == value
                   for key, value in self.conditions.items())


@dataclass(frozen=True)
class IssueOutcome:
    """One discriminated outcome of a multi-target issue row — closed codes only."""

    conditions: dict
    target: str


@dataclass(frozen=True)
class IssueTransition:
    """One row of the issue transition table (issues.yaml).

    `условие` is prose for humans and for the generated document — pinned by
    `test_every_route_to_anton_exists_from_both_author_statuses` in the
    read-only suite, so it is kept byte-for-byte and never consulted by
    `decide_issue_transition`. `событие` + `условия`/`исходы` is the actual
    executable rule (БТ2-1, closing R21-5): closed condition codes only,
    declared in issues.коды_условий or the `decision` code already closed in
    vocabulary.решения_по_issue.
    """

    source: str | None
    targets: tuple[str, ...]
    who: str
    condition: str
    event: str
    outcomes: tuple[IssueOutcome, ...]

    @classmethod
    def parse(cls, row: dict) -> "IssueTransition":
        _require(row, {"из", "в", "кто", "условие", "событие"},
                 {"условия", "исходы"}, "issues.переходы")
        if "условия" in row and "исходы" in row:
            raise ContractError(f"issues.переходы: и условия, и исходы разом — {row}")
        _string_list(row["в"], "issues.переходы.в")
        targets = tuple(row["в"])
        if "исходы" in row:
            outcomes = []
            for entry in row["исходы"]:
                _require(entry, {"условия", "в"}, set(), "issues.переходы.исходы")
                outcomes.append(IssueOutcome(dict(entry["условия"]), entry["в"]))
            outcomes = tuple(outcomes)
        else:
            outcomes = (IssueOutcome(dict(row.get("условия") or {}), targets[0]),)
        unknown_targets = {o.target for o in outcomes} - set(targets)
        if unknown_targets:
            raise ContractError(
                f"issues.переходы: исход ведёт куда не объявлено в `в`: "
                f"{sorted(unknown_targets)} — {row}")
        return cls(row["из"], targets, row["кто"], row["условие"], row["событие"], outcomes)


@dataclass(frozen=True)
class FramingOutcome:
    """One discriminated outcome of a framing row — closed codes only."""

    conditions: dict
    target: str


@dataclass(frozen=True)
class FramingTransition:
    """One row of the objection-to-framing automaton (framing.yaml).

    Same split as `IssueTransition`: `условие` is prose, pinned by
    `test_framing_automaton_is_closed_and_reachable` (reads the raw dict,
    untouched) and by the generated document. `событие` + `условия`/`исходы`
    is what `decide_framing_transition` executes — closing R16-3 (the
    automaton's fifth input) and R21-5 for this table, built entirely on
    `framing_decision`, already closed in vocabulary.решения_по_возражению.
    """

    source: str | None
    target: str
    who: str
    condition: str
    event: str
    outcomes: tuple[FramingOutcome, ...]

    @classmethod
    def parse(cls, row: dict) -> "FramingTransition":
        _require(row, {"из", "в", "кто", "условие", "событие"},
                 {"условия", "исходы"}, "framing.переходы")
        if "условия" in row and "исходы" in row:
            raise ContractError(f"framing.переходы: и условия, и исходы разом — {row}")
        if "исходы" in row:
            outcomes = []
            for entry in row["исходы"]:
                _require(entry, {"условия", "в"}, set(), "framing.переходы.исходы")
                outcomes.append(FramingOutcome(dict(entry["условия"]), entry["в"]))
            outcomes = tuple(outcomes)
        else:
            outcomes = (FramingOutcome(dict(row.get("условия") or {}), row["в"]),)
        wrong = [o for o in outcomes if o.target != row["в"]]
        if wrong:
            raise ContractError(
                f"framing.переходы: исход ведёт не туда, куда объявлено в `в`: {row}")
        return cls(row["из"], row["в"], row["кто"], row["условие"], row["событие"], outcomes)


@dataclass(frozen=True)
class VerdictRow:
    """One row of the verdict table, checked top to bottom."""

    condition: str
    verdict: str

    @classmethod
    def parse(cls, row: dict) -> "VerdictRow":
        _require(row, {"условие", "вердикт"}, set(), "issues.вердикт")
        return cls(row["условие"], row["вердикт"])


@dataclass(frozen=True)
class PrecheckCode:
    """One programmatic precheck code (Б15)."""

    code: str
    fires_on: str
    fixture: str

    @classmethod
    def parse(cls, row: dict) -> "PrecheckCode":
        _require(row, {"код", "срабатывает", "фикстура"}, set(), "precheck.коды")
        return cls(row["код"], row["срабатывает"], row["фикстура"])


@dataclass(frozen=True)
class AcceptanceItem:
    """One acceptance criterion, addressable by a stable id.

    A plain string could not be compared as a set when one block absorbs
    another, and its text could be rewritten under the same meaning without
    anything noticing. Both are now structural.
    """

    id: str
    condition: str


@dataclass(frozen=True)
class Block:
    """One block of the work plan."""

    name: str
    what: str
    depends: tuple[str, ...]
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    external: tuple[str, ...] = ()
    acceptance: tuple[AcceptanceItem, ...] = ()
    state: str | None = None
    blocker: str | None = None
    reopened_because: str | None = None
    absorbed_by: str | None = None
    absorbs: tuple[str, ...] = ()
    declared_counts: dict = field(default_factory=dict)
    outside_mvp: bool = False
    commits: tuple[str, ...] = ()

    @classmethod
    def parse(cls, name: str, row: dict, vocabulary: dict | None = None) -> "Block":
        _require(
            row, {"что", "зависит", "читает", "пишет", "внешние_действия", "приёмка"},
            {"состояние", "блокер", "переоткрыт_из_за", "объединён_с", "поглощает",
             "объявленное_количество", "вне_MVP", "коммиты"},
            f"blocks.блоки.{name}")
        where = f"blocks.блоки.{name}"
        for field_name in ("зависит", "читает", "пишет", "внешние_действия"):
            _string_list(row[field_name], f"{where}.{field_name}")
        _string_list(row.get("поглощает") or [], f"{where}.поглощает")
        _string_list(row.get("коммиты") or [], f"{where}.коммиты")
        for sha in row.get("коммиты") or []:
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ContractError(f"{where}.коммиты: {sha!r} — не полный sha коммита")
        _nonempty_string(row["что"], f"{where}.что")
        if "вне_MVP" in row and not isinstance(row["вне_MVP"], bool):
            raise ContractError(f"{where}.вне_MVP: ожидался boolean")
        counts = row.get("объявленное_количество") or {}
        if not isinstance(counts, dict):
            raise ContractError(f"{where}.объявленное_количество: ожидался словарь")
        for key, value in counts.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ContractError(f"{where}.объявленное_количество.{key}: "
                                    f"ожидалось положительное целое")
        if vocabulary is not None:
            block_states = vocabulary["состояния_блока"]
            missing = {"рабочие", "терминальные"} - set(block_states)
            if missing:
                raise ContractError(
                    f"vocabulary.состояния_блока: отсутствует {sorted(missing)}")
            states = (set(block_states["рабочие"])
                      | set(block_states["терминальные"]))
            if row.get("состояние") is not None and row["состояние"] not in states:
                raise ContractError(
                    f"{where}.состояние: {row['состояние']!r} нет в словаре")
            allowed = set(vocabulary["внешние_действия"])
            unknown = set(row["внешние_действия"]) - allowed
            if unknown:
                raise ContractError(f"{where}.внешние_действия: {sorted(unknown)} нет в словаре")
        items = []
        seen = set()
        # 🚩 Ревью #40: `приёмка: null` роняла загрузчик сырым TypeError —
        # повреждённая запись обязана приходить как названный отказ.
        if not isinstance(row["приёмка"], list) or not row["приёмка"]:
            raise ContractError(f"{where}.приёмка: ожидался непустой список, "
                                f"получено {type(row['приёмка']).__name__}")
        for entry in row["приёмка"]:
            if not isinstance(entry, dict):
                raise ContractError(f"{where}.приёмка: элемент {entry!r} — не запись")
            _require(entry, {"id", "условие"}, set(), f"{where}.приёмка")
            _nonempty_string(entry["id"], f"{where}.приёмка.id")
            _nonempty_string(entry["условие"], f"{where}.приёмка.условие")
            if entry["id"] in seen:
                raise ContractError(f"{name}: duplicate acceptance id {entry['id']!r}")
            seen.add(entry["id"])
            items.append(AcceptanceItem(entry["id"], entry["условие"]))
        return cls(
            name=name,
            what=row["что"],
            depends=tuple(row["зависит"]),
            reads=tuple(row["читает"]),
            writes=tuple(row["пишет"]),
            external=tuple(row["внешние_действия"]),
            acceptance=tuple(items),
            state=row.get("состояние"),
            blocker=row.get("блокер"),
            reopened_because=row.get("переоткрыт_из_за"),
            absorbed_by=row.get("объединён_с"),
            absorbs=tuple(row.get("поглощает") or ()),
            declared_counts=dict(counts),
            outside_mvp=bool(row.get("вне_MVP", False)),
            commits=tuple(row.get("коммиты") or ()),
        )

    def scope(self, plan: dict | None = None) -> dict:
        """The canonical record a permission is granted for.

        Not the block's name: a name can be kept while the work behind it
        grows, and the old permission would silently cover the new scope.
        Acceptance goes in with its *text*, not only its ids, because the text
        can be rewritten under an unchanged id.

        `plan` adds what is not stored on the block but is nonetheless part of
        what was permitted — most importantly which gates hold it. Dropping a
        block out of a gate removes a precondition without touching its row,
        and the permission would have stayed valid.

        `состояние` is deliberately out: it changes as the work proceeds, and
        a scope that moved with progress would invalidate itself constantly.
        """
        record = {
            "алгоритм": SCOPE_ALGORITHM,
            "блок": self.name,
            "что": self.what,
            "зависит": sorted(self.depends),
            "читает": sorted(self.reads),
            "пишет": sorted(self.writes),
            "внешние_действия": sorted(self.external),
            "приёмка": [{"id": i.id, "условие": i.condition} for i in self.acceptance],
            "поглощает": sorted(self.absorbs),
            "объединён_с": self.absorbed_by,
            "объявленное_количество": dict(sorted(self.declared_counts.items())),
            "вне_MVP": self.outside_mvp,
        }
        if plan is not None:
            # Правило, на которое ссылается критерий блока, — часть его объёма.
            # Иначе раздел `согласия` можно переписать целиком, а отпечатки
            # блоков, живущих по нему, не шелохнутся (ревью #26).
            referenced = sorted(
                name for name in ("согласия",)
                if any(f"`{name}`" in item.condition for item in self.acceptance))
            if referenced:
                record["правила_по_ссылке"] = {
                    name: plan[name] for name in referenced if name in plan}
            order = plan["порядок"]
            # position, not membership: moving БТ2 ahead of Б1 changes what runs
            # next without touching a single field of either block
            record["место_в_порядке"] = (order.index(self.name)
                                         if self.name in order else None)
            # the whole executable side of every gate that touches this block:
            # swapping Ш1 for an already-closed block inside `до_закрытия`
            # removes the safety boundary while every block row stays identical
            gates = {}
            for gate, spec in plan["шлюзы"].items():
                sides = {}
                if self.name in spec["блокирует"]:
                    sides["сторона"] = "блокирует"
                if self.name in spec["до_закрытия"]:
                    sides["сторона"] = sides.get("сторона", "") + "|до_закрытия"
                if sides:
                    sides["блокирует"] = sorted(spec["блокирует"])
                    sides["до_закрытия"] = sorted(spec["до_закрытия"])
                    gates[gate] = sides
            record["шлюзы"] = dict(sorted(gates.items()))
        return record

    def scope_sha256(self, plan: dict | None = None) -> str:
        payload = json.dumps(self.scope(plan), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Missing:
    def __repr__(self):  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()


def _string_list(value, where: str) -> None:
    """A list of strings, and not a bare string.

    `пишет: "core/x.py"` used to become a tuple of characters, silently.
    """
    if not isinstance(value, list):
        raise ContractError(f"{where}: ожидался список, получено {type(value).__name__}")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{where}: элемент {item!r} — не непустая строка")


def _nonempty_string(value, where: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{where}: ожидалась непустая строка")


def _require(row: dict, mandatory: set, optional: set, where: str) -> None:
    missing = mandatory - set(row)
    if missing:
        raise ContractError(f"{where}: row is missing {sorted(missing)} — {row}")
    unknown = set(row) - mandatory - optional
    if unknown:
        raise ContractError(f"{where}: unknown fields {sorted(unknown)} — {row}")


# --------------------------------------------------------------------------
# the outcome of a decision
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Outcome:
    """Exactly one outcome: a move, its actions, and a refusal code or None."""

    to: str
    actions: tuple[str, ...] = ()
    refusal: str | None = None

    def as_dict(self) -> dict:
        return {"to": self.to, "actions": list(self.actions), "refusal": self.refusal}


@dataclass(frozen=True)
class Tables:
    """Every table, loaded once, typed, and answering questions."""

    raw: dict
    transitions: tuple[Transition, ...]
    issue_transitions: tuple[IssueTransition, ...]
    framing_transitions: tuple[FramingTransition, ...]
    verdict: tuple[VerdictRow, ...]
    precheck_codes: tuple[PrecheckCode, ...]
    blocks: dict

    # БТ2: тип issue по коду блокера — какой столбец `допустимые_решения`
    # открывает эта эскалация. Локальная таблица кода в коде (не «условие»
    # строкой): различитель `блокер` объявлен в issues.коды_условий, и
    # соответствие типам проверяется `_check_issue_codes` при каждом `load()`,
    # так что расхождение — падение загрузки, а не тихая дыра.
    ISSUE_TYPE_BY_BLOCKER = {
        "сменой_решения": "блокер_сменой_решения",
        "только_сменой_цели": "блокер_только_сменой_цели",
        "правкой_круги_исчерпаны": "блокер_правкой_круги_исчерпаны",
        "неизвестное_высокой_существенности": "неизвестное_высокой_существенности",
    }

    @classmethod
    def from_raw(cls, raw: dict) -> "Tables":
        """Type an already-loaded set of tables.

        Split out of `load` so a test can mutate a copy in memory and watch an
        invariant fire, without writing to the real YAML.
        """
        return cls(
            raw=raw,
            transitions=tuple(Transition.parse(row) for row in raw["run"]["переходы"]),
            issue_transitions=tuple(
                IssueTransition.parse(row) for row in raw["issues"]["переходы"]),
            framing_transitions=tuple(
                FramingTransition.parse(row) for row in raw["framing"]["переходы"]),
            verdict=tuple(VerdictRow.parse(row) for row in raw["issues"]["вердикт"]),
            precheck_codes=tuple(
                PrecheckCode.parse(row) for row in raw["precheck"]["коды"]),
            blocks={name: Block.parse(name, row, raw["vocabulary"])
                    for name, row in raw["blocks"]["блоки"].items()},
        )

    # -- convenience views ---------------------------------------------------
    @property
    def vocabulary(self) -> dict:
        return self.raw["vocabulary"]

    @property
    def run(self) -> dict:
        return self.raw["run"]

    @property
    def issues(self) -> dict:
        return self.raw["issues"]

    @property
    def framing(self) -> dict:
        return self.raw["framing"]

    @property
    def precheck(self) -> dict:
        return self.raw["precheck"]

    @property
    def stages(self) -> dict:
        return self.raw["stages"]

    @property
    def findings(self) -> list:
        return self.raw["findings"]["находки"]

    @property
    def plan(self) -> dict:
        return self.raw["blocks"]

    @property
    def events(self) -> tuple[str, ...]:
        seen = []
        for transition in self.transitions:
            if transition.event not in seen:
                seen.append(transition.event)
        return tuple(seen)

    # -- the core -----------------------------------------------------------
    def decide(self, state: str | None, event: str, conditions: dict | None = None) -> Outcome:
        """Return the single outcome for (state, event, conditions).

        Zero matching rows or more than one is a contract error, never a
        silent "take the first". That refusal is the whole point: it is what
        keeps the meaning of the rules inside the table.
        """
        conditions = dict(conditions or {})
        self._validate_conditions(conditions)

        if event not in self.events:
            raise ContractError(f"unknown event {event!r}")
        states = self._states()
        if state is not None and state not in states:
            raise ContractError(f"unknown run state {state!r}")

        candidates = [t for t in self.transitions
                      if t.source == state and t.event == event and t.matches(conditions)]
        if not candidates:
            raise ContractError(
                f"no outcome for ({state!r}, {event!r}) with {conditions!r}")
        if len(candidates) > 1:
            raise ContractError(
                f"{len(candidates)} outcomes for ({state!r}, {event!r}) with {conditions!r}")
        winner = candidates[0]
        return Outcome(to=winner.target, actions=winner.actions, refusal=winner.refusal)

    def condition_keys(self, state: str | None, event: str) -> tuple[str, ...]:
        """Condition codes that any rule of this (state, event) pair looks at."""
        keys = []
        for transition in self.transitions:
            if transition.source == state and transition.event == event:
                for key in transition.conditions:
                    if key not in keys:
                        keys.append(key)
        return tuple(keys)

    def pairs(self) -> tuple[tuple[str | None, str], ...]:
        seen = []
        for transition in self.transitions:
            pair = (transition.source, transition.event)
            if pair not in seen:
                seen.append(pair)
        return tuple(seen)

    # -- БТ2: the issue automaton (issues.yaml) ------------------------------
    # A second `decide`-shaped input (БТ2-3), same "exactly one outcome, never
    # first-match-wins" discipline as the run automaton — but reading a
    # DIFFERENT registry (issue status, not run state). `decision` and
    # `framing_decision` are separate closed lists (vocabulary.yaml), so the
    # two channels cannot be crossed here: feeding a framing code in is
    # refused as an unknown condition code.
    def decide_issue_transition(self, status: str | None, event: str,
                                conditions: dict | None = None) -> Outcome:
        conditions = dict(conditions or {})
        self._validate_issue_conditions(conditions)
        statuses = self._issue_statuses()
        if status is not None and status not in statuses:
            raise ContractError(f"unknown issue status {status!r}")
        events = {t.event for t in self.issue_transitions}
        if event not in events:
            raise ContractError(f"unknown issue event {event!r}")

        matched = [(t, o) for t in self.issue_transitions
                  if t.source == status and t.event == event
                  for o in t.outcomes
                  if all(conditions.get(k, _MISSING) == v for k, v in o.conditions.items())]
        if not matched:
            raise ContractError(
                f"no outcome for issue ({status!r}, {event!r}) with {conditions!r}")
        if len(matched) > 1:
            raise ContractError(
                f"{len(matched)} outcomes for issue ({status!r}, {event!r}) with {conditions!r}")
        _, outcome = matched[0]

        # Контракт E / БТ2-2: "решение Антона вне списка допустимых для типа
        # issue" — это отказ пользователя (Outcome.refusal), не поломка
        # движка. `блокер` необязателен структурно, но реальный вызов на
        # `вынесен_Антону` обязан его передать; иначе решение не той формы
        # молча проходит бы дальше (БТ2-3).
        if event == "anton-decision" and "блокер" in conditions:
            issue_type = self.ISSUE_TYPE_BY_BLOCKER[conditions["блокер"]]
            allowed = self.issues["допустимые_решения"][issue_type]
            if conditions.get("decision") not in allowed:
                return Outcome(to=status, refusal="РЕШЕНИЕ_ВНЕ_ТИПА")
        return Outcome(to=outcome.target)

    def _issue_pairs(self) -> tuple[tuple[str | None, str], ...]:
        seen = []
        for transition in self.issue_transitions:
            pair = (transition.source, transition.event)
            if pair not in seen:
                seen.append(pair)
        return tuple(seen)

    def _issue_condition_keys(self, state, event) -> tuple[str, ...]:
        keys = []
        for transition in self.issue_transitions:
            if transition.source == state and transition.event == event:
                for outcome in transition.outcomes:
                    for key in outcome.conditions:
                        if key not in keys:
                            keys.append(key)
        return tuple(keys)

    def _issue_combinations(self, state, event) -> list[dict]:
        keys = self._issue_condition_keys(state, event)
        if not keys:
            return [{}]
        codes = self._issue_codes()
        combinations = [{}]
        for key in keys:
            combinations = [dict(base, **{key: value})
                            for base in combinations for value in codes[key]]
        return combinations

    def _issue_codes(self) -> dict:
        codes = dict(self.issues.get("коды_условий") or {})
        codes["decision"] = self.vocabulary["решения_по_issue"]
        return codes

    def _issue_statuses(self) -> set:
        statuses = self.vocabulary["статусы_issue"]
        required = {"ждут_автора", "ждут_критика", "ждут_Антона", "терминальные"}
        missing = required - set(statuses)
        if missing:
            raise ContractError(f"vocabulary.статусы_issue: отсутствует {sorted(missing)}")
        return (set(statuses["ждут_автора"]) | set(statuses["ждут_критика"])
                | set(statuses["ждут_Антона"]) | set(statuses["терминальные"]))

    def _validate_issue_conditions(self, conditions: dict) -> None:
        codes = self._issue_codes()
        for key, value in conditions.items():
            if key not in codes:
                raise ContractError(f"unknown issue condition code {key!r}")
            if value not in codes[key]:
                raise ContractError(f"{key}={value!r} is not a declared issue value")

    # -- БТ2: the framing automaton (framing.yaml) — the fifth input (R16-3) --
    def decide_framing_transition(self, status: str | None, event: str,
                                  conditions: dict | None = None) -> Outcome:
        conditions = dict(conditions or {})
        self._validate_framing_conditions(conditions)
        statuses = self._framing_statuses()
        if status is not None and status not in statuses:
            raise ContractError(f"unknown framing status {status!r}")
        events = {t.event for t in self.framing_transitions}
        if event not in events:
            raise ContractError(f"unknown framing event {event!r}")

        matched = [(t, o) for t in self.framing_transitions
                  if t.source == status and t.event == event
                  for o in t.outcomes
                  if all(conditions.get(k, _MISSING) == v for k, v in o.conditions.items())]
        if not matched:
            raise ContractError(
                f"no outcome for framing ({status!r}, {event!r}) with {conditions!r}")
        if len(matched) > 1:
            raise ContractError(
                f"{len(matched)} outcomes for framing ({status!r}, {event!r}) with {conditions!r}")
        _, outcome = matched[0]
        return Outcome(to=outcome.target)

    def _framing_pairs(self) -> tuple[tuple[str | None, str], ...]:
        seen = []
        for transition in self.framing_transitions:
            pair = (transition.source, transition.event)
            if pair not in seen:
                seen.append(pair)
        return tuple(seen)

    def _framing_condition_keys(self, state, event) -> tuple[str, ...]:
        keys = []
        for transition in self.framing_transitions:
            if transition.source == state and transition.event == event:
                for outcome in transition.outcomes:
                    for key in outcome.conditions:
                        if key not in keys:
                            keys.append(key)
        return tuple(keys)

    def _framing_combinations(self, state, event) -> list[dict]:
        keys = self._framing_condition_keys(state, event)
        if not keys:
            return [{}]
        codes = {"framing_decision": self.vocabulary["решения_по_возражению"]}
        combinations = [{}]
        for key in keys:
            combinations = [dict(base, **{key: value})
                            for base in combinations for value in codes[key]]
        return combinations

    def _framing_statuses(self) -> set:
        statuses = self.vocabulary["статусы_возражения"]
        missing = {"активные", "терминальные"} - set(statuses)
        if missing:
            raise ContractError(f"vocabulary.статусы_возражения: отсутствует {sorted(missing)}")
        return set(statuses["активные"]) | set(statuses["терминальные"])

    def _validate_framing_conditions(self, conditions: dict) -> None:
        codes = {"framing_decision": self.vocabulary["решения_по_возражению"]}
        for key, value in conditions.items():
            if key not in codes:
                raise ContractError(f"unknown framing condition code {key!r}")
            if value not in codes[key]:
                raise ContractError(f"{key}={value!r} is not a declared framing value")

    # -- validation ---------------------------------------------------------
    def _states(self) -> set:
        states = self.vocabulary["состояния_прогона"]
        # БТ2: this runs on every `load()` now (`_check_codes`), so a
        # malformed vocabulary must fail as `ContractError`, not as a bare
        # `KeyError` — the mutation ratchet caught exactly this: a missing
        # `рабочие`/`терминальные` key used to crash the caller instead of
        # refusing the load.
        missing = {"рабочие", "терминальные"} - set(states)
        if missing:
            raise ContractError(
                f"vocabulary.состояния_прогона: отсутствует {sorted(missing)}")
        return set(states["рабочие"]) | set(states["терминальные"])

    def _validate_conditions(self, conditions: dict) -> None:
        codes = self.vocabulary["коды_условий"]
        for key, value in conditions.items():
            if key not in codes:
                raise ContractError(f"unknown condition code {key!r}")
            if value not in codes[key]:
                raise ContractError(f"{key}={value!r} is not a declared value")

    def _check_codes(self) -> None:
        """The closed-code closure of all three automata — cheap, so `load()`
        runs it on every call (БТ2-4, closing R12-5): a typo in a condition
        code used to load silently and quietly disable the transition it
        broke, surfacing only if and when someone remembered to call the full
        `check()`. This does NOT run `_check_plan()` or the combinatorial
        "exactly one outcome" sweep — the mutation ratchet
        (test_roundtable_mutations.py) depends on the loader accepting a
        structurally valid table whose *plan* is still broken, so that split
        stays: code closure is load-time, the heavier analysis stays in
        `check()`.
        """
        codes = self.vocabulary["коды_условий"]
        actions = set(self.vocabulary["коды_действий"])
        refusals = set(self.vocabulary["коды_отказа"])
        states = self._states()

        for transition in self.transitions:
            if transition.source is not None and transition.source not in states:
                raise ContractError(f"unknown source state: {transition}")
            if transition.target not in states:
                raise ContractError(f"unknown target state: {transition}")
            for key, value in transition.conditions.items():
                if key not in codes:
                    raise ContractError(f"unknown condition code {key!r} in {transition}")
                if value not in codes[key]:
                    raise ContractError(f"{key}={value!r} undeclared in {transition}")
            for action in transition.actions:
                if action not in actions:
                    raise ContractError(f"unknown action {action!r} in {transition}")
            if transition.refusal is not None and transition.refusal not in refusals:
                raise ContractError(f"unknown refusal {transition.refusal!r} in {transition}")
        self._check_issue_codes()
        self._check_framing_codes()

    def _check_issue_codes(self) -> None:
        statuses = self._issue_statuses()
        local = self.issues.get("коды_условий") or {}
        for key, values in local.items():
            if not values:
                raise ContractError(f"issues.коды_условий.{key}: пустой список")
        # БТ2-5: строгая проверка не только верхнего уровня, но и того, что
        # закрытый различитель `блокер` и типы issue из `допустимые_решения`
        # согласованы друг с другом — выдуманное вложенное значение в любой
        # из двух таблиц отвергается здесь.
        if set(self.ISSUE_TYPE_BY_BLOCKER) != set(local.get("блокер", ())):
            raise ContractError(
                "issues: коды_условий.блокер и ISSUE_TYPE_BY_BLOCKER расходятся")
        if set(self.ISSUE_TYPE_BY_BLOCKER.values()) != set(self.issues["допустимые_решения"]):
            raise ContractError(
                "issues: тип issue по блокеру не покрывает все допустимые_решения")
        if "РЕШЕНИЕ_ВНЕ_ТИПА" not in self.vocabulary["коды_отказа"]:
            raise ContractError("issues: код отказа РЕШЕНИЕ_ВНЕ_ТИПА не объявлен в vocabulary")
        codes = self._issue_codes()
        for transition in self.issue_transitions:
            if transition.source is not None and transition.source not in statuses:
                raise ContractError(f"unknown issue status: {transition}")
            for target in transition.targets:
                if target not in statuses:
                    raise ContractError(f"unknown issue status: {transition}")
            for outcome in transition.outcomes:
                for key, value in outcome.conditions.items():
                    if key not in codes:
                        raise ContractError(f"unknown issue condition code {key!r} in {transition}")
                    if value not in codes[key]:
                        raise ContractError(f"{key}={value!r} undeclared in {transition}")

    def _check_framing_codes(self) -> None:
        statuses = self._framing_statuses()
        codes = {"framing_decision": self.vocabulary["решения_по_возражению"]}
        for transition in self.framing_transitions:
            if transition.source is not None and transition.source not in statuses:
                raise ContractError(f"unknown framing status: {transition}")
            if transition.target not in statuses:
                raise ContractError(f"unknown framing status: {transition}")
            for outcome in transition.outcomes:
                for key, value in outcome.conditions.items():
                    if key not in codes:
                        raise ContractError(f"unknown framing condition code {key!r} in {transition}")
                    if value not in codes[key]:
                        raise ContractError(f"{key}={value!r} undeclared in {transition}")

    def check(self) -> list[str]:
        """Every invariant the engine itself depends on. Returns what it checked."""
        checked = []
        working = set(self.vocabulary["состояния_прогона"]["рабочие"])

        self._check_codes()
        checked.append(f"{len(self.transitions)} переходов: коды закрыты")

        combinations = 0
        for state, event in self.pairs():
            for conditions in self._combinations(state, event):
                self.decide(state, event, conditions)  # raises unless exactly one
                combinations += 1
        checked.append(f"{combinations} комбинаций условий: ровно один исход")

        for state in working:
            forward = [t for t in self.transitions
                       if t.source == state
                       and t.event not in ("cancel-run", "submit-framing-decision")]
            if not forward:
                raise ContractError(f"{state}: the only way out is cancellation")
        checked.append(f"{len(working)} рабочих состояний: у каждого есть продолжение")

        # БТ2: те же две гарантии — единственный исход на комбинацию условий —
        # для issue-автомата и автомата возражений (закрывает R16-3 как
        # проверяемый факт, а не только наличие функции).
        issue_combinations = 0
        for state, event in self._issue_pairs():
            for conditions in self._issue_combinations(state, event):
                self.decide_issue_transition(state, event, conditions)
                issue_combinations += 1
        checked.append(f"{issue_combinations} комбинаций issue-автомата: ровно один исход")

        framing_combinations = 0
        for state, event in self._framing_pairs():
            for conditions in self._framing_combinations(state, event):
                self.decide_framing_transition(state, event, conditions)
                framing_combinations += 1
        checked.append(f"{framing_combinations} комбинаций автомата возражений: ровно один исход")
        checked.extend(self._check_plan())
        return checked

    # -- the work plan -------------------------------------------------------
    # Six review rounds on the prose of the plan found six classes of
    # contradiction. Every one of them is a set comparison, so it belongs here,
    # where a test catches the seventh for free.

    ОСНОВАНИЕ_ПОЛЯ = {
        "план_артефакт": {"путь", "sha256"},
        "событие_транскрипта": {"сессия", "native_uuid", "цитата"},
    }

    def closed(self, name: str) -> bool:
        """A block counts as closed for its dependants.

        An absorbed block is closed only once its absorber is done — otherwise
        `БИ depends on БТ2` and `БТ2 closes with БИ` would be a deadlock that
        runs through two different kinds of edge and no cycle check would see it.
        """
        block = self.blocks[name]
        if name == self.plan["отпечаток_изоляции"]["проверяет_блок"] \
                and not self.isolation_ok():
            return False
        if block.state == "сделано":
            return True
        if block.state == "объединён_с" and block.absorbed_by:
            return self.blocks[block.absorbed_by].state == "сделано"
        return False

    def permitted(self, name: str) -> dict | None:
        """The permission that covers this block at its *current* scope.

        A missing hash used to act as a wildcard, which quietly turned every
        permission back into a permission by name — the exact defect this
        registry exists to remove. A grant with no recorded hash for the block
        is history, not authority.
        """
        wanted = self.blocks[name].scope_sha256(self.plan)
        for grant in self.plan["разрешения_исполнения"]:
            if name not in grant["блоки"]:
                continue
            if grant.get("scope_sha256", {}).get(name) == wanted:
                return grant
        return None

    def hold_reasons(self, name: str) -> list[str]:
        """Every reason this block is not runnable — all of them, in order.

        Not the first one: a block can be unpermitted *and* waiting on a
        dependency *and* held by a gate, and printing only one of the three
        sends the reader to fix the wrong thing.
        """
        block = self.blocks[name]
        reasons = []
        grant = self.permitted(name)
        if grant is None:
            covered = any(name in g["блоки"] for g in self.plan["разрешения_исполнения"])
            reasons.append("объём изменился после разрешения" if covered
                           else "нет разрешения")
        unmet = [d for d in block.depends if not self.closed(d)]
        if unmet:
            reasons.append(f"ждёт зависимость {', '.join(sorted(unmet))}")
        for gate, spec in self.plan["шлюзы"].items():
            if name in spec["блокирует"] and not all(
                    self.closed(b) for b in spec["до_закрытия"]):
                reasons.append(f"удерживается шлюзом {gate}")
        if block.blocker:
            reasons.append(f"заблокирован: {block.blocker}")
        return reasons

    def next_runnable(self) -> str | None:
        for name in self.plan["порядок"]:
            if self.closed(name):
                continue
            if not self.hold_reasons(name):
                return name
        return None

    def gate_violations(self, is_closed, is_started, executed: dict | None = None,
                        rows: dict | None = None) -> list[str]:
        """Состояния, запрещённые шлюзами. Одно правило для плана и прогона.

        Ревью #36: сухой прогон проверял, можно ли НАЧАТЬ следующую волну, а
        обычная проверка — допустимо ли получившееся состояние, и они расходились.
        Б3б правит код запуска, подтверждение изоляции отменяется — записать
        закрытие Б3б по правилам плана было уже нельзя, хотя прогон шёл дальше.

        Исключение ровно одно и узкое: единственное незакрытое предусловие —
        доказывающий блок, и его повторный прогон СТОИТ В ПЛАНЕ после этого
        блока. Работа, сделанная при действовавшем подтверждении, остаётся
        историей; новую без повторного доказательства всё так же не начать.
        """
        prover = self.plan["отпечаток_изоляции"]["проверяет_блок"]
        rows = self.plan["исполнение"]["блоки"] if rows is None else rows
        executed = self.plan["исполнение"]["выполнено"] if executed is None else executed
        out = []
        for gate, spec in self.plan["шлюзы"].items():
            open_ones = sorted(b for b in spec["до_закрытия"] if not is_closed(b))
            if not open_ones:
                continue
            for name in sorted(spec["блокирует"]):
                if not is_started(name):
                    continue
                if open_ones == [prover] and self._reproof_after(name, rows, prover, executed):
                    continue
                out.append(f"шлюз {gate}: начат {name}, а не закрыты {open_ones}")
        return out

    def _reproof_after(self, name: str, rows: dict, prover: str,
                       executed: dict | None = None) -> bool:
        """Запланирован ли повторный прогон доказывающего блока после `name`.

        Ревью #37: волна блока бралась только из списка БУДУЩИХ работ, а при
        настоящем закрытии строку блока оттуда убирают — исключение исчезало
        ровно в тот момент, ради которого заводилось. Выполненные волны живут
        отдельным списком `выполнено`, он и отвечает на вопрос «когда».
        """
        executed = self.plan["исполнение"]["выполнено"] if executed is None else executed
        if prover not in rows:
            return False
        own = rows[name]["волна"] if name in rows else executed.get(name)
        if own is None:
            return False
        waves = rows[prover]["волна"]
        return max(waves if isinstance(waves, list) else [waves]) > (
            max(own) if isinstance(own, list) else own)

    def _check_plan(self) -> list[str]:
        checked = []
        plan = self.plan
        names = set(self.blocks)
        listed = set(plan["порядок"]) | set(plan["вне_порядка"])
        if listed != names:
            raise ContractError(f"blocks: план и перечень блоков разошлись: "
                                f"{sorted(names ^ listed)}")
        for name, block in self.blocks.items():
            unknown = set(block.depends) - names
            if unknown:
                raise ContractError(f"{name}: зависит от несуществующего {sorted(unknown)}")
        self._check_no_cycles()
        checked.append(f"{len(self.blocks)} блоков: зависимости известны и без циклов")

        # gate: nothing downstream may be started while the repair is open
        violations = self.gate_violations(
            self.closed,
            lambda name: self.blocks[name].state in ("сделано", "неполный"))
        if violations:
            raise ContractError(violations[0])
        checked.append(f"{len(plan['шлюзы'])} шлюзов: удерживаемое не начато")

        # authority: a permission must point somewhere resolvable
        for registry in ("заключения_ревью", "разрешения_исполнения",
                         "история_разрешений"):
            for entry in plan[registry]:
                unknown = set(entry["блоки"]) - names
                if unknown:
                    raise ContractError(f"{registry}: неизвестные блоки {sorted(unknown)}")
                basis = entry.get("основание")
                if not isinstance(basis, dict) or "вид" not in basis:
                    raise ContractError(f"{registry}: основание без вида — {entry['блоки']}")
                required = self.ОСНОВАНИЕ_ПОЛЯ.get(basis["вид"])
                if required is None:
                    raise ContractError(f"{registry}: неизвестный вид основания {basis['вид']!r}")
                missing = required - set(basis)
                if missing:
                    raise ContractError(
                        f"{registry}: основание вида {basis['вид']} без {sorted(missing)}")
                if basis["вид"] == "план_артефакт" and not _is_sha256(basis["sha256"]):
                    raise ContractError(f"{registry}: sha256 не похож на sha256")
                # 16.09 план исчез из ~/.claude/plans: основание вне репозитория
                # может пропасть в любой день. Только путь от корня, без выхода вверх.
                if basis["вид"] == "план_артефакт":
                    raw_path = str(basis["путь"])
                    if raw_path.startswith("~") or Path(raw_path).is_absolute() \
                            or ".." in Path(raw_path).parts:
                        raise ContractError(
                            f"{registry}: артефакт-основание вне репозитория: {raw_path}")
                if basis["вид"] == "событие_транскрипта" \
                        and not _is_uuid(basis["native_uuid"]):
                    raise ContractError(f"{registry}: native_uuid не похож на uuid")
        for grant in plan["разрешения_исполнения"]:
            recorded = grant.get("scope_sha256")
            if not isinstance(recorded, dict):
                raise ContractError(
                    f"разрешения_исполнения: {grant['блоки']} без карты scope_sha256")
            if set(recorded) != set(grant["блоки"]):
                raise ContractError(
                    f"разрешения_исполнения: карта scope_sha256 не совпадает с блоками "
                    f"{sorted(set(recorded) ^ set(grant['блоки']))}")
            for value in recorded.values():
                if not _is_sha256(value):
                    raise ContractError("разрешения_исполнения: scope не похож на sha256")
        checked.append("полномочия: основание структурно разрешимо, scope записан на каждый блок")

        # A block being worked on needs a live permission for its current
        # scope. A finished one needs only to have had one: history explains
        # why closed work was closed, it does not authorise anything now.
        working = set(self.vocabulary["состояния_блока"]["рабочие"])
        historic = {b for g in plan["история_разрешений"] for b in g["блоки"]}
        for name, block in self.blocks.items():
            if name == "Б0а" or block.state is None:
                continue
            if block.state in working and self.permitted(name) is None:
                named = any(name in g["блоки"] for g in plan["разрешения_исполнения"])
                raise ContractError(
                    f"{name}: в работе, а разрешение "
                    f"{'на другой объём' if named else 'отсутствует'}")
            if block.state == "сделано" and self.permitted(name) is None \
                    and name not in historic:
                # Круг 42: «нет нигде» было неправдой, когда разрешение есть, но
                # выдано на прежний объём. Слова совпадают с ветвью «в работе»,
                # чтобы опыт с подменой шлюза не зависел от состояния блока.
                named = any(name in g["блоки"] for g in plan["разрешения_исполнения"])
                raise ContractError(
                    f"{name}: закрыт, а разрешение "
                    f"{'на другой объём' if named else 'отсутствует'}")
        checked.append("в работе — только под действующим разрешением на текущий объём")

        # An absorbed block's ids legitimately appear twice: in it and in its
        # absorber. Everywhere else a shared id means two blocks claim one
        # criterion, and neither owns it.
        everywhere = {}
        for name, block in self.blocks.items():
            if block.state == "объединён_с":
                continue
            for item in block.acceptance:
                if item.id in everywhere and everywhere[item.id] != name:
                    raise ContractError(
                        f"ID приёмки {item.id!r} у двух блоков: "
                        f"{everywhere[item.id]} и {name}")
                everywhere[item.id] = name
        checked.append(f"{len(everywhere)} критериев приёмки: ID уникальны глобально")

        for name, block in self.blocks.items():
            if block.state == "переоткрыт" and not block.reopened_because:
                raise ContractError(f"{name}: переоткрыт, но не сказано почему")
            if block.state == "неполный" and not block.blocker:
                raise ContractError(f"{name}: неполный, но не сказано, чем заблокирован")

        # 🚩 R19-7: объём описывал намерение, но не ограничивал исполнение —
        # коммит блока мог тронуть что угодно. Закрытый блок обязан назвать свои
        # коммиты (их сверяет `authority`), а блок, пишущий код движка, — файл
        # тестов: иначе сверка запретила бы ему тесты или их спрятали бы в чужом.
        rule = plan["сверка_записи"]
        _require(rule, {"трейлер", "код_движка", "тесты", "до_правила"},
                 {"откачено_без_трейлера"}, "blocks.сверка_записи")
        # Круг 42 (R42-8): коммит, чью пометку git не разобрал, остаётся в истории
        # только как доказанное исключение — откачен и переложен заново.
        exempt = rule.get("откачено_без_трейлера", {})
        if not isinstance(exempt, dict):
            raise ContractError("blocks.сверка_записи.откачено_без_трейлера: ожидалась карта")
        for sha, entry in exempt.items():
            where = f"blocks.сверка_записи.откачено_без_трейлера.{str(sha)[:7]}"
            if not _is_sha40(sha):
                raise ContractError(f"{where}: ключ — полный sha коммита")
            _require(entry, {"откат", "заново", "почему"}, set(), where)
            for key in ("откат", "заново"):
                if not _is_sha40(entry[key]):
                    raise ContractError(f"{where}.{key}: ожидался полный sha коммита")
            _nonempty_string(entry["почему"], f"{where}.почему")
        _string_list(rule["до_правила"], "blocks.сверка_записи.до_правила")
        for key in ("трейлер", "код_движка", "тесты"):
            _nonempty_string(rule[key], f"blocks.сверка_записи.{key}")
        grandfathered = set(rule["до_правила"])
        unknown = grandfathered - set(self.blocks)
        if unknown:
            raise ContractError(f"сверка записи: {sorted(unknown)} нет среди блоков")
        for name, block in self.blocks.items():
            if block.commits and block.state != "сделано":
                raise ContractError(f"{name}: коммиты записаны, а блок не закрыт")
            if (block.state == "сделано" and name not in grandfathered
                    and not block.commits):
                raise ContractError(
                    f"{name}: закрыт, но коммиты не названы — выход за `пишет` не сверить")
            if name in grandfathered or block.state == "сделано":
                continue
            code = [path for path in block.writes
                    if path.startswith(rule["код_движка"]) and path.endswith(".py")]
            tests = [path for path in block.writes if path.startswith(rule["тесты"])]
            if code and not tests:
                raise ContractError(
                    f"{name}: пишет код движка {code}, но файл тестов не объявлен")
        checked.append(f"сверка записи: закрытые блоки называют коммиты, "
                       f"до правила — {len(grandfathered)}")

        fingerprint = plan["отпечаток_изоляции"]
        artefacts, declared = fingerprint["артефакты"], set(fingerprint["входит_в_отпечаток"])
        missing_core = set(fingerprint["требуются_всегда"]) - set(artefacts)
        if missing_core:
            raise ContractError(
                f"отпечаток изоляции: ядро {sorted(missing_core)} выброшено из артефактов")
        if not isinstance(fingerprint.get("подтверждение_действует"), bool):
            raise ContractError("отпечаток изоляции: подтверждение_действует — только да или нет")
        _string_list(fingerprint.get("входы"), "blocks.отпечаток_изоляции.входы")
        uncovered = [path for path in artefacts.values()
                     if not _overlaps([path], fingerprint["входы"])]
        if uncovered:
            raise ContractError(f"отпечаток изоляции: {uncovered} хешируется, но не во входах — "
                                f"его правка не отменила бы подтверждение")
        unlisted = set(artefacts) - declared
        if unlisted:
            raise ContractError(
                f"отпечаток изоляции: {sorted(unlisted)} считается, но не объявлено")
        # Объявленное, но не считаемое, обязано быть названо с причиной —
        # иначе таблица обещает больше, чем проверяет, и никто этого не видит.
        promised = declared - set(artefacts) - {"версии_CLI"}
        unexplained = promised - set(fingerprint["пока_не_вычисляется"])
        if unexplained:
            raise ContractError(
                f"отпечаток изоляции: {sorted(unexplained)} обещано, но не считается "
                f"и не объяснено")
        # 🚩 Ревью #32: причина отсрочки без владельца — ничья работа. Каждое
        # несчитаемое поле обязано указать критерий незакрытого блока, который
        # его вычислит, и этот блок обязан держать шлюз изоляции.
        criteria = {item.id: (name, item.condition)
                    for name, block in self.blocks.items() for item in block.acceptance}
        gate_blocks = set(plan["шлюзы"]["изоляция_подтверждена"]["до_закрытия"])
        for field_name, entry in fingerprint["пока_не_вычисляется"].items():
            if not isinstance(entry, dict) or not str(entry.get("почему", "")).strip():
                raise ContractError(f"отпечаток изоляции: {field_name} отложено без причины")
            target = entry.get("закрывает")
            if target not in criteria:
                raise ContractError(
                    f"отпечаток изоляции: {field_name} отложено без владельца — "
                    f"критерия {target!r} нет")
            owner, condition = criteria[target]
            if field_name not in condition:
                raise ContractError(
                    f"отпечаток изоляции: {field_name} отдано критерию {target}, "
                    f"который о нём не говорит")
            if self.blocks[owner].state == "сделано":
                raise ContractError(
                    f"отпечаток изоляции: {field_name} отдано закрытому блоку {owner}")
            if owner not in gate_blocks:
                raise ContractError(
                    f"отпечаток изоляции: владелец {owner} поля {field_name} "
                    f"не держит шлюз изоляции")
        checked.append(f"отпечаток изоляции: считается {len(artefacts) + 1} полей из "
                       f"{len(declared)}; несчитаемые держат шлюз закрытым")

        self._check_absorption()
        checked.append("поглощение: формулы объединения соблюдены")
        # Сухой прогон — последним: он опирается на всё проверенное выше, и его
        # отказ не должен заслонять более точную причину.
        self._check_execution()
        checked.append("исполнение: у каждого незакрытого блока исполнитель, волны "
                       "уважают зависимости и шлюзы, сухой прогон проходит до конца")

        sources = {
            "схемы_контрактов": self.vocabulary["схемы_контрактов"],
            "операции": self.vocabulary["операции"],
            "коды_предпроверки": self.precheck["коды"],
            **plan["списки"],
        }
        for name, block in self.blocks.items():
            for key, declared in block.declared_counts.items():
                if key not in sources:
                    raise ContractError(f"{name}: нечем сверить {key}")
                actual = len(sources[key])
                if actual != declared:
                    raise ContractError(
                        f"{name}: объявлено {declared} {key}, в списке {actual}")
        checked.append("объявленные количества сходятся с длиной списков")
        return checked

    def _check_no_cycles(self) -> None:
        colour = {}

        def walk(name):
            state = colour.get(name)
            if state == "grey":
                raise ContractError(f"цикл зависимостей через {name}")
            if state == "black":
                return
            colour[name] = "grey"
            for dependency in self.blocks[name].depends:
                walk(dependency)
            colour[name] = "black"

        for name in self.blocks:
            walk(name)

    def _check_absorption(self) -> None:
        merged = {n: b.absorbed_by for n, b in self.blocks.items()
                  if b.state == "объединён_с" and b.absorbed_by}
        for start in merged:
            seen, cursor = [], start
            while cursor in merged:
                if cursor in seen:
                    raise ContractError(f"цикл поглощения: {' → '.join(seen + [cursor])}")
                seen.append(cursor)
                cursor = merged[cursor]

        for name, block in self.blocks.items():
            if block.state != "объединён_с":
                continue
            if not block.absorbed_by:
                raise ContractError(f"{name}: объединён_с без поглотителя")
            if block.absorbed_by not in self.blocks:
                raise ContractError(f"{name}: поглотитель {block.absorbed_by} не существует")
            absorber = self.blocks[block.absorbed_by]
            if name not in absorber.absorbs:
                raise ContractError(f"{absorber.name}: не объявил поглощение {name}")
            if name in absorber.depends:
                raise ContractError(
                    f"{absorber.name} зависит от поглощённого {name}: тупик")
            if not set(block.depends) <= set(absorber.depends):
                raise ContractError(
                    f"{absorber.name}: зависимости {name} потеряны при поглощении")
            # by (id, condition): keeping the id and rewriting the text is how
            # an acceptance criterion disappears while the set comparison passes
            ours = {(i.id, i.condition) for i in absorber.acceptance}
            theirs = {(i.id, i.condition) for i in block.acceptance}
            if not theirs <= ours:
                raise ContractError(
                    f"{absorber.name}: приёмка {name} потеряна или подменена: "
                    f"{sorted(i for i, _ in theirs - ours)}")
            for field_name, ours_set, theirs_set in (
                    ("пишет", set(absorber.writes), set(block.writes)),
                    ("читает", set(absorber.reads), set(block.reads)),
                    ("внешние_действия", set(absorber.external), set(block.external))):
                if not theirs_set <= ours_set:
                    raise ContractError(
                        f"{absorber.name}: {field_name} блока {name} не покрыто")

    def _combinations(self, state, event):
        """Every combination of the condition codes this pair reads."""
        keys = self.condition_keys(state, event)
        if not keys:
            return [{}]
        codes = self.vocabulary["коды_условий"]
        combinations = [{}]
        for key in keys:
            combinations = [dict(base, **{key: value})
                            for base in combinations for value in codes[key]]
        return combinations

    # -- isolation ----------------------------------------------------------
    def _check_execution(self) -> None:
        """Пункт 5 PEV как проверяемые данные, а не абзац плана.

        Параллельные исполнители с общим файлом правят одно и то же; волна,
        стоящая раньше своей зависимости, — работа на несуществующем основании.
        """
        spec = self.plan["исполнение"]
        _require(spec, {"роли", "проверки", "шаги", "блоки", "выполнено"}, set(),
                 "blocks.исполнение")
        roles, checks = set(spec["роли"]), set(spec["проверки"])
        rows = spec["блоки"]
        pending = {name for name, block in self.blocks.items()
                   if block.state != "сделано" and not block.outside_mvp}
        fingerprint = self.plan["отпечаток_изоляции"]
        prover = fingerprint["проверяет_блок"]
        # Ревью #34–#35: «сделано» в таблице — не «изоляция подтверждена», и
        # «все поля умеем считать» — тоже не она. Действует ли подтверждение,
        # записано явным флагом (его сверяет с реальностью `authority`), а
        # отменяет его любой блок, пишущий во входы отпечатка. Решается по
        # таблице, без обращения к среде: `check` остаётся чистым.
        writers = {name for name in pending
                   if name != prover and _overlaps(self.blocks[name].writes, fingerprint["входы"])}
        needed = (not fingerprint["подтверждение_действует"] or bool(writers)
                  or bool(fingerprint["пока_не_вычисляется"]))
        if needed:
            pending.add(prover)
            if prover not in rows:
                raise ContractError(
                    f"исполнение: подтверждение изоляции не действует или будет отменено "
                    f"{sorted(writers)}, а повторного {prover} в плане нет")
        # Выполненные волны — отдельный список: он остаётся, когда строка блока
        # уходит из будущих работ, и только по нему видно, ПРИ КАКОМ допуске
        # блок был закрыт (ревью #37).
        executed = spec["выполнено"]
        for name, wave in executed.items():
            if name not in self.blocks:
                raise ContractError(f"исполнение: выполнено {name}, которого нет среди блоков")
            if name in rows:
                raise ContractError(f"исполнение: {name} и выполнен, и в будущих работах")
            if self.blocks[name].state != "сделано":
                raise ContractError(f"исполнение: {name} записан выполненным, а состояние "
                                    f"{self.blocks[name].state!r}")
            if not isinstance(wave, int) or isinstance(wave, bool):
                raise ContractError(f"исполнение: волна выполненного {name} — не целое")
        listed = set(rows)
        if pending - listed:
            raise ContractError(f"исполнение: без исполнителя {sorted(pending - listed)}")
        if listed - pending:
            raise ContractError(f"исполнение: {sorted(listed - pending)} закрыт или вне MVP")
        waves_of = {}
        by_wave = {}
        for name, row in rows.items():
            where = f"blocks.исполнение.блоки.{name}"
            _require(row, {"волна", "исполнитель", "изоляция", "ревью"}, set(), where)
            own = row["волна"] if isinstance(row["волна"], list) else [row["волна"]]
            if len(own) > 1 and name != prover:
                raise ContractError(f"{where}: несколько волн бывает только у {prover}")
            if not own or any(not isinstance(w, int) or isinstance(w, bool) for w in own):
                raise ContractError(f"{where}: волна — целое или список целых")
            waves_of[name] = sorted(own)
            if row["исполнитель"] not in roles:
                raise ContractError(f"{where}: исполнитель {row['исполнитель']!r} не из ролей")
            unknown = set(row["ревью"]) - checks
            if unknown:
                raise ContractError(f"{where}: проверки {sorted(unknown)} не из списка")
            if "codex" not in row["ревью"]:
                raise ContractError(f"{where}: блок без внешнего критика")
            if row["изоляция"] not in ("worktree", "основное_дерево"):
                raise ContractError(f"{where}: изоляция {row['изоляция']!r}")
            for wave in own:
                by_wave.setdefault(wave, []).append(name)
        for name in rows:
            for dependency in self.blocks[name].depends:
                if dependency not in pending:
                    continue
                if dependency not in rows:
                    raise ContractError(
                        f"исполнение: {name} ждёт {dependency}, которого нет в плане исполнения")
                if waves_of[dependency][0] >= waves_of[name][0]:
                    raise ContractError(
                        f"исполнение: {name} в волне {waves_of[name][0]}, а его зависимость "
                        f"{dependency} — не раньше")
        for wave, names in by_wave.items():
            if len(names) > 1 and any(rows[n]["изоляция"] != "worktree" for n in names):
                raise ContractError(f"исполнение: волна {wave} параллельна, а не в worktree")
            for left, right in itertools.combinations(sorted(names), 2):
                shared = _overlaps(self.blocks[left].writes, self.blocks[right].writes)
                if shared:
                    raise ContractError(f"исполнение: {left} и {right} в волне {wave} "
                                        f"пишут общее {shared}")
        owners = {self._criterion_owner(entry["закрывает"])
                  for entry in fingerprint["пока_не_вычисляется"].values()}
        if prover in rows and owners:
            last_owner = max(waves_of[o][0] for o in owners)
            if waves_of[prover][-1] <= last_owner:
                raise ContractError(f"исполнение: повторный {prover} не позже "
                                    f"{sorted(owners)}, чьи поля отпечатка он доказывает")
        self._dry_run(waves_of, by_wave, pending, prover, owners, writers,
                      fingerprint["подтверждение_действует"], dict(executed))

    def _criterion_owner(self, criterion: str) -> str:
        return next(name for name, block in self.blocks.items()
                    if any(item.id == criterion for item in block.acceptance))

    def _dry_run(self, waves_of: dict, by_wave: dict, pending: set, prover: str,
                 owners: set, writers: set, confirmed: bool, executed: dict) -> None:
        """Сквозной сухой прогон волн с меняющимся по ходу допуском.

        Ревью #34: правила по отдельности зелёные, а план не проходился.
        Ревью #35: прогон считал подтверждение изоляции неизменным, хотя его
        отменяет каждый блок, пишущий во входы отпечатка, а восстанавливает
        только прогон доказывающего блока ПОСЛЕ полного отпечатка. Здесь волны
        проходятся по порядку, и спрашивается ТОТ ЖЕ `hold_reasons`, что в бою.
        Единственное допущение — разрешение Антона: оно выдаётся на объём и
        заранее не выводится.
        """
        done = {name for name, block in self.blocks.items()
                if block.state == "сделано" and name not in pending}
        state = {"подтверждено": confirmed}
        future = dict(self.plan["исполнение"]["блоки"])

        def closed(name: str) -> bool:
            if name == prover:
                return state["подтверждено"]
            block = self.blocks[name]
            if block.state == "объединён_с" and block.absorbed_by:
                return block.absorbed_by in done
            return name in done

        saved = self.__dict__.get("closed"), self.__dict__.get("permitted")
        object.__setattr__(self, "closed", closed)
        object.__setattr__(self, "permitted", lambda name: {"сухой_прогон": True})
        try:
            for wave in sorted(by_wave):
                names = sorted(by_wave[wave])
                for name in names:
                    held = self.hold_reasons(name)
                    if held:
                        raise ContractError(
                            f"исполнение: сухой прогон — {name} в волне {wave} "
                            f"удержан: {'; '.join(held)}")
                if prover in names:
                    if not owners <= done:
                        raise ContractError(
                            f"исполнение: сухой прогон — повторный {prover} в волне {wave} "
                            f"до полного отпечатка, ждёт {sorted(owners - done)}")
                    if writers & set(names):
                        raise ContractError(
                            f"исполнение: сухой прогон — в волне {wave} {prover} "
                            f"подтверждает то, что меняет {sorted(writers & set(names))}")
                    state["подтверждено"] = True
                if writers & set(names):
                    state["подтверждено"] = False
                done |= set(names) - {prover}
                # Ревью #36: состояние ПОСЛЕ волны проверяется тем же правилом,
                # которым оформляется настоящее закрытие блока. Иначе прогон
                # разрешает то, что записать в таблицу уже нельзя.
                # Закрытый блок уходит из будущих работ в выполненные — так же,
                # как это делает живая сессия. Иначе прогон проверял бы
                # состояние, которого в таблице никогда не будет (ревью #37).
                for name in names:
                    if name != prover:
                        executed[name] = wave
                        future.pop(name, None)
                illegal = self.gate_violations(
                    closed,
                    lambda n: n in done or self.blocks[n].state in ("сделано", "неполный"),
                    executed, future)
                if illegal:
                    raise ContractError(
                        f"исполнение: сухой прогон — после волны {wave} состояние "
                        f"запрещено: {illegal[0]}")
            if not state["подтверждено"]:
                raise ContractError(
                    f"исполнение: сухой прогон — после последней волны подтверждение "
                    f"изоляции отменено и не восстановлено")
        finally:
            for attribute, value in zip(("closed", "permitted"), saved):
                if value is None:
                    self.__dict__.pop(attribute, None)
                else:
                    object.__setattr__(self, attribute, value)

    def isolation_ok(self, observed_versions: dict | None = None) -> bool:
        """Whether the isolation proof still describes the current command.

        The gate used to read `closed("Ш1")` and nothing else, so the proof was
        eternal: change `adapters.py` without touching a CLI version and it
        stayed green on evidence that no longer described what runs.
        """
        return not self.isolation_drift(observed_versions)

    def isolation_drift(self, observed_versions: dict | None = None) -> list[str]:
        """Every field of the fingerprint that no longer matches. Fails closed."""
        spec = self.plan["отпечаток_изоляции"]
        report_path = ROOT / spec["отчёт"]
        if not report_path.exists():
            return ["отчёта нет"]
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return ["отчёт нечитаем"]
        spec_report = self.plan["отпечаток_изоляции"]
        # 🚩 Ревью #27: сравнивались ТОЛЬКО хеши файлов. Отчёт с вердиктом FAIL
        # или INCOMPLETE, со снятой заморозкой команды — и шлюз открывался,
        # потому что файлы-то не менялись. Совпадение отпечатка доказывает, что
        # проверяли ЭТУ команду, но не то, что проверка удалась.
        if report.get("verdict") != spec_report["успешный_вердикт"]:
            return [f"вердикт отчёта {report.get('verdict')!r}, а не "
                    f"{spec_report['успешный_вердикт']!r}"]
        if report.get("command_frozen") is not True:
            return ["команда не помечена замороженной"]

        # 🚩 Ревью #29, тот же класс во второй половине: отсутствующий файл
        # давал пустую строку, пустая строка в отчёте — тоже, и два «ничего»
        # совпадали. Отсутствие обязательного файла — самостоятельный отказ, а
        # пустой отпечаток не доказательство ни с одной стороны.
        missing = [field_name for field_name, relative in spec["артефакты"].items()
                   if not (ROOT / relative).is_file()]
        if missing:
            return [f"нет обязательного файла: {', '.join(sorted(missing))}"]

        recorded = report.get("отпечаток") or {}
        drift = []
        for field_name, digest in self.isolation_fingerprint().items():
            if not digest or not recorded.get(field_name):
                drift.append(f"{field_name}: пустой отпечаток не доказательство")
            elif recorded[field_name] != digest:
                drift.append(field_name)

        # Версии среды спрашиваются ВСЕГДА, а не только когда их передали.
        #
        # 🚩 Ревью #28: «не смогли спросить» возвращало None, отсутствующее поле
        # в отчёте — тоже None, и два неизвестных сравнивались как РАВНЫЕ. Нет
        # данных превращалось в согласие. Теперь недоступность среды и пустые
        # версии в отчёте — самостоятельные расхождения, до всякого сравнения.
        recorded_versions = report.get("versions")
        if not isinstance(recorded_versions, dict) or not all(
                recorded_versions.get(vendor) for vendor in spec_report["версии_команд"]):
            drift.append("в отчёте нет версий обоих вендоров")
            return drift
        if observed_versions is None and _WITHOUT_ENVIRONMENT.get():
            # Не спросили — значит не подтверждено: отсутствие ответа не согласие.
            drift.append(VERSIONS_NOT_ASKED)
        else:
            observed = (observed_versions if observed_versions is not None
                        else observe_cli_versions(spec_report["версии_команд"]))
            if observed is None:
                drift.append("среду не удалось спросить о версиях")
            elif recorded_versions != observed:
                drift.append("версии_CLI")

        # 🚩 Ревью #31: неполный отпечаток открывал шлюз живых вызовов. Совпадение
        # трёх полей из семи выдавалось за подтверждение всей изоляции, хотя
        # окружение и HOME/CODEX_HOME передаются сборщику параметрами и меняются,
        # не трогая ни одного хешируемого файла. Допуск — только полный отпечаток:
        # несчитаемое поле — расхождение, а не пропуск.
        for field_name in sorted(spec["пока_не_вычисляется"]):
            drift.append(f"{field_name}: не вычисляется")
        return drift

    def isolation_fingerprint(self) -> dict:
        """Digests of everything the proof depends on, computed from the tree."""
        spec = self.plan["отпечаток_изоляции"]
        out = {}
        for field_name, relative in spec["артефакты"].items():
            path = ROOT / relative
            # Пустая строка для пропавшего файла — не «значение», а признак его
            # отсутствия; сравнивать её ни с чем нельзя (ревью #29).
            out[field_name] = (hashlib.sha256(path.read_bytes()).hexdigest()
                               if path.is_file() else "")
        return out


@functools.lru_cache(maxsize=1)
def _cli_version(command: tuple) -> str | None:
    import subprocess
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


# Круг 42 (R42-11): генератор документа спрашивал среду о версиях CLI, и текст
# документа менялся от того, что установлено на машине. Пока идёт рендер, среда
# не спрашивается вовсе: версии сверяет только команда `isolation`.
_WITHOUT_ENVIRONMENT = contextvars.ContextVar("roundtable_without_environment", default=False)
VERSIONS_NOT_ASKED = "версии_CLI: сверяет команда isolation, документ среду не спрашивает"


def observe_cli_versions(commands: dict) -> dict | None:
    """Спросить среду, какие вендоры стоят сейчас. Не ответила — не согласие."""
    observed = {}
    for vendor, command in commands.items():
        version = _cli_version(tuple(command))
        if version is None:
            return None
        observed[vendor] = version
    return observed


def _is_sha40(value) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(c in "0123456789abcdef" for c in value))


def _is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _is_uuid(value) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split("-")
    return ([len(p) for p in parts] == [8, 4, 4, 4, 12]
            and all(c in "0123456789abcdef-" for c in value))


def memory_receipt(plan: dict, home: Path | None = None) -> list[str]:
    """Проверка второго шага БК: память обязана ссылаться на коммит канона.

    Память живёт вне git, поэтому «обновим тем же коммитом» невыполнимо. Вместо
    обещания — квитанция: каждый named файл памяти называет коммит, который
    действительно трогал канон.
    """
    home = Path(home) if home else Path.home()
    expected = canon_commit(plan)
    if expected is None:
        return ["не удалось спросить git, какой коммит трогал канон последним"]
    problems = []
    # 🚩 Ревью #38: пустой список файлов выключал проверку целиком и при этом
    # печатал «память актуальна». Проверка без предмета — не проверка.
    if not plan["проверка_памяти"]["файлы"]:
        return ["список файлов памяти пуст — проверять нечего"]
    for relative in plan["проверка_памяти"]["файлы"]:
        path = Path(str(relative).replace("~", str(home), 1))
        if not path.is_file():
            problems.append(f"нет файла памяти: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        # any *historic* canon commit used to pass, so memory could name a
        # long-superseded state and look fresh. It must name the current one.
        if not any(expected.startswith(sha)
                   for sha in re.findall(r"\b[0-9a-f]{7,40}\b", text)):
            problems.append(f"{path.name}: не называет текущий канон {expected[:7]}")
            continue
        # 🚩 Ревью #40: дописать текущий хеш в старый текст — и «память
        # актуальна». Хеш доказывает только, что его дописали. Поэтому файлы,
        # которые ведутся записями, обязаны иметь запись с датой не раньше
        # даты текущего канона: старый текст с новым хешем её не даёт.
        #
        # Граница названа честно (R40-1): сфабриковать строку с датой можно,
        # как и любой замок в репозитории. Проверка ловит забывчивость и
        # «подправил хеш, содержимое не трогал», а не сознательную подделку.
        if str(relative) not in plan["проверка_памяти"]["ведутся_записями"]:
            continue
        day = canon_date(plan)
        if day is None:
            problems.append("не удалось спросить git о дате канона")
            continue
        dates = re.findall(r"\b(20\d\d-\d\d-\d\d)\b", text)
        if not any(found >= day for found in dates):
            problems.append(f"{path.name}: нет записи с датой не раньше {day} — "
                            f"назван новый канон, а содержимое не менялось")
    return problems


def canon_date(plan: dict) -> str | None:
    """Дата последнего изменения канона, YYYY-MM-DD."""
    out = _git("log", "-1", "--date=format:%Y-%m-%d", "--format=%ad", "--",
               *plan["проверка_памяти"]["канон"])
    return (out or "").strip() or None


def canon_commit(plan: dict) -> str | None:
    """The last commit that touched the canon. What memory has to point at."""
    import subprocess
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%H", "--"]
            + list(plan["проверка_памяти"]["канон"]),
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def _overlaps(left, right) -> list[str]:
    """Общие пути двух областей записи: совпадение или вложенность в каталог."""
    return sorted({a for a in left if not a.startswith("~")
                   for b in right if not b.startswith("~")
                   if a == b or (a.endswith("/") and b.startswith(a))
                   or (b.endswith("/") and a.startswith(b))})


def within(path: str, writes) -> bool:
    """Путь внутри объявленной области записи: точное имя или каталог с `/`."""
    return any(path == entry or (entry.endswith("/") and path.startswith(entry))
               for entry in writes if not entry.startswith("~"))


def _git(*args: str) -> str | None:
    import subprocess
    try:
        done = subprocess.run(["git", "-C", str(ROOT), *args],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _paths(raw: str) -> list[str]:
    """Имена из вывода git с `-z`: пробелы и не-ASCII приходят как есть."""
    return [path for path in raw.split("\x00") if path]


def write_scope_receipt(tables: "Tables") -> list[str]:
    """R19-7: коммиты каждого закрытого блока не выходят за его `пишет`.

    Сверяется в обе стороны. Названный коммит обязан существовать, быть
    обычным (у слияния diff пуст, и оно прятало бы что угодно), нести трейлер
    своего блока и трогать только объявленное. И наоборот: коммит с трейлером
    блока, не названный в его списке, — работа мимо учёта. Коммит без трейлера
    сверке невидим; это граница, а не гарантия — её держит ревью блока.

    Молчание git — отказ, а не пустой diff: ревью #33 нашло, что `None` от
    упавшего git превращался в «коммит ничего не трогал» и в пустую историю.
    """
    trailer = tables.plan["сверка_записи"]["трейлер"]
    trailer_format = f"%(trailers:key={trailer},valueonly,separator=%x02)"
    problems = []
    listed = {}
    for name, block in tables.blocks.items():
        for sha in block.commits:
            listed[sha] = name
            parents = _git("rev-list", "--parents", "-n", "1", sha)
            if parents is None:
                problems.append(f"{name}: коммита {sha[:7]} нет")
                continue
            # Ревью #34: коммит из ветки исполнителя, ещё не влитый, проходил.
            # Засчитывается только то, что входит в историю проверяемой версии.
            if _git("merge-base", "--is-ancestor", sha, "HEAD") is None:
                problems.append(f"{name}: {sha[:7]} не входит в проверяемую ветку")
                continue
            # корневой коммит — обычный: одна запись без родителя
            if len(parents.split()) > 2:
                problems.append(f"{name}: {sha[:7]} — слияние, diff не сверить")
                continue
            claimed = _git("log", "-1", f"--format={trailer_format}", sha)
            if claimed is None:
                problems.append(f"{name}: {sha[:7]} — git не отдал трейлеры")
                continue
            # только настоящий трейлер: строка «Блок: X» посреди текста не в счёт
            if name not in [v.strip() for v in claimed.strip().split("\x02")]:
                problems.append(f"{name}: {sha[:7]} без трейлера «{trailer}: {name}»")
            raw = _git("-c", "core.quotePath=false", "diff-tree", "--root",
                       "--no-commit-id", "--name-only", "-r", "--no-renames", "-z", sha)
            if raw is None:
                problems.append(f"{name}: {sha[:7]} — git не отдал diff, сверить нечего")
                continue
            outside = [path for path in _paths(raw) if not within(path, block.writes)]
            if outside:
                problems.append(f"{name}: {sha[:7]} вышел за `пишет`: {outside}")
    history = _git("log", f"--format=%H%x00{trailer_format}%x01")
    if history is None:
        return problems + ["git не отдал историю — работу мимо учёта не проверить"]
    for record in history.split("\x01"):
        if "\x00" not in record:
            continue
        sha, values = record.strip("\n").split("\x00", 1)
        for claimed in (v.strip() for v in values.split("\x02")):
            if claimed and listed.get(sha) != claimed:
                problems.append(f"{sha[:7]} помечен «{trailer}: {claimed}», но в коммитах "
                                f"{claimed} не назван — работа мимо учёта")
    return problems + unparsed_block_marks(tables)


def unparsed_block_marks(tables: "Tables") -> list[str]:
    """Круг 42 (R42-8): пометка блока в тексте, которую git не разобрал трейлером.

    git считает трейлерами только ПОСЛЕДНИЙ абзац сообщения. Пустая строка
    между пометкой и подписью оставляла пометку текстом тела: коммит выглядел
    непомеченным, и сверка его не проверяла вовсе. Строка пометки в начале
    строки тела без разобранного трейлера — отказ; упоминание посреди фразы —
    не пометка. Исключение — только доказанное (`_exemption_problems`).
    """
    rule = tables.plan["сверка_записи"]
    trailer = rule["трейлер"]
    exempt = rule.get("откачено_без_трейлера") or {}
    trailer_format = f"%(trailers:key={trailer},valueonly,separator=%x02)"
    parsed_log = _git("log", f"--format=%H%x00{trailer_format}%x01")
    bodies = _git("log", "--format=%H%x00%B%x01")
    if parsed_log is None or bodies is None:
        return ["git не отдал сообщения коммитов — пометку в тексте не проверить"]
    parsed = {}
    for record in parsed_log.split("\x01"):
        if "\x00" not in record:
            continue
        sha, values = record.strip("\n").split("\x00", 1)
        parsed[sha] = {value.strip() for value in values.split("\x02") if value.strip()}
    pattern = re.compile(rf"^{re.escape(trailer)}:[ \t]*(\S+)[ \t]*$", re.M)
    problems = []
    for record in bodies.split("\x01"):
        if "\x00" not in record:
            continue
        sha, body = record.strip("\n").split("\x00", 1)
        unparsed = sorted(set(pattern.findall(body)) - parsed.get(sha, set()))
        if not unparsed:
            continue
        if sha in exempt:
            problems += _exemption_problems(sha, unparsed, exempt[sha], trailer)
            continue
        problems.append(f"{sha[:7]}: пометка «{trailer}: {unparsed[0]}» стоит в тексте, но git "
                        f"не разобрал её трейлером — пустая строка отделила её от подписи; "
                        f"работа мимо учёта")
    return problems


def _exemption_problems(sha: str, unparsed: list, entry: dict, trailer: str) -> list[str]:
    """Исключение доказывается историей, а не записью в таблице.

    Работа коммита откачена (откат трогает его файлы и стоит после него) и
    переложена заново коммитом с теми же файлами и настоящим трейлером того же
    блока. Иначе список исключений стал бы новым способом спрятать работу.
    """
    label = f"{sha[:7]}: исключение из правила о пометке"
    why = entry.get("почему")
    if not isinstance(why, str) or not why.strip():
        return [f"{label} без причины"]
    undone, redone = entry.get("откат"), entry.get("заново")
    for name, value in (("откат", undone), ("заново", redone)):
        if _git("rev-list", "-n", "1", str(value)) is None:
            return [f"{label}: коммита «{name}» {str(value)[:7]} нет"]
    if len({sha, undone, redone}) < 3:
        return [f"{label}: исходный, откат и переложенный — три разных коммита"]
    for older, newer in ((sha, undone), (undone, redone), (redone, "HEAD")):
        if _git("merge-base", "--is-ancestor", older, newer) is None:
            return [f"{label}: {older[:7]} не предшествует {newer[:7]} — "
                    f"откат и перекладка не доказаны"]

    def files(commit: str) -> set:
        raw = _git("-c", "core.quotePath=false", "diff-tree", "--root", "--no-commit-id",
                   "--name-only", "-r", "--no-renames", "-z", commit)
        return set(_paths(raw or ""))
    own = files(sha)
    if not own or not own <= files(undone):
        return [f"{label}: откат {undone[:7]} не трогает файлы коммита"]
    if files(redone) != own:
        return [f"{label}: переложенный {redone[:7]} трогает другие файлы"]
    marks = _git("log", "-1", f"--format=%(trailers:key={trailer},valueonly,separator=%x02)",
                 redone)
    carried = {value.strip() for value in (marks or "").split("\x02") if value.strip()}
    if marks is None or not set(unparsed) <= carried:
        return [f"{label}: переложенный {redone[:7]} не несёт трейлер «{trailer}: {unparsed[0]}»"]
    return []


def staged_outside_scope(tables: "Tables", name: str) -> list[str]:
    """Что из подготовленного к коммиту вышло за `пишет` блока — до коммита."""
    staged = _git("-c", "core.quotePath=false", "diff", "--cached", "--name-only",
                  "--no-renames", "-z")
    if staged is None:
        raise ContractError("git не ответил, что подготовлено к коммиту")
    return [path for path in _paths(staged) if not within(path, tables.blocks[name].writes)]


# Обвязка, попадающая в реплику пользователя не от него: напоминания среды,
# вывод локальных команд и вставленный чужой текст. Разрешение — слова человека,
# поэтому цитата ищется в остатке (ревью #39).
INJECTED = ("system-reminder", "command-name", "command-message", "command-args",
            "local-command-stdout", "local-command-caveat", "pasted_content")


def own_words(text: str) -> str:
    """Реплика без служебных вставок и вставленного чужого текста."""
    for tag in INJECTED:
        text = re.sub(rf"<{tag}\b.*?</{tag}>", " ", text, flags=re.S)
        text = re.sub(rf"<{tag}\b[^>]*>", " ", text)
    return text


def resolve_basis(basis: dict, home: Path | None = None) -> str | None:
    """Actually open what the permission points at. Returns the failure, or None.

    Structure checks proved a string was non-empty. That is what let a citation
    through that I could not confirm afterwards.
    """
    home = Path(home) if home else Path.home()
    if basis["вид"] == "план_артефакт":
        raw = str(basis["путь"])
        # Артефакт под ~/ живёт вне репозитория и может исчезнуть — что и
        # случилось 16.09 с утверждённым планом. Путь внутри репозитория
        # резолвится от корня и переживает уборку временных каталогов.
        path = (Path(raw.replace("~", str(home), 1)) if raw.startswith("~")
                else Path(raw) if Path(raw).is_absolute() else ROOT / raw)
        if not path.is_file():
            return f"артефакта нет: {path}"
        # Путь от корня, но ярлык внутри может вести наружу — сверяем реальный.
        if not (raw.startswith("~") or Path(raw).is_absolute()) \
                and not path.resolve().is_relative_to(Path(ROOT).resolve()):
            return f"артефакт вне репозитория: {raw} → {path.resolve()}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != basis["sha256"]:
            return f"sha256 не совпал: {digest[:12]}… против {basis['sha256'][:12]}…"
        return None

    # 🚩 Ревью #38: идентификатор сессии подставлялся в путь как есть, и
    # `../..` уводил чтение за пределы каталога переписок. Пустая цитата при
    # этом «находилась» в любой реплике: `"" in text` — всегда истина.
    session, wanted, quote = basis["сессия"], basis["native_uuid"], basis["цитата"]
    if not _is_uuid(session):
        return f"сессия не похожа на идентификатор: {session!r}"
    if not _is_uuid(wanted):
        return f"событие не похоже на идентификатор: {wanted!r}"
    if len(str(quote).strip()) < MIN_QUOTE:
        return f"цитата короче {MIN_QUOTE} знаков — доказывать ей нечего"
    candidates = list(home.glob(f".claude/projects/*/{session}.jsonl"))
    if not candidates:
        return f"сессии нет: {session}"
    # 🚩 Ревью #39: файл переписки мог оказаться ярлыком наружу — и «основание»
    # читалось из чего угодно.
    transcript = candidates[0]
    projects = (home / ".claude/projects").resolve()
    if not transcript.resolve().is_relative_to(projects):
        return f"запись сессии ведёт наружу: {transcript.resolve()}"
    for line in transcript.open(encoding="utf-8"):
        if wanted not in line:
            continue
        record = json.loads(line)
        if record.get("uuid") != wanted:
            continue
        if record.get("type") != "user":
            return f"{wanted}: не реплика пользователя"
        content = record.get("message", {}).get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        # 🚩 Ревью #39: «разрешаю» засчитывалось, даже когда стояло в служебной
        # вставке или в чужом тексте, вставленном в реплику, — а собственные
        # слова Антона говорили обратное. Разрешение даёт человек, а не обвязка.
        own = own_words(text)
        if quote in own:
            return None
        return (f"{wanted}: цитата есть только в служебной вставке, не в словах человека"
                if quote in text else f"{wanted}: цитата не найдена в реплике")
    return f"{wanted}: события нет в сессии"


def load(directory: Path = TABLES_DIR) -> Tables:
    """Load, type and cross-check every table in `directory`.

    БТ2-4 (closing R12-5): the closed-code closure of all three automata is
    checked here, on every load — a typo in a condition code fails the load
    instead of silently disabling the transition it broke. The heavier plan
    analysis (`_check_plan`, folded into `Tables.check`) stays a deliberate
    second step: test_roundtable_mutations.py relies on a structurally valid
    table with a broken *plan* still loading, so a mutant can be told apart
    by which of the two guards actually caught it.
    """
    raw = {name: load_table(name, directory) for name in TABLE_NAMES}
    tables = Tables.from_raw(raw)
    tables._check_codes()
    return tables


# --------------------------------------------------------------------------
# generation of the normative sections of the document
#
# The tables of §6.7, §6.8, §8, §8.0, §8.1 and §11 existed twice — in YAML and
# by hand — and drifted apart twice. They are generated now; the reasoning
# around each block stays written by a human, which is the part prose is
# actually good at. Marker mechanics follow deploy/stc_block.py:121
# `inject_block`, but that module is wired to a single hard-coded marker pair
# and sits on the deploy path, so it is left alone.
# --------------------------------------------------------------------------

BEGIN = "<!-- ROUNDTABLE:BEGIN {name} -->"
END = "<!-- ROUNDTABLE:END {name} -->"
GENERATED_NOTE = (
    "<!-- сгенерировано из core/scripts/roundtable/tables/*.yaml; "
    "правки внутри блока стираются -->"
)


def _code_value(value) -> str:
    """A condition value exactly as the CLI and the YAML spell it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _cell(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (list, tuple)):
        return ", ".join(f"`{item}`" for item in value) if value else "—"
    if isinstance(value, dict):
        return ", ".join(f"`{k}`={_code_value(v)}" for k, v in value.items()) or "—"
    return str(value)


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _render_verdict(tables: Tables) -> list[str]:
    rows = [[str(i), row.condition, f"`{row.verdict}`"]
            for i, row in enumerate(tables.verdict, start=1)]
    lines = ["**Таблица вердикта.** Проверяется сверху вниз, первое совпадение выигрывает.",
             ""]
    lines += _table(["#", "Условие", "Вердикт"], rows)
    outside = tables.issues["вердикт_вне_таблицы"]
    lines += ["", "Вне таблицы:"]
    lines += [f"- `{name}` — {why}" for name, why in outside.items()]
    duty = tables.issues["обязательства"]
    lines += ["", f"**Обязательства:** {duty['что_входит']} → {duty['куда']}."]
    return lines


def _render_issue_transitions(tables: Tables) -> list[str]:
    rows = [[_cell(row.source), _cell(list(row.targets)), row.who, row.condition]
            for row in tables.issue_transitions]
    lines = _table(["Из", "В", "Кто вправе", "Условие"], rows)
    closers = tables.issues["кто_завершает"]
    lines += ["", "**Кто вправе завершить issue:**"]
    for who, statuses in closers.items():
        lines.append(f"- **{who}** — {_cell(statuses)}")
    return lines


DECISION_EVENTS = ("submit-decision", "submit-framing-decision")


def _render_run_transitions(tables: Tables) -> list[str]:
    # The decision rows are the same rows §8.0 renders; printing them here as
    # well would put thirty lines of the contract in the document twice — the
    # very shape this generation exists to remove.
    rows = [[_cell(t.source), f"`{t.event}`", _cell(t.conditions), f"`{t.target}`",
             _cell(list(t.actions)), _cell(t.refusal and f"`{t.refusal}`")]
            for t in tables.transitions if t.event not in DECISION_EVENTS]
    lines = ["Решения Антона — отдельной таблицей в §8.0, чтобы одни и те же "
             "строки не стояли в документе дважды.", ""]
    lines += _table(["Из", "Событие", "Условия", "В", "Действия", "Отказ"], rows)
    lines += ["", "**Что значит каждое действие:**"]
    lines += [f"- `{code}` — {meaning}" for code, meaning in tables.run["действия"].items()]
    revoke = tables.run["revoke_operation"]
    lines += ["", "**Отзыв операции:**"]
    lines += [f"- цель — `{revoke['цель']}`; разрешено, если {revoke['разрешено_если']}",
              f"- зависимое событие: {_cell(revoke['зависимое_событие'])} → `{revoke['иначе']}`",
              f"- {revoke['компенсация']}; отката истории: {_cell(revoke['отката_истории'])}"]
    return lines


def _render_run_events(tables: Tables) -> list[str]:
    lines = []
    for event, title in (("submit-decision", "Решения по issue (контракт E)"),
                         ("submit-framing-decision", "Решения по возражению к постановке")):
        key = "decision" if event == "submit-decision" else "framing_decision"
        rows = [[f"`{t.conditions.get(key)}`", _cell(t.source), f"`{t.target}`",
                 _cell({k: v for k, v in t.conditions.items() if k != key}),
                 _cell(list(t.actions)), _cell(t.refusal and f"`{t.refusal}`")]
                for t in tables.transitions if t.event == event]
        lines += [f"**{title}** — операция `{event}`:", ""]
        lines += _table(["Решение", "Прогон из", "Прогон в", "При условии",
                         "Побочные действия", "Отказ"], rows)
        lines += [""]
    return lines[:-1]


def _render_framing(tables: Tables) -> list[str]:
    framing = tables.framing
    rows = [[_cell(row["из"]), f"`{row['в']}`", row["кто"], row["условие"]]
            for row in framing["переходы"]]
    lines = [f"Операция — `{framing['операция']}` по `{framing['цель']}`.", ""]
    lines += _table(["Из", "В", "Кто", "Условие"], rows)
    lines += ["", "**Влияние открытого возражения на вердикт стадии:**", ""]
    lines += _table(["Стадия", "Влияние"],
                    [[f"**{stage}**", f"`{effect}`"]
                     for stage, effect in framing["влияние_по_стадиям"].items()])
    limit = framing["ограничитель_смены_решения"]
    why = limit["почему"]
    lines += ["", f"**Ограничитель смены решения:** {limit['сколько']} за {limit['за']}; "
                  f"исход второй — `{limit['исход_второй']}` ({limit['природа']}). "
                  f"{why[:1].upper()}{why[1:]}."]
    lines += ["", f"**Флаг прогона:** `{framing['флаг_прогона']}`, "
                  f"обязателен в {_cell(framing['флаг_обязателен_в'])}.", "", "**Хранение:**", ""]
    lines += _table(["Что", "Срок"],
                    [[f"**{what}** — {_cell(spec.get('поля'))}" if spec.get("поля") else f"**{what}**",
                      spec["срок"]] for what, spec in framing["хранение"].items()])
    return lines


def _render_findings(tables: Tables) -> list[str]:
    """Every review finding and what proves its status.

    Nine rounds, ~60 findings, and "все приняты" used to be a claim with no
    executable basis — the exact shape those rounds kept catching.
    """
    from collections import Counter
    findings = tables.findings
    counts = Counter(f["статус"] for f in findings)
    lines = [f"Находок ревью: **{len(findings)}** из {len(set(f['круг'] for f in findings))} "
             f"кругов. " + "; ".join(f"{status} — {n}" for status, n in counts.most_common())
             + "."]
    waiting = [f for f in findings if f["статус"] == "ждёт_Антона"]
    if waiting:
        lines += ["", "🗳️ **Ждут продуктового решения Антона** — не дефект, а "
                  "граница продукта:"]
        lines += [f"- `{f['id']}` (#{f['круг']}) {f['что']} — {f['почему']}"
                  for f in waiting]
    open_ones = [f for f in findings if f["статус"] == "открыта"]
    if open_ones:
        lines += ["", "🔴 **Открытые — принято, исполнителя нет:**"]
        lines += [f"- `{f['id']}` (#{f['круг']}) {f['что']} — {f['почему']}" for f in open_ones]
    dismissed = [f for f in findings if f["статус"] == "избыточна"]
    if dismissed:
        lines += ["", "**Отклонены с обоснованием:**"]
        lines += [f"- `{f['id']}` (#{f['круг']}) {f['что']} — {f['почему']}" for f in dismissed]
    by_break = [f for f in findings
                if f["статус"] == "устранена"
                and f.get("поломка", "вне_таблиц") != "вне_таблиц"]
    only_test = [f for f in findings
                 if f["статус"] == "устранена"
                 and f.get("поломка", "вне_таблиц") == "вне_таблиц"]
    lines += ["", f"**Чем подтверждена «устранена».** Привязана исполнимая поломка — "
              f"**{len(by_break)}**; только имя теста — **{len(only_test)}**. "
              "⚠️ Привязку «находка ↔ поломка ↔ сторож» устанавливает человек при "
              "ревью; программа её не выводит, а защищает отпечатком от подмены. "
              "У второй группы табличной поломки нет вовсе, и подмену имени теста "
              "там сверять не с чем — слабость названа, а не спрятана."]
    lines += ["", "**Все находки.** «Устранена» обязана назвать существующий тест "
              "и либо ID исполнимой поломки, либо объяснение, почему её нет; "
              "«назначена блоку» — существующий критерий **незакрытого** блока. "
              "Текст находки под отпечатком: сохранить ID и переписать смысл нельзя."]
    rows = [[f"`{f['id']}`", str(f["круг"]), f["что"], f["статус"],
             f"`{f.get('тест') or f.get('критерий') or '—'}`",
             f"`{f['поломка']}`" if f.get("поломка") else "—"] for f in findings]
    lines += _table(["ID", "Круг", "Находка", "Статус", "Чем подтверждено", "Поломка"], rows)
    return lines


def _render_status(tables: Tables) -> list[str]:
    """The header line of the document, computed instead of typed.

    It said "next block — Б1" for as long as someone remembered to edit it.
    """
    done = [n for n in tables.plan["порядок"] if tables.closed(n)]
    lines = [f"Закрыто: {_cell(done)}." if done else "Закрытых блоков нет."]
    runnable = tables.next_runnable()
    if runnable:
        lines.append(f"Следующий исполнимый блок — **{runnable}**.")
    elif all(tables.closed(n) for n in tables.plan["порядок"]):
        lines.append("**MVP завершён.**")
    else:
        first = next(n for n in tables.plan["порядок"] if not tables.closed(n))
        reasons = "; ".join(tables.hold_reasons(first))
        lines.append(f"**Остановлено** на **{first}** — {reasons}.")
    gates = [g for g, spec in tables.plan["шлюзы"].items()
             if not all(tables.closed(b) for b in spec["до_закрытия"])]
    if gates:
        lines.append(f"Закрытые шлюзы: {_cell(gates)}.")
    return lines


def _render_blocks(tables: Tables) -> list[str]:
    plan = tables.plan
    rows = []
    marks = {"сделано": " ✅", "неполный": " 🚧", "идёт": " 🚧",
             "переоткрыт": " 🔁", "объединён_с": " 🔗"}
    for position, name in enumerate(plan["порядок"], start=1):
        block = tables.blocks[name]
        rows.append([
            str(position), f"**{name}**{marks.get(block.state, '')}", block.what,
            _cell(list(block.depends)), _cell(list(block.writes)),
            _cell([i.id for i in block.acceptance]),
        ])
    lines = _table(["#", "Блок", "Что", "Зависит от", "Область записи",
                    "Критерии приёмки"], rows)

    lines += ["", "**Чем удерживается каждый незакрытый блок** — все причины, "
              "а не первая: блок бывает и неразрешён, и без зависимости, и под "
              "шлюзом разом."]
    for name in plan["порядок"]:
        if tables.closed(name):
            continue
        block = tables.blocks[name]
        reasons = tables.hold_reasons(name)
        note = f" (переоткрыт: {block.reopened_because})" if block.reopened_because else ""
        lines.append(
            f"- **{name}** — {'; '.join(reasons) if reasons else 'исполним'}{note}")

    lines += ["", "**Шлюзы.**"]
    for gate, spec in plan["шлюзы"].items():
        open_ones = [b for b in spec["до_закрытия"] if not tables.closed(b)]
        state = f"закрыт, ждёт {_cell(open_ones)}" if open_ones else "открыт"
        lines.append(f"- `{gate}` — {state}; держит {_cell(spec['блокирует'])}. "
                     f"{spec['почему']}")

    lines += ["", "**Полномочия.** Заключение критиков и право исполнять — разные "
              "вещи и разные реестры. Разрешение выдаётся на **объём работ**, а не "
              "на имя блока: изменился объём — разрешение аннулировано."]
    for entry in plan["заключения_ревью"]:
        lines.append(f"- заключение ревью #{entry['круг']}: {_cell(entry['блоки'])} "
                     f"({entry['дата']})")
    for grant in plan["разрешения_исполнения"]:
        basis = grant["основание"]
        lines.append(f"- **действует** — {grant['кем']}: {_cell(grant['блоки'])} "
                     f"({grant['дата']}) — «{basis.get('цитата', '')}»")
    for grant in plan["история_разрешений"]:
        basis = grant["основание"]
        lines.append(f"- история, права не даёт — {grant['кем']}: "
                     f"{_cell(grant['блоки'])} ({grant['дата']}) — "
                     f"«{basis.get('цитата', '')}»")

    drift = tables.isolation_drift()
    fingerprint = plan["отпечаток_изоляции"]
    deferred = fingerprint["пока_не_вычисляется"]
    computed = [f for f in fingerprint["входит_в_отпечаток"] if f not in deferred]
    lines += ["", "**Отпечаток изоляции.** Шлюз живых вызовов открывается только на "
              f"полном отпечатке. Вычисляется {len(computed)} из "
              f"{len(fingerprint['входит_в_отпечаток'])}: {_cell(computed)}."]
    if deferred:
        lines.append(f"Не вычисляется — и потому само держит шлюз закрытым: "
                     f"{_cell(sorted(deferred))}.")
    lines.append(f"Отчёт `{fingerprint['отчёт']}`. "
                 + ("Сейчас **совпадает** полностью." if not drift
                    else f"Сейчас **не подтверждено**: {_cell(drift)} — "
                         f"{fingerprint['проверяет_блок']} считается незакрытым."))

    lines += ["", "**Вне порядка:**"]
    for name, why in plan["вне_порядка"].items():
        lines.append(f"- **{name}** — {tables.blocks[name].what} ({why})")
    return lines


SECTIONS = {
    "status": _render_status,
    "findings": _render_findings,
    "verdict": _render_verdict,
    "issue-transitions": _render_issue_transitions,
    "run-transitions": _render_run_transitions,
    "run-events": _render_run_events,
    "framing-automaton": _render_framing,
    "blocks": _render_blocks,
}


def render_section(name: str, tables: Tables) -> str:
    if name not in SECTIONS:
        raise ContractError(f"unknown generated section {name!r}")
    token = _WITHOUT_ENVIRONMENT.set(True)
    try:
        lines = SECTIONS[name](tables)
    finally:
        _WITHOUT_ENVIRONMENT.reset(token)
    return "\n".join([GENERATED_NOTE, ""] + lines).rstrip() + "\n"


def inject_sections(text: str, tables: Tables) -> str:
    """Replace the body of every named marker block. Idempotent by construction.

    A missing marker is an error rather than an append: where a generated table
    belongs inside the document is a human decision, and silently appending six
    tables to the end would wreck it.
    """
    for name in SECTIONS:
        begin, end = BEGIN.format(name=name), END.format(name=name)
        start = text.find(begin)
        stop = text.find(end)
        if start < 0 or stop < 0 or stop < start:
            raise ContractError(f"marker block {name!r} is missing from the document")
        # 🚩 Ревью #38: второй такой же блок с противоположным выводом дописывался
        # в документ, а генератор смотрел только на первое вхождение.
        if text.count(begin) > 1 or text.count(end) > 1:
            raise ContractError(
                f"раздел {name!r} встречается в документе дважды: генератор обновит "
                f"первый, читатель поверит любому")
        body = render_section(name, tables)
        text = text[:start + len(begin)] + "\n\n" + body + "\n" + text[stop:]
    return text


def render_document(path: Path, tables: Tables, write: bool = True) -> bool:
    """Regenerate the managed blocks. Returns True when the file would change."""
    path = Path(path)
    current = path.read_text(encoding="utf-8")
    updated = inject_sections(current, tables)
    if updated != current and write:
        path.write_text(updated, encoding="utf-8")
    return updated != current


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _parse_condition(raw: str):
    if "=" not in raw:
        raise ContractError(f"--condition wants key=value, got {raw!r}")
    key, _, value = raw.partition("=")
    if value == "true":
        return key, True
    if value == "false":
        return key, False
    return key, value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Roundtable tables — the executable contract")
    parser.add_argument("--tables", default=str(TABLES_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="load every table and verify the engine's invariants")
    sub.add_parser("authority", help="resolve every permission against the real world")
    sub.add_parser("isolation", help="whether the isolation proof still describes the command")
    scope = sub.add_parser("scope", help="staged files of one block against its write scope")
    scope.add_argument("block")

    render = sub.add_parser("render", help="regenerate the normative sections of the document")
    render.add_argument("--document", default=str(DOCUMENT))
    render.add_argument("--check", action="store_true",
                        help="report drift instead of writing")

    decide = sub.add_parser("decide", help="compute the single outcome of one event")
    decide.add_argument("--state", default=None)
    decide.add_argument("--event", required=True)
    decide.add_argument("--condition", action="append", default=[])

    args = parser.parse_args(argv)

    try:
        tables = load(Path(args.tables))
        if args.command == "check":
            for line in tables.check():
                print(f"✓ {line}")
            print("✓ contract valid")
            return 0
        if args.command == "authority":
            # `check` stays pure: table invariants only. Everything that has to
            # open a transcript, a plan file or git history lives here, because
            # a permission that cannot be resolved is not a permission.
            plan = tables.plan
            problems = []
            for registry in ("заключения_ревью", "разрешения_исполнения",
                             "история_разрешений"):
                for entry in plan[registry]:
                    problem = resolve_basis(entry["основание"])
                    label = f"{registry} {entry['блоки']}"
                    if problem:
                        problems.append(f"{label}: {problem}")
                    else:
                        print(f"✓ {label}")
            if plan["отпечаток_изоляции"]["подтверждение_действует"]:
                drift = tables.isolation_drift()
                if drift:
                    problems.append(f"таблица говорит «подтверждение изоляции действует», "
                                    f"а отпечаток расходится: {drift}")
            scope_problems = write_scope_receipt(tables)
            problems += [f"сверка записи: {problem}" for problem in scope_problems]
            if not scope_problems:
                print("✓ коммиты закрытых блоков не выходят за объявленное")
            # 🚩 R39-3, частично: самовыдача расширенного объёма требует НОВОГО
            # основания. Одну и ту же реплику нельзя переиспользовать под второе
            # разрешение, и дата каждого следующего обязана быть позже — иначе
            # «ОК» из прошлого месяца покрывал бы любой сегодняшний объём.
            seen, previous = {}, None
            for grant in plan["разрешения_исполнения"]:
                basis = grant["основание"]
                key = basis.get("native_uuid") or basis.get("sha256")
                if key in seen:
                    problems.append(f"разрешение {grant['блоки']}: то же основание, "
                                    f"что у {seen[key]} — одна реплика, два разрешения")
                seen[key] = grant["блоки"]
                if previous is not None and str(grant["дата"]) <= str(previous):
                    problems.append(f"разрешение {grant['блоки']}: дата не позже "
                                    f"предыдущего — порядок выдачи не восстановить")
                previous = grant["дата"]
            for problem in memory_receipt(plan):
                problems.append(f"память: {problem}")
            else:
                if not any(p.startswith("память") for p in problems):
                    print("✓ память ссылается на коммит канона")
            for problem in problems:
                print(f"✗ {problem}")
            return 1 if problems else 0

        if args.command == "scope":
            if args.block not in tables.blocks:
                raise ContractError(f"блока {args.block!r} нет")
            outside = staged_outside_scope(tables, args.block)
            for path in outside:
                print(f"✗ {args.block}: {path} вне `пишет`")
            if not outside:
                print(f"✓ {args.block}: подготовленное не выходит за `пишет`")
            return 1 if outside else 0

        if args.command == "isolation":
            # Separate command, separate exit code. Isolation being stale must
            # not block the offline blocks, and `authority` returning 0 while
            # printing ✗ let a red result through an `&&` chain.
            drift = tables.isolation_drift()
            if drift:
                print(f"✗ отпечаток изоляции расходится по {drift}: "
                      f"{tables.plan['отпечаток_изоляции']['проверяет_блок']} "
                      f"считается незакрытым, живые вызовы удержаны")
                return 1
            print("✓ отпечаток изоляции совпадает с отчётом")
            return 0

        if args.command == "render":
            changed = render_document(Path(args.document), tables, write=not args.check)
            if args.check and changed:
                print("✗ сгенерированные разделы разошлись с таблицами: "
                      "запусти `render` без --check")
                return 1
            print("✓ разделы совпадают с таблицами" if not changed else "✓ разделы обновлены")
            return 0
        conditions = dict(_parse_condition(item) for item in args.condition)
        outcome = tables.decide(args.state, args.event, conditions)
        print(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2))
        return 0
    except ContractError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
