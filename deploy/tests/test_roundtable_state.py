"""Б1 — durable state: the journal survives, the lock refuses, repeats are free.

The two acceptance criteria are `resume` surviving a `kill -9` and a reboot, and
a parallel call being refused. Both are tested the only way they mean anything:
by actually killing a process with SIGKILL and by actually holding the lock from
a second process. A mocked crash proves the mock.
"""

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "core" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from roundtable import state as S  # noqa: E402
from roundtable import tables as T  # noqa: E402

TABLES = T.load()


class _TestRun:
    """Test-only harness: each mutating call takes and releases a *real*
    `RunLock` around itself — exactly one `open_run` cycle — so every
    existing single-call test body exercises the held-lock mechanism (Б1-6)
    rather than a bypass token, and a child process spawned *between* two
    calls never contends with anything the fixture itself is holding (review
    #14 found the previous `_token=S._LIVE` fixture design could not spawn a
    competing process without first tearing itself down).
    """

    _MUTATING = {
        "submit", "record_event", "revoke", "start_round", "set_flag",
        "record_attempt", "mark_possible_duplicate", "assign_idea_candidates",
    }

    def __init__(self, directory, tables):
        self.directory = Path(directory)
        self.tables = tables

    def _bare(self) -> S.RunStore:
        return S.RunStore(self.directory, self.tables)

    def __getattr__(self, name):
        if name in self._MUTATING:
            def call(*args, **kwargs):
                with S.RunLock(self.directory) as lock:
                    store = S.RunStore(self.directory, self.tables, _lock=lock)
                    return getattr(store, name)(*args, **kwargs)
            return call
        return getattr(self._bare(), name)

    @property
    def journal_path(self):
        return self.directory / S.JOURNAL

    @property
    def snapshot_path(self):
        return self.directory / S.SNAPSHOT


@pytest.fixture
def run(tmp_path):
    directory = tmp_path / "run"
    S.RunStore(directory, TABLES).create("run-1", "план")   # self-locked bootstrap
    return _TestRun(directory, TABLES)


def _child(code: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code), *map(str, args)],
        capture_output=True, text=True, timeout=120)


# --------------------------------------------------------------------------
# the journal is the truth, the snapshot is a cache
# --------------------------------------------------------------------------

def test_the_state_survives_losing_the_snapshot_entirely(run):
    run.submit("start")
    before = run.load()
    run.snapshot_path.unlink()
    after = run.load()
    assert (after.state, after.stage) == (before.state, before.stage) == ("создан", "план")


def test_a_corrupted_snapshot_changes_nothing(run):
    run.submit("start")
    run.snapshot_path.write_text('{"state": "завершён", "run_id": "чужой"}', encoding="utf-8")
    assert run.load().state == "создан", "the cache must never decide anything"


def test_a_torn_last_line_is_dropped_but_a_broken_middle_is_an_error(run):
    run.submit("start")
    with open(run.journal_path, "a", encoding="utf-8") as handle:
        handle.write('{"kind": "operation", "partia')      # kill -9 mid-write
    assert run.load().state == "создан"

    lines = run.journal_path.read_text(encoding="utf-8").splitlines()
    lines[1] = "{ not json"
    run.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(S.StateError):
        run.load()


# --------------------------------------------------------------------------
# kill -9 and a cold start
# --------------------------------------------------------------------------

def test_an_event_written_before_a_sigkill_is_still_there_afterwards(run):
    # The child dies between the journal append and the snapshot rewrite — the
    # exact window that would lose a run if the snapshot were the source.
    result = _child("""
        import os, sys
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunStore, RunLock
        lock = RunLock(sys.argv[2])
        lock.__enter__()
        store = RunStore(sys.argv[2], _lock=lock)
        store._write_snapshot = lambda state: os.kill(os.getpid(), 9)
        store.submit("start")
        """, SCRIPTS, run.directory)
    assert result.returncode == -signal.SIGKILL, "the child must really be killed"

    reopened = S.RunStore(run.directory, TABLES).load()
    assert reopened.state == "создан", "the applied event did not survive"
    assert json.loads(run.snapshot_path.read_text(encoding="utf-8"))["state"] is None, (
        "the stale cache is expected — and it is why nothing reads it back")


