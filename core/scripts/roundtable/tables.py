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
import functools
import hashlib
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
        "порядок_критики",
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
class IssueTransition:
    """One row of the issue transition table (issues.yaml)."""

    source: str | None
    targets: tuple[str, ...]
    who: str
    condition: str

    @classmethod
    def parse(cls, row: dict) -> "IssueTransition":
        _require(row, {"из", "в", "кто", "условие"}, set(), "issues.переходы")
        return cls(row["из"], tuple(row["в"]), row["кто"], row["условие"])


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

    @classmethod
    def parse(cls, name: str, row: dict, vocabulary: dict | None = None) -> "Block":
        _require(
            row, {"что", "зависит", "читает", "пишет", "внешние_действия", "приёмка"},
            {"состояние", "блокер", "переоткрыт_из_за", "объединён_с", "поглощает",
             "объявленное_количество", "вне_MVP"},
            f"blocks.блоки.{name}")
        where = f"blocks.блоки.{name}"
        for field_name in ("зависит", "читает", "пишет", "внешние_действия"):
            _string_list(row[field_name], f"{where}.{field_name}")
        _string_list(row.get("поглощает") or [], f"{where}.поглощает")
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
            states = (set(vocabulary["состояния_блока"]["рабочие"])
                      | set(vocabulary["состояния_блока"]["терминальные"]))
            if row.get("состояние") is not None and row["состояние"] not in states:
                raise ContractError(
                    f"{where}.состояние: {row['состояние']!r} нет в словаре")
            allowed = set(vocabulary["внешние_действия"])
            unknown = set(row["внешние_действия"]) - allowed
            if unknown:
                raise ContractError(f"{where}.внешние_действия: {sorted(unknown)} нет в словаре")
        items = []
        seen = set()
        for entry in row["приёмка"]:
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
    verdict: tuple[VerdictRow, ...]
    precheck_codes: tuple[PrecheckCode, ...]
    blocks: dict

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

    # -- validation ---------------------------------------------------------
    def _states(self) -> set:
        states = self.vocabulary["состояния_прогона"]
        return set(states["рабочие"]) | set(states["терминальные"])

    def _validate_conditions(self, conditions: dict) -> None:
        codes = self.vocabulary["коды_условий"]
        for key, value in conditions.items():
            if key not in codes:
                raise ContractError(f"unknown condition code {key!r}")
            if value not in codes[key]:
                raise ContractError(f"{key}={value!r} is not a declared value")

    def check(self) -> list[str]:
        """Every invariant the engine itself depends on. Returns what it checked."""
        checked = []
        codes = self.vocabulary["коды_условий"]
        actions = set(self.vocabulary["коды_действий"])
        refusals = set(self.vocabulary["коды_отказа"])
        states = self._states()
        working = set(self.vocabulary["состояния_прогона"]["рабочие"])

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
        for gate, spec in plan["шлюзы"].items():
            open_ones = [b for b in spec["до_закрытия"] if not self.closed(b)]
            if not open_ones:
                continue
            started = [b for b in spec["блокирует"]
                       if self.blocks[b].state in ("сделано", "неполный")]
            if started:
                raise ContractError(
                    f"шлюз {gate}: начаты {sorted(started)}, а не закрыты {sorted(open_ones)}")
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
                raise ContractError(f"{name}: закрыт, но разрешения на него нет нигде")
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

        fingerprint = plan["отпечаток_изоляции"]
        artefacts, declared = fingerprint["артефакты"], set(fingerprint["входит_в_отпечаток"])
        missing_core = set(fingerprint["требуются_всегда"]) - set(artefacts)
        if missing_core:
            raise ContractError(
                f"отпечаток изоляции: ядро {sorted(missing_core)} выброшено из артефактов")
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
        checked.append(f"отпечаток изоляции: считается {len(artefacts) + 1} полей из "
                       f"{len(declared)}; несчитаемые держат шлюз закрытым")

        self._check_absorption()
        checked.append("поглощение: формулы объединения соблюдены")

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


def observe_cli_versions(commands: dict) -> dict | None:
    """Спросить среду, какие вендоры стоят сейчас. Не ответила — не согласие."""
    observed = {}
    for vendor, command in commands.items():
        version = _cli_version(tuple(command))
        if version is None:
            return None
        observed[vendor] = version
    return observed


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
    return problems


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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != basis["sha256"]:
            return f"sha256 не совпал: {digest[:12]}… против {basis['sha256'][:12]}…"
        return None

    session = basis["сессия"]
    candidates = list(home.glob(f".claude/projects/*/{session}.jsonl"))
    if not candidates:
        return f"сессии нет: {session}"
    wanted, quote = basis["native_uuid"], basis["цитата"]
    for line in candidates[0].open(encoding="utf-8"):
        if wanted not in line:
            continue
        record = json.loads(line)
        if record.get("uuid") != wanted:
            continue
        if record.get("type") != "user":
            return f"{wanted}: не реплика пользователя"
        content = record.get("message", {}).get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return None if quote in text else f"{wanted}: цитата не найдена в реплике"
    return f"{wanted}: события нет в сессии"


def load(directory: Path = TABLES_DIR) -> Tables:
    """Load, type and cross-check every table in `directory`."""
    raw = {name: load_table(name, directory) for name in TABLE_NAMES}
    return Tables.from_raw(raw)


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
    return "\n".join([GENERATED_NOTE, ""] + SECTIONS[name](tables)).rstrip() + "\n"


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
            for problem in memory_receipt(plan):
                problems.append(f"память: {problem}")
            else:
                if not any(p.startswith("память") for p in problems):
                    print("✓ память ссылается на коммит канона")
            for problem in problems:
                print(f"✗ {problem}")
            return 1 if problems else 0

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
