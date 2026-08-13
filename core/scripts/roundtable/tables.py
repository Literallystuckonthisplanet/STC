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
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve()
TABLES_DIR = HERE.parent / "tables"
DOCUMENT = HERE.parents[3] / "docs" / "roundtable.md"

CONTRACT_VERSION = 1

TABLE_NAMES = ("vocabulary", "run", "issues", "framing", "precheck", "blocks", "stages")

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
        "порядок", "вне_порядка", "блоки", "приёмка_БТ", "списки",
        "последовательные_из_за_общих_файлов", "разрешено_ревью",
        "разрешено_Антоном", "вызовов_критиков_требуют", "заморозка_команды",
    },
    "stages": {
        "стадии", "слепой_вопрос", "сигнал_нежизнеспособности",
        "метрика_цены_понимания", "приоритет_расхода",
    },
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

    version = data.get("версия_контракта")
    if version != CONTRACT_VERSION:
        raise ContractError(
            f"{path}: contract version {version!r}, this engine speaks {CONTRACT_VERSION}")

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
class Block:
    """One block of the work plan."""

    name: str
    what: str
    depends: tuple[str, ...]
    state: str | None = None
    files: str | None = None
    acceptance: str | None = None
    blocker: str | None = None
    declared_counts: dict = field(default_factory=dict)
    outside_mvp: bool = False

    @classmethod
    def parse(cls, name: str, row: dict) -> "Block":
        _require(
            row, {"что", "зависит"},
            {"состояние", "файлы", "приёмка", "блокер", "объявленное_количество", "вне_MVP"},
            f"blocks.блоки.{name}")
        return cls(
            name=name,
            what=row["что"],
            depends=tuple(row["зависит"]),
            state=row.get("состояние"),
            files=row.get("файлы"),
            acceptance=row.get("приёмка"),
            blocker=row.get("блокер"),
            declared_counts=dict(row.get("объявленное_количество") or {}),
            outside_mvp=bool(row.get("вне_MVP", False)),
        )


class _Missing:
    def __repr__(self):  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()


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
        return checked

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


def load(directory: Path = TABLES_DIR) -> Tables:
    """Load, type and cross-check every table in `directory`."""
    raw = {name: load_table(name, directory) for name in TABLE_NAMES}
    return Tables(
        raw=raw,
        transitions=tuple(Transition.parse(row) for row in raw["run"]["переходы"]),
        issue_transitions=tuple(
            IssueTransition.parse(row) for row in raw["issues"]["переходы"]),
        verdict=tuple(VerdictRow.parse(row) for row in raw["issues"]["вердикт"]),
        precheck_codes=tuple(PrecheckCode.parse(row) for row in raw["precheck"]["коды"]),
        blocks={name: Block.parse(name, row) for name, row in raw["blocks"]["блоки"].items()},
    )


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


def _render_blocks(tables: Tables) -> list[str]:
    plan = tables.plan
    rows = []
    marks = {"сделано": " ✅", "неполный": " 🚧"}
    for position, name in enumerate(plan["порядок"], start=1):
        block = tables.blocks[name]
        rows.append([str(position), f"**{name}**{marks.get(block.state, '')}", block.what,
                     _cell(list(block.depends)), _cell(block.files),
                     _cell(block.acceptance)])
    lines = _table(["#", "Блок", "Что", "Зависит от", "Файлы (область записи)",
                    "Приёмка"], rows)
    blocked = [b for b in tables.blocks.values() if b.blocker]
    if blocked:
        lines += ["", "**Чем заблокировано:**"]
        lines += [f"- 🚧 **{b.name}** — {b.blocker}" for b in blocked]
    freeze = plan["заморозка_команды"]
    lines += ["", "**Заморозка команды критика:** "
              + ("да" if freeze["заморожена"] else f"нет — {freeze['почему']}")
              + f" (отчёт `{freeze['отчёт']}`)."]
    lines += ["", "**Вне порядка:**"]
    for name, why in plan["вне_порядка"].items():
        lines.append(f"- **{name}** — {tables.blocks[name].what} ({why})")
    lines += ["", "**Кем разрешено брать в работу.** Список ревью — факт о том, что "
              "согласовано, а не указатель на следующий шаг: он двигается только "
              "новым кругом."]
    lines += ["", f"- ревью #11, без нового круга: {_cell(plan['разрешено_ревью'])}"]
    lines += [f"- Антоном лично: {_cell(sorted(plan['разрешено_Антоном']))} — "
              + "; ".join(f"{name} ({why})"
                          for name, why in sorted(plan["разрешено_Антоном"].items()))]
    lines += [f"- никем ещё не разрешено, нужен круг или слово Антона: "
              f"{_cell(plan['вызовов_критиков_требуют'])}"]
    lines += ["", "**Делят файлы — при делегировании строго последовательно:** "
              + "; ".join(_cell(group) for group in plan["последовательные_из_за_общих_файлов"])
              + "."]
    lines += ["", "**Приёмка БТ:**"]
    lines += [f"- {item}" for item in plan["приёмка_БТ"]]
    return lines


SECTIONS = {
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
