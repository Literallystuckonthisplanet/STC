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

БТ2 rework (round of findings after the first commit) fixed five more ways
the measurement could report coverage that was not there, and named two rules
nothing was watching:

* a typo in `--only`/`--class` matched nothing, so the loop over zero targets
  finished with every class at "0 mutated, 100 %" and exit code 0 — a filter
  fixed the reference of nothing was passable as "measured everything".
  `main` now validates both against the real table names and `CLASSES` first,
  before touching a temp directory, and refuses with a non-zero exit;
* `_targets` only ever walked lists and dicts — a bare scalar top-level field
  (`precheck.yaml: общий_резолвер: отложен`) was never a mutation target at
  all, not even an excluded one. Flipping it to `готово` — declaring an
  admittedly-unbuilt shared resolver built — passed everything silently. Every
  top-level shape is a target now, scalars included, and one specific pin
  (`test_the_shared_resolver_status_is_pinned_until_it_actually_ships` in
  `test_roundtable_decide.py`) closes exactly that row;
* a mutation generator returning `None` looked identical whether the row was
  a deliberate exclusion or the generator itself had a bug — both `None`
  results printed the same. Every generator now returns `(value, reason)`;
  a `None` with an empty reason is a `RatchetDefect`, not a quiet miss;
* `CLASS_EXCLUSIONS` (below) was pinned by nothing outside this file — a line
  could be added or widened and "100 %" would still print. Its exact content
  is now pinned, by name, in `test_the_class_exclusions_are_named_and_nothing_
  more` (`test_roundtable_decide.py`) — the same "spell out every name" shape
  the findings registry uses, not a hash;
* a caught mutant that killed `load()` badly enough to abort collection was
  told apart from a genuine measurement defect by grepping pytest's own
  terminal-width-truncated summary line for `"ContractErr"` — fragile by the
  script's own admission in a comment. It now imports `roundtable.tables` and
  calls `load()` on the mutated copy IN THIS PROCESS, and checks the actual
  exception type;
* nothing addressed an outcome ENTRY inside a row's `исходы` list — a row was
  one target no matter how many outcomes it discriminated, so permuting which
  target which condition led to, *inside* one row, was invisible to every
  class. `_targets` now walks into `исходы` as its own addressable target,
  and `test_every_issue_and_framing_route_is_pinned_end_to_end`
  (`test_roundtable_decide.py`) pins the full `(из, событие, условия) → в`
  table for BOTH automata, not only `anton-decision`;
* the prose `условие` and the structural `событие`/`условия`/`исходы` of one
  row could drift apart with nothing noticing — DECIDED (see the block
  report): pin the pair literally in a test rather than invent a
  word-matching heuristic against free Russian text, which would be its own
  source of false confidence.

So the contract of this script is now:

* the tables are copied to a scratch directory — the canon is never written to,
  because `kill -9` mid-run used to leave the repository holding a corrupt table;
* the control base must be **green** before a single mutation is applied;
* each mutant runs the real `pytest`, against every suite file that reads the
  tables, not hand-called functions and not one file in isolation;
* a mutant counts as caught only when a test **fails**, or when a collection
  error is CONFIRMED (by loading the mutant in-process) to be the contract's
  own refusal — anything else is a defect of this script, not a caught
  mutation, and stops the run;
* the report names the test that caught each row, so "what protects this rule"
  is answerable instead of assumed;
* four mutation classes are tried (БТ2-8), not one — "delete the rule" catches
  a different defect than "swap it for another value the loader still
  accepts". Each class keeps its OWN denominator, broken down by table, field
  and outcome, because a class that cannot apply to a row (a boolean class on
  a row with no boolean, say) is an exclusion that needs its own stated
  reason — copying one class's reasons onto another would hide the difference
  between "nothing to mutate here" and "nobody is watching here".

R38-9 stays OPEN in this table, on purpose: `blocks.yaml:проверки_источников`
is excluded here with the note "already covered by an address guard", and the
finding says that reason expired — the row should be measured, not excluded.
Fixing it means editing `порядок_критики.вне_замера` in blocks.yaml AND the
parity check that pins `NOTES` against it
(`test_what_the_ratchet_does_not_measure_is_named` in
`test_roundtable_tables.py`) — both outside this block's five writable files.
The coordinator has taken this one to Anton separately; leave it as is.

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
SCRIPTS = ROOT / "core" / "scripts"

