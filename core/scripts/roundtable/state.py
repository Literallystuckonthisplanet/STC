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
import binascii
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
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

# БУ-13: operations whose repeat key carries the journal position. A run can be
# incomplete, continued and incomplete again inside one round; without the
# position the second `resume` would read as a repeat of the first. The position
# is the number of journal entries that are not records of these operations, so
# the same command in the same state (even after it was applied) stays one
# operation, and one after any new event is a new one. Not read from a table, the
# same known boundary as the list above.
OPERATIONS_KEYED_BY_POSITION = ("resume",)

# БУ-13: why a run closed as incomplete when it was not the budget. Recorded as data of
# the `вердикт` event; `resume` reads it back (`input_can_progress`).
CAUSE_INPUT_NOT_BUILT = "вход_не_собирается"
INCOMPLETE_CAUSES = (CAUSE_INPUT_NOT_BUILT,)


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
        self._owner_pid = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Круг 45: на месте замка заранее ставили символическую ссылку — замок
        # открывался по ней и перезаписывал чужой файл. Открываем без перехода
        # по ссылке и только обычный файл.
        try:
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StateError(f"{self.path}: замок — символическая ссылка, открывать нельзя")
            raise
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise StateError(f"{self.path}: замок — не обычный файл")
        self._handle = os.fdopen(descriptor, "a+")
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
        self._owner_pid = os.getpid()
        return self

    def __exit__(self, *exc_info):
        self._held = False
        if self._handle is not None:
            # `flock(2)`: locks obtained via `fork()`-inherited descriptors are
            # associated with the *open file description*, which parent and
            # child share — calling `LOCK_UN` from either releases it for
            # both (review #22 finding 2). Only the owning process may do
            # that; a child closes its own inherited copy of the descriptor,
            # which does not touch the lock the parent is still holding.
            if os.getpid() == self._owner_pid:
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

        Also checks the owning PID (review #22 finding 2): a `fork()`ed
        child inherits `_held=True` by copying the parent's memory, but it
        never took the lock itself — treating that inherited flag as real
        would let the child believe it may write, and would let its
        `__exit__` release a lock it never earned.
        """
        return self._held and self._owner_pid == os.getpid()

    def holds(self, directory: Path) -> bool:
        """Whether this instance holds the lock of `directory`, as it is on disk now.

        Круг 44: `is_held()` видел процесс, но не файл. Файл замка удалили
        посреди работы — второй вызов создал новый и взял его, и писали оба;
        а замок другого каталога, переданный магазину, открывал чужой прогон.
        Держим мы открытый файл, а не имя: сверяется, что под именем замка
        этого каталога лежит ровно тот файл, который заперт.
        """
        if not self.is_held() or self._handle is None:
            return False
        if Path(os.path.abspath(self.path)) != Path(os.path.abspath(Path(directory) / LOCK)):
            return False
        try:
            on_disk = os.stat(self.path)
        except FileNotFoundError:
            return False
        ours = os.fstat(self._handle.fileno())
        return (on_disk.st_dev, on_disk.st_ino) == (ours.st_dev, ours.st_ino)


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


_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Receipt:
    """БУ-11: what the journal holds about the bytes of one received answer.

    The bytes themselves live in a file named by `sha256` next to the journal; the
    attempt key (run, phase, round, critic, attempt) is the key of the entry this
    receipt sits in, `question_hash` is the hash of the question that was asked.
    """

    sha256: str
    length: int
    question_hash: str


@dataclass(frozen=True)
class Validation:
    """БУ-11: the result of checking a received answer; `reason` is clipped and empty when accepted."""

    accepted: bool
    reason: str
    question_hash: str


@dataclass(frozen=True)
class Pin:
    """БУ-12: one pinned input or package of a round (an event of the journal)."""

    event: str
    round_number: int
    revision: str
    content_hash: str
    hidden_hash: str | None
    at: str
    position: int = -1                 # its place in the journal: what came before it and after is decided by that


@dataclass(frozen=True)
class AntonOk:
    """БУ-15: one recorded OK of Anton and what it is tied to.

    `session` / `native_uuid` / `reply_at` name the reply in the transcript it came from; `run_id`,
    `stage`, `artifact`, `revision` (full hash) and `round_number` name what it was given for;
    `position` is its place in the journal (what came before it and what after is decided by that).
    """

    session: str
    native_uuid: str
    reply_at: str
    run_id: str
    stage: str
    artifact: str
    revision: str
    round_number: int
    position: int
    at: str

    def same_as(self, other: "AntonOk") -> bool:
        return all(getattr(self, n) == getattr(other, n) for n in (
            "session", "native_uuid", "reply_at", "run_id", "stage", "artifact", "revision", "round_number"))


_OK_FIELDS = ("session", "native_uuid", "reply_at", "run_id", "stage", "artifact", "revision", "round_number")


@dataclass(frozen=True)
class Attempt:
    """One critic call attempt, keyed as §8.1 requires."""

    key: tuple
    status: str
    at: str
    possible_duplicate: bool = False
    receipt: Receipt | None = None
    validation: Validation | None = None


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
    pins: list = field(default_factory=list)
    incomplete_cause: str | None = None
    entries_seen: int = 0
    last_verdict: str | None = None
    last_verdict_position: int = -1
    last_verdict_at: str = ""
    round_mark_position: int = -1
    anton_oks: list = field(default_factory=list)
    stage_exit_position: int = -1
    session: str | None = None

    @property
    def input_revision(self) -> str | None:
        """The revision the current input is pinned for: that of the latest `вход_закреплён`."""
        revisions = [p.revision for p in self.pins if p.event == "вход_закреплён"]
        return revisions[-1] if revisions else None

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
            "incomplete_cause": self.incomplete_cause,
            "anton_oks": [{**{n: getattr(o, n) for n in _OK_FIELDS}, "position": o.position, "at": o.at}
                          for o in self.anton_oks],
            "stage_exit_position": self.stage_exit_position,
            "pins": [{"event": p.event, "round": p.round_number, "revision": p.revision,
                      "content_hash": p.content_hash, "hidden_hash": p.hidden_hash, "at": p.at}
                     for p in self.pins],
            "operations": [
                {"operation_id": o.operation_id, "key": list(o.key),
                 "input_hash": o.input_hash, "outcome": o.outcome,
                 "refusal": o.refusal, "at": o.at, "revoked": o.revoked}
                for o in self.operations
            ],
            "attempts": [
                {"key": list(a.key), "status": a.status, "at": a.at,
                 "возможен_дубль": a.possible_duplicate,
                 "ответ": a.receipt and {"sha256": a.receipt.sha256, "length": a.receipt.length,
                                         "question_hash": a.receipt.question_hash},
                 "проверка": a.validation and {"accepted": a.validation.accepted,
                                               "reason": a.validation.reason}}
                for a in self.attempts.values()
            ],
        }


def ok_standing(state: RunState, spec: dict) -> tuple:
    """`(anton_ok, detail)` for the exit: is there an OK on the current revision after the current verdict.

    The OK counts when the verdict is the stage's own and of the current round, the current revision was
    pinned BEFORE it (the critics judged that very revision), and the record is newer than the verdict and
    names the current revision. Whatever else the journal holds is history that opens nothing.
    """
    fresh = state.last_verdict == spec["вердикт"] and state.last_verdict_position > state.round_mark_position
    if not fresh:
        return ("устарел" if state.anton_oks else "нет"), \
            "последний вердикт — с прошлого круга: в текущем круге вердикта ещё нет"
    if not state.anton_oks:
        return "нет", "нет записанного ОК Антона на решение"
    pins = [p for p in state.pins if p.event == "вход_закреплён"]
    judged = bool(pins) and pins[-1].position < state.last_verdict_position
    good = [o for o in state.anton_oks
            if judged and o.revision == state.input_revision and o.position > state.last_verdict_position]
    if good:
        return "есть", ""
    return "устарел", "ОК Антона дан не после последнего вердикта текущего круга или на другую редакцию"


def _card_bytes(encoded) -> bytes:
    """Байты карточки идеи из журнала — или отказ, но не пустая карточка.

    Круг 44: нестрогий `b64decode` молча выбрасывал недопустимые знаки, и
    испорченная запись читалась как пустая карточка. Годится только то, что
    строгое чтение принимает и что кодируется обратно в ту же строку.
    """
    if not isinstance(encoded, str) or not encoded:
        raise StateError(f"журнал: байты карточки идеи не записаны — {encoded!r}")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise StateError(f"журнал: байты карточки идеи повреждены — {encoded!r}") from None
    if base64.b64encode(decoded).decode("ascii") != encoded:
        raise StateError(f"журнал: байты карточки идеи записаны не канонично — {encoded!r}")
    return decoded


def _receipt(raw, where: str) -> Receipt:
    """The receipt of an answer as the journal holds it — or a refusal, never a half-read record."""
    if not isinstance(raw, dict) or set(raw) != {"sha256", "length", "question_hash"}:
        raise StateError(f"журнал: квитанция ответа {where} должна быть из sha256, length, question_hash")
    length = raw["length"]
    if (not isinstance(raw["sha256"], str) or not _HEX64.fullmatch(raw["sha256"])
            or not isinstance(raw["question_hash"], str) or not _HEX64.fullmatch(raw["question_hash"])
            or isinstance(length, bool) or not isinstance(length, int) or length < 0):
        raise StateError(f"журнал: квитанция ответа {where} повреждена")
    return Receipt(raw["sha256"], length, raw["question_hash"])


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
        if self._lock is None or not self._lock.holds(self.directory):
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

        A file that already ends with `\\n` is left untouched here even if
        its last line is corrupt (review #22 finding 1) — that is not a torn
        tail, there is nothing to repair, and there must be no path that
        quietly drops it. `_append` calls this and then `_next_seq` →
        `_entries`, which now refuses such a file outright, so a write onto
        a corrupted-but-terminated journal is refused too, not silently
        appended past.
        """
        raw = self._journal_bytes()
        if raw is None:
            return
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
        """Append one journal entry and get it onto the disk before returning.

        Право записи сверяется ещё раз прямо перед записью (круг 44): между
        проверкой в начале операции и дописыванием замок могли увести.

        Граница, а не гарантия: между последней сверкой и самой записью окно
        остаётся. Закрыть его нечем — тот, кто может удалять файлы каталога
        прогона, может и дописать журнал напрямую. Замок защищает от второго
        вызова программы, а не от владельца файлов.
        """
        self._require_live("append")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._repair_tail()
        entry = {"seq": self._next_seq(), "at": _now(), **entry}
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        self._require_live("append")
        descriptor = self._open_journal(os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return entry

    def _open_journal(self, flags: int) -> int:
        """Журнал открывается без перехода по символической ссылке (круг 45):
        иначе по ссылке читался бы чужой файл как журнал и дописывался."""
        try:
            descriptor = os.open(self.journal_path, flags | os.O_NOFOLLOW, 0o644)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise StateError(
                    f"{self.journal_path}: журнал — символическая ссылка, открывать нельзя")
            raise
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise StateError(f"{self.journal_path}: журнал — не обычный файл")
        return descriptor

    def _journal_bytes(self) -> bytes | None:
        """Весь журнал байтами, или None, если его ещё нет."""
        try:
            descriptor = self._open_journal(os.O_RDONLY)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()

    def _next_seq(self) -> int:
        return len(self._entries()) + 1

    def _entries(self) -> list:
        """Read the journal, ignoring a torn final line — but only a *torn* one.

        Bytes, decoded line by line — not the whole file at once. Decoding
        the whole file in one call turned a crash mid a multi-byte character
        (e.g. a Cyrillic letter cut in half) into an uncaught
        `UnicodeDecodeError` that buried an otherwise intact run (review #14
        finding 1).

        An unterminated tail — bytes after the last `\\n`, or the whole file
        if it has none — is what a crash mid-`write()` leaves, so it alone
        may be dropped silently. A line that already ends with `\\n` is a
        *complete* record: if it fails to parse, that is corruption, not an
        interrupted write, and review #22 finding 1 caught this module
        treating it the same as a torn tail — the last surviving line was
        dropped without a word whenever it happened to be broken, even when
        the file plainly ended in `\\n` right after it. Only the byte range
        that could not possibly have been fsynced gets the benefit of the
        doubt; anything the file itself claims is finished must actually be.
        """
        raw = self._journal_bytes()
        if raw is None:
            return []
        if not raw:
            return []
        terminated = raw.endswith(b"\n")
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
                is_last = index == len(lines) - 1
                if is_last and not terminated:
                    break  # a real torn tail from a kill -9 — the write never completed
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
        state = RunState(run_id=head["run_id"], stage=head["stage"], created_at=head["at"], entries_seen=1,
                         session=head.get("session"))
        if state.session is not None and (not isinstance(state.session, str) or not state.session.strip()):
            raise StateError("журнал: сессия прогона — непустая строка или не записана")
        for entry in entries[1:]:
            self._fold(state, entry)
        return state

    def _fold(self, state: RunState, entry: dict) -> None:
        kind = entry.get("kind")
        position = state.entries_seen
        state.entries_seen += 1
        if kind in ("operation", "event"):
            if kind == "operation":
                state.operations.append(Operation(
                    operation_id=entry["operation_id"], key=tuple(entry["key"]),
                    input_hash=entry["input_hash"], outcome=entry.get("outcome"),
                    refusal=entry.get("refusal"), at=entry["at"]))
            if entry.get("pin") is not None:
                state.pins.append(self._pin_of(entry, position))
            if entry.get("event") == "вердикт":
                cause = (entry.get("data") or {}).get("cause")
                if cause is not None and cause not in INCOMPLETE_CAUSES:
                    raise StateError(f"журнал: неизвестная причина неполного прогона {cause!r}")
                state.incomplete_cause = cause
                if (entry.get("outcome") or {}).get("moved"):
                    state.last_verdict = (entry.get("conditions") or {}).get("verdict")
                    state.last_verdict_position = position
                    state.last_verdict_at = entry["at"]
            if entry.get("ok") is not None:
                state.anton_oks.append(self._ok_of(entry, position))
            if entry.get("event") == "этап_пройден" and (entry.get("outcome") or {}).get("moved"):
                state.stage_exit_position = position
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
            previous = state.attempts.get(key)
            receipt = previous.receipt if previous else None
            if "answer" in entry:
                if entry.get("status") != "получена":
                    raise StateError(f"журнал: ответ {key} записан со статусом {entry.get('status')!r}, а не «получена»")
                if key[:1] != (state.run_id,) or (receipt is not None and receipt != _receipt(entry["answer"], key)):
                    raise StateError(f"журнал: квитанция ответа {key} чужая или записана дважды по-разному")
                receipt = _receipt(entry["answer"], key)
            state.attempts[key] = Attempt(
                key=key, status=entry["status"], at=entry["at"],
                possible_duplicate=entry.get("возможен_дубль", False),
                receipt=receipt, validation=previous.validation if previous else None)
        elif kind == "answer_checked":
            key = tuple(entry["key"])
            previous = state.attempts.get(key)
            if previous is None or previous.receipt is None:
                raise StateError(f"журнал: проверка ответа {key}, которого журнал не получал")
            if previous.validation is not None:
                raise StateError(f"журнал: проверка ответа {key} записана дважды")
            accepted, reason = entry.get("accepted"), entry.get("reason")
            if (entry.get("question_hash") != previous.receipt.question_hash or not isinstance(accepted, bool)
                    or not isinstance(reason, str) or (accepted and reason) or (not accepted and not reason.strip())):
                raise StateError(f"журнал: проверка ответа {key} не сходится с его квитанцией или повреждена")
            state.attempts[key] = replace(previous, validation=Validation(accepted, reason, entry["question_hash"]))
        elif kind == "round_started":
            state.round_number = entry["round"]
            state.round_mark_position = position
        elif kind == "flag":
            (state.flags.add if entry["on"] else state.flags.discard)(entry["flag"])
        elif kind == "published":
            state.published = True
        elif kind == "linked_run":
            state.linked_runs.append(entry["run_id"])
        elif kind == "idea_candidates_assigned":
            state.idea_candidates = tuple(
                IdeaCandidate(candidate_id=c["candidate_id"], source=c["source"],
                              canonical_bytes=_card_bytes(c.get("canonical_bytes_b64")))
                for c in entry["candidates"])
            state.idea_candidates_permutation = tuple(entry["permutation"])
        else:
            raise StateError(f"неизвестная запись журнала: {kind!r}")

    @staticmethod
    def _ok_of(entry: dict, position: int) -> AntonOk:
        """An OK as the journal holds it -- or `StateError`, never a bare `KeyError`."""
        raw = entry["ok"]
        if not isinstance(raw, dict) or set(raw) != set(_OK_FIELDS) or entry.get("event") != "ок_антона":
            raise StateError(f"журнал: запись ОК должна быть из {list(_OK_FIELDS)}")
        for name in _OK_FIELDS:
            value = raw[name]
            if name == "round_number":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise StateError(f"журнал: круг записи ОК {value!r}")
            elif not isinstance(value, str) or not value.strip():
                raise StateError(f"журнал: в записи ОК пусто поле {name}")
        return AntonOk(**raw, position=position, at=entry["at"])

    @staticmethod
    def _pin_of(entry: dict, position: int = -1) -> Pin:
        """A pin as the journal holds it -- or `StateError`, never a bare `KeyError`."""
        pin = entry["pin"]
        names = ("round", "revision", "content_hash", "hidden_hash")
        if not isinstance(pin, dict) or set(pin) != set(names):
            raise StateError("журнал: закрепление должно быть из round, revision, content_hash, hidden_hash")
        number = pin["round"]
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise StateError(f"журнал: круг закрепления {number!r}")
        for name in ("revision", "content_hash"):
            if not isinstance(pin[name], str) or not pin[name].strip():
                raise StateError(f"журнал: закрепление без {name}")
        if pin["hidden_hash"] is not None and not isinstance(pin["hidden_hash"], str):
            raise StateError("журнал: hidden_hash закрепления — строка или None")
        return Pin(entry["event"], number, pin["revision"], pin["content_hash"], pin["hidden_hash"], entry["at"],
                   position)

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
    def create(self, run_id: str, stage: str, session: str | None = None) -> RunState:
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
        if session is not None and (not isinstance(session, str) or not session.strip()):
            raise StateError("сессия прогона — непустая строка или не задана")
        with RunLock(self.directory) as lock:
            if self._entries():
                raise StateError(f"{self.directory}: прогон уже создан")
            previous, self._lock = self._lock, lock
            try:
                self._append({"kind": "run_created", "run_id": run_id, "stage": stage,
                              **({"session": session} if session is not None else {})})
            finally:
                self._lock = previous
            state = self.load()
            self._write_snapshot(state)
        return state

    def submit(self, operation: str, conditions: dict | None = None,
               target_kind: str | None = None, target_id: str | None = None,
               body=None, *, invalid_attempts=()) -> Operation:
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
        if operation in OPERATIONS_KEYED_BY_POSITION:
            # БУ-13: the conditions of a continuation are the journal's, never the caller's.
            if conditions:
                raise StateError(f"{operation!r}: условия продолжения считает журнал, переданные отвергнуты")
            conditions = self.resume_conditions(invalid_attempts)
        elif invalid_attempts:
            raise StateError(f"{operation!r}: invalid_attempts есть только у продолжения")
        state = self.load()
        key = self.operation_key(state, operation, target_kind, target_id)
        if operation in OPERATIONS_KEYED_BY_POSITION:
            key += (len([e for e in self._entries()
                         if not (e.get("kind") == "operation"
                                 and e.get("operation") in OPERATIONS_KEYED_BY_POSITION)]),)
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

    def record_event(self, event: str, conditions: dict | None = None, data: dict | None = None) -> RunState:
        """Apply an engine-internal event — `пакет_собран`, `вердикт`.

        These are not operations: nobody submits them, so the repeat contract
        does not apply and they carry no key. They still move the run through
        the same table.
        """
        self._require_live("record_event")
        if event in self.tables.vocabulary["операции"]:
            raise StateError(f"{event!r} — операция, ей нужен submit с ключом повтора")
        spec = self.tables.vocabulary["ок_антона"]
        if event in (spec["событие"], spec["переход"]):
            raise StateError(f"{event!r} пишется только своим методом хранилища "
                             "(record_stage_exit; запись ОК закрыта): условия считает журнал")
        state = self.load()
        extra = {"kind": "event", "event": event}
        if data:
            if set(data) != {"cause"} or data["cause"] not in INCOMPLETE_CAUSES or event != "вердикт":
                raise StateError(f"record_event: данные {sorted(data)} не из {INCOMPLETE_CAUSES} у «вердикт»")
            extra["data"] = dict(data)
        self._apply(state, event, conditions or {}, extra=extra)
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
        if order.index(status) >= order.index("получена") and (current is None or current.receipt is None):
            # БУ-11: the order is bytes, then the entry -- an answer is counted only through `record_received`
            raise StateError(f"попытка {key}: состояние {status} без квитанции ответа (record_received)")
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

    # -- the bytes of the answers (БУ-11) ------------------------------------
    def _answer_limit(self) -> int:
        return self.tables.vocabulary["ответ_критика"]["предел_байтов"]

    def _answers_fd(self, create: bool) -> int | None:
        """The answers directory as a descriptor, opened relative to the run directory without following links.

        Owner-only (0700) and ours: a directory that is a link, not a directory, or another user's is
        refused with a named reason (never the full path); a looser mode is tightened. None if it
        does not exist and `create` is off.
        """
        name = self.tables.vocabulary["ответ_критика"]["каталог"]
        try:
            run_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            raise StateError("каталог прогона недоступен") from None
        try:
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=run_fd)
                    os.fsync(run_fd)
                except FileExistsError:
                    pass
            try:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=run_fd)
            except FileNotFoundError:
                return None
            except OSError:
                raise StateError(f"каталог {name}: ссылка или не каталог, открывать нельзя") from None
        finally:
            os.close(run_fd)
        info = os.fstat(fd)
        if info.st_uid != os.getuid():
            os.close(fd)
            raise StateError(f"каталог {name}: принадлежит другому пользователю")
        if info.st_mode & 0o077:
            os.fchmod(fd, 0o700)
        return fd

    def _read_blob_in(self, dfd: int, digest: str, limit: int) -> bytes | None:
        """One answer file by name inside the opened directory; at most `limit + 1` bytes are read.

        Nothing but a regular file of ours is read: a link, a directory, a pipe or another user's
        file in its place is a named refusal (`StateError`).
        """
        try:
            descriptor = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        except FileNotFoundError:
            return None
        except OSError:
            raise StateError(f"файл ответа {digest[:12]}: на его месте ссылка или недоступный объект") from None
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            os.close(descriptor)
            raise StateError(f"файл ответа {digest[:12]}: не обычный файл или чужой")
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read(limit + 1)

    def _store_blob(self, raw: bytes) -> str:
        """Put the bytes of an answer on the disk under their sha256 and return it (БУ-11, step one).

        Written inside the owner-only answers directory by a temp name, fsync'd, renamed within the
        directory descriptor, and both directories fsync'd -- only then may the journal say the answer
        was received. Leftovers of an earlier failed write are removed first (we hold the lock). A file
        already there with the right content is kept; a damaged regular one is replaced; a link or a
        directory in its place is a named refusal.
        """
        if len(raw) > self._answer_limit() + 1:
            raise StateError("ответ длиннее предела хранения (предел + 1)")
        digest = hashlib.sha256(raw).hexdigest()
        dfd = self._answers_fd(create=True)
        try:
            for leftover in os.listdir(dfd):
                if leftover.startswith(".answer-"):
                    try:
                        os.unlink(leftover, dir_fd=dfd)
                    except OSError:
                        pass
            if self._read_blob_in(dfd, digest, len(raw)) != raw:
                temp = ".answer-" + uuid.uuid4().hex
                descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.replace(temp, digest, src_dir_fd=dfd, dst_dir_fd=dfd)
                    except (IsADirectoryError, NotADirectoryError):
                        raise StateError(f"файл ответа {digest[:12]}: на его месте каталог") from None
                except BaseException:
                    try:
                        os.unlink(temp, dir_fd=dfd)
                    except OSError:
                        pass
                    raise
            os.fsync(dfd)
            self._fsync_directory(self.directory)
        finally:
            os.close(dfd)
        return digest

    def _fsync_directory(self, path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def record_received(self, stage: str, round_number: int, critic: str, attempt: int,
                        raw: bytes, question_hash: str) -> Attempt:
        """The answer arrived: keep its exact bytes, then — and only then — count it (БУ-11).

        Order is the contract (`vocabulary.ответ_критика.порядок_записи`): the file is on the
        disk before the journal learns the hash. A failure between the two leaves the attempt
        where it was (not received, budget not spent) and an unreferenced file behind.
        Repeating the same answer for the same attempt changes nothing; another one is refused.
        """
        self._require_live("record_received")
        if not isinstance(raw, (bytes, bytearray)):
            raise StateError("record_received: ответ — байты")
        if not isinstance(question_hash, str) or not _HEX64.fullmatch(question_hash):
            raise StateError("record_received: хеш вопроса — sha256 в шестнадцатеричном виде")
        order = self.tables.vocabulary["попытка"]["состояния"]
        state = self.load()
        key = (state.run_id, stage, round_number, critic, attempt)
        current = state.attempts.get(key)
        if current is None:
            raise StateError(f"попытки {key} в журнале нет")
        raw = bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if current.receipt is not None:
            if (current.receipt.sha256, current.receipt.length, current.receipt.question_hash) == (
                    digest, len(raw), question_hash):
                return current                                        # идемпотентный повтор
            raise StateError(f"попытка {key}: ответ уже записан, другой не принимается")
        if order.index(current.status) >= order.index("получена"):
            raise StateError(f"попытка {key}: состояние {current.status} без квитанции ответа")
        self._store_blob(raw)                                         # step one: the bytes
        self._append({"kind": "attempt", "key": list(key), "status": "получена",
                      "возможен_дубль": current.possible_duplicate,
                      "answer": {"sha256": digest, "length": len(raw), "question_hash": question_hash}})
        state = self.load()
        self._write_snapshot(state)                                   # step two is the entry above
        return state.attempts[key]

    def record_validation(self, stage: str, round_number: int, critic: str, attempt: int,
                          accepted: bool, reason: str = "") -> Validation:
        """The result of checking a received answer, with the (clipped) reason of a refusal (БУ-11).

        Kept with the receipt's question hash. Written once: the same result again changes
        nothing, a different one is refused.
        """
        self._require_live("record_validation")
        if not isinstance(accepted, bool) or not isinstance(reason, str):
            raise StateError("record_validation: accepted — bool, reason — строка")
        if accepted and reason:
            raise StateError("record_validation: у принятого ответа причины отказа нет")
        if not accepted and not reason.strip():
            raise StateError("record_validation: отказ без причины")
        limit = self.tables.vocabulary["ответ_критика"]["предел_причины"]
        reason = reason if len(reason) <= limit else reason[:limit] + "…"
        state = self.load()
        key = (state.run_id, stage, round_number, critic, attempt)
        current = state.attempts.get(key)
        if current is None or current.receipt is None:
            raise StateError(f"попытка {key}: ответа в журнале нет, проверять нечего")
        result = Validation(accepted, reason, current.receipt.question_hash)
        if current.validation is not None:
            if current.validation == result:
                return current.validation
            raise StateError(f"попытка {key}: результат проверки уже записан, другой не принимается")
        self._append({"kind": "answer_checked", "key": list(key), "accepted": accepted,
                      "reason": reason, "question_hash": result.question_hash})
        self._write_snapshot(self.load())
        return result

    def read_answer(self, stage: str, round_number: int, critic: str, attempt: int) -> bytes:
        """The exact bytes of a received answer, checked against the journal's hash and length (БУ-11).

        A missing, altered, linked or foreign file is `ContractError`: the journal says one thing, the
        disk another. At most `length + 1` bytes are read.
        """
        state = self.load()
        key = (state.run_id, stage, round_number, critic, attempt)
        current = state.attempts.get(key)
        if current is None or current.receipt is None:
            raise tables_module.ContractError(f"попытка {key}: квитанции ответа в журнале нет")
        receipt = current.receipt
        try:
            dfd = self._answers_fd(create=False)
            if dfd is None:
                data = None
            else:
                try:
                    data = self._read_blob_in(dfd, receipt.sha256, receipt.length)
                finally:
                    os.close(dfd)
        except StateError as error:
            raise tables_module.ContractError(f"попытка {key}: {error}") from None
        if data is None:
            raise tables_module.ContractError(f"попытка {key}: файла ответа {receipt.sha256[:12]} нет")
        if hashlib.sha256(data).hexdigest() != receipt.sha256 or len(data) != receipt.length:
            raise tables_module.ContractError(f"попытка {key}: файл ответа не совпал с хешем и длиной из журнала")
        return data

    # -- the continuation of an incomplete run (БУ-13) -----------------------
    def resume_conditions(self, invalid_attempts=()) -> dict:
        """The two conditions of `resume`, counted from the journal -- the only source of them.

        `invalid_attempts`: keys of received answers that no one has judged yet and that the caller's
        single reading of the journal found invalid. A forged list can only take budget away, never add.
        """
        state = self.load()
        return {"budget_remains": self._budget_remains(state, frozenset(map(tuple, invalid_attempts))),
                "input_can_progress": self._input_can_progress(state)}

    def _input_can_progress(self, state: RunState) -> bool:
        """False when resuming cannot change anything: the input did not build, or a new round has no pinned input."""
        if state.incomplete_cause is not None:
            return False
        number = state.round_number
        return number <= 1 or any(p.event == "вход_закреплён" and p.round_number == number for p in state.pins)

    def _budget_remains(self, state: RunState, invalid: frozenset) -> bool:
        """Whether every critic of the open phase without a valid answer can still be asked.

        The open phase is the stage and round of the latest attempt. A critic is out of budget when the
        answers received without a valid one reached the retry limit or the calls cut off before an answer
        reached the abort limit. A received answer nobody has judged yet keeps the critic in, unless the
        caller's reading found it invalid. The limits come from the tables through the stage's own readers.
        """
        from . import contracts            # imported late: contracts imports this module

        if not state.attempts:
            return True
        _, stage, round_number, _, _ = next(reversed(state.attempts))
        tables = self.tables
        order = contracts._attempt_states(tables)
        settled = order.index("провалидирована")
        limit = 1 + contracts.retry_budget(tables)
        cutoff = contracts.abort_limit(tables)
        for critic in sorted({k[3] for k in state.attempts if k[1] == stage and k[2] == round_number}):
            mine = [a for k, a in state.attempts.items() if k[1:4] == (stage, round_number, critic)]
            if any((a.validation is not None and a.validation.accepted) or contracts._rank(order, a) >= settled
                   for a in mine):
                continue
            answered, aborted = contracts._split_attempts(state, tables, stage, round_number, critic)
            if any(a.validation is None and a.key not in invalid for a in answered):
                continue
            if len(answered) >= limit or len(aborted) >= cutoff:
                return False
        return True

    # -- the OK of Anton (БУ-15) ----------------------------------------------
    def ok_journal_problem(self, state: RunState, session: str | None = None) -> str | None:
        """Why an OK cannot be given on this run now, judged by the journal alone -- or None.

        There is a revision pinned, the critics judged THAT revision (its pin stands before the last verdict),
        the verdict belongs to the current round, and the OK comes from the run's own session if one was recorded.
        """
        spec = self.tables.vocabulary["ок_антона"]
        revision = state.input_revision
        if revision is None:
            return "нет закреплённого входа: редакции, на которую давать ОК, нет"
        if state.last_verdict != spec["вердикт"] or state.last_verdict_position < state.round_mark_position:
            return "в текущем круге вердикта для Антона ещё нет: ОК давать не на что"
        last_pin = [p for p in state.pins if p.event == "вход_закреплён"][-1]
        if last_pin.position > state.last_verdict_position:
            return "текущую редакцию критики не судили: закрепление новее последнего вердикта"
        if session is not None and state.session is not None and session != state.session:
            return "реплика из другой сессии, чем та, в которой начат прогон"
        return None

    def _record_anton_ok(self, **fields) -> AntonOk:
        """Write one OK of Anton with what it is tied to, as the journal event `ок_антона`. CLOSED: the caller
        of the stage (`contracts.record_anton_ok`) makes the proof from the transcript before this.

        Here the journal's own checks are made again, so that the door cannot be used on its own: the
        state is `ждёт_Антона`, the revision is the current one and was judged, the verdict is of the current
        round. The same reply again comes back as the same record (no second one), the same reply with other
        content is a conflict, another reply makes a new record.
        """
        self._require_live("_record_anton_ok")
        if set(fields) != set(_OK_FIELDS):
            raise StateError(f"_record_anton_ok: нужны ровно поля {list(_OK_FIELDS)}")
        state = self.load()
        candidate = AntonOk(**fields, position=-1, at="")
        for name in _OK_FIELDS:
            value = fields[name]
            if name == "round_number":
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise StateError(f"_record_anton_ok: круг {value!r}")
            elif not isinstance(value, str) or not value.strip():
                raise StateError(f"_record_anton_ok: пусто поле {name}")
        if fields["run_id"] != state.run_id or fields["stage"] != state.stage:
            raise StateError("_record_anton_ok: ОК другого прогона или другой стадии")
        for old in state.anton_oks:
            if (old.session, old.native_uuid) == (candidate.session, candidate.native_uuid):
                if old.same_as(candidate):
                    return old                                         # идемпотентный повтор той же реплики
                raise Refusal("КОНФЛИКТ_ВХОДА", "та же реплика уже записана как ОК на другое")
        problem = self.ok_journal_problem(state, fields["session"])
        if problem is None and fields["revision"] != state.input_revision:
            problem = "ОК на другую редакцию, чем текущая"
        if problem is not None:
            raise Refusal("ОК_НЕ_ЗАСЧИТАН", problem)
        self._apply(state, "ок_антона", {"ok_binding": True}, extra={
            "kind": "event", "event": "ок_антона", "ok": dict(fields)})
        return self.load().anton_oks[-1]

    def record_stage_exit(self) -> RunState:
        """БУ-5, БУ-10: the exit from the stage -- the event `этап_пройден` of `run.yaml`, its conditions counted HERE.

        `anton_ok` and `framing_objection` come from the journal (`ok_standing`), never from the caller; there is
        no other door (`record_event` refuses this event). A refusal is the table's code (`Refusal`), nothing is
        written. Already left -- the same state, no second transition.
        """
        self._require_live("record_stage_exit")
        spec = self.tables.vocabulary["ок_антона"]
        state = self.load()
        if state.stage != spec["этап"]:
            raise StateError(f"выход со стадии {spec['этап']!r}, а прогон стадии {state.stage!r}")
        if state.stage_exit_position >= 0:
            return state
        standing, detail = ok_standing(state, spec)
        conditions = {"anton_ok": standing,
                      "framing_objection": self.tables.framing["флаг_прогона"] in state.flags}
        outcome = self.tables.decide(state.state, spec["переход"], conditions)
        if outcome.refusal is not None:
            raise Refusal(outcome.refusal, detail or "открыто возражение к постановке — оно держит стадию")
        self._apply(state, spec["переход"], conditions, extra={"kind": "event", "event": spec["переход"]})
        return self.load()

    # -- pins (БУ-12) --------------------------------------------------------
    @staticmethod
    def pin_status(state: RunState, event: str, *, round_number: int, revision: str,
                   content_hash: str, hidden_hash: str | None = None):
        """What `pin` would do, without writing: the same `Pin` (a repeat), None (a new event) or a refusal text."""
        for old in (p for p in state.pins if p.event == event):
            same = (old.revision, old.content_hash, old.hidden_hash) == (revision, content_hash, hidden_hash)
            if old.round_number == round_number:
                if same:
                    return old
                return f"{event}: в круге {round_number} уже закреплено другое содержимое"
            if old.revision == revision and not same:
                return f"{event}: редакция та же, содержимое другое (круг {old.round_number})"
        return None

    def pin(self, event: str, *, round_number: int, revision: str, content_hash: str,
            hidden_hash: str | None = None) -> Pin:
        """Pin the input of the stage or its second package for one round as a journal event.

        The same pin again — no duplicate, the old event comes back. Other content in the same
        round, or other content under the same revision in another round, is refused with the
        table's code. A new revision in a new round gets a new event; the old one stays.
        """
        self._require_live("pin")
        spec = self.tables.vocabulary["закрепление"]
        if event not in spec["события"]:
            raise StateError(f"закрепление: {event!r} не из vocabulary.закрепление.события")
        if isinstance(round_number, bool) or not isinstance(round_number, int) or round_number < 1:
            raise StateError(f"закрепление: круг — целое от 1, получено {round_number!r}")
        for name, value in (("revision", revision), ("content_hash", content_hash)):
            if not isinstance(value, str) or not value.strip():
                raise StateError(f"закрепление: {name} пусто")
        if hidden_hash is not None and (not isinstance(hidden_hash, str) or not hidden_hash.strip()):
            raise StateError("закрепление: hidden_hash — строка или None")
        state = self.load()
        status = self.pin_status(state, event, round_number=round_number, revision=revision,
                                 content_hash=content_hash, hidden_hash=hidden_hash)
        if isinstance(status, Pin):
            return status                                              # безопасный повтор
        if status is not None:
            raise Refusal(spec["иное_содержимое"], status)
        self._apply(state, event, {}, extra={
            "kind": "event", "event": event,
            "pin": {"round": round_number, "revision": revision, "content_hash": content_hash,
                    "hidden_hash": hidden_hash}})
        return next(p for p in reversed(self.load().pins) if p.event == event)

    def start_round(self, number: int) -> RunState:
        self._require_live("start_round")
        self._append({"kind": "round_started", "round": number})
        state = self.load()
        self._write_snapshot(state)
        return state

    def set_flag(self, flag: str, on: bool = True) -> RunState:
        self._require_live("set_flag")
        if not on and flag == self.tables.framing["флаг_прогона"]:
            # БУ-15: the objection to the framing is closed by Anton's decision (the operations block), never by a flag call
            raise Refusal("ФЛАГ_ЗАЩИЩЁН", "возражение к постановке снимается решением Антона, а не set_flag")
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
        # Круг 45: пустая карточка записывалась, а потом сама запись не
        # читалась — прогон ломался навсегда. Проверяется ДО записи то же, что
        # потребует чтение.
        for candidate in candidates:
            if not isinstance(candidate.canonical_bytes, bytes) or not candidate.canonical_bytes:
                raise StateError(
                    f"карточка идеи {candidate.candidate_id!r}: байты пусты или не байты")
            for name in ("candidate_id", "source"):
                value = getattr(candidate, name)
                if not isinstance(value, str) or not value.strip():
                    raise StateError(f"карточка идеи: поле {name} пусто — {value!r}")
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
