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


def test_the_table_list_of_refusal_reasons_is_pinned():
    assert set(LIMITS["отвергается"]) == {
        "симлинк", "путь_с_родительским_переходом", "путь_вне_корня",
        "превышение_размера", "отсутствие_обязательного_файла"}


def test_every_refusal_reason_of_the_table_is_actually_produced(root, monkeypatch):
    produced = set()

    def attempt(files):
        try:
            _build(root, files=files)
        except C.PackageRefused as refused:
            produced.add(refused.reason)

    attempt([("../x.md", "existing_evidence")])
    os.symlink(root / ".env", root / "docs" / "l.md")
    attempt([("docs/l.md", "existing_evidence")])
    (root / "docs" / "big.md").write_text("я" * LIMITS["предел_файла_байт"], encoding="utf-8")
    attempt([("docs/big.md", "existing_evidence")])
    attempt([("docs/none.md", "existing_evidence")])
    real = Path.resolve
    monkeypatch.setattr(Path, "resolve",
                        lambda self, *a, **k: Path("/elsewhere") if self.name == "plan.md"
                        else real(self, *a, **k))
    attempt([("docs/plan.md", "existing_evidence")])
    monkeypatch.undo()
    assert produced == set(LIMITS["отвергается"])


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
    package = C.build_package(root, [],
                              sections={name: "…" for name in shown},
                              registries=REGISTRIES, stage="идея", blind=True,
                              tables=TABLES)
    assert set(package.sections) == shown

    for hidden in TABLES.stages["слепой_вопрос"]["прячем"]:
        with pytest.raises(C.PackageRefused) as refused:
            C.build_package(root, [],
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


# --------------------------------------------------------------------------
# review #12 / round 2: text in the package, one read, a snapshot
# --------------------------------------------------------------------------

import builtins  # noqa: E402
import io  # noqa: E402
import subprocess  # noqa: E402
import unicodedata  # noqa: E402


def _spy_every_read_path(monkeypatch, suffix):
    """Count every way of reaching the file's content."""
    hits = []
    real_os_open, real_open, real_io_open = os.open, builtins.open, io.open
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def note(path):
        if str(path).endswith(suffix):
            hits.append(str(path))

    def os_open(path, *a, **k):
        note(path)
        return real_os_open(path, *a, **k)

    def b_open(path, *a, **k):
        note(path)
        return real_open(path, *a, **k)

    def i_open(path, *a, **k):
        note(path)
        return real_io_open(path, *a, **k)

    monkeypatch.setattr(os, "open", os_open)
    monkeypatch.setattr(builtins, "open", b_open)
    monkeypatch.setattr(io, "open", i_open)
    monkeypatch.setattr(Path, "read_bytes", lambda s, *a, **k: (note(s), real_bytes(s, *a, **k))[1])
    monkeypatch.setattr(Path, "read_text", lambda s, *a, **k: (note(s), real_text(s, *a, **k))[1])
    return hits


def test_b2_1_the_file_is_read_once_by_any_path_and_the_package_lives_without_it(root, monkeypatch):
    hits = _spy_every_read_path(monkeypatch, "plan.md")
    package = _build(root)
    assert len(hits) == 1
    raw = (root / "docs" / "plan.md").read_bytes()
    assert package.manifest[0].sha256 == C.digest(raw)
    assert package.files["docs/plan.md"].encode("utf-8") == raw
    before = len(hits)
    (root / "docs" / "plan.md").unlink()
    assert "строка" in package.material() and package.hash == C.digest(package.canonical_bytes)
    assert len(hits) == before, "material() and hash must not touch the disk"


def test_b2_2_a_unique_marker_from_a_declared_file_reaches_the_material(root):
    (root / "docs" / "plan.md").write_text("МАРКЕР-ФАЙЛА-7731", encoding="utf-8")
    assert "МАРКЕР-ФАЙЛА-7731" in _build(root).material()


def test_b2_3_a_file_replaced_right_after_the_open_does_not_enter_the_package(root, monkeypatch):
    path = root / "docs" / "plan.md"
    original = path.read_text(encoding="utf-8")
    real = os.open
    opens = []

    def swapping(target, *args, **kwargs):
        descriptor = real(target, *args, **kwargs)
        if str(target) == "plan.md":
            opens.append(1)
            side = path.with_name("side.tmp")
            side.write_text("ПОДМЕНА", encoding="utf-8")
            os.replace(side, path)
        return descriptor

    monkeypatch.setattr(C.os, "open", swapping)
    package = _build(root)
    assert opens == [1]
    assert package.files["docs/plan.md"] == original
    assert "ПОДМЕНА" not in package.material()


def test_b2_3_a_change_after_the_build_does_not_change_the_built_package(root):
    package = _build(root)
    before = (package.hash, package.material())
    (root / "docs" / "plan.md").write_text("потом изменили", encoding="utf-8")
    assert (package.hash, package.material()) == before


def test_b2_3_a_file_that_is_not_text_is_refused(root):
    (root / "docs" / "bin.md").write_bytes(b"\xff\xfe\x00\x80")
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/bin.md", "existing_evidence")])
    assert refused.value.reason == "файл_не_текст"


def test_b2_3_a_directory_is_not_a_file_and_its_descriptor_is_closed(root, monkeypatch):
    closed, opened = [], []
    real_open, real_close = os.open, os.close

    def spy_open(*a, **k):
        descriptor = real_open(*a, **k)
        opened.append(descriptor)
        return descriptor

    def spy_close(descriptor):
        closed.append(descriptor)
        return real_close(descriptor)

    monkeypatch.setattr(C.os, "open", spy_open)
    monkeypatch.setattr(C.os, "close", spy_close)
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs", "existing_evidence")])
    assert refused.value.reason == "файл_не_обычный"
    assert opened and sorted(opened) == sorted(closed)


def test_b2_3_the_file_text_is_what_pushes_the_package_over_its_limit(tmp_path, root):
    import shutil

    import yaml
    base = len(_build(root, files=[("docs/absent.md", "planned_output")]).canonical_bytes)
    directory = tmp_path / "tables"
    shutil.copytree(T.TABLES_DIR, directory)
    path = directory / "vocabulary.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["пакет"]["предел_пакета_байт"] = base + 200
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    limited = T.load(directory)
    _build(root, files=[("docs/absent.md", "planned_output")], tables=limited)
    (root / "docs" / "long.md").write_text("д" * 150, encoding="utf-8")  # 300 bytes
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/long.md", "existing_evidence")], tables=limited)
    assert refused.value.reason == "превышение_размера"
    assert "пакет" in refused.value.detail


SHOWN = list(TABLES.stages["слепой_вопрос"]["показываем"])
HIDDEN = list(TABLES.stages["слепой_вопрос"]["прячем"])


def _blind(root, sections, files=()):
    return C.build_package(root, list(files), sections=sections,
                           registries=REGISTRIES, stage="идея", blind=True,
                           tables=TABLES)


def test_b2_4_the_blind_package_sections_equal_the_listed_set_exactly(root):
    assert set(_blind(root, {n: "…" for n in SHOWN}).sections) == set(SHOWN)


def test_b2_4_an_incomplete_blind_package_is_refused_by_name(root):
    for dropped in SHOWN:
        sections = {n: "…" for n in SHOWN if n != dropped}
        with pytest.raises(C.PackageRefused) as refused:
            _blind(root, sections)
        assert refused.value.reason == "слепой_пакет_неполон", dropped


def test_b2_4_a_blank_shown_section_counts_as_missing(root):
    for blank in ("", "   \n\t"):
        with pytest.raises(C.PackageRefused) as refused:
            _blind(root, {**{n: "…" for n in SHOWN}, SHOWN[0]: blank})
        assert refused.value.reason == "слепой_пакет_неполон"


def test_b2_5_a_blind_package_takes_no_artefact_files(root):
    with pytest.raises(C.PackageRefused) as refused:
        _blind(root, {n: "…" for n in SHOWN}, files=[("docs/plan.md", "existing_evidence")])
    assert refused.value.reason == "слепой_пакет_с_файлами"


def test_b2_5_the_author_decision_marker_never_reaches_the_blind_material(root):
    marker = "АВТОРСКОЕ-РЕШЕНИЕ-5521"
    (root / "docs" / "plan.md").write_text(marker, encoding="utf-8")
    assert HIDDEN, "the table must name what is hidden"
    for hidden in HIDDEN:
        with pytest.raises(C.PackageRefused) as refused:
            _blind(root, {**{n: "…" for n in SHOWN}, hidden: marker})
        assert refused.value.reason in ("слепой_вопрос_показывает_лишнее",
                                        "раздел_вне_пакета"), hidden
    with pytest.raises(C.PackageRefused) as refused:
        _blind(root, {n: "…" for n in SHOWN}, files=[("docs/plan.md", "existing_evidence")])
    assert refused.value.reason == "слепой_пакет_с_файлами"
    assert marker not in _blind(root, {n: "…" for n in SHOWN}).material()


def test_b2_6_the_package_with_file_text_is_byte_for_byte_reproducible(root):
    first, second = _build(root), _build(root)
    assert first.canonical_bytes == second.canonical_bytes
    assert first.material() == second.material()
    assert "файлы" in first.as_dict()


def test_b2_6_the_hash_does_not_depend_on_the_hash_seed(root):
    code = (
        "import sys;sys.path.insert(0, sys.argv[1]);"
        "from roundtable import context as C, tables as T;"
        "S={'задача':'a','ограничения':'b','критерий_успеха':'c'};"
        "R={'решения':[{'decision_id':'D-2','kind':'framing'},{'decision_id':'D-1','kind':'framing'}],"
        "'области':[{'area_id':'A-2'},{'area_id':'A-1'}],'журнал_доказательств':[]};"
        "print(C.build_package(sys.argv[2],[('docs/plan.md','existing_evidence')],S,R,'план',"
        "tables=T.load()).hash)")
    hashes = set()
    for seed in ("1", "2", "777"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        out = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(root)],
                             capture_output=True, text=True, env=env, timeout=180)
        assert out.returncode == 0, out.stderr
        hashes.add(out.stdout.strip())
    assert len(hashes) == 1