# БТ2-7 (closing R15-8): the tables, the executable-decide suite and the idea
# stage's own suite all read these tables; a mutation "dies" the moment ANY
# of the three notices, and all three must run so that death is credited.
SUITES = (
    Path(__file__).with_name("test_roundtable_tables.py"),
    Path(__file__).with_name("test_roundtable_decide.py"),
    Path(__file__).with_name("test_roundtable_context.py"),
)
SUITE = SUITES[0]  # alias kept for the existing suite that reads this name


def _module():
    """Import the real engine ONCE, so a caught mutant can be classified by
    the actual exception `load()` raises rather than by pattern-matching
    another program's terminal output (finding 5)."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import roundtable.tables
    return roundtable.tables


# Rows that state intent for a human rather than a rule for the engine. They
# are excluded from the denominator instead of being pinned by a change
# detector — a test that only notices edited prose is noise, and noise is how
# a suite stops being read.
NOTES = {
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

# Exclusions that hold for only ONE class, not all four — the whole point of
# per-class denominators (БТ2-8) is that a row can be genuinely covered
# against deletion while staying blind to a class that mutates it a
# different way, and pretending otherwise would hide exactly that gap.
#
# Finding 4: this dict is pinned BY NAME in
# test_the_class_exclusions_are_named_and_nothing_more (test_roundtable_decide.py) —
# spelled out one entry at a time, the same shape the findings registry uses,
# so a silently-added or silently-widened entry fails a test instead of
# passing "100 %" unnoticed. Full parity with blocks.yaml is impossible from
# here (R38-9); this is the parity this file CAN own.
CLASS_EXCLUSIONS = {
    "убрать_правило": {
        # `почему` (precheck.yaml) is prose explaining to a HUMAN why the
        # shared resolver is deferred; nothing reads its presence or its
        # text — deleting the key changes nothing any test or check inspects.
        # Its neighbour `общий_резолвер` (the actual status) is NOT excluded:
        # it is pinned by test_the_shared_resolver_status_is_pinned_until_
        # it_actually_ships (finding 2).
        ("precheck.yaml", "почему"):
            "проза для человека; ни один тест не читает наличие или текст поля",
    },
    "подменить_значение_на_допустимое": {
        # `коды_условий.run_finished` is the DECLARED ENUM ITSELF
        # ([true, false]) for a condition key no transition in run.yaml ever
        # reads (`test_closed_code_lists_are_pinned_whole` only pins the KEY
        # SET of `коды_условий`, never a key's own value list). Flipping the
        # first element in place ([true,false] → [false,false]) has nowhere
        # to surface: nothing computes combinations for `run_finished`
        # because nothing declares it as a condition on any transition.
        ("vocabulary.yaml", "коды_условий", "run_finished"):
            "run_finished — объявленный, но нигде не читаемый код условия; "
            "ни одна комбинация условий по нему не строится",
    },
    "подсунуть_недопустимое": {
        # `хранение` is read field-by-field by name (`FRAMING["хранение"][...]
        # ["срок"]`), never parsed against a closed set of keys — an extra
        # field next to the ones a test reads is invisible to every test that
        # exists, and to every check in tables.py. Deletion and the id/text
        # class still see this row; this one class does not.
        ("framing.yaml", "хранение"):
            "читается по конкретному полю (['срок']…), не по закрытому набору ключей",
        # `валидация` rows are joined into one string by `правило` and matched
        # with `in` (test_every_constrained_element_has_at_least_one_validation_
        # rule) — an unrecognised sibling key next to `правило`/`исход` is
        # never read by anything. Deletion IS read (it shortens the joined
        # string), so that class still measures this row.
        ("issues.yaml", "валидация"):
            "правило/исход читаются построчно; лишний соседний ключ не читает никто",
        # `классы_файлов` is checked by `set(...) == {"existing_evidence",
        # "planned_output"}` — the KEYS are pinned, the two description
        # strings are not read by anything. Deletion changes the key set and
        # is still caught.
        ("precheck.yaml", "классы_файлов"):
            "пинуются только ключи (set(...) ==); описание-строка не читается",
        # `фикстуры.не_смешивать_с` is checked by truthiness only
        # (`assert PRECHECK["фикстуры"]["не_смешивать_с"]`) — a REPLACEMENT
        # string is still truthy, so only THIS one field is blind; its
        # siblings (`каталог`, `эталон`, `правило`) are each pinned by
        # `.endswith(...)`/`in` and stay measured — the exclusion is scoped
        # to the one sub-key, not the whole `фикстуры` dict.
        ("precheck.yaml", "фикстуры", "не_смешивать_с"):
            "проверяется только истинностью значения; любая непустая строка проходит",
        # `почему` — see the `убрать_правило` exclusion above for the same
        # key: prose for a human, read by nothing.
        ("precheck.yaml", "почему"):
            "проза для человека; ни один тест не читает наличие или текст поля",
        # stages.yaml — every row here is read by specific-field assertions
        # (membership, truthiness, an exact string) in
        # test_roundtable_tables.py; none of the five sections is parsed
        # against a closed key set, so an extra field beside the ones a test
        # names is invisible to all of them. Deletion still lands on a named
        # field and is caught; this class is the one that is blind here.
        ("stages.yaml", "стадии", "идея"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "стадии", "план"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "стадии", "ревью"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "слепой_вопрос"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "сигнал_нежизнеспособности"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "метрика_цены_понимания"):
            "поля читаются по имени, а не строгой схемой строки",
        ("stages.yaml", "приоритет_расхода"):
            "поля читаются по имени, а не строгой схемой строки",
        # blocks.yaml — `_check_plan` (tables.py) and the plan-analysis tests
        # read these sections by NAMED sub-field (`entry["основание"]`,
        # `entry["дата"]`, `spec["блокирует"]`, `row["исполнитель"]`…), never
        # by closing the row's field set the way `Block.parse`/`_require`
        # does for `блоки` itself — an unrecognised sibling key is invisible
        # to every one of those reads. Deletion still removes a NAMED field
        # and is caught; this class alone is blind here.
        ("blocks.yaml", "заключения_ревью", 0):
            "читается по named-полям (основание, блоки…), не строгой схемой",
        ("blocks.yaml", "разрешения_исполнения", 0):
            "читается по named-полям (основание, scope_sha256…), не строгой схемой",
        ("blocks.yaml", "разрешения_исполнения", 1):
            "читается по named-полям (основание, scope_sha256…), не строгой схемой",
        ("blocks.yaml", "история_разрешений", 0):
            "читается по named-полям, не строгой схемой",
        ("blocks.yaml", "история_разрешений", 1):
            "читается по named-полям, не строгой схемой",
        ("blocks.yaml", "история_разрешений", 2):
            "читается по named-полям, не строгой схемой",
        ("blocks.yaml", "шлюзы", "ремонт_после_ревью_12"):
            "spec['блокирует']/['до_закрытия'] читаются по имени",
        ("blocks.yaml", "шлюзы", "изоляция_подтверждена"):
            "spec['блокирует']/['до_закрытия'] читаются по имени",
        ("blocks.yaml", "исполнение", "роли"):
            "читается по named-полям (row['исполнитель']…), не строгой схемой",
        ("blocks.yaml", "исполнение", "проверки"):
            "читается по named-полям, не строгой схемой",
        ("blocks.yaml", "сверка_записи", "код_движка"):
            "читается по named-полям, не строгой схемой",
        ("blocks.yaml", "порядок_критики", "почему"):
            "проза, объясняющая правило человеку, не разбирается движком",
        # vocabulary.yaml — `операции` is pinned only for the THREE names that
        # also appear in `операции_без_бюджета` (test_the_budget_exempt_
        # operations_are_named); the other eight are read only through
        # `len(...)` (test_declared_counts_match_the_lists_they_describe),
        # which a same-length substitution does not change.
        ("vocabulary.yaml", "операции", 2):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 4):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 5):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 6):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 7):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 8):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 9):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        ("vocabulary.yaml", "операции", 10):
            "не входит в операции_без_бюджета — единственную проверку по значению этого списка",
        # `схемы_контрактов` is checked only for disjointness with
        # `схемы_вне_контрактов` (one name, "precheck_frontmatter") and by
        # `len(...)` — no test reads any of these nine names by value.
        ("vocabulary.yaml", "схемы_контрактов", 0):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 1):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 2):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 3):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 4):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 5):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 6):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 7):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        ("vocabulary.yaml", "схемы_контрактов", 8):
            "проверяется только непересечением со схемы_вне_контрактов и длиной списка",
        # `попытка.почему` — prose for a human; the sibling fields
        # (`ключ`, `состояния`, `флаг_неопределённого_окна`) are each pinned
        # by value, this one is not.
        ("vocabulary.yaml", "попытка", "почему"):
            "проза для человека; ни один тест не читает содержимое поля",
        # `повтор_невалидного_ответа.порядок`/`.оба_невалидны` — checked by
        # truthiness only (`assert budget["порядок"]`); a replacement string
        # is still truthy. Their siblings are pinned by exact value.
        ("vocabulary.yaml", "повтор_невалидного_ответа", "порядок"):
            "проверяется только истинностью значения; любая непустая строка проходит",
        ("vocabulary.yaml", "повтор_невалидного_ответа", "оба_невалидны"):
            "проверяется только истинностью значения; любая непустая строка проходит",
        # findings.yaml — NEW gap this rework's scalar/nested walk surfaced,
        # NOT one of the seven named findings and NOT fixed here: every one
        # of the 135 `находки` rows is a bare dict with no `_require`-style
        # field closure (unlike `блоки`, `переходы`, `исходы` — each parsed
        # by a typed class in tables.py). An unrecognised sibling field next
        # to `id`/`круг`/`что`/`статус`/`критерий` is invisible to every test
        # and every check. findings.yaml is not among БТ2's five writable
        # files and this table's schema belongs to the block that owns the
        # findings registry — flagged in the block report, not fixed here.
        ("findings.yaml", "находки"):
            "находки — свободные словари без строгой схемы полей; чужая область (БК/учёт)",
    },
}


def _excluded_reason(class_name, path_name, path):
    """Longest-prefix match against `CLASS_EXCLUSIONS`, or `None`."""
    full = (path_name,) + path
    best = None
    for entry, reason in CLASS_EXCLUSIONS.get(class_name, {}).items():
        if full[:len(entry)] == entry and (best is None or len(entry) > len(best[0])):
            best = (entry, reason)
    return best[1] if best else None


FAILED = re.compile(r"^FAILED (\S+)", re.M)
ERRORED = re.compile(r"^ERROR (\S+)", re.M)

# pytest: 0 всё прошло, 1 тесты упали. 2 — "прерван"; с несколькими файлами
# аргументом это ЗАКОННЫЙ исход, когда один файл ловит мутацию коллекцией
# (module-scope `T.load()` в test_roundtable_decide.py/test_roundtable_context.py
# падает раньше первого теста) — сам этот файл всё равно "поймал", просто не
# падением теста, а ошибкой сбора. 3 внутренняя ошибка, 4 ошибка параметров,
# 5 не собрано ни одного теста остаются недопустимыми: процесс не сделал того,
# о чём его просили. Раньше код возврата не читался вовсе, и ошибка запуска
# выглядела зелёной базой — тот же класс, что и всё «100 %» до этого.
PYTEST_RAN = {0, 1, 2}
RAN_OR_COLLECTION_ERROR = re.compile(r"(\d+) (?:passed|failed)|^ERROR ", re.M)


class RatchetDefect(RuntimeError):
    """The measurement is broken — which is worse than a low score."""


def _pytest(tables_dir: Path, stop_early: bool) -> tuple[list[str], list[str]]:
    """Run the real suites against `tables_dir`. Returns (failures, errors)."""
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
    return FAILED.findall(done.stdout), ERRORED.findall(done.stdout)


def _is_contract_refusal(tables_dir: Path) -> bool:
    """Finding 5: classify a collection ERROR by loading the mutant IN THIS
    PROCESS and reading the real exception type — never by matching text in
    another process's (width-truncated) summary line."""
    module = _module()
    try:
        module.load(tables_dir)
    except module.ContractError:
        return True
    except Exception:
        return False
    return False


