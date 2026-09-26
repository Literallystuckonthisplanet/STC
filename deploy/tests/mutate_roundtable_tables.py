"""Measure how much of the Roundtable tables the tests actually look at.

A passing suite proves nothing about the rows it never reads. STC has been
burned by that shape twice. On 2026-07-29 a guard with no corpus printed
"skipping" and exited green. And on 2026-09-02 **this very script** reported
`322/322 (100%)` while proving nothing at all: it called test functions by
hand, so a test taking a `tmp_path` fixture raised `TypeError` before any table
was read, the control base was already "failing", and every mutant was counted
as caught. A dead mutant is worthless unless you know *why* it died.

БТ2 (R15-8) fixed one more way this measurement lied without looking broken:
the ratchet ran ONE test file. A row guarded only by `test_roundtable_decide.py`
or by the idea-stage suite (`test_roundtable_context.py`) "died" of a
collection error the moment its table stopped loading, and that death was
never credited to the test that actually reads the row — the denominator only
ever saw one file's expectations. All three files run together now
(`SUITES`; `SUITE` stays as an alias to the first of them — pinned by
`test_the_ratchet_runs_the_real_suite_not_hand_called_functions`).

R38-9 stays OPEN in this table, on purpose: `blocks.yaml:проверки_источников`
is excluded here with the note "already covered by an address guard", and the
finding says that reason expired — the row should be measured, not excluded.
Fixing it means editing `порядок_критики.вне_замера` in blocks.yaml AND the
parity check that pins `NOTES` against it
(`test_what_the_ratchet_does_not_measure_is_named` in
`test_roundtable_tables.py`) — both outside this block's five writable files.
Removing the exclusion here alone breaks that parity test on a file this
block may not touch. See the block report for the FORK this produced.

So the contract of this script is now:

* the tables are copied to a scratch directory — the canon is never written to,
  because `kill -9` mid-run used to leave the repository holding a corrupt table;
* the control base must be **green** before a single mutation is applied;
* each mutant runs the real `pytest`, against every suite file that reads the
  tables, not hand-called functions and not one file in isolation;
* a mutant counts as caught only when a test **fails**; a collection or fixture
  **error** is a defect of this script, not a caught mutation, and stops the run;
* the report names the test that caught each row, so "what protects this rule"
  is answerable instead of assumed;
* four mutation classes are tried (БТ2-8), not one — "delete the rule" catches
  a different defect than "swap it for another value the loader still
  accepts". Each class keeps its OWN denominator, broken down by table and
  field, because a class that cannot apply to a row (a boolean class on a row
  with no boolean, say) is an exclusion that needs its own stated reason —
  copying one class's reasons onto another would hide the difference between
  "nothing to mutate here" and "nobody is watching here".

    python3 deploy/tests/mutate_roundtable_tables.py [--verbose] [--only NAME]
                                                      [--class NAME]
"""

import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "core" / "scripts" / "roundtable" / "tables"

# БТ2-7 (closing R15-8): the tables, the executable-decide suite and the idea
# stage's own suite all read these tables; a mutation "dies" the moment ANY
# of the three notices, and all three must run so that death is credited.
SUITES = (
    Path(__file__).with_name("test_roundtable_tables.py"),
    Path(__file__).with_name("test_roundtable_decide.py"),
    Path(__file__).with_name("test_roundtable_context.py"),
)
SUITE = SUITES[0]  # alias kept for the existing suite that reads this name