def test_the_declaration_order_does_not_change_the_hash(root):
    (root / "docs" / "next.md").write_text("позже", encoding="utf-8")
    one = [("docs/plan.md", "existing_evidence"), ("docs/next.md", "existing_evidence")]
    assert _build(root, files=one).hash == _build(root, files=one[::-1]).hash


# -- round 2: the descriptor walk and the named refusals --------------------

def _reason(root, files, **kwargs):
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=files, **kwargs)
    return refused.value.reason


def test_a_parent_swapped_for_a_symlink_after_the_early_check_is_still_refused(root, monkeypatch):
    outside = root.parent / (root.name + "_out")
    outside.mkdir()
    (outside / "plan.md").write_text("ЧУЖОЕ", encoding="utf-8")
    real = C._check_path

    def swap_after_check(r, relative):
        target = real(r, relative)
        import shutil
        shutil.rmtree(r / "docs")
        os.symlink(outside, r / "docs")
        return target

    monkeypatch.setattr(C, "_check_path", swap_after_check)
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "симлинк"


def test_a_leaf_swapped_for_a_symlink_after_the_early_check_is_refused(root, monkeypatch):
    real = C._check_path

    def swap_after_check(r, relative):
        target = real(r, relative)
        (r / relative).unlink()
        os.symlink(r / ".env", r / relative)
        return target

    monkeypatch.setattr(C, "_check_path", swap_after_check)
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "симлинк"