def _short(node: str) -> str:
    return node.rsplit("::", 1)[-1]


# --------------------------------------------------------------------------
# БТ2-8: four mutation classes, each its own generator.
#
# Every generator takes the CURRENT value of one target (`_get(data, path)` —
# a dict, a list, a list ITEM, an outcome entry, or a bare scalar; every shape
# `_targets` can address) and returns `(value, reason)`:
#   * `(new_value, None)` — the mutation applies; `new_value` may be the
#     `_Deleted` sentinel;
#   * `(None, "why not")` — this class has nothing to say about this
#     particular target's shape; `reason` is mandatory and is what the report
#     prints for the exclusion (finding 3 — an empty reason is a
#     `RatchetDefect`, not a silent miss).
# --------------------------------------------------------------------------

MUTATION_SENTINEL = "◆НЕДОПУСТИМОЕ_ЗНАЧЕНИЕ_БТ2◆"
UNKNOWN_FIELD = "__недопустимое_поле_БТ2__"


class _DeletedMarker:
    pass


_Deleted = _DeletedMarker()


def _remove_row(value):
    # "убрать_правило": every target can be deleted. No exclusion exists for
    # this class — it is the ratchet's original, universal mutation.
    return _Deleted, None


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


def _substitute_admissible_value(value):
    # "подменить_значение_на_допустимое": flip the first boolean this target
    # carries anywhere inside it. `true`/`false` are both declared for every
    # boolean field this contract has (vocabulary.коды_условий, вне_MVP,
    # подтверждение_действует…) — the loader accepts the result exactly as
    # well as the original, on purpose. БТ2-9 is this class: the catch, if
    # any, must come from a test pinning what the target *means*, never from
    # `check()` or `_require`.
    copied = copy.deepcopy(value)
    found = _find_bool_leaf(copied)
    if not found:
        return None, "в строке нет булева поля ни на одном уровне вложенности"
    container, key = found
    container[key] = not container[key]
    return copied, None


