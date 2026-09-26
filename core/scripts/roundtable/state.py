#!/usr/bin/env python3
"""Б1 — durable run state: the journal, the lock, and the repeat contract.

Three properties are load-bearing here, and each one is a defect that has
already happened somewhere:

**The journal is the truth, the snapshot is a cache.** Every change is appended
to `journal.jsonl` and fsynced before anything else; `run.json` is derived and
rewritten afterwards, and it is never read back to decide anything. A `kill -9`
between the two therefore cannot lose or corrupt a run — the worst case is a
stale cache that the next load overwrites. It also makes "history is never
rewritten" (§7.1) structural rather than a promise.

**The lock is an flock, not a lock file.** A file that merely exists survives
`kill -9` forever and would wedge the run; an flock is released by the kernel
when the process dies. Read-only operations take no lock at all, and which ones
those are is read from the table (`операции_без_бюджета`), not hardcoded.

**The rules come from the tables.** This module never decides what a transition
means: it calls `tables.decide` and applies the outcome. The one thing it owns
is *when* an operation is a repeat, a conflict or a revocation (§7.1).
"""

from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import tables as tables_module

RUNS_ROOT = Path.home() / ".stc" / "roundtable" / "runs"

JOURNAL = "journal.jsonl"
SNAPSHOT = "run.json"
LOCK = "lock"

# Operations that require a target — §7.1's key names "вид_цели / ID_цели",
# but nothing forces a caller to actually supply one. `submit-decision` and
# `submit-framing-decision` are meaningless pointed at nothing: a decision
# with no issue or framing to attach to has no addressee (Б1-5). This list is
# not read from a table: no table field for "which operations need a target"
# exists yet, and `vocabulary.yaml` is out of this block's write scope. A
# known boundary, not a fix — a block that owns the vocabulary should absorb
# this list into it.
OPERATIONS_REQUIRING_TARGET = ("submit-decision", "submit-framing-decision")


class StateError(Exception):
    """The store was asked for something the contract does not allow."""


@dataclass(frozen=True)
class Refusal(Exception):
    """An operation was refused, and the refusal has a code (§8)."""

    code: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - message plumbing
        return f"{self.code}: {self.detail}" if self.detail else self.code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_hash(body) -> str:
    """The input hash of an operation body (§7.1).

    Canonical JSON, so that a re-sent identical body hashes identically no
    matter how the caller ordered its keys — otherwise "the same input" would
    depend on dictionary order and every repeat would look like a conflict.
    """
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the lock
# --------------------------------------------------------------------------

class RunLock:
    """An exclusive, non-blocking lock on one run directory.

    Held by the kernel: if the holder is `kill -9`ed, the lock is gone with it
    and the next call succeeds. A lock file that is merely created would have
    to be cleaned up by the dead process itself.
    """

    def __init__(self, directory: Path):
        self.path = Path(directory) / LOCK
        self._handle = None
        self._held = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        try:
            fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._handle.close()
            self._handle = None
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise Refusal("ПРОГОН_ЗАНЯТ", f"прогон уже занят другим вызовом: {self.path.parent.name}")
            raise
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(f"{os.getpid()} {_now()}\n")
        self._handle.flush()
        self._held = True
        return self

    def __exit__(self, *exc_info):
        self._held = False
        if self._handle is not None:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
        return False

    def is_held(self) -> bool:
        """Whether *this* instance currently holds the lock (review #14, Б1-6).

        Asked at call time, not cached: a `RunStore` that outlived its
        `with open_run(...)` block must lose write access the moment the
        block exits, and a store that never got a lock at all (a no-budget
        operation) must never have had it in the first place. Checking where
        the store came from proved neither of those — only asking the lock
        itself, right now, does.
        """
        return self._held


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Operation:
    """One applied operation and everything the repeat contract needs (§7.1)."""

    operation_id: str
    key: tuple
    input_hash: str
    outcome: dict | None
    refusal: str | None
    at: str
    revoked: bool = False

    @property
    def moved_the_run(self) -> bool:
        return bool(self.outcome and self.outcome.get("moved"))


@dataclass(frozen=True)
class IdeaCandidate:
    """One idea card as handed into a run (§Б1-8..10).

    The record owns its own bytes — embedded, not referenced by path. A file
    that changed or vanished between the assignment and a crash-and-reload
    must not change what a resumed run holds; only what is inside the
    journal entry can be trusted to come back byte for byte.
    """

    candidate_id: str
    source: str
    canonical_bytes: bytes

    def blind(self) -> dict:
        """The anonymised projection (§Б1-10): `source` never leaves here."""
        return {"candidate_id": self.candidate_id, "canonical_bytes": self.canonical_bytes}


