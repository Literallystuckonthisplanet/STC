"""Measure how much of the Roundtable tables the tests actually look at.

A passing suite proves nothing about the rows it never reads. STC has been
burned by that shape twice. On 2026-07-29 a guard with no corpus printed
"skipping" and exited green. And on 2026-09-02 **this very script** reported
`322/322 (100%)` while proving nothing at all: it called test functions by
hand, so a test taking a `tmp_path` fixture raised `TypeError` before any table
was read, the control base was already "failing", and every mutant was counted
as caught. A dead mutant is worthless unless you know *why* it died.

So the contract of this script is now:

* the tables are copied to a scratch directory — the canon is never written to,
  because `kill -9` mid-run used to leave the repository holding a corrupt table;
* the control base must be **green** before a single mutation is applied;
* each mutant runs the real `pytest`, not hand-called functions;
* a mutant counts as caught only when a test **fails**; a collection or fixture
  **error** is a defect of this script, not a caught mutation, and stops the run;
* the report names the test that caught each row, so "what protects this rule"
  is answerable instead of assumed.

    python3 deploy/tests/mutate_roundtable_tables.py [--verbose] [--only NAME]
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
SUITE = Path(__file__).with_name("test_roundtable_tables.py")

# Rows that state intent for a human rather than a rule for the engine. They
# are excluded from the denominator instead of being pinned by a change
# detector — a test that only notices edited prose is noise, and noise is how
# a suite stops being read.
NOTES = {
    ("blocks.yaml", "вне_порядка"),
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

FAILED = re.compile(r"^FAILED (\S+)", re.M)
ERRORED = re.compile(r"^ERROR (\S+)", re.M)
RAN = re.compile(r"(\d+) (?:passed|failed)")

# pytest: 0 всё прошло, 1 тесты упали. Всё остальное — процесс не сделал того,
# о чём его просили: 2 прерван, 3 внутренняя ошибка, 4 ошибка параметров,
# 5 не собрано ни одного теста. Раньше код возврата не читался вовсе, и ошибка
# запуска выглядела зелёной базой — тот же класс, что и всё «100 %» до этого.
PYTEST_RAN = {0, 1}


class RatchetDefect(RuntimeError):
    """The measurement is broken — which is worse than a low score."""


def _pytest(tables_dir: Path, stop_early: bool) -> tuple[list[str], list[str]]:
    """Run the real suite against `tables_dir`. Returns (failures, errors)."""
    environment = dict(os.environ, ROUNDTABLE_TABLES_DIR=str(tables_dir))
    argv = [sys.executable, "-m", "pytest", str(SUITE),
            "-q", "--tb=no", "-rfE", "-p", "no:cacheprovider"]
    if stop_early:
        argv.append("-x")
    done = subprocess.run(argv, cwd=ROOT, env=environment,
                          capture_output=True, text=True)
    if done.returncode not in PYTEST_RAN:
        raise RatchetDefect(
            f"pytest завершился кодом {done.returncode} — он не выполнял тесты. "
            f"Считать это зелёной базой значит мерить ничто.\n{done.stdout[-400:]}")
    if not RAN.search(done.stdout):
        raise RatchetDefect(
            f"pytest не отчитался ни об одном выполненном тесте:\n{done.stdout[-400:]}")
    return FAILED.findall(done.stdout), ERRORED.findall(done.stdout)


def _short(node: str) -> str:
    return node.rsplit("::", 1)[-1]


def main(verbose=False, only=None) -> int:
    scratch = Path(tempfile.mkdtemp(prefix="roundtable-mutation-"))
    try:
        for path in sorted(CANON.glob("*.yaml")):
            shutil.copy(path, scratch / path.name)

        failures, errors = _pytest(scratch, stop_early=False)
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
        total = caught = 0
        missed, guards = [], {}

        for path in sorted(originals):
            if only and only != path.name:
                continue
            data = yaml.safe_load(originals[path])
            targets = []
            for key, value in data.items():
                if key == "версия_контракта" or (path.name, key) in NOTES:
                    continue
                if isinstance(value, list):
                    targets += [(key, i) for i in range(len(value))]
                elif isinstance(value, dict):
                    targets += [(key, k) for k in value]

            for key, index in targets:
                mutated = copy.deepcopy(data)
                mutated[key].pop(index)
                path.write_text(yaml.dump(mutated, allow_unicode=True, sort_keys=False),
                                encoding="utf-8")
                total += 1
                failures, errors = _pytest(scratch, stop_early=True)
                path.write_text(originals[path], encoding="utf-8")

                if errors:
                    raise RatchetDefect(
                        f"{path.name}: {key}[{index}] дал ОШИБКУ {_short(errors[0])}, "
                        f"а не падение проверки. Мутант умер по чужой причине — "
                        f"это дефект измерения, а не пойманная мутация.")
                if failures:
                    caught += 1
                    guards[f"{path.name}: {key}[{index}]"] = _short(failures[0])
                else:
                    missed.append(f"{path.name}: {key}[{index}]")

        percent = caught * 100 // total if total else 0
        print(f"строк удалено по одной        : {total}")
        print(f"замечено проверками           : {caught} ({percent}%)")
        print(f"не замечено                   : {len(missed)}")
        for row in missed:
            print("   не проверяется:", row)
        if verbose:
            print("\nкто стережёт какую строку:")
            for row, guard in sorted(guards.items()):
                print(f"   {row:<52} ← {guard}")
        return 0 if percent == 100 else 1
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
    sys.exit(main("--verbose" in argv, name))
