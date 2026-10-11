"""Б1 — durable state: the journal survives, the lock refuses, repeats are free.

The two acceptance criteria are `resume` surviving a `kill -9` and a reboot, and
a parallel call being refused. Both are tested the only way they mean anything:
by actually killing a process with SIGKILL and by actually holding the lock from
a second process. A mocked crash proves the mock.
"""

import base64
import hashlib
import json
import os
import shutil
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
        "record_received", "record_validation", "pin", "_record_anton_ok", "record_stage_exit",
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
        if status == "получена":                  # БУ-11: an answer is counted only together with its bytes
            attempt = run.record_received("план", 1, "claude", 1, b"{}", QUESTION)
        else:
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


def test_a_terminated_but_corrupt_line_is_an_error_not_a_silently_dropped_tail(run):
    """Review #22 finding 1: `_entries()` first strips the empty piece after
    the final `\\n`, then allows the *remaining* last line to be dropped on a
    parse error — so a line that already ends with `\\n` but is corrupt gets
    treated as an "unfinished write" and silently disappears. Only bytes
    that never got a trailing `\\n` may be torn; anything the file itself
    marks as finished must actually parse, or the load must refuse."""
    run.set_flag("до")
    with open(run.journal_path, "ab") as handle:
        handle.write(b"{broken JSON}\n")            # завершённая, но повреждённая строка

    with pytest.raises(S.StateError):
        run.load()

    # запись тоже должна отказать, а не тихо дописаться поверх порчи (§Б1-7)
    with pytest.raises(S.StateError):
        run.set_flag("после-порчи")


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


def test_a_forked_childs_exit_does_not_release_the_parents_lock(tmp_path):
    """Review #22 finding 2: `RunLock` tracked *whether* it was held but not
    *which process* took it. A `fork()`ed child inherits both the open
    descriptor and `_held=True` by copying the parent's memory; its own
    `__exit__` calling `LOCK_UN` releases the lock for the shared open file
    description — the parent's, too — even though the parent's own `_held`
    stays True and a second, independent lock must still be refused."""
    directory = tmp_path / "run"
    directory.mkdir()
    lock = S.RunLock(directory)
    lock.__enter__()

    pid = os.fork()
    if pid == 0:
        lock.__exit__(None, None, None)   # child: must not release the parent's lock
        os._exit(0)
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, "ребёнок должен завершиться чисто"

    assert lock.is_held() is True, "чужой __exit__ не должен снимать владение у родителя"
    with pytest.raises(S.Refusal) as refused:
        with S.RunLock(directory):
            pass                          # второй, независимый замок не должен взяться
    assert refused.value.code == "ПРОГОН_ЗАНЯТ"

    lock.__exit__(None, None, None)       # настоящий владелец освобождает как положено


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


def test_a_lock_whose_file_was_deleted_no_longer_backs_writes(run):
    """Круг 44: замок проверял процесс, но не то, что он всё ещё держит ТОТ
    файл. Файл замка удалили посреди работы первого вызова — второй взял
    новый замок на тот же прогон, и оба записали. Теперь первый, чей файл
    исчез, теряет право записи: писатель на прогон снова один."""
    first_lock = S.RunLock(run.directory).__enter__()
    first = S.RunStore(run.directory, TABLES, _lock=first_lock)
    first.submit("start")                                     # контроль: пишет, пока замок цел

    (run.directory / S.LOCK).unlink()                         # вмешательство извне
    with S.RunLock(run.directory) as second_lock:
        second = S.RunStore(run.directory, TABLES, _lock=second_lock)
        with pytest.raises(S.StateError, match="блокировкой"):
            first.set_flag("пауза", True)
        second.set_flag("пауза", True)                        # писатель остался один
    first_lock.__exit__(None, None, None)

    kinds = [e["kind"] for e in run._entries()]
    assert kinds.count("flag") == 1, kinds


def test_a_lock_replaced_by_another_file_under_the_same_name_is_not_ours(run):
    """То же, но файл не просто удалён, а подменён новым с тем же именем:
    имя совпадает, а держим мы уже не его."""
    lock = S.RunLock(run.directory).__enter__()
    store = S.RunStore(run.directory, TABLES, _lock=lock)
    path = run.directory / S.LOCK
    path.unlink()
    path.write_text("чужой\n", encoding="utf-8")
    with pytest.raises(S.StateError, match="блокировкой"):
        store.submit("start")
    lock.__exit__(None, None, None)
    assert [e["kind"] for e in run._entries()] == ["run_created"]


def test_a_lock_of_another_run_directory_does_not_open_this_one(run, tmp_path):
    """Круг 44: магазину прогона можно было передать замок ДРУГОГО каталога —
    замок держится, значит «можно писать», хотя этот прогон занят кем-то ещё."""
    elsewhere = tmp_path / "other"
    with S.RunLock(run.directory):                             # прогон занят честным вызовом
        with S.RunLock(elsewhere) as foreign:
            store = S.RunStore(run.directory, TABLES, _lock=foreign)
            with pytest.raises(S.StateError, match="блокировкой"):
                store.submit("start")
    assert [e["kind"] for e in run._entries()] == ["run_created"]