@dataclass(frozen=True)
class Attempt:
    """One critic call attempt, keyed as §8.1 requires."""

    key: tuple
    status: str
    at: str
    possible_duplicate: bool = False


@dataclass
class RunState:
    """The folded state of one run. Built from the journal, never from the cache."""

    run_id: str
    stage: str
    state: str | None = None
    validity: str = "актуален"
    round_number: int = 0
    flags: set = field(default_factory=set)
    operations: list = field(default_factory=list)
    attempts: dict = field(default_factory=dict)
    linked_runs: list = field(default_factory=list)
    published: bool = False
    created_at: str = ""
    idea_candidates: tuple = ()
    idea_candidates_permutation: tuple = ()

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "state": self.state,
            "действительность": self.validity,
            "round": self.round_number,
            "flags": sorted(self.flags),
            "linked_runs": list(self.linked_runs),
            "published": self.published,
            "created_at": self.created_at,
            "idea_candidates": [
                {"candidate_id": c.candidate_id, "source": c.source,
                 "canonical_bytes_b64": base64.b64encode(c.canonical_bytes).decode("ascii")}
                for c in self.idea_candidates
            ],
            "idea_candidates_permutation": list(self.idea_candidates_permutation),
            "operations": [
                {"operation_id": o.operation_id, "key": list(o.key),
                 "input_hash": o.input_hash, "outcome": o.outcome,
                 "refusal": o.refusal, "at": o.at, "revoked": o.revoked}
                for o in self.operations
            ],
            "attempts": [
                {"key": list(a.key), "status": a.status, "at": a.at,
                 "возможен_дубль": a.possible_duplicate}
                for a in self.attempts.values()
            ],
        }


# --------------------------------------------------------------------------
# the store
# --------------------------------------------------------------------------