def test_a_hard_link_is_refused(root):
    os.link(root / ".env", root / "docs" / "hard.md")
    assert _reason(root, [("docs/hard.md", "existing_evidence")]) == "жёсткая_ссылка"


def test_a_fifo_is_refused_and_does_not_hang(root):
    os.mkfifo(root / "docs" / "pipe")
    import signal

    def alarm(*_):
        raise AssertionError("opening the FIFO hung")

    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(10)
    try:
        assert _reason(root, [("docs/pipe", "existing_evidence")]) == "файл_не_обычный"
    finally:
        signal.alarm(0)


def test_a_path_through_a_regular_file_is_a_named_refusal(root):
    assert _reason(root, [("docs/plan.md/x", "existing_evidence")]) == "файл_нечитаем"


def test_unreadable_paths_are_named_refusals_not_raw_errors(root):
    assert _reason(root, [("docs/" + "я" * 300, "existing_evidence")]) == "файл_нечитаем"
    assert _reason(root, [("docs/a\x00b.md", "existing_evidence")]) == "файл_нечитаем"
    locked = root / "docs" / "locked.md"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(0)
    try:
        if os.geteuid() != 0:
            assert _reason(root, [("docs/locked.md", "existing_evidence")]) == "файл_нечитаем"
    finally:
        locked.chmod(0o600)