def test_a_corrupt_card_encoding_is_refused_not_read_as_an_empty_card(run):
    """Круг 44: байты карточки идеи хранятся в журнале в кодировке base64, и
    нестрогое чтение превращало испорченную запись в пустую карточку —
    содержимое пропадало без единого слова. Испорченное — отказ."""
    run.assign_idea_candidates([S.IdeaCandidate("C1", "автор", b"one")])
    good = run.journal_path.read_text(encoding="utf-8")
    encoded = base64.b64encode(b"one").decode("ascii")
    for broken in ("!!!!", encoded + "!", encoded[:-1], "", 7):
        forged = good.replace(json.dumps(encoded), json.dumps(broken))
        assert forged != good, broken
        run.journal_path.write_text(forged, encoding="utf-8")
        with pytest.raises(S.StateError, match="карточк"):
            run.load()
    run.journal_path.write_text(good, encoding="utf-8")
    assert run.load().idea_candidates[0].canonical_bytes == b"one"   # контроль


def test_an_empty_card_is_refused_before_anything_is_written(run):
    """Круг 45: пустая карточка идеи записывалась в журнал, а затем сама
    запись отказывалась читаться — прогон больше не открывался. Отказ обязан
    быть ДО записи, и прогон обязан остаться читаемым."""
    before = run.journal_path.read_bytes()
    for bad in (b"", "строка вместо байтов"):
        with pytest.raises(S.StateError, match="карточк"):
            run.assign_idea_candidates([S.IdeaCandidate("C1", "автор", bad)])
        assert run.journal_path.read_bytes() == before, "журнал тронут до отказа"
    run.load()                                                # прогон по-прежнему открывается


def test_a_lock_planted_as_a_link_does_not_overwrite_the_target(run, tmp_path):
    """Круг 45: на месте файла замка заранее стоит символическая ссылка —
    замок открывался по ней и перезаписывал внешний файл."""
    victim = tmp_path / "victim.txt"
    victim.write_text("важное\n", encoding="utf-8")
    lock = run.directory / S.LOCK
    if lock.exists() or lock.is_symlink():
        lock.unlink()
    lock.symlink_to(victim)
    with pytest.raises(S.StateError, match="ссылк"):
        with S.RunLock(run.directory):
            pass
    assert victim.read_text(encoding="utf-8") == "важное\n", "чужой файл перезаписан"


def test_a_journal_planted_as_a_link_is_neither_read_nor_appended(tmp_path):
    """Сверх отчёта: журнал открывался тем же способом — по ссылке читался
    чужой файл как журнал и дописывался."""
    directory = tmp_path / "run"
    S.RunStore(directory, TABLES).create("run-1", "план")
    journal = directory / S.JOURNAL
    victim = tmp_path / "victim.jsonl"
    victim.write_bytes(journal.read_bytes())
    journal.unlink()
    journal.symlink_to(victim)
    before = victim.read_bytes()
    with pytest.raises(S.StateError, match="ссылк"):
        S.RunStore(directory, TABLES).load()
    with pytest.raises(S.StateError, match="ссылк"):
        with S.RunLock(directory) as lock:
            S.RunStore(directory, TABLES, _lock=lock).submit("start")
    assert victim.read_bytes() == before, "по ссылке дописан чужой файл"


# --------------------------------------------------------------------------
# БУ-11 — the bytes of a received answer
# --------------------------------------------------------------------------

QUESTION = "a" * 64
ANSWERS = "ответы"


def _launched(run, stage="идея:слепой", critic="claude", number=1):
    run.record_attempt(stage, 1, critic, number, "подготовлена")
    run.record_attempt(stage, 1, critic, number, "запущена")


def test_bu11_the_bytes_come_back_exactly_after_a_restart_and_are_not_in_the_journal(run):
    raw = "ответ \u0000 с кириллицей и переводом\r\nстроки".encode("utf-8") + bytes(range(200, 256))
    _launched(run)
    attempt = run.record_received("идея:слепой", 1, "claude", 1, raw, QUESTION)
    assert attempt.status == "получена" and attempt.receipt.length == len(raw)
    assert attempt.receipt.sha256 == hashlib.sha256(raw).hexdigest() and attempt.receipt.question_hash == QUESTION
    cold = S.RunStore(run.directory, TABLES)                                   # the restart: nothing cached
    assert cold.read_answer("идея:слепой", 1, "claude", 1) == raw
    assert (run.directory / ANSWERS / attempt.receipt.sha256).read_bytes() == raw
    assert base64.b64encode(raw).decode() not in run.journal_path.read_text(encoding="utf-8")
    assert cold.load().attempts[attempt.key].receipt == attempt.receipt