def _substitute_text_keep_id(value):
    # "подменить_текст_сохранив_ID": only targets addressable by a stable
    # `id` qualify (blocks.приёмка, findings.находки) — the whole point of an
    # id is that the row is still "the same rule" by identity while its text
    # changes, so this class is exactly the attack an id is supposed to
    # survive.
    if not isinstance(value, dict) or "id" not in value:
        return None, "строка не адресуется полем id"
    copied = copy.deepcopy(value)
    for key, sub in copied.items():
        if key == "id":
            continue
        if isinstance(sub, str) and sub.strip():
            copied[key] = sub + " (подмена БТ2, тот же id)"
            return copied, None
    return None, "у строки есть id, но нет соседнего текстового поля для подмены"


def _substitute_invalid_value(value):
    # "подсунуть_недопустимое": inject a field no schema declared, or — for a
    # bare scalar target — replace it with a value from no closed list at
    # all. Lists and bare booleans have no generic "invalid" member (every
    # bool is valid by definition), so they are not eligible for this class.
    if isinstance(value, dict):
        copied = copy.deepcopy(value)
        copied[UNKNOWN_FIELD] = True
        return copied, None
    if isinstance(value, str):
        return MUTATION_SENTINEL, None
    return None, "у булева/списка/числа нет обобщённого недопустимого значения"