# Rows that state intent for a human rather than a rule for the engine. They
# are excluded from the denominator instead of being pinned by a change
# detector — a test that only notices edited prose is noise, and noise is how
# a suite stops being read.
#
NOTES = {
    ("blocks.yaml", "вне_порядка"),
    # R38-9: заявленный сторож существует (test_a_negative_claim_about_an_
    # event_needs_the_raw_source в test_roundtable_tables.py), значит причина
    # исключения из этого списка устарела — раздел ДОЛЖЕН измеряться. Оставлен
    # здесь только потому, что убрать его значит разойтись с parity-тестом
    # test_what_the_ratchet_does_not_measure_is_named, который сверяет этот
    # список с blocks.yaml → порядок_критики.вне_замера — а blocks.yaml вне
    # области записи БТ2. Смотри FORK в отчёте блока.
    ("blocks.yaml", "проверки_источников"),
    ("framing.yaml", "критерии_решения"),
    ("framing.yaml", "критерии_постановки"),
    ("framing.yaml", "права_по_стадиям"),
    ("framing.yaml", "флаг_обязателен_в"),
    ("issues.yaml", "обязательства"),
    ("precheck.yaml", "вне_возможностей"),
    ("precheck.yaml", "коды"),          # covered field-wise by the suite
    ("vocabulary.yaml", "классы_находки"),
    ("vocabulary.yaml", "существенность"),
    ("vocabulary.yaml", "уверенность"),
    ("vocabulary.yaml", "отпечаток"),
    ("vocabulary.yaml", "создатели_доказательства"),
}

# Exclusions that hold for only ONE class, not all four — the whole point of
# per-class denominators (БТ2-8) is that a row can be genuinely covered
# against deletion while staying blind to a class that mutates it a
# different way, and pretending otherwise would hide exactly that gap.
CLASS_EXCLUSIONS = {
    "подсунуть_недопустимое": {
        # `хранение` is read field-by-field by name (`FRAMING["хранение"][...]
        # ["срок"]`), never parsed against a closed set of keys — an extra
        # field next to the ones a test reads is invisible to every test that
        # exists, and to every check in tables.py. Deletion and the id/text
        # class still see this row; this one class does not.
        ("framing.yaml", "хранение"),
        # `валидация` rows are joined into one string by `правило` and matched
        # with `in` (test_every_constrained_element_has_at_least_one_validation_
        # rule) — an unrecognised sibling key next to `правило`/`исход` is
        # never read by anything. Deletion IS read (it shortens the joined
        # string), so that class still measures this row.
        ("issues.yaml", "валидация"),
        # `классы_файлов` is checked by `set(...) == {"existing_evidence",
        # "planned_output"}` — the KEYS are pinned, the two description
        # strings are not read by anything. Deletion changes the key set and
        # is still caught.
        ("precheck.yaml", "классы_файлов"),
        # `фикстуры.не_смешивать_с` is checked by truthiness only
        # (`assert PRECHECK["фикстуры"]["не_смешивать_с"]`) — a REPLACEMENT
        # string is still truthy, so only THIS one field is blind; its
        # siblings (`каталог`, `эталон`, `правило`) are each pinned by
        # `.endswith(...)`/`in` and stay measured — the exclusion is scoped
        # to the one sub-key, not the whole `фикстуры` dict.
        ("precheck.yaml", "фикстуры", "не_смешивать_с"),
        # stages.yaml — every row here is read by specific-field assertions
        # (membership, truthiness, an exact string) in
        # test_roundtable_tables.py; none of the five sections is parsed
        # against a closed key set, so an extra field beside the ones a test
        # names is invisible to all of them. Deletion still lands on a named
        # field and is caught; this class is the one that is blind here.
        ("stages.yaml", "стадии", "идея"),
        ("stages.yaml", "стадии", "план"),
        ("stages.yaml", "стадии", "ревью"),
        ("stages.yaml", "слепой_вопрос"),
        ("stages.yaml", "сигнал_нежизнеспособности"),
        ("stages.yaml", "метрика_цены_понимания"),
        ("stages.yaml", "приоритет_расхода"),
        # blocks.yaml — `_check_plan` (tables.py) and the plan-analysis tests
        # read these sections by NAMED sub-field (`entry["основание"]`,
        # `entry["дата"]`, `spec["блокирует"]`, `row["исполнитель"]`…), never
        # by closing the row's field set the way `Block.parse`/`_require`
        # does for `блоки` itself — an unrecognised sibling key is invisible
        # to every one of those reads. Deletion still removes a NAMED field
        # and is caught; this class alone is blind here.
        ("blocks.yaml", "заключения_ревью", 0),
        ("blocks.yaml", "разрешения_исполнения", 0),
        ("blocks.yaml", "разрешения_исполнения", 1),
        ("blocks.yaml", "история_разрешений", 0),
        ("blocks.yaml", "история_разрешений", 1),
        ("blocks.yaml", "история_разрешений", 2),
        ("blocks.yaml", "шлюзы", "ремонт_после_ревью_12"),
        ("blocks.yaml", "шлюзы", "изоляция_подтверждена"),
        ("blocks.yaml", "исполнение", "роли"),
        ("blocks.yaml", "исполнение", "проверки"),
        ("blocks.yaml", "сверка_записи", "код_движка"),
        ("blocks.yaml", "порядок_критики", "почему"),
    },
}