def test_bu11_the_file_is_on_the_disk_before_the_journal_learns_of_it(run, monkeypatch):
    _launched(run)
    seen = {}
    real = S.RunStore._append

    def probe(self, entry):
        if "answer" in entry:
            seen["file_first"] = (self.directory / ANSWERS / entry["answer"]["sha256"]).is_file()
        return real(self, entry)

    monkeypatch.setattr(S.RunStore, "_append", probe)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    assert seen == {"file_first": True}


def test_bu11_a_failure_between_the_file_and_the_entry_does_not_count_the_answer(run, monkeypatch):
    _launched(run)
    real = S.RunStore._append

    def failing(self, entry):
        if "answer" in entry:
            raise OSError("диск")
        return real(self, entry)

    monkeypatch.setattr(S.RunStore, "_append", failing)
    with pytest.raises(OSError):
        run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    monkeypatch.undo()
    attempt = run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)]
    assert attempt.status == "запущена" and attempt.receipt is None               # not counted
    with pytest.raises(T.ContractError):
        run.read_answer("идея:слепой", 1, "claude", 1)
    assert run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION).status == "получена"   # positive control


def test_bu11_the_same_answer_again_is_a_repeat_and_another_one_is_refused(run):
    _launched(run)
    first = run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    entries = len(run.journal_path.read_text(encoding="utf-8").splitlines())
    assert run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION) == first
    assert len(run.journal_path.read_text(encoding="utf-8").splitlines()) == entries
    for raw, question in ((b"abd", QUESTION), (b"abc", "b" * 64)):
        with pytest.raises(S.StateError):
            run.record_received("идея:слепой", 1, "claude", 1, raw, question)
    with pytest.raises(S.StateError):                                           # no attempt, no answer
        run.record_received("идея:слепой", 1, "codex", 1, b"abc", QUESTION)
    with pytest.raises(S.StateError):
        run.record_received("идея:слепой", 1, "claude", 1, "text", QUESTION)    # bytes, not text


@pytest.mark.parametrize("damage", ["подмена", "обрезан", "удалён", "ссылка"])
def test_bu11_a_changed_missing_or_linked_file_is_a_contract_error_on_reading(run, tmp_path, damage):
    _launched(run)
    receipt = run.record_received("идея:слепой", 1, "claude", 1, b"original answer", QUESTION).receipt
    path = run.directory / ANSWERS / receipt.sha256
    assert run.read_answer("идея:слепой", 1, "claude", 1) == b"original answer"       # positive control
    if damage == "подмена":
        path.write_bytes(b"another answer!")                                          # same length, other bytes
    elif damage == "обрезан":
        path.write_bytes(b"original")
    elif damage == "удалён":
        path.unlink()
    else:
        outside = tmp_path / "outside"
        outside.write_bytes(b"original answer")
        path.unlink()
        path.symlink_to(outside)
    with pytest.raises(T.ContractError):
        run.read_answer("идея:слепой", 1, "claude", 1)


def test_bu11_the_result_of_the_check_is_kept_with_the_clipped_reason_and_written_once(run):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    limit = TABLES.vocabulary["ответ_критика"]["предел_причины"]
    result = run.record_validation("идея:слепой", 1, "claude", 1, False, "п" * 5000)
    assert result.accepted is False and len(result.reason) == limit + 1 and result.reason.endswith("…")
    assert result.question_hash == QUESTION
    assert run.record_validation("идея:слепой", 1, "claude", 1, False, "п" * 5000) == result      # a repeat
    stored = S.RunStore(run.directory, TABLES).load().attempts[("run-1", "идея:слепой", 1, "claude", 1)]
    assert stored.validation == result                                                          # after the restart
    with pytest.raises(S.StateError):
        run.record_validation("идея:слепой", 1, "claude", 1, True)                               # another result
    with pytest.raises(S.StateError):
        run.record_validation("идея:слепой", 1, "codex", 1, True)                                # no answer to judge
    _launched(run, number=2)
    run.record_received("идея:слепой", 1, "claude", 2, b"abc2", QUESTION)
    for accepted, reason in ((True, "причина у принятого"), (False, "  ")):
        with pytest.raises(S.StateError):
            run.record_validation("идея:слепой", 1, "claude", 2, accepted, reason)
    assert run.record_validation("идея:слепой", 1, "claude", 2, True).reason == ""


def test_bu11_later_statuses_and_the_duplicate_mark_keep_the_receipt(run):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    run.record_validation("идея:слепой", 1, "claude", 1, True)
    run.record_attempt("идея:слепой", 1, "claude", 1, "провалидирована")
    run.mark_possible_duplicate("идея:слепой", 1, "claude", 1)
    attempt = S.RunStore(run.directory, TABLES).load().attempts[("run-1", "идея:слепой", 1, "claude", 1)]
    assert attempt.status == "провалидирована" and attempt.possible_duplicate
    assert attempt.receipt is not None and attempt.validation.accepted