def test_resume_works_from_a_cold_interpreter_after_the_kill(run):
    run.submit("start")
    run.record_event("пакет_собран")
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"})
    assert run.load().state == "неполный"

    # `resume` is an operation, so it goes through the repeat contract.
    killed = _child("""
        import os, sys
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunStore, RunLock
        lock = RunLock(sys.argv[2])
        lock.__enter__()
        store = RunStore(sys.argv[2], _lock=lock)
        store._write_snapshot = lambda state: os.kill(os.getpid(), 9)
        store.submit("resume", body={"reason": "после падения"})
        """, SCRIPTS, run.directory)
    assert killed.returncode == -signal.SIGKILL, killed.stderr

    # A reboot is a cold process with nothing cached: read it back in a fresh
    # interpreter rather than from this one's memory.
    result = _child("""
        import sys
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunStore
        print(RunStore(sys.argv[2]).load().state)
        """, SCRIPTS, run.directory)
    assert result.stdout.strip() == "идёт_круг", result.stderr


def test_a_killed_holder_leaves_no_lock_behind(run):
    result = _child("""
        import os, sys, time
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunLock
        lock = RunLock(sys.argv[2])
        lock.__enter__()
        print("held", flush=True)
        os.kill(os.getpid(), 9)
        """, SCRIPTS, run.directory)
    assert result.returncode == -signal.SIGKILL

    with S.RunLock(run.directory):        # the kernel released it with the process
        pass


# --------------------------------------------------------------------------
# the lock
# --------------------------------------------------------------------------

def test_a_parallel_changing_call_is_refused_with_a_code(run):
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent("""
            import sys, time
            sys.path.insert(0, sys.argv[1])
            from roundtable.state import RunLock
            with RunLock(sys.argv[2]):
                print("held", flush=True)
                time.sleep(30)
            """), str(SCRIPTS), str(run.directory)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(S.Refusal) as refused:
            with S.open_run(run.directory, "submit-decision"):
                pass
        assert refused.value.code == "ПРОГОН_ЗАНЯТ"
        assert refused.value.code in TABLES.vocabulary["коды_отказа"]
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_the_read_only_operations_take_no_lock_at_all(run):
    # §7: precheck, publish-check and status neither spend budget nor take the
    # lock — and which ones those are comes from the table, not from here.
    free = TABLES.vocabulary["операции_без_бюджета"]
    assert set(free) == {"precheck", "publish-check", "status"}
    with S.RunLock(run.directory):
        for operation in free:
            assert S.takes_lock(operation, TABLES) is False
            with S.open_run(run.directory, operation) as store:
                assert store.load().run_id == "run-1"
    for operation in ("start", "submit-revision", "submit-decision", "cancel-run"):
        assert S.takes_lock(operation, TABLES) is True


# --------------------------------------------------------------------------
# the repeat contract (§7.1)
# --------------------------------------------------------------------------

def _to_anton(run):
    run.submit("start")
    run.record_event("пакет_собран")
    run.record_event("вердикт", {"verdict": "РЕШЕНИЕ_АНТОНА"})
    return run