@pytest.mark.parametrize("alias", ["docs//plan.md", "./docs/plan.md", "docs/./plan.md",
                                   "docs/plan.md/", "", "."])
def test_a_non_canonical_path_is_refused(root, alias):
    assert _reason(root, [(alias, "existing_evidence")]) == "путь_не_канонический"


def test_one_file_under_two_spellings_is_a_duplicate(root):
    composed = unicodedata.normalize("NFC", "é.md")
    decomposed = unicodedata.normalize("NFD", "é.md")
    (root / "docs" / composed).write_text("e", encoding="utf-8")
    both = [(f"docs/{composed}", "existing_evidence"), (f"docs/{decomposed}", "existing_evidence")]
    assert _reason(root, both) == "файл_объявлен_дважды"
    assert _reason(root, [("docs/plan.md", "existing_evidence"),
                          ("DOCS/PLAN.md", "existing_evidence")]) == "файл_объявлен_дважды"


def test_duplicate_ids_in_a_registry_are_refused(root):
    twice = {**REGISTRIES, "решения": [
        {"decision_id": "D-1", "kind": "framing"}, {"decision_id": "D-1", "kind": "framing"}]}
    assert _reason(root, None, registries=twice) == "дубль_в_реестре"
    twice = {**REGISTRIES, "области": [{"area_id": "A-1"}, {"area_id": "A-1"}]}
    assert _reason(root, None, registries=twice) == "дубль_в_реестре"


def test_equal_fingerprints_in_a_different_order_give_the_same_hash(root):
    one = {**SPAN, "id": "EV-1"}
    two = {**SPAN, "id": "EV-2"}
    first = _build(root, registries={**REGISTRIES, "журнал_доказательств": [one, two]})
    second = _build(root, registries={**REGISTRIES, "журнал_доказательств": [two, one]})
    assert first.hash == second.hash


def test_mutating_the_inputs_after_the_build_changes_nothing(root):
    sections = dict(SECTIONS)
    registries = {"решения": [dict(d) for d in REGISTRIES["решения"]],
                  "области": [dict(a) for a in REGISTRIES["области"]],
                  "журнал_доказательств": []}
    package = _build(root, sections=sections, registries=registries)
    before = (package.hash, package.material(), package.canonical_bytes)
    sections["задача"] = "ИЗМЕНЕНО"
    registries["решения"][0]["status"] = "ИЗМЕНЕНО"
    registries["области"].append({"area_id": "A-9"})
    assert (package.hash, package.material(), package.canonical_bytes) == before
    assert "ИЗМЕНЕНО" not in package.material()
    assert package.as_dict() == package.as_dict()
    assert package.as_dict() is not package.as_dict()


def test_unserialisable_nan_and_non_string_values_are_refused(root):
    bad = {**REGISTRIES, "решения": [{"decision_id": "D-1", "kind": "framing", "x": object()}]}
    assert _reason(root, None, registries=bad) == "некорректный_вход"
    bad = {**REGISTRIES, "решения": [{"decision_id": "D-1", "kind": "framing",
                                      "x": float("nan")}]}
    assert _reason(root, None, registries=bad) == "некорректный_вход"
    assert _reason(root, None, sections={**SECTIONS, "задача": 5}) == "некорректный_вход"
    assert _reason(root, None, sections={**SECTIONS, "задача": None}) == "некорректный_вход"


def test_malformed_containers_are_refused_by_name(root):
    assert _reason(root, "docs/plan.md") == "некорректный_вход"
    assert _reason(root, [("docs/plan.md",)]) == "некорректный_вход"
    assert _reason(root, [(Path("docs/plan.md"), "existing_evidence")]) == "некорректный_вход"
    assert _reason(root, [("docs/plan.md", 5)]) == "некорректный_вход"
    assert _reason(root, None, registries=[]) == "некорректный_вход"
    assert _reason(root, None, registries={**REGISTRIES, "решения": [5]}) == "некорректный_вход"
    assert _reason(root, None, registries={**REGISTRIES, "решения": [{"kind": "framing"}]}) == "некорректный_вход"
    assert _reason(root, None, registries={**REGISTRIES, "области": [{}]}) == "некорректный_вход"


def test_an_unknown_stage_is_refused_in_both_modes(root):
    assert _reason(root, None, stage="нет_такой") == "неизвестная_стадия"
    assert _reason(root, None, stage="нет_такой", blind=True) == "неизвестная_стадия"