def test_bu11_a_receipt_of_another_run_or_a_second_different_one_in_the_journal_is_corruption(run):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    lines = run.journal_path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[-1])
    forged["answer"] = {**forged["answer"], "length": 99}
    run.journal_path.write_text("\n".join(lines + [json.dumps(forged, ensure_ascii=False)]) + "\n", encoding="utf-8")
    with pytest.raises(S.StateError, match="квитанция"):
        S.RunStore(run.directory, TABLES).load()


# --------------------------------------------------------------------------
# БУ-12 — pins
# --------------------------------------------------------------------------

def _started(run):
    run.submit("start")
    return run


def _pin(run, event="пакет_закреплён", round_number=1, revision="r" * 64, content="c" * 64, hidden="h" * 64):
    return run.pin(event, round_number=round_number, revision=revision, content_hash=content, hidden_hash=hidden)


def test_bu12_a_pin_is_a_journal_event_and_survives_a_restart(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    pin = _pin(run)
    assert (pin.event, pin.round_number, pin.revision, pin.content_hash, pin.hidden_hash) == (
        "пакет_закреплён", 1, "r" * 64, "c" * 64, "h" * 64)
    assert S.RunStore(run.directory, TABLES).load().pins == [pin]
    assert run.load().state == "идёт_круг"                                         # a pin moves nothing
    events = [json.loads(line) for line in run.journal_path.read_text(encoding="utf-8").splitlines()]
    assert [e["event"] for e in events if e.get("kind") == "event"][-1] == "пакет_закреплён"


def _idea_run(tmp_path, session=None):
    directory = tmp_path / "run"
    S.RunStore(directory, TABLES).create("run-1", "идея", session)
    return _TestRun(directory, TABLES)


def test_bu12_the_same_pin_again_comes_back_without_a_second_event(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    first = _pin(run)
    size = run.journal_path.read_bytes()
    assert _pin(run) == first and run.journal_path.read_bytes() == size
    assert _pin(run, event="вход_закреплён") != first                              # the other kind is its own event


def test_bu12_other_content_in_the_same_round_is_refused_and_the_old_event_stays(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    first = _pin(run)
    size = run.journal_path.read_bytes()
    for kwargs in ({"content": "d" * 64}, {"hidden": "i" * 64}, {"revision": "q" * 64}):
        with pytest.raises(S.Refusal) as refused:
            _pin(run, **kwargs)
        assert refused.value.code == "КОНФЛИКТ_ВХОДА"
    assert run.journal_path.read_bytes() == size and run.load().pins == [first]


def test_bu12_a_new_revision_in_a_new_round_gets_a_new_event_and_the_old_one_stays(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    first = _pin(run)
    second = _pin(run, round_number=2, revision="n" * 64, content="e" * 64)
    assert run.load().pins == [first, second]
    assert _pin(run, round_number=2, revision="n" * 64, content="e" * 64) == second
    with pytest.raises(S.Refusal):                                                  # the old revision with other content
        _pin(run, round_number=3, revision="r" * 64, content="f" * 64)
    assert run.load().pins == [first, second]
    same_again = _pin(run, round_number=3, revision="r" * 64)                       # the same revision and content: its own event
    assert same_again.round_number == 3 and len(run.load().pins) == 3


def test_bu12_the_closed_shape_of_a_pin(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    for kwargs in ({"event": "придуманное"}, {"round_number": 0}, {"round_number": True}, {"revision": " "},
                   {"content": ""}):
        with pytest.raises(S.StateError):
            _pin(run, **kwargs)
    assert run.load().pins == []
    created = _idea_run(tmp_path / "other")
    with pytest.raises(T.ContractError):                                           # a run not started has no pin to make
        _pin(created)


def test_bu13_resume_is_one_operation_per_journal_position(run):
    run.submit("start")
    run.record_event("пакет_собран")
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"})
    first = run.submit("resume", body={"reason": "1"})
    assert first.moved_the_run and run.load().state == "идёт_круг"
    assert run.submit("resume", body={"reason": "1"}) == first      # the same command again: one operation
    assert len([o for o in run.load().operations if o.key[3] == "resume"]) == 1
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"})                              # incomplete again, the same round
    second = run.submit("resume", body={"reason": "1"})
    assert second.operation_id != first.operation_id and second.key != first.key
    assert run.load().state == "идёт_круг"                                                    # it really moved the run


def _exhausted_incomplete(run):
    """An incomplete run whose critic used both of the retries on rejected answers."""
    run.submit("start")
    run.record_event("пакет_собран")
    for number in (1, 2):
        _launched(run, number=number)
        run.record_received("идея:слепой", 1, "claude", number, b"x%d" % number, QUESTION)
        run.record_validation("идея:слепой", 1, "claude", number, False, "не json")
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"})
    assert run.load().state == "неполный"


def test_bu13_resume_without_budget_is_the_named_refusal_and_does_not_move_the_run(run):
    _exhausted_incomplete(run)
    refused = run.submit("resume", body={"reason": "нечем"})
    assert refused.refusal == "ПРОДОЛЖИТЬ_НЕЧЕМ" and not refused.moved_the_run
    assert run.load().state == "неполный"
    # the same command at the same position is the same operation, not a second refusal in the journal
    assert run.submit("resume", body={"reason": "нечем"}) == refused


@pytest.mark.parametrize("forged", [{"budget_remains": True}, {"budget_remains": False}, {"input_can_progress": True},
                                    {"verdict": "ОДОБРЕНО"}])
def test_bu13_conditions_of_a_resume_come_from_the_journal_a_forged_one_is_refused(run, forged):
    """The caller cannot buy budget: a passed condition is refused, whatever it says, and nothing is written."""
    _exhausted_incomplete(run)
    size = run.journal_path.read_bytes()
    with pytest.raises(S.StateError):
        run.submit("resume", forged, body={"reason": "подделка"})
    assert run.journal_path.read_bytes() == size and run.load().state == "неполный"
    refused = run.submit("resume", body={"reason": "честно"})                      # positive control: counted by the journal
    assert refused.refusal == "ПРОДОЛЖИТЬ_НЕЧЕМ" and run.load().state == "неполный"


def test_bu13_an_unjudged_answer_keeps_the_critic_in_unless_the_reading_found_it_invalid(run):
    run.submit("start")
    run.record_event("пакет_собран")
    for number in (1, 2):
        _launched(run, number=number)
        run.record_received("идея:слепой", 1, "claude", number, b"x%d" % number, QUESTION)
        if number == 1:
            run.record_validation("идея:слепой", 1, "claude", number, False, "не json")
    key = ("run-1", "идея:слепой", 1, "claude", 2)
    assert run.resume_conditions()["budget_remains"] is True                      # the last answer may still be valid
    assert run.resume_conditions([key])["budget_remains"] is False                # ... unless it was found invalid
    assert run.resume_conditions([("run-1", "идея:слепой", 1, "claude", 9)])["budget_remains"] is True


def test_bu13_the_cause_of_an_input_that_does_not_build_stops_the_continuation(run):
    run.submit("start")
    run.record_event("пакет_собран")
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"}, {"cause": S.CAUSE_INPUT_NOT_BUILT})
    assert run.load().incomplete_cause == S.CAUSE_INPUT_NOT_BUILT
    assert run.resume_conditions() == {"budget_remains": True, "input_can_progress": False}
    refused = run.submit("resume", body={"reason": "ещё раз"})
    assert refused.refusal == "НУЖНА_КОРРЕКЦИЯ_ВХОДА" and run.load().state == "неполный"
    with pytest.raises(S.StateError):
        run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"}, {"cause": "выдумка"})


def test_bu13_a_new_round_without_a_pinned_input_does_not_progress(run):
    run.submit("start")
    run.record_event("пакет_собран")
    run.record_event("вердикт", {"verdict": "НЕПОЛНЫЙ_ПРОГОН"})
    assert run.resume_conditions()["input_can_progress"] is True
    run.start_round(2)
    assert run.resume_conditions()["input_can_progress"] is False
    assert run.submit("resume").refusal == "НУЖНА_КОРРЕКЦИЯ_ВХОДА"


# --------------------------------------------------------------------------
# БУ-11, hardening: the order bytes -> event, the size, the answers directory
# --------------------------------------------------------------------------

def _answers_dir(run):
    return run.directory / ANSWERS


def test_bu11_an_answer_status_is_never_set_without_a_receipt(run):
    _launched(run)
    for status in ("получена", "провалидирована", "зафиксирована"):
        with pytest.raises(S.StateError, match="без квитанции"):
            run.record_attempt("идея:слепой", 1, "claude", 1, status)
    with pytest.raises(S.StateError):                                    # nor for an attempt that does not exist
        run.record_attempt("идея:слепой", 1, "codex", 1, "получена")
    assert run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)].status == "запущена"
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)           # positive control
    assert run.record_attempt("идея:слепой", 1, "claude", 1, "провалидирована").status == "провалидирована"


def _rewrite_last(run, mutate):
    lines = run.journal_path.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(mutate(json.loads(lines[-1])), ensure_ascii=False, sort_keys=True)
    run.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bu11_a_journal_entry_with_an_answer_and_another_status_is_corruption(run):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    _rewrite_last(run, lambda e: {**e, "status": "зафиксирована"})
    with pytest.raises(S.StateError, match="не «получена»"):
        S.RunStore(run.directory, TABLES).load()


@pytest.mark.parametrize("damage", [
    lambda e: {k: v for k, v in e.items() if k != "reason"},
    lambda e: {**e, "reason": 5},
    lambda e: {**e, "accepted": "да"},
    lambda e: {k: v for k, v in e.items() if k != "question_hash"},
    lambda e: {**e, "accepted": True, "reason": "не пусто"},
])
def test_bu11_a_damaged_validation_entry_is_a_state_error_not_a_key_error(run, damage):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    run.record_validation("идея:слепой", 1, "claude", 1, False, "причина")
    _rewrite_last(run, damage)
    with pytest.raises(S.StateError):
        S.RunStore(run.directory, TABLES).load()


@pytest.mark.parametrize("damage", [
    lambda e: {**e, "pin": {k: v for k, v in e["pin"].items() if k != "hidden_hash"}},
    lambda e: {**e, "pin": {**e["pin"], "round": 0}},
    lambda e: {**e, "pin": {**e["pin"], "revision": ""}},
    lambda e: {**e, "pin": {**e["pin"], "hidden_hash": 7}},
    lambda e: {**e, "pin": "не словарь"},
])
def test_bu12_a_damaged_pin_entry_is_a_state_error_not_a_key_error(tmp_path, damage):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    _pin(run)
    _rewrite_last(run, damage)
    with pytest.raises(S.StateError):
        S.RunStore(run.directory, TABLES).load()


def test_bu11_the_size_of_a_stored_answer_is_bounded_by_the_table(run):
    limit = TABLES.vocabulary["ответ_критика"]["предел_байтов"]
    assert limit >= TABLES.vocabulary["пакет"]["предел_раздела_байт"]
    _launched(run)
    with pytest.raises(S.StateError, match="предел"):
        run.record_received("идея:слепой", 1, "claude", 1, b"x" * (limit + 2), QUESTION)
    assert not _answers_dir(run).exists() and run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)].receipt is None
    attempt = run.record_received("идея:слепой", 1, "claude", 1, b"x" * (limit + 1), QUESTION)     # the cut-off form is kept
    assert attempt.receipt.length == limit + 1
    assert run.read_answer("идея:слепой", 1, "claude", 1) == b"x" * (limit + 1)


