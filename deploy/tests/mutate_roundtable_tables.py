"""Measure how much of the Roundtable tables the tests actually look at.

A passing suite proves nothing about the rows it never reads. STC has already
been burned by that shape once: on 2026-07-29 a guard with no corpus printed
"skipping" and exited green. And through all ten review rounds of this very
design, 221 tests were green — they simply knew nothing about it.

So: delete one row at a time and see whether anything fails. A deletion nobody
notices is a row nobody checks.

    python3 deploy/tests/mutate_roundtable_tables.py [--verbose]

Not a test itself: it reloads the suite a few hundred times and belongs in a
deliberate run, not in every `pytest deploy/tests`.
"""

import copy
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TABLES = ROOT / "core" / "scripts" / "roundtable" / "tables"
SUITE = Path(__file__).with_name("test_roundtable_tables.py")

# Rows that state intent for a human rather than a rule for the engine. They
# are excluded from the denominator instead of being pinned by a change
# detector — a test that only notices edited prose is noise, and noise is how
# a suite stops being read.
NOTES = {
    ("blocks.yaml", "последовательные_из_за_общих_файлов"),
    ("blocks.yaml", "вне_порядка"),
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


def _run_suite():
    """True when at least one assertion fails."""
    spec = importlib.util.spec_from_file_location("rt_tables_probe", SUITE)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return True
    for name in dir(module):
        if not name.startswith("test_"):
            continue
        try:
            getattr(module, name)()
        except Exception:
            return True
    return False


def main(verbose=False):
    files = sorted(TABLES.glob("*.yaml"))
    original = {f: f.read_text(encoding="utf-8") for f in files}
    total = caught = 0
    missed = []

    try:
        for path in files:
            data = yaml.safe_load(original[path])
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
                path.write_text(
                    yaml.dump(mutated, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                total += 1
                if _run_suite():
                    caught += 1
                else:
                    missed.append(f"{path.name}: {key}[{index}]")
                path.write_text(original[path], encoding="utf-8")
    finally:
        for path, text in original.items():
            path.write_text(text, encoding="utf-8")

    percent = caught * 100 // total if total else 0
    print(f"rows deleted one at a time : {total}")
    print(f"noticed by the suite       : {caught} ({percent}%)")
    print(f"unnoticed                  : {len(missed)}")
    if verbose:
        for row in missed:
            print("   unchecked:", row)
    return 0 if percent >= 90 else 1


if __name__ == "__main__":
    sys.exit(main("--verbose" in sys.argv))
