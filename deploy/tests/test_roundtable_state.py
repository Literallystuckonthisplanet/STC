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


@pytest.fixture
def run(tmp_path):
    store = S.RunStore(tmp_path / "run", TABLES)
    store.create("run-1", "план")
    return store


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
        from roundtable.state import RunStore
        store = RunStore(sys.argv[2])
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
        from roundtable.state import RunStore
        store = RunStore(sys.argv[2])
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

    store = S.RunStore(tmp_path / "run", T.load(directory))
    store.create("run-2", "план")
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