def test_bu11_only_length_plus_one_bytes_are_read_from_a_file_that_grew(run):
    _launched(run)
    receipt = run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION).receipt
    (_answers_dir(run) / receipt.sha256).write_bytes(b"abc" + b"z" * 10_000_000)
    with pytest.raises(T.ContractError, match="не совпал"):
        run.read_answer("идея:слепой", 1, "claude", 1)


def test_bu11_the_answers_directory_is_owner_only_and_tightened_if_it_was_not(run):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    assert (os.stat(_answers_dir(run)).st_mode & 0o777) == 0o700
    receipt = run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)].receipt
    assert (os.stat(_answers_dir(run) / receipt.sha256).st_mode & 0o077) == 0
    os.chmod(_answers_dir(run), 0o755)
    _launched(run, number=2)
    run.record_received("идея:слепой", 1, "claude", 2, b"abd", QUESTION)
    assert (os.stat(_answers_dir(run)).st_mode & 0o777) == 0o700


def test_bu11_a_symlinked_answers_directory_is_refused_for_writing_and_reading_without_the_path(run, tmp_path):
    _launched(run)
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    outside = tmp_path / "outside"
    shutil.copytree(_answers_dir(run), outside)
    shutil.rmtree(_answers_dir(run))
    _answers_dir(run).symlink_to(outside)
    _launched(run, number=2)
    with pytest.raises(S.StateError) as error:
        run.record_received("идея:слепой", 1, "claude", 2, b"abd", QUESTION)
    assert str(tmp_path) not in str(error.value) and not list(outside.glob("*abd*"))
    assert len(list(outside.iterdir())) == 1                                      # nothing was written through the link
    with pytest.raises(T.ContractError) as error:
        run.read_answer("идея:слепой", 1, "claude", 1)
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize("kind", ["симлинк", "каталог", "канал"])
def test_bu11_a_link_a_directory_or_a_pipe_in_place_of_the_file_is_a_named_refusal_not_a_hang(run, tmp_path, kind):
    _launched(run)
    digest = hashlib.sha256(b"abc").hexdigest()
    _answers_dir(run).mkdir(mode=0o700)
    place = _answers_dir(run) / digest
    if kind == "симлинк":
        place.symlink_to(tmp_path / "nowhere")
    elif kind == "каталог":
        place.mkdir()
    else:
        os.mkfifo(place)
    with pytest.raises(S.StateError) as error:
        run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    assert str(tmp_path) not in str(error.value) and digest[:12] in str(error.value)
    assert run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)].receipt is None
    if kind == "канал":
        with pytest.raises(T.ContractError):
            S.RunStore(run.directory, TABLES).read_answer("идея:слепой", 1, "claude", 1)
    place.unlink() if kind != "каталог" else place.rmdir()                          # positive control: the place cleared
    assert run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION).status == "получена"