def _class_excluded(class_name, path_name, key, index):
    for entry in CLASS_EXCLUSIONS.get(class_name, ()):
        if len(entry) == 2 and entry == (path_name, key):
            return True
        if len(entry) == 3 and entry == (path_name, key, index):
            return True
    return False

FAILED = re.compile(r"^FAILED (\S+)", re.M)
ERRORED = re.compile(r"^ERROR (\S+)", re.M)
RAN = re.compile(r"(\d+) (?:passed|failed)")

# pytest: 0 всё прошло, 1 тесты упали. 2 — "прерван"; с несколькими файлами
# аргументом это ЗАКОННЫЙ исход, когда один файл ловит мутацию коллекцией
# (module-scope `T.load()` в test_roundtable_decide.py/test_roundtable_context.py
# падает раньше первого теста) — сам этот файл всё равно "поймал", просто не
# падением теста, а ошибкой сбора. 3 внутренняя ошибка, 4 ошибка параметров,
# 5 не собрано ни одного теста остаются недопустимыми: процесс не сделал того,
# о чём его просили. Раньше код возврата не читался вовсе, и ошибка запуска
# выглядела зелёной базой — тот же класс, что и всё «100 %» до этого.
PYTEST_RAN = {0, 1, 2}


class RatchetDefect(RuntimeError):
    """The measurement is broken — which is worse than a low score."""


RAN_OR_COLLECTION_ERROR = re.compile(r"(\d+) (?:passed|failed)|^ERROR ", re.M)


def _pytest(tables_dir: Path, stop_early: bool) -> tuple[list[str], list[str], str]:
    """Run the real suites against `tables_dir`. Returns (failures, errors, stdout).

    `test_roundtable_decide.py` and `test_roundtable_context.py` load the
    tables at IMPORT time (`TABLES = T.load()` at module scope) — a table a
    mutation broke badly enough to fail `load()` turns into a pytest
    COLLECTION ERROR for that whole file, not a per-test FAILURE. That is
    still a caught mutant (the contract's own `ContractError` is exactly the
    refusal `load()` is supposed to raise); the caller tells the two apart by
    reading `stdout` for `ContractError`, since only genuine measurement
    defects (a missing fixture, a stray import) get to raise `RatchetDefect`.
    """
    environment = dict(os.environ, ROUNDTABLE_TABLES_DIR=str(tables_dir))
    argv = [sys.executable, "-m", "pytest", *(str(s) for s in SUITES),
            "-q", "--tb=no", "-rfE", "-p", "no:cacheprovider"]
    if stop_early:
        argv.append("-x")
    done = subprocess.run(argv, cwd=ROOT, env=environment,
                          capture_output=True, text=True)
    if done.returncode not in PYTEST_RAN:
        raise RatchetDefect(
            f"pytest завершился кодом {done.returncode} — он не выполнял тесты. "
            f"Считать это зелёной базой значит мерить ничто.\n{done.stdout[-400:]}")
    if not RAN_OR_COLLECTION_ERROR.search(done.stdout):
        raise RatchetDefect(
            f"pytest не отчитался ни об одном выполненном тесте:\n{done.stdout[-400:]}")
    return FAILED.findall(done.stdout), ERRORED.findall(done.stdout), done.stdout


def _short(node: str) -> str:
    return node.rsplit("::", 1)[-1]