def test_the_same_key_and_the_same_body_is_idempotent(run):
    _to_anton(run)
    body = {"decision": "принять_риск", "issue": "I-1"}
    first = run.submit("submit-decision",
                       {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                       target_kind="issue", target_id="I-1", body=body)
    entries_after_first = len(run._entries())
    second = run.submit("submit-decision",
                        {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                        target_kind="issue", target_id="I-1", body=body)
    assert second.operation_id == first.operation_id
    assert len(run._entries()) == entries_after_first, "a repeat must not write a round"


def test_the_same_key_with_a_different_body_is_refused(run):
    _to_anton(run)
    conditions = {"decision": "принять_риск", "all_verdict_blocking_resolved": True}
    run.submit("submit-decision", conditions, "issue", "I-1", {"note": "первое"})
    with pytest.raises(S.Refusal) as refused:
        run.submit("submit-decision", conditions, "issue", "I-1", {"note": "другое"})
    assert refused.value.code == "КОНФЛИКТ_ВХОДА"


def test_two_decisions_on_different_issues_in_one_round_do_not_collide(run):
    # Round 9: without вид_цели/ID_цели in the key both got the same key and the
    # second was refused as КОНФЛИКТ_ВХОДА.
    _to_anton(run)
    conditions = {"decision": "принять_риск", "all_verdict_blocking_resolved": False}
    first = run.submit("submit-decision", conditions, "issue", "I-1", {"n": 1})
    second = run.submit("submit-decision", conditions, "issue", "I-2", {"n": 2})
    third = run.submit("submit-framing-decision",
                       {"framing_decision": "подтвердить_постановку"},
                       "framing", "F-1", {"n": 3})
    assert len({first.operation_id, second.operation_id, third.operation_id}) == 3


def test_the_key_carries_every_field_the_contract_names(run):
    state = run.load()
    key = run.operation_key(state, "submit-decision", "issue", "I-7")
    assert key == ("run-1", "план", 0, "submit-decision", "issue", "I-7")
    with pytest.raises(S.StateError):
        run.operation_key(state, "submit-decision", "issue", None)
    with pytest.raises(S.StateError):
        run.operation_key(state, "submit-decision", "предмет", "I-7")


def test_a_refusal_is_recorded_as_an_outcome_and_does_not_move_the_run(run):
    _to_anton(run)
    operation = run.submit("submit-decision",
                           {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
                           "issue", "I-1", {"n": 1})
    assert operation.refusal == "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ"
    assert operation.moved_the_run is False
    assert run.load().state == "ждёт_Антона"


# --------------------------------------------------------------------------
# revoke-operation (§7.1)
# --------------------------------------------------------------------------

def test_an_operation_with_nothing_depending_on_it_can_be_revoked(run):
    _to_anton(run)
    operation = run.submit("submit-decision",
                           {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
                           "issue", "I-1", {"n": 1})
    run.revoke(operation.operation_id)
    assert run.load().operations[-1].revoked is True
    # Revoking frees the key: the same key with a new body is now allowed.
    run.submit("submit-decision",
               {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
               "issue", "I-1", {"n": 2})


def test_an_operation_that_moved_the_run_cannot_be_revoked(run):
    _to_anton(run)
    operation = run.submit("submit-decision",
                           {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                           "issue", "I-1", {"n": 1})
    with pytest.raises(S.Refusal) as refused:
        run.revoke(operation.operation_id)
    assert refused.value.code == "ЕСТЬ_ЗАВИСИМЫЕ_СОБЫТИЯ"
    assert refused.value.code == TABLES.run["revoke_operation"]["иначе"]


def test_a_later_operation_blocks_the_revocation_of_an_earlier_one(run):
    _to_anton(run)
    first = run.submit("submit-decision",
                       {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
                       "issue", "I-1", {"n": 1})
    run.submit("submit-decision",
               {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
               "issue", "I-2", {"n": 2})
    with pytest.raises(S.Refusal):
        run.revoke(first.operation_id)


def test_the_history_is_never_rewritten(run):
    _to_anton(run)
    operation = run.submit("submit-decision",
                           {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
                           "issue", "I-1", {"n": 1})
    before = run.journal_path.read_text(encoding="utf-8")
    run.revoke(operation.operation_id)
    after = run.journal_path.read_text(encoding="utf-8")
    assert after.startswith(before), "a revocation appends, it never edits"
    assert TABLES.run["revoke_operation"]["отката_истории"] is False


# --------------------------------------------------------------------------
# the attempt journal (§8.1)
# --------------------------------------------------------------------------

def test_an_attempt_walks_the_declared_states_and_never_backwards(run):
    order = TABLES.vocabulary["попытка"]["состояния"]
    for status in order:
        attempt = run.record_attempt("план", 1, "claude", 1, status)
        assert attempt.status == status
    with pytest.raises(S.StateError):
        run.record_attempt("план", 1, "claude", 1, "запущена")
    with pytest.raises(S.StateError):
        run.record_attempt("план", 1, "claude", 1, "придумана")


def test_attempts_of_different_critics_and_rounds_are_separate(run):
    run.record_attempt("план", 1, "claude", 1, "запущена")
    run.record_attempt("план", 1, "codex", 1, "подготовлена")
    run.record_attempt("план", 2, "claude", 1, "подготовлена")
    assert len(run.load().attempts) == 3


def test_the_uncertain_window_is_flagged_rather_than_papered_over(run):
    # §8.1: "never call a critic twice" is unachievable — there is a window in
    # which the vendor answered and the engine died before saving.
    run.record_attempt("план", 1, "claude", 1, "запущена")
    run.mark_possible_duplicate("план", 1, "claude", 1)
    state = run.load()
    assert state.attempts[("run-1", "план", 1, "claude", 1)].possible_duplicate is True
    assert TABLES.vocabulary["попытка"]["флаг_неопределённого_окна"] in state.flags


# --------------------------------------------------------------------------
# the rules stay in the tables
# --------------------------------------------------------------------------

def test_the_transition_comes_from_the_table_and_not_from_this_module(tmp_path):
    import shutil
    import yaml
    directory = tmp_path / "tables"
    shutil.copytree(T.TABLES_DIR, directory)
    path = directory / "run.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for row in data["переходы"]:
        if row.get("условия", {}).get("verdict") == "ОДОБРЕНО":
            row["в"] = "неполный"
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    bare = S.RunStore(tmp_path / "run", T.load(directory))
    bare.create("run-2", "план")                              # self-locked bootstrap
    with S.RunLock(tmp_path / "run") as lock:
        store = S.RunStore(tmp_path / "run", T.load(directory), _lock=lock)
        store.submit("start")
        store.record_event("пакет_собран")
        store.record_event("вердикт", {"verdict": "ОДОБРЕНО"})
        assert store.load().state == "неполный", "the engine did not read the edited table"


def test_the_actions_named_by_the_table_are_applied(run):
    _to_anton(run)
    run.start_round(3)
    run.submit("submit-decision", {"decision": "изменить_цель"}, "issue", "I-1", {"n": 1})
    state = run.load()
    assert state.validity == "superseded", "mark_run_superseded was not applied"
    assert state.state == "завершён"


def test_resetting_the_round_counter_does_not_touch_anything_else(run):
    _to_anton(run)
    run.start_round(2)
    run.submit("submit-decision", {"decision": "сменить_решение", "change_index": "первая"},
               "issue", "I-1", {"n": 1})
    state = run.load()
    assert state.round_number == 0
    assert state.validity == "актуален", "the counter reset must not supersede the run"


def test_an_unknown_operation_or_a_hand_written_event_is_refused(run):
    with pytest.raises(S.StateError):
        run.submit("выпить-чаю")
    with pytest.raises(S.StateError):
        run.record_event("start"), "start is an operation and needs the repeat key"
    with pytest.raises(S.StateError):
        S.RunStore(run.directory, TABLES).create("run-1", "летняя")


def test_the_canonical_hash_ignores_key_order_but_not_content():
    assert S.canonical_hash({"a": 1, "b": 2}) == S.canonical_hash({"b": 2, "a": 1})
    assert S.canonical_hash({"a": 1}) != S.canonical_hash({"a": 2})


# --------------------------------------------------------------------------
# Б1-1 / Б1-7 — an interrupted journal write is repaired, not inherited
# --------------------------------------------------------------------------

def test_a_torn_journal_tail_is_repaired_by_the_next_operation_and_stays_readable(run):
    """Б1-1 / Б1-7 / R12-2: обрыв → новая операция → холодная загрузка.

    Before the fix, appending onto a torn tail either glued the new entry
    onto the broken one, or left the fragment sitting as a *middle* line —
    which `_entries()` then refused forever, burying the run for good.
    """
    run.submit("start")
    with open(run.journal_path, "a", encoding="utf-8") as handle:
        handle.write('{"kind": "operation", "partia')      # обрыв на полуслове

    run.record_event("пакет_собран")                        # операция поверх обрыва

    text = run.journal_path.read_text(encoding="utf-8")
    assert "partia" not in text, "торн-хвост должен быть вырезан под той же блокировкой"

    reloaded = S.RunStore(run.directory, TABLES).load()      # холодная загрузка
    assert reloaded.state == "идёт_круг"
    assert reloaded.stage == "план"


def test_a_torn_multibyte_character_does_not_bury_the_run_forever(run):
    """Review #14 finding 1: обрыв на середине кириллической буквы даёт
    `UnicodeDecodeError` при чтении всего файла разом — это не
    `JSONDecodeError`, и старая терпимость к рваному хвосту его не ловила.
    Красный до правки: `UnicodeDecodeError: 'utf-8' codec can't decode
    byte 0xd0 in position ...: unexpected end of data`."""
    run.submit("start")
    raw = run.journal_path.read_bytes()
    run.journal_path.write_bytes(raw + b'{"kind": "flag", "flag": "\xd0\xb6\xd0\xb8\xd0')

    state = run.load()                       # не должно поднимать UnicodeDecodeError
    assert state.state == "создан"

    run.set_flag("после-обрыва")             # новая операция поверх обрыва
    assert run.load().flags == {"после-обрыва"}


def test_a_complete_record_missing_only_its_newline_is_kept_not_dropped(run):
    """Review #14 finding 2: обрыв ровно после последнего байта JSON, до
    перевода строки — запись цела, но без терминатора. Старый код
    приклеивал следующую запись без разделителя; склейка не парсилась как
    JSON, и `_entries` молча выбрасывала ОБЕ записи, хотя `set_flag` уже
    вернул успех для первой из них."""
    run.submit("start")
    raw = run.journal_path.read_bytes()
    complete_no_newline = json.dumps(
        {"seq": 99, "at": "x", "kind": "flag", "flag": "цел", "on": True},
        ensure_ascii=False, sort_keys=True).encode("utf-8")
    run.journal_path.write_bytes(raw + complete_no_newline)   # цела, но без \n

    run.set_flag("после")                    # успех — не должен потерять "цел"

    state = run.load()
    assert "цел" in state.flags, "целая запись без завершающего \\n не должна тихо теряться"
    assert "после" in state.flags


def test_a_real_sigkill_mid_tail_repair_does_not_erase_prior_entries(run):
    """Review #14 finding 3: починка хвоста в старом коде открывала журнал в
    режиме "w" — файл обнулялся на диске раньше, чем в него попадал хотя бы
    один починенный байт. Второе падение в этом окне стирало всё, что уже
    было надёжно записано. Убиваем починку по-настоящему, посреди работы, и
    проверяем файл после."""
    run.submit("start")
    with open(run.journal_path, "a", encoding="utf-8") as handle:
        handle.write('{"kind": "operation", "partia')      # обрыв на полуслове

    killed = _child("""
        import os, sys
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunStore
        store = RunStore(sys.argv[2])
        os.replace = lambda *a, **k: os.kill(os.getpid(), 9)
        store._repair_tail()
        """, SCRIPTS, run.directory)
    assert killed.returncode == -signal.SIGKILL, killed.stderr

    raw = run.journal_path.read_bytes()
    assert raw, "обрыв починки не должен обнулять журнал"
    assert b'"kind": "run_created"' in raw, "запись о создании прогона должна остаться цела"

    S.RunStore(run.directory, TABLES)._repair_tail()          # успешный повтор чинит файл
    assert S.RunStore(run.directory, TABLES).load().state == "создан"


# --------------------------------------------------------------------------
# Б1-2 — the hash covers the operation, conditions, target and body
# --------------------------------------------------------------------------

def test_differing_conditions_under_the_same_key_are_a_conflict_not_a_silent_repeat(run):
    """Б1-2 / R12-3: only the body used to be hashed, so a second decision
    under the same key with different `conditions` (but the same body) was
    swallowed as an "identical repeat" instead of being refused."""
    _to_anton(run)
    body = {"n": 1}
    run.submit("submit-decision",
               {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
               "issue", "I-1", body)
    with pytest.raises(S.Refusal) as refused:
        run.submit("submit-decision",
                   {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                   "issue", "I-1", body)
    assert refused.value.code == "КОНФЛИКТ_ВХОДА"


# --------------------------------------------------------------------------
# Б1-3 — after revoke-operation the new decision applies, the old one stays visible
# --------------------------------------------------------------------------

def test_after_revoke_the_new_decision_applies_and_the_old_one_stays_visible(run):
    """Б1-3 / R13-1: revoke frees the key for a *new* decision — it must not
    replace the old record. The stale acceptance once asked for a silent
    replacement, which §7.1's "history is never rewritten" forbids."""
    _to_anton(run)
    first = run.submit("submit-decision",
                       {"decision": "запросить_ещё_правку", "budget_fits_quorum": False},
                       "issue", "I-1", {"n": 1})
    run.revoke(first.operation_id)
    second = run.submit("submit-decision",
                        {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                        "issue", "I-1", {"n": 2})

    state = run.load()
    old = next(o for o in state.operations if o.operation_id == first.operation_id)
    assert old.revoked is True
    assert old.refusal == "БЮДЖЕТ_НЕ_ВМЕЩАЕТ_КВОРУМ", "старая запись видна в истории, не стёрта"
    assert second.moved_the_run is True
    assert state.state == "завершён"


# --------------------------------------------------------------------------
# Б1-5 — submit-decision / submit-framing-decision without a target
# --------------------------------------------------------------------------

def test_submit_decision_and_framing_decision_without_a_target_are_refused(run):
    _to_anton(run)
    with pytest.raises(S.StateError):
        run.submit("submit-decision",
                   {"decision": "принять_риск", "all_verdict_blocking_resolved": True},
                   body={"n": 1})
    with pytest.raises(S.StateError):
        run.submit("submit-framing-decision",
                   {"framing_decision": "подтвердить_постановку"}, body={"n": 1})


def test_an_empty_or_blank_target_id_is_not_a_real_target(run):
    """Review #14 finding 7: only `target_kind is None` was checked, so
    `target_id=""` or a whitespace-only `target_id` passed as if it named a
    real issue — recording a decision against a target that does not exist."""
    _to_anton(run)
    conditions = {"decision": "принять_риск", "all_verdict_blocking_resolved": True}
    with pytest.raises(S.StateError):
        run.submit("submit-decision", conditions, target_kind="issue", target_id="",
                   body={"x": 1})
    with pytest.raises(S.StateError):
        run.submit("submit-decision", conditions, target_kind="issue", target_id="   ",
                   body={"x": 1})


# --------------------------------------------------------------------------
# Б1-6 — a mutating RunStore cannot be obtained outside open_run
# --------------------------------------------------------------------------

def test_a_mutating_runstore_is_unobtainable_outside_open_run(tmp_path):
    """Б1-6 / R13-2: `_append` used to be reachable through every public
    method on a bare `RunStore(directory)` — the lock `open_run` takes was
    then only a convention, not something the store itself enforced."""
    bare = S.RunStore(tmp_path / "run", TABLES)
    bare.create("run-x", "план")            # bootstrap, not a table operation
    assert bare.load().run_id == "run-x"    # reading needs no lock, no token

    mutations = (
        lambda: bare.submit("start"),
        lambda: bare.record_event("пакет_собран"),
        lambda: bare.revoke("не-существует"),
        lambda: bare.start_round(1),
        lambda: bare.set_flag("флаг"),
        lambda: bare.record_attempt("план", 1, "claude", 1, "запущена"),
        lambda: bare.assign_idea_candidates([S.IdeaCandidate("C1", "автор", b"x")]),
    )
    for mutate in mutations:
        with pytest.raises(S.StateError):
            mutate()

    with S.open_run(bare.directory, "start") as live:
        live.submit("start")
    assert bare.load().state == "создан", "через open_run та же самая мутация проходит"


def test_open_run_for_a_no_budget_operation_yields_a_read_only_store(run):
    """Review #14 finding 4: `open_run` skips the lock for `операции_без_бюджета`
    (precheck/publish-check/status) but used to still hand out a "live" store —
    write access was granted for free, without ever taking a lock."""
    for operation in TABLES.vocabulary["операции_без_бюджета"]:
        with S.open_run(run.directory, operation) as store:
            with pytest.raises(S.StateError):
                store.set_flag("флаг-без-бюджета")


def test_a_leaked_store_loses_write_access_the_moment_open_run_exits(run):
    """Review #14 finding 5: `_live` was set once at construction and never
    cleared — a reference kept outside its `with open_run(...)` block kept
    writing after the lock was released, and a race between two such leaked
    references reproduced a duplicate `seq`."""
    leaked = []
    with S.open_run(run.directory, "start") as store:
        leaked.append(store)
        store.submit("start")             # works: the lock is still held here
    with pytest.raises(S.StateError):
        leaked[0].set_flag("после-выхода")  # the same object, lock now released


def test_a_racing_create_never_produces_two_run_created_entries(tmp_path):
    """Review #14 finding 6: `create()` wrote unguarded and outside any lock —
    two racing calls produced two `run_created` entries, and `load()` then
    refused forever with "неизвестная запись журнала: 'run_created'". Two
    real threads, each opening its own file descriptor onto the same lock
    file, give genuine kernel-level flock contention — not a mock."""
    directory = tmp_path / "run"
    results = []
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        store = S.RunStore(directory, TABLES)
        try:
            store.create("run-race", "план")
            results.append("created")
        except (S.StateError, S.Refusal) as error:
            results.append(f"refused: {error}")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert results.count("created") == 1, results
    store = S.RunStore(directory, TABLES)
    state = store.load()                                    # не падает навсегда
    assert state.run_id == "run-race"
    entries = [e for e in store._entries() if e.get("kind") == "run_created"]
    assert len(entries) == 1


# --------------------------------------------------------------------------
# Б1-8 / Б1-9 / Б1-10 — idea candidates: source, permutation, canonical bytes
# --------------------------------------------------------------------------

def test_idea_candidates_assigned_entry_carries_source_permutation_and_bytes(run):
    candidates = [
        S.IdeaCandidate("C1", "автор", b"\x00canon-one\xff"),
        S.IdeaCandidate("C2", "критик:codex", "канон-два — не ascii".encode("utf-8")),
    ]
    state = run.assign_idea_candidates(candidates, permutation=[1, 0])

    assert [c.candidate_id for c in state.idea_candidates] == ["C1", "C2"]
    assert state.idea_candidates_permutation == (1, 0)
    assert state.idea_candidates[0].source == "автор"
    assert state.idea_candidates[1].canonical_bytes == "канон-два — не ascii".encode("utf-8")

    entries = [e for e in run._entries() if e.get("kind") == "idea_candidates_assigned"]
    assert len(entries) == 1
    assert entries[0]["candidates"][0]["source"] == "автор"
    assert entries[0]["permutation"] == [1, 0]


def test_idea_candidates_survive_a_crash_and_a_cold_load_byte_for_byte(run):
    """Б1-9 / R14-8 / R16-7: random IDs and order used to not survive a
    restart, and the journal restored IDs but not the cards' own bytes."""
    candidates = [
        S.IdeaCandidate("C1", "автор", b"\x01\x02canon-one"),
        S.IdeaCandidate("C2", "критик:claude", b"canon-two\x00tail"),
    ]
    run.assign_idea_candidates(candidates, permutation=[1, 0])

    killed = _child("""
        import os, sys
        sys.path.insert(0, sys.argv[1])
        from roundtable.state import RunStore, RunLock
        lock = RunLock(sys.argv[2])
        lock.__enter__()
        store = RunStore(sys.argv[2], _lock=lock)
        store._write_snapshot = lambda state: os.kill(os.getpid(), 9)
        store.submit("start")
        """, SCRIPTS, run.directory)
    assert killed.returncode == -signal.SIGKILL, killed.stderr

    reloaded = S.RunStore(run.directory, TABLES).load()       # холодная загрузка
    assert [c.candidate_id for c in reloaded.idea_candidates] == ["C1", "C2"]
    assert reloaded.idea_candidates_permutation == (1, 0)
    assert reloaded.idea_candidates[0].canonical_bytes == b"\x01\x02canon-one"
    assert reloaded.idea_candidates[1].canonical_bytes == b"canon-two\x00tail"


def test_reassigning_a_different_set_of_idea_candidates_is_refused_and_source_stays_hidden(run):
    """Б1-10 / R15-3: a second, *different* assignment must be a conflict —
    and whichever model proposed a card must not leak into the blind view."""
    first = [S.IdeaCandidate("C1", "автор", b"one"), S.IdeaCandidate("C2", "критик:codex", b"two")]
    run.assign_idea_candidates(first)
    run.assign_idea_candidates(first)                         # тот же набор — идемпотентно

    other = [S.IdeaCandidate("C1", "автор", b"one"), S.IdeaCandidate("C3", "критик:claude", b"three")]
    with pytest.raises(S.Refusal) as refused:
        run.assign_idea_candidates(other)
    assert refused.value.code == "КОНФЛИКТ_ВХОДА"

    state = run.load()
    blind = [c.blind() for c in state.idea_candidates]
    assert all("source" not in b for b in blind)
    assert [b["candidate_id"] for b in blind] == ["C1", "C2"]