def test_bu11_a_damaged_regular_file_under_the_digest_name_is_replaced(run):
    _launched(run)
    digest = hashlib.sha256(b"abc").hexdigest()
    _answers_dir(run).mkdir(mode=0o700)
    (_answers_dir(run) / digest).write_bytes("\x00 битый сирота".encode("utf-8"))
    run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    assert (_answers_dir(run) / digest).read_bytes() == b"abc"


def test_bu11_a_failed_rename_leaves_no_temp_file_and_the_leftovers_of_a_crash_are_swept(run, monkeypatch):
    _launched(run)
    _answers_dir(run).mkdir(mode=0o700)
    (_answers_dir(run) / ".answer-прошлое-падение").write_bytes(b"obsolete")
    real = os.replace
    calls = []

    def failing(src, dst, *args, **kwargs):
        calls.append(kwargs)
        raise OSError("диск")

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(OSError):
        run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION)
    monkeypatch.setattr(os, "replace", real)
    assert list(_answers_dir(run).iterdir()) == []                                   # the leftover swept, no new temp
    assert calls and "src_dir_fd" in calls[0] and "dst_dir_fd" in calls[0]            # by descriptor, not by path
    assert run.load().attempts[("run-1", "идея:слепой", 1, "claude", 1)].receipt is None
    assert run.record_received("идея:слепой", 1, "claude", 1, b"abc", QUESTION).status == "получена"


