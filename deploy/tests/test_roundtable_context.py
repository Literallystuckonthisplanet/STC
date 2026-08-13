"""Б2 — the package: the same bytes twice, and every path refusal named.

Guarantee 1 is the one this block carries: both critics got the same verifiable
package, proven by a hash. So the tests are about the two ways that guarantee
dies — a build that is not reproducible, and a manifest that lets something in
that was never declared.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "core" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from roundtable import context as C  # noqa: E402
from roundtable import tables as T  # noqa: E402

TABLES = T.load()
LIMITS = TABLES.vocabulary["пакет"]

SECTIONS = {"задача": "согласовать план", "ограничения": "недельный лимит",
            "критерий_успеха": "вердикт считает программа"}
REGISTRIES = {
    "решения": [{"decision_id": "D-2", "kind": "closed_decision",
                 "text_hash": "b" * 8, "status": "закрыто"},
                {"decision_id": "D-1", "kind": "framing",
                 "text_hash": "a" * 8, "status": "открыто"}],
    "области": [{"area_id": "A-2"}, {"area_id": "A-1"}],
    "журнал_доказательств": [],
}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "plan.md").write_text("# План\nстрока\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=нельзя\n", encoding="utf-8")
    return tmp_path


def _build(root, files=None, **kwargs):
    options = {"sections": SECTIONS, "registries": REGISTRIES, "stage": "план",
               "tables": TABLES}
    options.update(kwargs)
    return C.build_package(root, files or [("docs/plan.md", "existing_evidence")],
                           **options)


# --------------------------------------------------------------------------
# guarantee 1: two builds, one hash
# --------------------------------------------------------------------------

def test_two_builds_of_the_same_input_have_the_same_hash(root):
    first, second = _build(root), _build(root)
    assert first.hash == second.hash
    assert C.same_package(first, second)
    assert first.canonical_bytes == second.canonical_bytes


def test_the_package_carries_no_build_time_and_no_host_paths(root):
    # A timestamp is the one ingredient that would silently break guarantee 1,
    # and an absolute path would make the hash depend on whose machine built it.
    material = _build(root).material()
    assert str(root) not in material
    for token in ("собран", "build_at", "timestamp", "20260"):
        assert token not in material, token


def test_the_registries_are_ordered_so_the_caller_cannot_change_the_hash(root):
    shuffled = {
        "решения": list(reversed(REGISTRIES["решения"])),
        "области": list(reversed(REGISTRIES["области"])),
        "журнал_доказательств": [],
    }
    assert _build(root).hash == _build(root, registries=shuffled).hash


def test_changing_a_declared_file_changes_the_hash(root):
    before = _build(root).hash
    (root / "docs" / "plan.md").write_text("# План\nдругая строка\n", encoding="utf-8")
    assert _build(root).hash != before


def test_the_manifest_hash_covers_every_declared_file(root):
    (root / "docs" / "next.md").write_text("позже", encoding="utf-8")
    one = _build(root)
    two = _build(root, files=[("docs/plan.md", "existing_evidence"),
                              ("docs/next.md", "existing_evidence")])
    assert one.manifest_hash != two.manifest_hash
    assert len(two.manifest) == 2


def test_the_material_goes_out_as_text_and_matches_the_hashed_bytes(root):
    package = _build(root)
    assert package.material().encode("utf-8") == package.canonical_bytes
    assert C.digest(package.canonical_bytes) == package.hash


# --------------------------------------------------------------------------
# path refusals (§6.9) — one test per named reason
# --------------------------------------------------------------------------

def test_a_parent_traversal_is_refused(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("../secrets.md", "existing_evidence")])
    assert refused.value.reason == "путь_с_родительским_переходом"
    assert refused.value.reason in LIMITS["отвергается"]


def test_an_absolute_path_is_refused(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("/etc/hosts", "existing_evidence")])
    assert refused.value.reason == "путь_с_родительским_переходом"


def test_a_symlinked_file_is_refused(root):
    os.symlink(root / ".env", root / "docs" / "linked.md")
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/linked.md", "existing_evidence")])
    assert refused.value.reason == "симлинк"


def test_a_symlinked_parent_directory_is_refused_too(root):
    # The leaf can be perfectly innocent while a directory above it points out
    # of the root — checking only the final component would miss it.
    (root / "outside").mkdir()
    (root / "outside" / "plan.md").write_text("чужое", encoding="utf-8")
    os.symlink(root / "outside", root / "docs" / "linked")
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/linked/plan.md", "existing_evidence")])
    assert refused.value.reason == "симлинк"


def test_an_oversize_file_is_refused(root):
    big = "я" * (LIMITS["предел_файла_байт"] // 2 + 10)
    (root / "docs" / "big.md").write_text(big, encoding="utf-8")
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/big.md", "existing_evidence")])
    assert refused.value.reason == "превышение_размера"


def test_a_missing_existing_evidence_file_is_refused_but_planned_output_is_not(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/absent.md", "existing_evidence")])
    assert refused.value.reason == "отсутствие_обязательного_файла"

    package = _build(root, files=[("docs/absent.md", "planned_output")])
    assert package.manifest[0].sha256 is None, "a file created later has no hash yet"


def test_a_file_declared_twice_is_refused(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/plan.md", "existing_evidence"),
                            ("docs/plan.md", "existing_evidence")])
    assert refused.value.reason == "файл_объявлен_дважды"


def test_an_unknown_file_class_is_refused(root):
    with pytest.raises(C.PackageRefused):
        _build(root, files=[("docs/plan.md", "может_быть")])


def test_every_declared_refusal_reason_is_reachable():
    # A named reason nobody can produce is decoration; this pins the list to the
    # code that raises it.
    assert set(LIMITS["отвергается"]) == {
        "симлинк", "путь_с_родительским_переходом", "путь_вне_корня",
        "превышение_размера", "отсутствие_обязательного_файла"}


# --------------------------------------------------------------------------
# what never enters the package (§6.9)
# --------------------------------------------------------------------------

def test_the_sections_that_never_enter_are_refused_not_dropped(root):
    for name in LIMITS["не_попадает"]:
        with pytest.raises(C.PackageRefused) as refused:
            _build(root, sections={**SECTIONS, name: "что-то"})
        assert refused.value.reason == "раздел_вне_пакета", name


def test_the_registries_must_all_be_present(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, registries={"решения": [], "области": []})
    assert refused.value.reason == "реестры_не_полны"
    assert set(LIMITS["реестры"]) == {"решения", "области", "журнал_доказательств"}


def test_a_decision_of_an_unknown_kind_is_refused(root):
    bad = {**REGISTRIES, "решения": [{"decision_id": "D-9", "kind": "что-то",
                                      "text_hash": "c" * 8, "status": "открыто"}]}
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, registries=bad)
    assert refused.value.reason == "неизвестный_вид_решения"
    assert set(LIMITS["виды_решений_в_реестре"]) == {"closed_decision", "framing"}


# --------------------------------------------------------------------------
# evidence fingerprints (§6.1, round 10)
# --------------------------------------------------------------------------

SPAN = {"тип": "source_span", "создатель": "критик", "хеш_файла": "f" * 8,
        "путь": "docs/plan.md", "якорь": "ref:budget", "диапазон_строк": [10, 20]}
COMMAND = {"тип": "command_run", "создатель": "автор", "команда": "pytest -q",
           "версия_инструмента": "8.0", "хеш_редакции": "e" * 8,
           "код_возврата": 0, "хеш_вывода": "d" * 8}


def test_the_fingerprint_ignores_the_identifier_and_the_time(root):
    # Round 10: with the id in the fingerprint, re-sending the same span got a
    # fresh id and passed as new evidence.
    plain = C.fingerprint(SPAN, TABLES)
    decorated = C.fingerprint({**SPAN, "id": "EV-77", "время": "2026-08-13"}, TABLES)
    assert plain == decorated


def test_the_fingerprint_changes_when_the_content_does():
    assert C.fingerprint(SPAN, TABLES) != C.fingerprint({**SPAN, "якорь": "ref:scope"}, TABLES)
    assert C.fingerprint(COMMAND, TABLES) != C.fingerprint({**COMMAND, "код_возврата": 1}, TABLES)


def test_an_incomplete_or_unknown_evidence_record_is_refused():
    with pytest.raises(C.PackageRefused) as refused:
        C.fingerprint({"тип": "source_span", "путь": "docs/plan.md"}, TABLES)
    assert refused.value.reason == "неполное_доказательство"
    with pytest.raises(C.PackageRefused):
        C.fingerprint({"тип": "слухи"}, TABLES)


def test_a_critic_cannot_bring_an_executed_command(root):
    # The critic runs with --tools "": such a record is impossible, not merely
    # suspicious.
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, registries={**REGISTRIES,
                                 "журнал_доказательств": [{**COMMAND, "создатель": "критик"}]})
    assert refused.value.reason == "недопустимый_создатель_доказательства"


def test_the_evidence_journal_reaches_the_package_with_its_fingerprints(root):
    package = _build(root, registries={**REGISTRIES,
                                       "журнал_доказательств": [SPAN, COMMAND]})
    records = package.registries["журнал_доказательств"]
    assert {r["отпечаток"] for r in records} == {
        C.fingerprint(SPAN, TABLES), C.fingerprint(COMMAND, TABLES)}


# --------------------------------------------------------------------------
# the blind question (stages.yaml)
# --------------------------------------------------------------------------

def test_the_blind_package_hides_the_solution_and_nothing_else(root):
    shown = set(TABLES.stages["слепой_вопрос"]["показываем"])
    package = C.build_package(root, [("docs/plan.md", "existing_evidence")],
                              sections={name: "…" for name in shown},
                              registries=REGISTRIES, stage="идея", blind=True,
                              tables=TABLES)
    assert set(package.sections) == shown

    for hidden in TABLES.stages["слепой_вопрос"]["прячем"]:
        with pytest.raises(C.PackageRefused) as refused:
            C.build_package(root, [("docs/plan.md", "existing_evidence")],
                            sections={**{n: "…" for n in shown}, hidden: "…"},
                            registries=REGISTRIES, stage="идея", blind=True,
                            tables=TABLES)
        assert refused.value.reason in ("слепой_вопрос_показывает_лишнее",
                                        "раздел_вне_пакета"), hidden


def test_a_blind_question_is_refused_on_a_stage_that_does_not_ask_one(root):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, stage="план", blind=True)
    assert refused.value.reason == "слепой_вопрос_не_на_этой_стадии"
    assert TABLES.stages["стадии"]["план"]["первый_вопрос"] == "найди_непокрытое"


# --------------------------------------------------------------------------
# the limits are data
# --------------------------------------------------------------------------

def test_the_limits_come_from_the_table_and_not_from_the_module(tmp_path, root):
    import shutil

    import yaml
    directory = tmp_path / "tables"
    shutil.copytree(T.TABLES_DIR, directory)
    path = directory / "vocabulary.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["пакет"]["предел_файла_байт"] = 4
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    with pytest.raises(C.PackageRefused) as refused:
        _build(root, tables=T.load(directory))
    assert refused.value.reason == "превышение_размера"


def test_the_canonicalisation_rule_states_why_it_exists():
    assert "времени сборки" in LIMITS["канонизация"], (
        "the reason a build carries no timestamp must stay written down")