CLASSES = {
    "убрать_правило": _remove_row,
    "подменить_значение_на_допустимое": _substitute_admissible_value,
    "подменить_текст_сохранив_ID": _substitute_text_keep_id,
    "подсунуть_недопустимое": _substitute_invalid_value,
}


# --------------------------------------------------------------------------
# Targets are PATHS — tuples of dict keys and list indices — not (key, index)
# pairs. Three things share this one walk now (finding 2, finding 6):
#   * a bare scalar top-level field is a target of its own (`(key,)`);
#   * a list/dict item is a target, as before (`(key, i)` / `(key, k)`);
#   * an OUTCOME inside a row's `исходы` list is its OWN target
#     (`(key, i, "исходы", j)`) — reordering which condition routes to which
#     `в`, inside one row, is now addressable and mutatable on its own,
#     instead of being invisible to every class because the row around it
#     still contained a legal decision code, still a legal state, and never
#     tripped `_require`.
# --------------------------------------------------------------------------

def _walk(value):
    """Yield path SUFFIXES under `value` (not including `value` itself)."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            yield (i,)
            if isinstance(item, dict) and isinstance(item.get("исходы"), list):
                for j in range(len(item["исходы"])):
                    yield (i, "исходы", j)
    elif isinstance(value, dict):
        for k in value:
            yield (k,)


def _targets(data, path_name):
    targets = []
    for key, value in data.items():
        if key == "версия_контракта" or (path_name, key) in NOTES:
            continue
        if isinstance(value, (list, dict)):
            for suffix in _walk(value):
                targets.append((key,) + suffix)
        else:
            targets.append((key,))
    return targets


def _get(data, path):
    node = data
    for part in path:
        node = node[part]
    return node


def _apply(data, path, new_value):
    """A deep-copied `data` with `path` replaced by `new_value` (or removed,
    for the `_Deleted` sentinel)."""
    mutated = copy.deepcopy(data)
    parent = mutated
    for part in path[:-1]:
        parent = parent[part]
    last = path[-1]
    if new_value is _Deleted:
        if isinstance(parent, list):
            parent.pop(last)
        else:
            del parent[last]
    else:
        parent[last] = new_value
    return mutated


def _run_generator(mutate, value, label):
    """Call one class's generator and enforce finding 3's rule: a miss
    (`None`) MUST carry a non-empty reason, or it is a defect of the
    generator, not an exclusion.

    Split out of `main` so this rule is testable on its own, without
    spawning a subprocess `pytest` over the whole suite — a test living in
    `test_roundtable_decide.py` that called `main()` directly would have
    that subprocess re-collect and re-run the very test that started it,
    recursively.
    """
    new_value, reason = mutate(value)
    # Круг 42 (R42-14): причина из одних пробелов проходила как настоящая —
    # тот же приём, что пустой ID цели в блоке прогона.
    if new_value is None and not (reason or "").strip():
        raise RatchetDefect(
            f"{label}: генератор класса вернул None без причины — это дефект "
            f"генератора, а не обоснованное исключение.")
    return new_value, reason


def _format(path_name, path, class_name):
    rendered = ""
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else part
    return f"{path_name}: {rendered} × {class_name}"


def main(verbose=False, only=None, only_class=None) -> int:
    # Finding 1: a typo in --only/--class used to filter out every table (or
    # every class), finish the loop over zero targets, and print "0 mutated,
    # 100 %" with exit code 0 — indistinguishable from a real, full pass.
    table_names = sorted(p.name for p in CANON.glob("*.yaml"))
    if only is not None and only not in table_names:
        print(f"✗ --only {only!r} не совпадает ни с одной таблицей: {table_names}")
        return 2
    if only_class is not None and only_class not in CLASSES:
        print(f"✗ --class {only_class!r} не совпадает ни с одним классом: {sorted(CLASSES)}")
        return 2

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

            for target_path in targets:
                for class_name, mutate in CLASSES.items():
                    if only_class and only_class != class_name:
                        continue
                    label = _format(path.name, target_path, class_name)

                    reason = _excluded_reason(class_name, path.name, target_path)
                    if reason is not None:
                        excluded[class_name].append((label, reason))
                        continue

                    value = _get(data, target_path)
                    new_value, gen_reason = _run_generator(mutate, value, label)

                    if new_value is None:
                        excluded[class_name].append((label, gen_reason))
                        continue

                    mutated = _apply(data, target_path, new_value)
                    path.write_text(
                        yaml.dump(mutated, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
                    totals[class_name] += 1
                    failures, errors = _pytest(scratch, stop_early=True)

                    # Finding 5: a collection ERROR only counts as caught once
                    # loading the STILL-MUTATED copy in THIS process raises
                    # the contract's own refusal — checked before the file is
                    # restored, and never by pattern-matching pytest's own
                    # (possibly truncated) summary text.
                    contract_refusal = bool(errors) and _is_contract_refusal(path.parent)
                    path.write_text(originals[path], encoding="utf-8")

                    if errors and not contract_refusal:
                        raise RatchetDefect(
                            f"{label} дал ОШИБКУ {_short(errors[0])}, а не падение "
                            f"проверки, и загрузка мутанта в этом процессе не "
                            f"подтвердила ContractError. Мутант умер по чужой "
                            f"причине — это дефект измерения, а не пойманная "
                            f"мутация.")
                    if failures or contract_refusal:
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
                for row, why in excluded[class_name]:
                    print(f"     исключено: {row} — {why}")
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