# --------------------------------------------------------------------------
# БУ-15 — the record of an OK as the journal holds it
# --------------------------------------------------------------------------

OK_FIELDS = dict(session="11111111-2222-3333-4444-555555555555", native_uuid="aaaaaaaa-bbbb-cccc-dddd-000000000001",
                 reply_at="2999-01-01T00:00:00Z", run_id="run-1", stage="идея", artifact="карточка_решения",
                 revision="d" * 64, round_number=1)


def _waiting_for_anton(tmp_path, session=None):
    run = _started(_idea_run(tmp_path, session))
    run.record_event("пакет_собран")
    run.pin("вход_закреплён", round_number=1, revision="d" * 64, content_hash="c" * 64)    # the critics judge THIS revision
    run.record_event("вердикт", {"verdict": "РЕШЕНИЕ_АНТОНА"})
    return run


def test_bu15_the_record_of_an_ok_is_kept_once_with_its_place_in_the_journal(tmp_path):
    run = _waiting_for_anton(tmp_path)
    verdict_at = run.load().last_verdict_position
    first = run._record_anton_ok(**OK_FIELDS)
    assert first.position > verdict_at >= 0 and run.load().state == "ждёт_Антона"
    size = run.journal_path.read_bytes()
    assert run._record_anton_ok(**OK_FIELDS) == first and run.journal_path.read_bytes() == size
    other = run._record_anton_ok(**{**OK_FIELDS, "native_uuid": "aaaaaaaa-bbbb-cccc-dddd-000000000002"})
    assert other.position > first.position and S.RunStore(run.directory, TABLES).load().anton_oks == [first, other]
    with pytest.raises(S.Refusal):
        run._record_anton_ok(**{**OK_FIELDS, "revision": "c" * 64})


@pytest.mark.parametrize("bad", [{"run_id": "чужой"}, {"stage": "план"}, {"revision": " "}, {"round_number": 0},
                                 {"round_number": True}, {"session": 5}])
def test_bu15_a_record_of_another_run_or_a_damaged_field_is_refused_before_the_write(tmp_path, bad):
    run = _waiting_for_anton(tmp_path)
    size = run.journal_path.read_bytes()
    with pytest.raises(S.StateError):
        run._record_anton_ok(**{**OK_FIELDS, **bad})
    with pytest.raises(S.StateError):
        run._record_anton_ok(**{k: v for k, v in OK_FIELDS.items() if k != "revision"})
    assert run.journal_path.read_bytes() == size


@pytest.mark.parametrize("damage", [
    lambda e: {**e, "ok": {k: v for k, v in e["ok"].items() if k != "revision"}},
    lambda e: {**e, "ok": {**e["ok"], "round_number": "1"}},
    lambda e: {**e, "ok": {**e["ok"], "run_id": ""}},
    lambda e: {**e, "ok": "не словарь"},
])
def test_bu15_a_damaged_ok_entry_is_a_state_error_not_a_key_error(tmp_path, damage):
    run = _waiting_for_anton(tmp_path)
    run._record_anton_ok(**OK_FIELDS)
    _rewrite_last(run, damage)
    with pytest.raises(S.StateError):
        S.RunStore(run.directory, TABLES).load()