class RunStore:
    """One run directory: append, fold, and hand back the state."""

    def __init__(self, directory: Path, tables=None, *, _lock: "RunLock | None" = None):
        self.directory = Path(directory)
        self.tables = tables or tables_module.load()
        self.journal_path = self.directory / JOURNAL
        self.snapshot_path = self.directory / SNAPSHOT
        self._lock = _lock

    def _require_live(self, what: str) -> None:
        """Refuse a mutation unless a currently held lock backs this handle (Б1-6).

        Review #14 (R26-1..3): checking *where the store came from* let three
        different holes through — a no-budget operation (`precheck` etc.)
        handed out a "live" store despite never taking a lock; a leaked
        reference kept writing after its `with open_run(...)` block had
        already exited; `create()` wrote unguarded, outside any lock at all.
        Asking the lock itself whether it is held *right now* closes all
        three: no lock at all, and a lock already released, both say no.
        """
        if self._lock is None or not self._lock.is_held():
            raise StateError(
                f"{what}: изменяющий RunStore получают только под держимой блокировкой (open_run)")

    # -- durability ---------------------------------------------------------
    def _repair_tail(self) -> None:
        """Make the journal end in a terminated line before writing onto it (§Б1-7).

        The bytes after the last `\\n` fall into exactly three shapes, told
        apart without ever decoding the whole file at once:

        * empty — the file already ends with `\\n`; untouched;
        * decode as UTF-8 and parse as one complete JSON object, just missing
          the terminator — the process died between the `write()` that
          reported success and the following `\\n` landing on disk (review
          #14 finding 2). That record already looked like success to its
          caller; dropping it as "torn" would be a silent loss, so it is kept
          and only terminated;
        * anything else — bytes that do not even decode as UTF-8 (a crash mid
          a multi-byte character, finding 1) or that are not valid JSON — is
          a genuinely unfinished write and is dropped.

        The repair itself is a temp file next to the journal, fsync'd, then
        `os.replace` over the original — the same shape `_write_snapshot`
        already uses. The previous version opened the journal in `"w"` mode,
        which truncates it to zero bytes before a single repaired byte is
        written; a second crash in that window erased every entry that was
        already durable (finding 3).
        """
        if not self.journal_path.exists():
            return
        raw = self.journal_path.read_bytes()
        if not raw or raw.endswith(b"\n"):
            return

        if b"\n" in raw:
            head, tail = raw.rsplit(b"\n", 1)
            head += b"\n"
        else:
            head, tail = b"", raw

        try:
            json.loads(tail.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            repaired = head                                   # genuinely torn — dropped
        else:
            repaired = raw + b"\n"                             # complete, just unterminated

        if repaired == raw:
            return
        fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix=".journal-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(repaired)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.journal_path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _append(self, entry: dict) -> dict:
        """Append one journal entry and get it onto the disk before returning."""
        self.directory.mkdir(parents=True, exist_ok=True)
        self._repair_tail()
        entry = {"seq": self._next_seq(), "at": _now(), **entry}
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with open(self.journal_path, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def _next_seq(self) -> int:
        return len(self._entries()) + 1

    def _entries(self) -> list:
        """Read the journal, ignoring a torn final line.

        Bytes, decoded line by line — not the whole file at once. Decoding
        the whole file in one call turned a crash mid a multi-byte character
        (e.g. a Cyrillic letter cut in half) into an uncaught
        `UnicodeDecodeError` that buried an otherwise intact run (review #14
        finding 1). Only the *last* line may be dropped this way: a broken
        line anywhere else means the file was damaged by something other
        than a crash, and quietly skipping it would silently lose a
        rule-bearing event.
        """
        if not self.journal_path.exists():
            return []
        raw = self.journal_path.read_bytes()
        if not raw:
            return []
        lines = raw.split(b"\n")
        if lines[-1] == b"":
            lines = lines[:-1]
        entries = []
        for index, raw_line in enumerate(lines):
            if not raw_line.strip():
                continue
            try:
                entries.append(json.loads(raw_line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                if index == len(lines) - 1:
                    break  # torn tail from a kill -9 — the write never completed
                raise StateError(f"{self.journal_path}: повреждена строка {index + 1}")
        return entries

    def _write_snapshot(self, state: RunState) -> None:
        """Rewrite the derived view atomically. Nothing ever reads it back."""
        payload = json.dumps(state.as_dict(), ensure_ascii=False, indent=2) + "\n"
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.directory, delete=False, prefix=".run-")
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.snapshot_path)
        directory = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    # -- folding ------------------------------------------------------------
    def load(self) -> RunState:
        entries = self._entries()
        if not entries:
            raise StateError(f"{self.directory}: прогона нет")
        head = entries[0]
        if head.get("kind") != "run_created":
            raise StateError(f"{self.directory}: журнал не начинается созданием прогона")
        state = RunState(run_id=head["run_id"], stage=head["stage"], created_at=head["at"])
        for entry in entries[1:]:
            self._fold(state, entry)
        return state

    def _fold(self, state: RunState, entry: dict) -> None:
        kind = entry.get("kind")
        if kind in ("operation", "event"):
            if kind == "operation":
                state.operations.append(Operation(
                    operation_id=entry["operation_id"], key=tuple(entry["key"]),
                    input_hash=entry["input_hash"], outcome=entry.get("outcome"),
                    refusal=entry.get("refusal"), at=entry["at"]))
            outcome = entry.get("outcome") or {}
            if outcome.get("moved"):
                state.state = outcome["to"]
                for action in outcome.get("actions", []):
                    self._apply_action(state, action, entry)
        elif kind == "revocation":
            state.operations = [
                replace(o, revoked=True) if o.operation_id == entry["operation_id"] else o
                for o in state.operations]
        elif kind == "attempt":
            key = tuple(entry["key"])
            state.attempts[key] = Attempt(
                key=key, status=entry["status"], at=entry["at"],
                possible_duplicate=entry.get("возможен_дубль", False))
        elif kind == "round_started":
            state.round_number = entry["round"]
        elif kind == "flag":
            (state.flags.add if entry["on"] else state.flags.discard)(entry["flag"])
        elif kind == "published":
            state.published = True
        elif kind == "linked_run":
            state.linked_runs.append(entry["run_id"])
        elif kind == "idea_candidates_assigned":
            state.idea_candidates = tuple(
                IdeaCandidate(candidate_id=c["candidate_id"], source=c["source"],
                              canonical_bytes=base64.b64decode(c["canonical_bytes_b64"]))
                for c in entry["candidates"])
            state.idea_candidates_permutation = tuple(entry["permutation"])
        else:
            raise StateError(f"неизвестная запись журнала: {kind!r}")

    def _apply_action(self, state: RunState, action: str, entry: dict) -> None:
        """One pure effect per action code, exactly as run.yaml names them."""
        if action == "reset_round_counter":
            state.round_number = 0          # бюджет НЕ обнуляется — это не наше поле
        elif action == "mark_run_superseded":
            state.validity = "superseded"
        elif action == "spawn_linked_run":
            state.linked_runs.append(entry.get("linked_run_id") or f"{state.run_id}-next")
        # The remaining codes (reopen_issue, recompute_verdict, kill_process_group,
        # mark_results_stale, record_extra_round, record_reason) belong to the
        # registry, the verdict and the runner — Б5, Б6, Б7. They are recorded in
        # the journal here and applied there.

    # -- the operations -----------------------------------------------------
    def create(self, run_id: str, stage: str) -> RunState:
        """Bootstrap a run's journal.

        There is no `create` entry in the operation vocabulary — the run
        does not exist yet, so `open_run` has nothing to look up a lock
        rule for. That does not make it safe unlocked: review #14 finding 6
        raced two `create()` calls and got two `run_created` entries, which
        `_fold` has no branch for — `load()` then refuses forever with
        "неизвестная запись журнала: 'run_created'". The check and the first
        append happen inside one dedicated lock instead, the same
        exclusivity every other write gets through `open_run`.
        """
        stages = set(self.tables.vocabulary["стадии"]["в_MVP"]) | set(
            self.tables.vocabulary["стадии"]["вне_MVP"])
        if stage not in stages:
            raise StateError(f"неизвестная стадия {stage!r}")
        with RunLock(self.directory):
            if self.journal_path.exists() and self._entries():
                raise StateError(f"{self.directory}: прогон уже создан")
            self._append({"kind": "run_created", "run_id": run_id, "stage": stage})
            state = self.load()
            self._write_snapshot(state)
        return state

    def submit(self, operation: str, conditions: dict | None = None,
               target_kind: str | None = None, target_id: str | None = None,
               body=None) -> Operation:
        """Apply one operation under the repeat contract of §7.1.

        Same key and same input hash → idempotent: the stored result comes
        back, no round is created and no budget is spent. Same key, different
        hash → `КОНФЛИКТ_ВХОДА`; replaying it needs an explicit
        `revoke-operation`, which stays visible in the history.

        The hash covers the operation, the conditions, the target and the
        body together (§Б1-2) — not the body alone. `conditions` drives the
        table transition and is not stored in `body`; hashing only the body
        let a second, differently-decided call under the same key through as
        a silent "repeat" of the first (R12-3).
        """
        self._require_live("submit")
        if operation not in self.tables.vocabulary["операции"]:
            raise StateError(f"неизвестная операция {operation!r}")
        if operation in OPERATIONS_REQUIRING_TARGET and (
                target_kind is None or not (target_id or "").strip()):
            # review #14 finding 7: `target_kind is None` alone let an empty
            # or whitespace-only `target_id` through as if it named a real
            # issue or framing — a decision recorded against nothing.
            raise StateError(f"{operation!r} без цели (вид_цели/ID_цели) — отказ (Б1-5)")
        state = self.load()
        key = self.operation_key(state, operation, target_kind, target_id)
        input_hash = canonical_hash({
            "operation": operation, "conditions": conditions or {},
            "target_kind": target_kind, "target_id": target_id, "body": body,
        })

        for previous in state.operations:
            if previous.key != key or previous.revoked:
                continue
            if previous.input_hash == input_hash:
                return previous                       # идемпотентный повтор
            raise Refusal("КОНФЛИКТ_ВХОДА",
                          f"тот же ключ {key} с другим телом; нужен revoke-operation")

        self._apply(state, operation, conditions or {}, extra={
            "kind": "operation",
            "operation_id": uuid.uuid4().hex[:12],
            "operation": operation,
            "key": list(key),
            "input_hash": input_hash,
        })
        return self.load().operations[-1]

    def record_event(self, event: str, conditions: dict | None = None) -> RunState:
        """Apply an engine-internal event — `пакет_собран`, `вердикт`.

        These are not operations: nobody submits them, so the repeat contract
        does not apply and they carry no key. They still move the run through
        the same table.
        """
        self._require_live("record_event")
        if event in self.tables.vocabulary["операции"]:
            raise StateError(f"{event!r} — операция, ей нужен submit с ключом повтора")
        state = self.load()
        self._apply(state, event, conditions or {}, extra={"kind": "event", "event": event})
        return self.load()

    def _apply(self, state: RunState, event: str, conditions: dict, extra: dict) -> None:
        outcome = self.tables.decide(state.state, event, conditions)
        self._append({
            **extra,
            "conditions": conditions,
            "outcome": {"to": outcome.to, "actions": list(outcome.actions),
                        "refusal": outcome.refusal,
                        # A refusal is an outcome, but it does not move the run.
                        "moved": outcome.refusal is None},
            "refusal": outcome.refusal,
        })
        self._write_snapshot(self.load())

    def operation_key(self, state: RunState, operation: str,
                      target_kind: str | None, target_id: str | None) -> tuple:
        """`прогон / стадия / круг / тип_операции / вид_цели / ID_цели` (§7.1).

        Round 9: without the last two fields two `submit-decision` calls on
        different issues of one round collided on a single key, and the second
        was refused as `КОНФЛИКТ_ВХОДА`.
        """
        if (target_kind is None) != (target_id is None):
            raise StateError("вид цели и ID цели задаются только вместе")
        if target_kind is not None and target_kind not in ("issue", "framing"):
            raise StateError(f"неизвестный вид цели {target_kind!r}")
        return (state.run_id, state.stage, state.round_number, operation,
                target_kind or "", target_id or "")

    def revoke(self, operation_id: str) -> None:
        """Revoke one operation, only while nothing depends on it (§7.1).

        Which events count as dependent is data: `run.yaml → revoke_operation`.
        Everything else is a compensating record — the history is not rewritten.
        """
        self._require_live("revoke")
        rules = self.tables.run["revoke_operation"]
        state = self.load()
        entries = self._entries()
        position = next((i for i, e in enumerate(entries)
                         if e.get("operation_id") == operation_id
                         and e.get("kind") == "operation"), None)
        if position is None:
            raise StateError(f"операции {operation_id} нет в журнале")
        if any(o.operation_id == operation_id and o.revoked for o in state.operations):
            raise StateError(f"операция {operation_id} уже отозвана")

        target = entries[position]
        dependents = []
        if (target.get("outcome") or {}).get("moved"):
            dependents.append("смена_состояния_прогона")
        for later in entries[position + 1:]:
            kind = later.get("kind")
            if kind == "operation":
                dependents.append("последующая_операция_на_ней")
            elif kind == "event" and (later.get("outcome") or {}).get("moved"):
                dependents.append("смена_состояния_прогона")
            elif kind == "linked_run":
                dependents.append("создан_дочерний_прогон")
            elif kind == "published":
                dependents.append("публикация")
        known = set(rules["зависимое_событие"])
        found = [d for d in dependents if d in known]
        if found:
            raise Refusal(rules["иначе"], f"зависимые события: {sorted(set(found))}")

        self._append({"kind": "revocation", "operation_id": operation_id})
        self._write_snapshot(self.load())

    # -- the attempt journal -------------------------------------------------
    def record_attempt(self, stage: str, round_number: int, critic: str, attempt: int,
                       status: str, possible_duplicate: bool = False) -> Attempt:
        """Move one attempt along the states declared in the vocabulary (§8.1)."""
        self._require_live("record_attempt")
        spec = self.tables.vocabulary["попытка"]
        order = spec["состояния"]
        if status not in order:
            raise StateError(f"неизвестное состояние попытки {status!r}")
        state = self.load()
        key = (state.run_id, stage, round_number, critic, attempt)
        current = state.attempts.get(key)
        if current is not None and order.index(status) <= order.index(current.status):
            raise StateError(
                f"попытка {key}: {current.status} → {status} — движение назад запрещено")
        self._append({"kind": "attempt", "key": list(key), "status": status,
                      "возможен_дубль": possible_duplicate})
        state = self.load()
        self._write_snapshot(state)
        return state.attempts[key]

    def mark_possible_duplicate(self, stage: str, round_number: int, critic: str,
                                attempt: int) -> None:
        """The window where a vendor answered and the engine died before saving.

        §8.1: "never call a critic twice" is unachievable, so the uncertainty is
        flagged and travels into the protocol rather than being papered over.
        """
        self._require_live("mark_possible_duplicate")
        spec = self.tables.vocabulary["попытка"]
        state = self.load()
        key = (state.run_id, stage, round_number, critic, attempt)
        current = state.attempts.get(key)
        if current is None:
            raise StateError(f"попытки {key} в журнале нет")
        self._append({"kind": "attempt", "key": list(key), "status": current.status,
                      "возможен_дубль": True})
        self._append({"kind": "flag", "flag": spec["флаг_неопределённого_окна"], "on": True})
        self._write_snapshot(self.load())

    def start_round(self, number: int) -> RunState:
        self._require_live("start_round")
        self._append({"kind": "round_started", "round": number})
        state = self.load()
        self._write_snapshot(state)
        return state

    def set_flag(self, flag: str, on: bool = True) -> RunState:
        self._require_live("set_flag")
        self._append({"kind": "flag", "flag": flag, "on": on})
        state = self.load()
        self._write_snapshot(state)
        return state

    # -- idea candidates ------------------------------------------------------
    def assign_idea_candidates(self, candidates: list[IdeaCandidate],
                               permutation: list[int] | None = None) -> RunState:
        """Assign the run's idea cards, once (§Б1-8, Б1-9, Б1-10).

        The journal entry embeds each card's `source`, the display
        `permutation` and its own canonical bytes — nothing is read back from
        outside the journal, so a crash-and-reload restores the same cards,
        the same IDs and the same order byte for byte. A second assignment of
        a *different* set is a conflict, the same shape `submit` uses for a
        repeated operation (§7.1); this one carries no operation key because
        nobody submits it directly — the caller already holds the lock for
        whatever operation triggered it.
        """
        self._require_live("assign_idea_candidates")
        if not candidates:
            raise StateError("набор карточек идеи не может быть пустым")
        ids = [c.candidate_id for c in candidates]
        if len(set(ids)) != len(ids):
            raise StateError(f"повторяющиеся ID карточек идеи: {ids}")
        permutation = list(permutation) if permutation is not None else list(range(len(candidates)))
        if sorted(permutation) != list(range(len(candidates))):
            raise StateError(
                f"перестановка {permutation} не соответствует набору из {len(candidates)} карточек")

        payload = [
            {"candidate_id": c.candidate_id, "source": c.source,
             "canonical_bytes_b64": base64.b64encode(c.canonical_bytes).decode("ascii")}
            for c in candidates]

        state = self.load()
        if state.idea_candidates:
            existing = [
                {"candidate_id": c.candidate_id, "source": c.source,
                 "canonical_bytes_b64": base64.b64encode(c.canonical_bytes).decode("ascii")}
                for c in state.idea_candidates]
            if existing == payload and list(state.idea_candidates_permutation) == permutation:
                return state                                  # идемпотентный повтор
            raise Refusal(
                "КОНФЛИКТ_ВХОДА",
                "карточки идеи уже назначены другим набором; повторное назначение отвергнуто (Б1-10)")

        self._append({"kind": "idea_candidates_assigned", "candidates": payload,
                      "permutation": permutation})
        state = self.load()
        self._write_snapshot(state)
        return state


# --------------------------------------------------------------------------
# the entry point every operation goes through
# --------------------------------------------------------------------------

def takes_lock(operation: str, tables=None) -> bool:
    """Whether an operation must hold the run lock.

    Driven by `операции_без_бюджета`: precheck, publish-check and status neither
    spend budget nor take the lock (§7), and that list lives in the vocabulary
    so this module cannot drift from it.
    """
    tables = tables or tables_module.load()
    if operation not in tables.vocabulary["операции"]:
        raise StateError(f"неизвестная операция {operation!r}")
    return operation not in tables.vocabulary["операции_без_бюджета"]


class open_run:
    """Open a run directory for one operation, taking the lock if it needs one.

        with open_run(directory, "submit-decision") as store:
            store.submit("submit-decision", {...})

    A parallel changing call is refused with `ПРОГОН_ЗАНЯТ` rather than made to
    wait: a queued writer would silently double an already-paid-for round.
    """

    def __init__(self, directory, operation: str, tables=None):
        self.directory = Path(directory)
        self.tables = tables or tables_module.load()
        self.operation = operation
        self._lock = RunLock(self.directory) if takes_lock(operation, self.tables) else None

    def __enter__(self) -> RunStore:
        if self._lock is not None:
            self._lock.__enter__()
        # A no-budget operation passes `_lock=None` on: the returned store is
        # then a read-only handle, never a "live" one — closing review #14
        # finding 4, where these three used to get write access for free.
        return RunStore(self.directory, self.tables, _lock=self._lock)

    def __exit__(self, *exc_info):
        if self._lock is not None:
            self._lock.__exit__(*exc_info)
        return False


def new_run_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def run_directory(run_id: str, root: Path = RUNS_ROOT) -> Path:
    return Path(root) / run_id