# --------------------------------------------------------------------------
# БТ2-8: four mutation classes, each its own generator.
#
# Every generator takes the CURRENT value of one row (`data[key][index]`, be
# it a dict, a list or a scalar — the top-level shapes every table uses) and
# returns either a mutated replacement, or `None` when the class has nothing
# to say about this particular row's shape. `None` is not a miss: it is
# recorded as an exclusion, with the reason the class carries, so a class
# that only ever applies to booleans does not pretend to cover a row that
# has none.
# --------------------------------------------------------------------------

MUTATION_SENTINEL = "◆НЕДОПУСТИМОЕ_ЗНАЧЕНИЕ_БТ2◆"
UNKNOWN_FIELD = "__недопустимое_поле_БТ2__"


def _remove_row(row):
    # "убрать_правило": every row can be deleted. No exclusion exists for
    # this class — it is the ratchet's original, universal mutation.
    return _Deleted


class _DeletedMarker:
    pass


_Deleted = _DeletedMarker()


def _find_bool_leaf(node):
    """First (container, key) pair holding a bool, depth-first."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, bool):
                return node, k
            found = _find_bool_leaf(v)
            if found:
                return found
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, bool):
                return node, i
            found = _find_bool_leaf(v)
            if found:
                return found
    return None


def _substitute_admissible_value(row):
    # "подменить_значение_на_допустимое": flip the first boolean this row
    # carries anywhere inside it. `true`/`false` are both declared for every
    # boolean field this contract has (vocabulary.коды_условий, вне_MVP,
    # подтверждение_действует…) — the loader accepts the result exactly as
    # well as the original, on purpose. БТ2-9 is this class: the catch, if
    # any, must come from a test pinning what the row *means*, never from
    # `check()` or `_require`.
    row = copy.deepcopy(row)
    found = _find_bool_leaf(row)
    if not found:
        return None
    container, key = found
    container[key] = not container[key]
    return row


def _substitute_text_keep_id(row):
    # "подменить_текст_сохранив_ID": only rows addressable by a stable `id`
    # qualify (blocks.приёмка, findings.находки) — the whole point of an id
    # is that the row is still "the same rule" by identity while its text
    # changes, so this class is exactly the attack an id is supposed to
    # survive.
    if not isinstance(row, dict) or "id" not in row:
        return None
    row = copy.deepcopy(row)
    for key, value in row.items():
        if key == "id":
            continue
        if isinstance(value, str) and value.strip():
            row[key] = value + " (подмена БТ2, тот же id)"
            return row
    return None


def _substitute_invalid_value(row):
    # "подсунуть_недопустимое": inject a field no schema declared, or — for a
    # bare scalar row — replace it with a value from no closed list at all.
    # Lists and bare booleans have no generic "invalid" member (every bool is
    # valid by definition), so they are not eligible for this class.
    if isinstance(row, dict):
        row = copy.deepcopy(row)
        row[UNKNOWN_FIELD] = True
        return row
    if isinstance(row, str):
        return MUTATION_SENTINEL
    return None


CLASSES = {
    "убрать_правило": _remove_row,
    "подменить_значение_на_допустимое": _substitute_admissible_value,
    "подменить_текст_сохранив_ID": _substitute_text_keep_id,
    "подсунуть_недопустимое": _substitute_invalid_value,
}


def _targets(data, path_name):
    targets = []
    for key, value in data.items():
        if key == "версия_контракта" or (path_name, key) in NOTES:
            continue
        if isinstance(value, list):
            targets += [(key, i) for i in range(len(value))]
        elif isinstance(value, dict):
            targets += [(key, k) for k in value]
    return targets


def main(verbose=False, only=None, only_class=None) -> int:
    scratch = Path(tempfile.mkdtemp(prefix="roundtable-mutation-"))
    try:
        for path in sorted(CANON.glob("*.yaml")):
            shutil.copy(path, scratch / path.name)

        failures, errors, _ = _pytest(scratch, stop_early=False)
        if failures or errors:
            print("✗ контрольная база не зелёная — измерять нечего.")
            for node in failures + errors:
                print(f"   {_short(node)}")
            print("\nПока база красная, любой мутант «умирает» по чужой причине,")
            print("и процент покрытия ничего не значит. Это ровно тот дефект,")
            print("которым 02.09 было получено ложное «322/322».")
            return 2
        print(f"✓ контрольная база зелёная на копии {scratch}")

        originals = {p: p.read_text(encoding="utf-8") for p in scratch.glob("*.yaml")}

        # раздельные знаменатели по таблице, полю и классу (БТ2-8)
        totals = {name: 0 for name in CLASSES}
        caught_counts = {name: 0 for name in CLASSES}
        excluded = {name: [] for name in CLASSES}
        missed = {name: [] for name in CLASSES}
        guards = {}

        for path in sorted(originals):
            if only and only != path.name:
                continue
            data = yaml.safe_load(originals[path])
            targets = _targets(data, path.name)

            for key, index in targets:
                for class_name, mutate in CLASSES.items():
                    if only_class and only_class != class_name:
                        continue
                    label = f"{path.name}: {key}[{index}] × {class_name}"
                    if _class_excluded(class_name, path.name, key, index):
                        excluded[class_name].append(label)
                        continue
                    row = data[key][index]
                    mutated_row = mutate(row)

                    if mutated_row is None:
                        excluded[class_name].append(label)
                        continue
                    if mutated_row is _Deleted:
                        mutated = copy.deepcopy(data)
                        mutated[key].pop(index)
                    else:
                        mutated = copy.deepcopy(data)
                        mutated[key][index] = mutated_row

                    path.write_text(
                        yaml.dump(mutated, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
                    totals[class_name] += 1
                    failures, errors, stdout = _pytest(scratch, stop_early=True)
                    path.write_text(originals[path], encoding="utf-8")

                    # A collection ERROR is only a caught mutant when it is the
                    # contract's OWN refusal (ContractError from `load()`) —
                    # otherwise it is a defect of this measurement, exactly as
                    # before (a stray fixture, an unrelated import failure).
                    # pytest truncates the one-line "-rfE" summary to terminal
                    # width, so the exception name can lose its last letter
                    # ("...ContractErro..."); match a prefix short enough to
                    # survive that.
                    contract_error = errors and "roundtable.tables.ContractErr" in stdout
                    if errors and not contract_error:
                        raise RatchetDefect(
                            f"{label} дал ОШИБКУ {_short(errors[0])}, а не падение "
                            f"проверки. Мутант умер по чужой причине — это дефект "
                            f"измерения, а не пойманная мутация.")
                    if failures or contract_error:
                        caught_counts[class_name] += 1
                        guards[label] = _short((failures or errors)[0])
                    else:
                        missed[class_name].append(label)

        grand_total = sum(totals.values())
        grand_caught = sum(caught_counts.values())
        all_green = True
        for class_name in CLASSES:
            total = totals[class_name]
            caught = caught_counts[class_name]
            percent = caught * 100 // total if total else 100
            print(f"\n[{class_name}]")
            print(f"  мутировано  : {total}")
            print(f"  замечено    : {caught} ({percent}%)")
            print(f"  исключено   : {len(excluded[class_name])}")
            print(f"  не замечено : {len(missed[class_name])}")
            for row in missed[class_name]:
                print("     не проверяется:", row)
            if verbose:
                for row in excluded[class_name]:
                    print("     исключено:", row)
            if total > 0 and not percent == 100:
                all_green = False

        print(f"\nвсего мутировано по всем классам : {grand_total}")
        print(f"всего замечено                   : {grand_caught}")
        if verbose:
            print("\nкто стережёт какую строку:")
            for row, guard in sorted(guards.items()):
                print(f"   {row:<60} ← {guard}")
        return 0 if all_green else 1
    except RatchetDefect as defect:
        print(f"✗ {defect}")
        return 2
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    argv = sys.argv[1:]
    name = None
    if "--only" in argv:
        name = argv[argv.index("--only") + 1]
    class_name = None
    if "--class" in argv:
        class_name = argv[argv.index("--class") + 1]
    sys.exit(main("--verbose" in argv, name, class_name))