def test_bu15_an_ok_cannot_be_recorded_when_the_run_is_not_waiting_for_anton(tmp_path):
    run = _started(_idea_run(tmp_path))
    run.record_event("пакет_собран")
    with pytest.raises((S.Refusal, T.ContractError)):            # no verdict yet: nothing to give an OK for
        run._record_anton_ok(**OK_FIELDS)


def test_bu15_the_door_of_the_record_is_closed_and_the_exit_is_only_the_stores_own(tmp_path):
    run = _waiting_for_anton(tmp_path)
    assert not hasattr(S.RunStore, "record_anton_ok")                                # the public name is gone
    size = run.journal_path.read_bytes()
    spec = TABLES.vocabulary["ок_антона"]
    for event, conditions in ((spec["переход"], {"anton_ok": "есть", "framing_objection": False}),
                              (spec["переход"], {}), (spec["событие"], {"ok_binding": True})):
        with pytest.raises(S.StateError, match="своим методом"):
            run.record_event(event, conditions)
    assert run.journal_path.read_bytes() == size and run.load().state == "ждёт_Антона"


def test_bu15_the_exit_counts_its_conditions_from_the_journal_and_takes_none_from_outside(tmp_path):
    run = _waiting_for_anton(tmp_path)
    with pytest.raises(S.Refusal) as refused:                                       # no OK
        run.record_stage_exit()
    assert refused.value.code == "НЕТ_ОК_АНТОНА" and run.load().state == "ждёт_Антона"
    with pytest.raises(TypeError):
        run.record_stage_exit({"anton_ok": "есть", "framing_objection": False})
    run._record_anton_ok(**OK_FIELDS)
    run.set_flag(TABLES.framing["флаг_прогона"])                                    # an open objection holds the exit
    with pytest.raises(S.Refusal) as refused:
        run.record_stage_exit()
    assert refused.value.code == "ЕСТЬ_ОТКРЫТОЕ_ВОЗРАЖЕНИЕ"
    with pytest.raises(S.Refusal) as refused:                                       # and cannot be taken off by a flag call
        run.set_flag(TABLES.framing["флаг_прогона"], False)
    assert refused.value.code == "ФЛАГ_ЗАЩИЩЁН" and TABLES.framing["флаг_прогона"] in run.load().flags
    run.set_flag("другой_флаг")
    run.set_flag("другой_флаг", False)                                              # other flags are not protected
    assert run.load().state == "ждёт_Антона"


def test_bu15_the_exit_with_an_ok_is_made_once(tmp_path):
    run = _waiting_for_anton(tmp_path)
    run._record_anton_ok(**OK_FIELDS)
    left = run.record_stage_exit()
    assert left.state == "завершён" and left.stage_exit_position > 0
    size = run.journal_path.read_bytes()
    assert run.record_stage_exit().state == "завершён" and run.journal_path.read_bytes() == size
    assert S.RunStore(run.directory, TABLES).load().stage_exit_position == left.stage_exit_position


def test_bu15_the_record_checks_the_journal_itself_revision_state_judged_and_session(tmp_path):
    run = _waiting_for_anton(tmp_path, session=OK_FIELDS["session"])
    size = run.journal_path.read_bytes()
    for bad, why in (({"revision": "c" * 64}, "другую редакцию"),
                     ({"session": "99999999-2222-3333-4444-555555555555"}, "другой сессии")):
        with pytest.raises(S.Refusal, match=why):
            run._record_anton_ok(**{**OK_FIELDS, **bad})
    assert run.journal_path.read_bytes() == size and run.load().anton_oks == []
    assert run._record_anton_ok(**OK_FIELDS).revision == "d" * 64                    # positive control
    assert run.load().session == OK_FIELDS["session"]


def test_bu15_a_revision_pinned_after_the_last_verdict_was_never_judged_and_takes_no_ok(tmp_path):
    run = _waiting_for_anton(tmp_path)
    run.pin("вход_закреплён", round_number=2, revision="e" * 64, content_hash="f" * 64)    # the verdict was about "d"
    size = run.journal_path.read_bytes()
    with pytest.raises(S.Refusal, match="не судили"):
        run._record_anton_ok(**{**OK_FIELDS, "revision": "e" * 64})
    with pytest.raises(S.Refusal):
        run._record_anton_ok(**OK_FIELDS)                                           # nor does the old one: it is not current
    assert run.journal_path.read_bytes() == size


def test_bu15_the_run_remembers_the_session_it_started_in(tmp_path):
    with_session = _idea_run(tmp_path / "a", session="11111111-2222-3333-4444-555555555555")
    assert with_session.load().session == "11111111-2222-3333-4444-555555555555"
    assert _idea_run(tmp_path / "b").load().session is None
    with pytest.raises(S.StateError):
        S.RunStore(tmp_path / "c", TABLES).create("run-1", "идея", " ")
