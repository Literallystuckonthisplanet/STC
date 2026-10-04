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
                 "text_hash": "b" * 64, "status": "закрыто"},
                {"decision_id": "D-1", "kind": "framing",
                 "text_hash": "a" * 64, "status": "открыто"}],
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


SHOWN = list(TABLES.stages["слепой_вопрос"]["показываем"])
HIDDEN = list(TABLES.stages["слепой_вопрос"]["прячем"])
WITHHELD = {"предложенное_решение": "построить всё на очереди сообщений и воркерах фонового режима",
            "автор": "Лунтик", "второй_критик": "Бибигон"}
BLIND_REGISTRIES = {"решения": [{"decision_id": "D-2", "kind": "closed_decision",
                                 "text_hash": "b" * 64, "status": "закрыто"}],
                    "области": [{"area_id": "A-1"}], "журнал_доказательств": []}


def _blind(root, sections=None, files=(), withheld=WITHHELD, registries=BLIND_REGISTRIES):
    sections = {n: "общий контекст задачи" for n in SHOWN} if sections is None else sections
    return C.build_package(root, list(files), sections=sections, registries=registries,
                           stage="идея", blind=True, tables=TABLES, withheld=withheld)


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
                                      "text_hash": "c" * 64, "status": "открыто"}]}
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
    package = _blind(root)
    assert set(package.sections) == set(SHOWN)

    for hidden in HIDDEN:
        with pytest.raises(C.PackageRefused) as refused:
            _blind(root, sections={**{n: "…" for n in SHOWN}, hidden: "…"})
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
import dataclasses  # noqa: E402
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
    # Replaced between the open and the read: the package is refused by name —
    # neither the substitute nor a half-old file may enter it.
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "файл_изменился"
    assert opens == [1]
    assert original not in path.read_text(encoding="utf-8")


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
    (root / "docs" / "dir.md").mkdir()
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/dir.md", "existing_evidence")])
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
    data["пакет"]["предел_раздела_байт"] = base + 200
    data["пакет"]["предел_файла_байт"] = base + 200
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    limited = T.load(directory)
    _build(root, files=[("docs/absent.md", "planned_output")], tables=limited)
    (root / "docs" / "long.md").write_text("д" * 150, encoding="utf-8")  # 300 bytes
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/long.md", "existing_evidence")], tables=limited)
    assert refused.value.reason == "превышение_размера"
    assert "пакет" in refused.value.detail


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
        "R={'решения':[{'decision_id':'D-2','kind':'framing','text_hash':'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','status':'x'},{'decision_id':'D-1','kind':'framing','text_hash':'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','status':'y'}],"
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
    os.mkfifo(root / "docs" / "pipe.md")
    import signal

    def alarm(*_):
        raise AssertionError("opening the FIFO hung")

    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(10)
    try:
        assert _reason(root, [("docs/pipe.md", "existing_evidence")]) == "файл_не_обычный"
    finally:
        signal.alarm(0)


def test_a_path_through_a_regular_file_is_a_named_refusal(root):
    assert _reason(root, [("docs/plan.md/x.md", "existing_evidence")]) == "файл_нечитаем"


def test_unreadable_paths_are_named_refusals_not_raw_errors(root):
    assert _reason(root, [("docs/" + "я" * 300 + ".md", "existing_evidence")]) == "файл_нечитаем"
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
        {"decision_id": "D-1", "kind": "framing", "text_hash": "a" * 64, "status": "x"},
        {"decision_id": "D-1", "kind": "framing", "text_hash": "b" * 64, "status": "y"}]}
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
    bad = {**REGISTRIES, "решения": [{"decision_id": "D-1", "kind": "framing", "text_hash": object(), "status": "x"}]}
    assert _reason(root, None, registries=bad) == "запись_вне_схемы"
    bad = {**REGISTRIES, "решения": [{"decision_id": "D-1", "kind": "framing",
                                      "text_hash": float("nan"), "status": "x"}]}
    assert _reason(root, None, registries=bad) == "запись_вне_схемы"
    with pytest.raises(C.PackageRefused) as refused:
        C.canonical_json({"x": float("nan")})
    assert refused.value.reason == "некорректный_вход"
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


# --------------------------------------------------------------------------
# round 3: the rules live in the table (Б2-7 ... Б2-10) and the audit leftovers
# --------------------------------------------------------------------------

import shutil  # noqa: E402
import sys as _sys  # noqa: E402,F401
import time  # noqa: E402
import types  # noqa: E402

import yaml  # noqa: E402

from roundtable import state as S  # noqa: E402


def _tables_with(tmp_path, **changes):
    """The real tables with some `пакет` rules replaced: proof that code reads data."""
    directory = tmp_path / "tables"
    shutil.copytree(T.TABLES_DIR, directory)
    path = directory / "vocabulary.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["пакет"].update(changes)
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return T.load(directory)


def _decision(**fields):
    return {**{"decision_id": "D-1", "kind": "closed_decision", "text_hash": "a" * 64,
               "status": "закрыто"}, **fields}


def _with(registries=None, **parts):
    return {**(registries or REGISTRIES), **parts}


# -- Б2-7: closed schemas of registry records --------------------------------

def test_b2_7_a_decision_with_a_missing_or_extra_field_is_refused(root):
    complete = _decision()
    for field_name in complete:
        broken = {k: v for k, v in complete.items() if k != field_name}
        expected = "некорректный_вход" if field_name == "decision_id" else "запись_вне_схемы"
        assert _reason(root, None, registries=_with(решения=[broken])) == expected, field_name
    assert _reason(root, None, registries=_with(решения=[_decision(лишнее="x")])) == "запись_вне_схемы"


def test_b2_7_an_area_with_an_extra_or_missing_field_is_refused(root):
    assert _reason(root, None, registries=_with(области=[{"area_id": "A-1", "x": 1}])) == "запись_вне_схемы"
    assert _reason(root, None, registries=_with(области=[{}])) == "некорректный_вход"


def test_b2_7_journal_records_need_the_common_and_the_fingerprint_fields(root):
    ok = _build(root, registries=_with(журнал_доказательств=[{**SPAN, "id": "EV-1", "время": "t"}]))
    assert len(ok.registries["журнал_доказательств"]) == 1
    for field_name in SPAN:
        broken = {k: v for k, v in SPAN.items() if k != field_name}
        expected = "некорректный_вход" if field_name == "тип" else "запись_вне_схемы"
        assert _reason(root, None, registries=_with(журнал_доказательств=[broken])) == expected, field_name
    assert _reason(root, None, registries=_with(журнал_доказательств=[{**SPAN, "чужое": 1}])) == "запись_вне_схемы"


def test_b2_7_the_schema_is_read_from_the_table_not_from_the_module(tmp_path, root):
    schemas = dict(TABLES.vocabulary["пакет"]["схемы_записей"])
    wider = _tables_with(tmp_path, схемы_записей={**schemas, "области": ["area_id", "title"]})
    assert _reason(root, None, registries=_with(области=[{"area_id": "A-1"}]),
                   tables=wider) == "запись_вне_схемы"
    ok = _build(root, registries=_with(области=[{"area_id": "A-1", "title": "t"}]), tables=wider)
    assert ok.registries["области"] == [{"area_id": "A-1", "title": "t"}]
    optional = _tables_with(tmp_path / "b", схемы_записей={**schemas, "журнал_необязательные": ["id"]})
    assert _reason(root, None, registries=_with(журнал_доказательств=[{**SPAN, "время": "t"}]),
                   tables=optional) == "запись_вне_схемы"


# -- Б2-8: a blind package carries no trace of what is hidden ----------------

def test_b2_8_the_blind_package_needs_the_withheld_texts_with_exactly_the_hidden_names(root):
    assert _blind(root).hash
    assert _reason_blind(root, withheld=None) == "некорректный_вход"
    assert _reason_blind(root, withheld={k: v for k, v in WITHHELD.items() if k != "автор"}) == "некорректный_вход"
    assert _reason_blind(root, withheld={**WITHHELD, "лишний": "x"}) == "некорректный_вход"
    assert _reason_blind(root, withheld={**WITHHELD, "автор": 5}) == "некорректный_вход"


def _reason_blind(root, **kwargs):
    with pytest.raises(C.PackageRefused) as refused:
        _blind(root, **kwargs)
    return refused.value.reason


def test_b2_8_registries_in_the_blind_mode_show_only_closed_decisions(root):
    assert TABLES.vocabulary["пакет"]["видимые_слепому_статусы_решений"] == ["закрыто"]
    open_one = _with(BLIND_REGISTRIES, решения=[_decision(status="открыто")])
    assert _reason_blind(root, registries=open_one) == "слепой_пакет_след_скрытого"


def test_b2_8_journal_records_in_the_blind_mode_come_only_from_the_precheck(root):
    allowed = {**SPAN, "создатель": "предпроверка"}
    assert _blind(root, registries=_with(BLIND_REGISTRIES, журнал_доказательств=[allowed])).hash
    for creator in ("критик", "автор"):
        broken = _with(BLIND_REGISTRIES, журнал_доказательств=[{**SPAN, "создатель": creator}])
        assert _reason_blind(root, registries=broken) == "слепой_пакет_след_скрытого", creator


LONG_TRACE = WITHHELD["предложенное_решение"]


SOLUTION = WITHHELD["предложенное_решение"]
PLAIN = {n: "общий контекст задачи" for n in SHOWN}
PRE = {**SPAN, "создатель": "предпроверка"}


def _traced(root, **kwargs):
    with pytest.raises(C.PackageRefused) as refused:
        _blind(root, **kwargs)
    assert refused.value.reason == "слепой_пакет_след_скрытого", refused.value
    return refused.value


@pytest.mark.parametrize("channel", ["section", "decision_id", "area_id", "anchor_multiline",
                                     "command", "hash_of_the_hidden_text"])
def test_b2_8_a_trace_is_found_in_every_channel_and_the_refusal_names_it(root, channel):
    slug = "построить_всё_на_очереди_сообщений_и_воркерах"
    sections, registries = dict(PLAIN), BLIND_REGISTRIES
    if channel == "section":
        sections[SHOWN[0]] = f"Контекст. {SOLUTION}. Конец."
    elif channel == "decision_id":
        registries = _with(BLIND_REGISTRIES, решения=[_decision(decision_id=slug)])
    elif channel == "area_id":
        registries = _with(BLIND_REGISTRIES, области=[{"area_id": slug}])
    elif channel == "anchor_multiline":
        anchor = "ref:\n" + SOLUTION[:20] + "\n" + SOLUTION[20:]
        registries = _with(BLIND_REGISTRIES, журнал_доказательств=[{**PRE, "якорь": anchor}])
    elif channel == "command":
        command = {"тип": "command_run", "создатель": "предпроверка", "команда": SOLUTION,
                   "версия_инструмента": "1", "хеш_редакции": "e" * 8, "код_возврата": 0,
                   "хеш_вывода": "d" * 8}
        registries = _with(BLIND_REGISTRIES, журнал_доказательств=[command])
    else:
        registries = _with(BLIND_REGISTRIES,
                           решения=[_decision(text_hash=C.digest(SOLUTION.encode("utf-8")))])
    error = _traced(root, sections=sections, registries=registries)
    assert SOLUTION not in str(error) and SOLUTION[:20] not in error.detail
    expected = {"section": "раздел.", "hash_of_the_hidden_text": "реестр.решения",
                "decision_id": "реестр.решения", "area_id": "реестр.области"}.get(channel, "реестр.журнал")
    assert error.detail.startswith(expected), error.detail


@pytest.mark.parametrize("disguise", [
    lambda s: s.upper(),
    lambda s: s.replace(" ", "\u00a0\u00a0"),
    lambda s: "\u200b".join(s),                                  # zero-width space between all letters
    lambda s: s.translate(str.maketrans("оеарсх", "oeapcx")),     # Latin look-alikes
    lambda s: s.replace("всё", "все"),
    lambda s: s.replace(" ", " «--» "),                           # quotes and punctuation
    lambda s: s.replace("очереди", "оче-\nреди"),                 # hyphenated line break
    lambda s: "".join(chr(ord(c) + 0xFEE0) if "a" <= c <= "z" else c for c in s) + s,
], ids=["upper", "nbsp", "zero-width", "look-alikes", "yo", "punctuation", "hyphen-wrap", "tail"])
def test_b2_8_the_trace_survives_every_cosmetic_disguise(root, disguise):
    sections = dict(PLAIN)
    sections[SHOWN[1]] = disguise(SOLUTION)
    _traced(root, sections=sections)


def test_b2_8_a_trace_glued_from_short_pieces_through_separators_is_found(root):
    sections = dict(PLAIN)
    sections[SHOWN[0]] = SOLUTION[:25] + " | "
    sections[SHOWN[1]] = "| " + SOLUTION[25:50]
    _traced(root, sections=sections)


@pytest.mark.parametrize("shown", [
    "решил Лунтика назначить", "решил ЛУНТИКУ поручить", "by_luntik_v2", "авторЛунтик",
    "Лyнтик", "Лун\u200bтик", "Л-у-н-т-и-к", "лунтик‑ов"])
def test_b2_8_a_short_hidden_name_is_found_by_its_stem(root, shown):
    hidden = {**WITHHELD, "автор": "Luntik" if shown == "by_luntik_v2" else "Лунтик"}
    sections = dict(PLAIN)
    sections[SHOWN[0]] = shown
    _traced(root, sections=sections, withheld=hidden)


def test_b2_8_the_stem_length_is_a_rule_of_the_table(tmp_path, root):
    sections = {**PLAIN, SHOWN[0]: "это Лунтовый случай"}
    _traced(root, sections=sections)  # the 4-character stem "лунт" of "Лунтик"
    longer = _tables_with(tmp_path, мин_длина_основы=6)
    assert C.build_package(root, [], sections, BLIND_REGISTRIES, "идея", blind=True,
                           tables=longer, withheld=WITHHELD).hash


@pytest.mark.parametrize("empty", ["", "   ", "!!! ...", "\u200b\u200b", "а"])
def test_b2_8_a_hidden_text_with_nothing_to_compare_is_refused_not_skipped(root, empty):
    for name in HIDDEN:
        with pytest.raises(C.PackageRefused) as refused:
            _blind(root, withheld={**WITHHELD, name: empty})
        assert refused.value.reason == "некорректный_вход", name
    assert _reason_blind(root, withheld={}) == "некорректный_вход"


def test_b2_8_ordinary_legitimate_input_is_not_refused(root):
    sections = {SHOWN[0]: "Согласовать план недели и проверить лимиты запросов к модели",
                SHOWN[1]: "Недельный лимит и бюджет на круг проверки",
                SHOWN[2]: "Вердикт считает программа, а не критик",
                SHOWN[3]: "Решение D-2 закрыто"}
    assert _blind(root, sections=sections).hash


def test_b2_8_the_trace_length_is_a_rule_of_the_table(tmp_path, root):
    sections = {n: "общий контекст задачи" for n in SHOWN}
    sections[SHOWN[0]] = "очереди сообщений и воркерах"  # 28 normalised chars
    assert _blind(root, sections=sections).hash  # below the shipped 40
    strict = _tables_with(tmp_path, мин_длина_следа=20)
    with pytest.raises(C.PackageRefused) as refused:
        C.build_package(root, [], sections, BLIND_REGISTRIES, "идея", blind=True,
                        tables=strict, withheld=WITHHELD)
    assert refused.value.reason == "слепой_пакет_след_скрытого"


def test_b2_8_the_hidden_texts_never_enter_the_material(root):
    material = _blind(root).material()
    for text in WITHHELD.values():
        assert text not in material


# -- Б2-9: which paths and which section names may enter ---------------------

@pytest.mark.parametrize("path", [".git/config", ".claude/settings.md", "CLAUDE.md", "docs/AGENTS.md",
                                  ".env", ".env.local", "docs/server.PEM", "keys/tls.key",
                                  ".GIT/config", ".codex/x.md", "sub/.git/HEAD"])
def test_b2_9_service_and_secret_paths_never_enter(root, path):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("секрет", encoding="utf-8")
    assert _reason(root, [(path, "existing_evidence")]) == "путь_запрещён"
    assert _reason(root, [(path, "planned_output")]) == "путь_запрещён"


def test_b2_9_the_forbidden_list_comes_from_the_table(tmp_path, root):
    (root / "docs" / "notes.txt").write_text("x", encoding="utf-8")
    assert _build(root, files=[("docs/notes.txt", "existing_evidence")]).files
    stricter = _tables_with(tmp_path, запрещённые_пути=[*TABLES.vocabulary["пакет"]["запрещённые_пути"], "*.txt"])
    assert _reason(root, [("docs/notes.txt", "existing_evidence")], tables=stricter) == "путь_запрещён"


def test_b2_9_a_build_root_inside_the_runs_directory_is_refused(root, monkeypatch):
    monkeypatch.setattr(S, "RUNS_ROOT", root.parent)
    assert _reason(root, None) == "путь_запрещён"
    monkeypatch.setattr(S, "RUNS_ROOT", root / "elsewhere")
    assert _build(root).hash


def test_b2_9_section_names_are_a_closed_list(root):
    assert _reason(root, None, sections={**SECTIONS, "придуманный": "x"}) == "раздел_неизвестен"
    assert set(TABLES.stages["слепой_вопрос"]["показываем"]) <= set(LIMITS["разделы"])
    assert not set(LIMITS["разделы"]) & set(LIMITS["не_попадает"])
    # the author and the second critic are data of `withheld`, never sections
    for name in ("автор", "второй_критик"):
        assert name not in LIMITS["разделы"]
        assert _reason(root, None, sections={**SECTIONS, name: "x"}) == "раздел_неизвестен"


def test_b2_9_a_section_value_is_a_non_empty_string_within_the_limit(tmp_path, root):
    assert _reason(root, None, sections={**SECTIONS, "задача": "  \n"}) == "некорректный_вход"
    small = _tables_with(tmp_path, предел_раздела_байт=60)
    assert _reason(root, None, sections={**SECTIONS, "задача": "я" * 31}, tables=small) == "превышение_размера"
    assert _build(root, sections={**SECTIONS, "задача": "я" * 30}, tables=small).hash


def test_b2_9_the_number_of_files_is_limited_by_the_table(tmp_path, root):
    (root / "docs" / "two.md").write_text("2", encoding="utf-8")
    two = [("docs/plan.md", "existing_evidence"), ("docs/two.md", "existing_evidence")]
    assert _build(root, files=two).hash
    one_only = _tables_with(tmp_path, предел_числа_файлов=1)
    assert _reason(root, two, tables=one_only) == "слишком_много_файлов"


def test_b2_9_the_package_size_is_counted_while_reading_and_stops_early(tmp_path, root, monkeypatch):
    for index in range(3):
        (root / "docs" / f"f{index}.md").write_text("я" * 75, encoding="utf-8")  # 150 bytes each
    small = _tables_with(tmp_path, предел_файла_байт=200, предел_пакета_байт=280,
                         предел_раздела_байт=100)
    opened = []
    real = os.open
    monkeypatch.setattr(C.os, "open", lambda p, *a, **k: (opened.append(str(p)), real(p, *a, **k))[1])
    files = [(f"docs/f{i}.md", "existing_evidence") for i in range(3)]
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=files, tables=small)
    assert refused.value.reason == "превышение_размера" and "файлы" in refused.value.detail
    assert "f2.md" not in opened, "the third file must not be read once the budget is gone"


# -- Б2-10: the named refusals and the immutable snapshot ---------------------

def test_b2_10_every_structural_refusal_has_its_own_name(root):
    os.link(root / ".env", root / "docs" / "hard.md")
    os.mkfifo(root / "docs" / "pipe.md")
    assert _reason(root, [("docs/hard.md", "existing_evidence")]) == "жёсткая_ссылка"
    assert _reason(root, [("docs/pipe.md", "existing_evidence")]) == "файл_не_обычный"
    assert _reason(root, [("docs//plan.md", "existing_evidence")]) == "путь_не_канонический"
    assert _reason(root, [("docs/plan.md", "existing_evidence"),
                          ("Docs/Plan.md", "existing_evidence")]) == "файл_объявлен_дважды"


def test_b2_10_the_package_is_an_immutable_snapshot(root):
    package = _build(root, files=[("docs/plan.md", "existing_evidence")])
    before = (package.hash, package.material())
    package.sections["задача"] = "ИЗМЕНЕНО"
    package.files["docs/plan.md"] = "ИЗМЕНЕНО"
    package.registries["решения"].clear()
    package.manifest.clear()
    package.as_dict()["стадия"] = "ИЗМЕНЕНО"
    assert package.sections["задача"] == SECTIONS["задача"]
    assert package.files["docs/plan.md"].startswith("# План")
    assert len(package.registries["решения"]) == 2
    assert len(package.manifest) == 1
    assert (package.hash, package.material()) == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        package.stage = "другая"
    with pytest.raises(dataclasses.FrozenInstanceError):
        package._bytes = b"x"


# -- audit leftovers 7 ... 11 --------------------------------------------------

def test_audit_7_a_hard_link_race_never_leaks_a_secret(tmp_path_factory, root):
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.txt"
    secret.write_text("СЕКРЕТ-ГОНКИ-9917", encoding="utf-8")
    (root / "docs" / "race.md").write_text("законное", encoding="utf-8")
    attacker = (
        "import os,sys\n"
        "root,secret=sys.argv[1:3]\n"
        "d=root+'/docs'\n"
        "while not os.path.exists(root+'/STOP'):\n"
        "    try:\n"
        "        os.link(secret,d+'/t.tmp'); os.replace(d+'/t.tmp',d+'/race.md')\n"
        "        open(d+'/w.tmp','w').write('законное'); os.replace(d+'/w.tmp',d+'/race.md')\n"
        "    except OSError:\n"
        "        pass\n")
    process = subprocess.Popen([sys.executable, "-c", attacker, str(root), str(secret)])
    built = refused = 0
    try:
        deadline = time.time() + 4
        while time.time() < deadline:
            try:
                package = _build(root, files=[("docs/race.md", "existing_evidence")])
            except C.PackageRefused:
                refused += 1
                continue
            built += 1
            assert "СЕКРЕТ-ГОНКИ-9917" not in package.material()
    finally:
        (root / "STOP").write_text("", encoding="utf-8")
        process.wait(timeout=20)
    assert built + refused > 20, "the race loop did not actually run"


def test_audit_7_a_file_unlinked_during_the_read_is_refused(root, monkeypatch):
    real = os.read

    def read_then_unlink(descriptor, size):
        data = real(descriptor, size)
        (root / "docs" / "plan.md").unlink(missing_ok=True)
        return data

    monkeypatch.setattr(C.os, "read", read_then_unlink)
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "файл_изменился"


def test_audit_8_a_component_on_another_device_is_outside_the_root(root, monkeypatch):
    real = os.fstat
    calls = []

    def spoof(descriptor):
        info = real(descriptor)
        calls.append(info.st_dev)
        if len(calls) == 2:  # the first call is the root, the second is `docs`
            fields = list(info)
            fields[2] = info.st_dev + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(C.os, "fstat", spoof)
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "путь_вне_корня"


def test_audit_9_the_last_component_is_opened_without_a_controlling_terminal(root, monkeypatch):
    flags = []
    real = os.open
    monkeypatch.setattr(C.os, "open", lambda p, f, *a, **k: (flags.append((str(p), f)), real(p, f, *a, **k))[1])
    _build(root)
    leaf = [f for name, f in flags if name == "plan.md"]
    assert leaf and all(f & os.O_NOCTTY and f & os.O_NOFOLLOW and f & os.O_NONBLOCK for f in leaf)


def test_audit_10_every_component_must_be_spelled_exactly_as_the_disk_spells_it(root):
    assert _reason(root, [("DOCS/plan.md", "existing_evidence")]) == "путь_не_канонический"
    assert _reason(root, [("docs/PLAN.MD", "existing_evidence")]) == "путь_не_канонический"
    composed = unicodedata.normalize("NFC", "é.md")
    (root / "docs" / composed).write_text("e", encoding="utf-8")
    decomposed = unicodedata.normalize("NFD", "é.md")
    assert _reason(root, [(f"docs/{decomposed}", "existing_evidence")]) == "путь_не_канонический"
    assert _build(root, files=[(f"docs/{composed}", "existing_evidence")]).files


def test_audit_11_the_root_must_be_a_path(root):
    for bad in (None, 5, b"/tmp", ["a"]):
        with pytest.raises(C.PackageRefused) as refused:
            C.build_package(bad, [], SECTIONS, REGISTRIES, "план", tables=TABLES)
        assert refused.value.reason == "некорректный_вход"
    assert _build(str(root)).hash == _build(Path(root)).hash


# --------------------------------------------------------------------------
# round 4: paths and secrets, field formats, the forged package, boundaries
# --------------------------------------------------------------------------

def _tables_edit(tmp_path, edit):
    """Real tables with `edit(пакет)` applied to the `пакет` section."""
    directory = tmp_path / "tables-edit"
    shutil.copytree(T.TABLES_DIR, directory)
    path = directory / "vocabulary.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data["пакет"])
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return T.load(directory)


def _write(root, relative, text="текст"):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


# -- C: the allow-list of extensions and the wider deny-list --------------------

@pytest.mark.parametrize("path", ["docs/plan", "docs/run.exe", "docs/archive.tar.gz", "docs/plan.md.bak",
                                  "docs/.hidden", "docs/Makefile"])
def test_c10_only_allowed_extensions_enter(root, path):
    _write(root, path)
    assert _reason(root, [(path, "existing_evidence")]) == "путь_запрещён"


@pytest.mark.parametrize("path", ["docs/a.md", "docs/B.MD", "docs/a.txt", "docs/a.rst", "docs/a.py",
                                  "docs/a.ts", "docs/a.tsx", "docs/a.js", "docs/a.sql", "docs/a.sh",
                                  "docs/a.yaml", "docs/a.yml", "docs/a.json", "docs/a.toml"])
def test_c10_every_allowed_extension_passes(root, path):
    _write(root, path)
    assert path in _build(root, files=[(path, "existing_evidence")]).files


@pytest.mark.parametrize("path", [
    ".stc/x.md", ".ssh/id.md", ".aws/credentials.md", ".docker/config.json", ".kube/config.yaml",
    ".npmrc", ".netrc", ".pypirc", ".pgpass", ".git-credentials", ".gitconfig", ".htpasswd", ".envrc",
    ".mcp.json", ".claude.json", "docs/settings.local.json", "docs/my_secret_plan.md",
    "docs/Credentials.md", "docs/token.txt", "docs/tokens.json", "docs/api_token.txt",
    "docs/id_rsa", "docs/id_ed25519.pub", "docs/prod.env", "docs/prod.env.md", "docs/.env.example",
    "docs/cert.pem.md", "docs/cert.PEM", "docs/server.key.md", "docs/store.p12", "docs/a.pfx",
    "docs/a.jks", "docs/terraform.tfstate", "docs/terraform.tfstate.backup", "docs/vars.tfvars",
    ".git/config", ".claude/settings.md", "CLAUDE.md", "docs/AGENTS.md", ".codex/x.md"])
def test_c11_the_deny_list_covers_credentials_and_tool_homes(root, path):
    _write(root, path)
    assert _reason(root, [(path, "existing_evidence")]) == "путь_запрещён"


@pytest.mark.parametrize("path", ["docs/environment.md", "docs/keyboard.md", "docs/tokenizer.py",
                                  "docs/identity.md", "docs/id_map.py", "docs/README.md",
                                  "docs/gitignore.md", "docs/secretary.md.txt"[:-4] if False else "docs/notes.md"])
def test_c11_ordinary_names_are_not_cut_by_the_wide_patterns(root, path):
    _write(root, path)
    assert path in _build(root, files=[(path, "existing_evidence")]).files


def test_c11_decided_narrowing_keeps_tokenizer_and_id_map_but_not_real_key_names(root):
    # DECIDED: `*token*` and `id_*` cut legitimate code (tokenizer.py, id_map.py);
    # the table names the real credential shapes instead (token, *_token, id_rsa*).
    for legit in ("docs/tokenizer.py", "docs/id_map.py"):
        _write(root, legit)
        assert _build(root, files=[(legit, "existing_evidence")]).files
    for secret in ("docs/token.txt", "docs/github_token.txt", "docs/id_rsa"):
        _write(root, secret)
        assert _reason(root, [(secret, "existing_evidence")]) == "путь_запрещён"


@pytest.mark.parametrize("text,where", [
    ("-----BEGIN RSA " + "PRIVATE KEY-----\nMII", "file"),  # подставной заголовок ключа собран из частей
    ("ключ " + "AKIA" + "ABCDEFGHIJKLMNOP", "file"),  # подставной ключ собран из частей
    ("token ghp_" + "a" * 36, "section"),
    ("sk-ant-" + "a" * 24, "anchor"),
    ("xoxb-1234567890-abc", "file"),
    ("-----BEGIN " + "PRIVATE KEY-----", "section")])
def test_c12_a_secret_signature_in_a_file_a_section_or_a_registry_value_is_refused(root, text, where):
    files, sections, registries = None, SECTIONS, REGISTRIES
    if where == "file":
        _write(root, "docs/leak.md", text)
        files = [("docs/leak.md", "existing_evidence")]
    elif where == "section":
        sections = {**SECTIONS, "задача": text}
    else:
        registries = _with(журнал_доказательств=[{**SPAN, "якорь": text}])
    assert _reason(root, files, sections=sections, registries=registries) == "похоже_на_секрет"


def test_c12_an_ordinary_text_is_not_taken_for_a_secret(root):
    _write(root, "docs/ok.md", "AKIA короткий, ghp_ мало, BEGIN KEY без чёрточек, sk-ant- пусто")
    assert _build(root, files=[("docs/ok.md", "existing_evidence")]).files


def test_c13_a_declared_file_inside_the_runs_directory_is_refused_even_if_the_root_is_above(root, monkeypatch):
    monkeypatch.setattr(S, "RUNS_ROOT", root / "docs")
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "путь_запрещён"
    monkeypatch.setattr(S, "RUNS_ROOT", root / "nowhere")
    assert _build(root).files


# -- D: formats of the registry fields ------------------------------------------

def test_d14_known_fields_must_have_their_form(root):
    cases = [
        _with(решения=[_decision(text_hash="b" * 8)]),
        _with(решения=[_decision(text_hash="B" * 64)]),
        _with(решения=[_decision(decision_id="с пробелом")]),
        _with(решения=[_decision(decision_id="x" * 65)]),
        _with(области=[{"area_id": "a/b"}]),
        _with(журнал_доказательств=[{**SPAN, "id": "EV 1"}]),
        _with(журнал_доказательств=[{**SPAN, "якорь": "я" * 201}]),
        _with(журнал_доказательств=[{**SPAN, "якорь": ""}]),
    ]
    for registries in cases:
        assert _reason(root, None, registries=registries) == "запись_вне_схемы", registries
    ok = _with(журнал_доказательств=[{**SPAN, "якорь": "я" * 200, "id": "EV-1.a:b"}])
    assert _build(root, registries=ok).hash


@pytest.mark.parametrize("value", [[10], [10, 20, 30], [20, 10], [-1, 5], ["1", "2"], [True, 2],
                                   "10-20", {"от": 1}, None, 1.5])
def test_d14_a_line_range_is_exactly_two_ordered_non_negative_integers(root, value):
    record = {**SPAN, "диапазон_строк": value}
    assert _reason(root, None, registries=_with(журнал_доказательств=[record])) == "запись_вне_схемы"


def test_d14_other_values_are_scalars_never_containers(root):
    for bad in ({"a": 1}, [1], None, True, 1.5, object()):
        record = {**SPAN, "время": bad}
        assert _reason(root, None, registries=_with(журнал_доказательств=[record])) == "запись_вне_схемы", bad
    assert _build(root, registries=_with(журнал_доказательств=[{**SPAN, "время": 5}])).hash


def test_d14_the_path_of_a_journal_record_passes_the_same_rules_as_a_declared_file(root):
    for bad, reason in (("../x.md", "путь_с_родительским_переходом"), ("/etc/hosts", "путь_с_родительским_переходом"),
                        ("docs//a.md", "путь_не_канонический"), (".env", "путь_запрещён"),
                        ("docs/x.exe", "путь_запрещён"), (".git/config", "путь_запрещён")):
        record = {**SPAN, "путь": bad}
        assert _reason(root, None, registries=_with(журнал_доказательств=[record])) == reason, bad
    # existence is not required: a span may cite a file the package does not carry
    record = {**SPAN, "путь": "docs/not-here.md"}
    assert _build(root, registries=_with(журнал_доказательств=[record])).hash


# -- E: the forged package, hostile types ---------------------------------------

def test_e15_a_package_whose_hash_or_stage_does_not_match_its_bytes_cannot_exist(root):
    good = _build(root)
    with pytest.raises(ValueError, match="хеш"):
        C.Package(stage=good.stage, _bytes=good.canonical_bytes, _hash="0" * 64)
    with pytest.raises(ValueError, match="хеш"):
        C.Package(stage=good.stage, _bytes=good.canonical_bytes + b" ", _hash=good.hash)
    forged = good.canonical_bytes.replace('"стадия":"план"'.encode(), '"стадия":"идея"'.encode(), 1)
    assert forged != good.canonical_bytes
    with pytest.raises(ValueError, match="стадия"):
        C.Package(stage="план", _bytes=forged, _hash=C.digest(forged))
    with pytest.raises(ValueError):
        C.Package(stage="план", _bytes=b"not json", _hash=C.digest(b"not json"))
    twin = C.Package(stage=good.stage, _bytes=good.canonical_bytes, _hash=good.hash)
    assert C.same_package(good, twin)
    other = _build(root, sections={**SECTIONS, "задача": "другая"})
    assert not C.same_package(good, other)


def test_e16_hostile_field_types_are_named_refusals_not_raw_errors(root):
    for status in ([], {}, None, 1.5):
        assert _reason(root, None, registries=_with(решения=[_decision(status=status)])) == "запись_вне_схемы"
    assert _reason(root, None, registries=_with(решения=[_decision(kind=[])])) == "запись_вне_схемы"
    record = {**SPAN, "создатель": ["критик"]}
    assert _reason(root, None, registries=_with(журнал_доказательств=[record])) == "запись_вне_схемы"
    assert _reason(root, None, registries=_with(журнал_доказательств=[{**SPAN, "тип": ["x"]}])) == "некорректный_вход"


def test_e16_lone_surrogates_are_refused_as_input(root):
    assert _reason(root, None, sections={**SECTIONS, "задача": "ab\ud800"}) == "некорректный_вход"
    assert _reason(root, [("docs/\ud800.md", "existing_evidence")]) == "некорректный_вход"
    assert _reason(root, None, registries=_with(
        журнал_доказательств=[{**SPAN, "якорь": "\ud800"}])) == "некорректный_вход"
    assert _reason(root, None, registries=_with(
        журнал_доказательств=[{**SPAN, "\ud800": "x"}])) == "запись_вне_схемы"  # an unknown field first
    with pytest.raises(C.PackageRefused) as refused:
        _blind(root, withheld={**WITHHELD, "автор": "Лун\ud800тик"})
    assert refused.value.reason == "некорректный_вход"


def test_e17_two_distinct_names_never_share_one_file_without_a_named_refusal(root):
    # The (st_dev, st_ino) set was removed: with exactly-spelled names and a
    # single link, two declarations of one file can only be a hard link, which is
    # already refused by name. This pins that reasoning.
    os.link(root / "docs" / "plan.md", root / "docs" / "again.md")
    assert _reason(root, [("docs/plan.md", "existing_evidence"),
                          ("docs/again.md", "existing_evidence")]) == "жёсткая_ссылка"


# -- F: boundaries, descriptors, "the code reads the table" ---------------------

def test_f_exactly_the_file_count_limit_passes_and_one_more_does_not(tmp_path, root):
    for index in range(3):
        _write(root, f"docs/f{index}.md", "x")
    three = _tables_edit(tmp_path, lambda p: p.update(предел_числа_файлов=3))
    files = [(f"docs/f{i}.md", "existing_evidence") for i in range(3)]
    assert len(_build(root, files=files, tables=three).manifest) == 3
    _write(root, "docs/f3.md", "x")
    assert _reason(root, files + [("docs/f3.md", "existing_evidence")],
                   tables=three) == "слишком_много_файлов"


def test_f_a_file_of_exactly_the_cap_passes_and_one_byte_more_does_not(tmp_path, root):
    cap = 100
    small = _tables_edit(tmp_path, lambda p: p.update(предел_файла_байт=cap))
    (root / "docs" / "edge.md").write_bytes(b"x" * cap)
    assert _build(root, files=[("docs/edge.md", "existing_evidence")], tables=small).files
    (root / "docs" / "edge.md").write_bytes(b"x" * (cap + 1))
    assert _reason(root, [("docs/edge.md", "existing_evidence")], tables=small) == "превышение_размера"


def test_f_the_running_total_equal_to_the_limit_is_not_a_refusal_of_the_running_total(tmp_path, root):
    (root / "docs" / "e1.md").write_bytes(b"x" * 100)
    (root / "docs" / "e2.md").write_bytes(b"x" * 100)
    exact = _tables_edit(tmp_path, lambda p: p.update(
        предел_пакета_байт=200, предел_файла_байт=100, предел_раздела_байт=100))
    with pytest.raises(C.PackageRefused) as refused:
        _build(root, files=[("docs/e1.md", "existing_evidence"), ("docs/e2.md", "existing_evidence")],
               tables=exact)
    assert refused.value.reason == "превышение_размера"
    assert "файлы" not in refused.value.detail, "200 == the limit: only the whole package is too big"


def _spoof_device(monkeypatch, which):
    """Change `st_dev` of one descriptor chosen by what it was opened as."""
    names, real_open, real_fstat = {}, os.open, os.fstat

    def spy_open(path, *a, **k):
        descriptor = real_open(path, *a, **k)
        names[descriptor] = str(path)
        return descriptor

    def spoof(descriptor):
        info = real_fstat(descriptor)
        if names.get(descriptor, "").endswith(which):
            fields = list(info)
            fields[2] = info.st_dev + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(C.os, "open", spy_open)
    monkeypatch.setattr(C.os, "fstat", spoof)


def test_f_audit_8_a_leaf_on_another_device_is_outside_the_root(root, monkeypatch):
    _spoof_device(monkeypatch, "plan.md")
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "путь_вне_корня"


def test_f_audit_8_a_directory_picked_by_descriptor_not_by_call_order(root, monkeypatch):
    _write(root, "docs/deeper/more.md")
    _spoof_device(monkeypatch, "deeper")
    assert _reason(root, [("docs/deeper/more.md", "existing_evidence")]) == "путь_вне_корня"


def test_f_audit_7_a_hard_link_that_appears_between_the_read_and_the_recheck_is_refused(root, monkeypatch):
    real = os.stat

    def second_link(path, *a, **k):
        info = real(path, *a, **k)
        if k.get("dir_fd") is not None and path == "plan.md":
            fields = list(info)[:10]
            fields[3] = 2  # st_nlink
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(C.os, "stat", second_link)
    assert _reason(root, [("docs/plan.md", "existing_evidence")]) == "жёсткая_ссылка"


def test_f_the_code_reads_the_blind_visibility_rules_from_the_table(tmp_path, root):
    open_visible = _tables_edit(tmp_path, lambda p: p.update(видимые_слепому_статусы_решений=["открыто"]))
    both = _with(BLIND_REGISTRIES, решения=[_decision(status="открыто")])
    assert C.build_package(root, [], PLAIN, both, "идея", blind=True, tables=open_visible,
                           withheld=WITHHELD).hash
    with pytest.raises(C.PackageRefused):
        C.build_package(root, [], PLAIN, BLIND_REGISTRIES, "идея", blind=True, tables=open_visible,
                        withheld=WITHHELD)
    author_visible = _tables_edit(tmp_path / "b", lambda p: p.update(видимые_слепому_создатели=["автор"]))
    by_author = _with(BLIND_REGISTRIES, журнал_доказательств=[{**SPAN, "создатель": "автор"}])
    assert C.build_package(root, [], PLAIN, by_author, "идея", blind=True, tables=author_visible,
                           withheld=WITHHELD).hash
    with pytest.raises(C.PackageRefused):
        C.build_package(root, [], PLAIN, _with(BLIND_REGISTRIES, журнал_доказательств=[PRE]),
                        "идея", blind=True, tables=author_visible, withheld=WITHHELD)


def test_f_the_code_reads_the_section_names_from_the_table(tmp_path, root):
    wider = _tables_edit(tmp_path, lambda p: p["разделы"].append("примечание"))
    assert _build(root, sections={**SECTIONS, "примечание": "x"}, tables=wider).hash
    assert _reason(root, None, sections={**SECTIONS, "примечание": "x"}) == "раздел_неизвестен"
    narrower = _tables_edit(tmp_path / "b", lambda p: p["разделы"].remove("предложенное_решение"))
    assert _reason(root, None, sections={**SECTIONS, "предложенное_решение": "x"},
                   tables=narrower) == "раздел_неизвестен"
    assert _build(root, sections={**SECTIONS, "предложенное_решение": "x"}).hash


def test_f_the_code_reads_the_decision_schema_from_the_table(tmp_path, root):
    def drop_status_hash(package):
        package["схемы_записей"]["решения"] = ["decision_id", "kind", "status"]
    lean = _tables_edit(tmp_path, drop_status_hash)
    lean_decision = {"decision_id": "D-1", "kind": "framing", "status": "x"}
    assert _build(root, registries=_with(решения=[lean_decision]), tables=lean).hash
    assert _reason(root, None, registries=_with(решения=[lean_decision])) == "запись_вне_схемы"
    assert _reason(root, None, registries=_with(решения=[_decision()]), tables=lean) == "запись_вне_схемы"


def test_f_the_code_reads_the_common_journal_fields_from_the_table(tmp_path, root):
    def add_common(package):
        package["схемы_записей"]["журнал_общие"].append("версия")
    wider = _tables_edit(tmp_path, add_common)
    record = {**SPAN, "версия": 2}
    assert _build(root, registries=_with(журнал_доказательств=[record]), tables=wider).hash
    assert _reason(root, None, registries=_with(журнал_доказательств=[SPAN]), tables=wider) == "запись_вне_схемы"
    assert _reason(root, None, registries=_with(журнал_доказательств=[record])) == "запись_вне_схемы"


def test_f_the_code_reads_the_extension_list_the_secret_signatures_and_the_formats(tmp_path, root):
    _write(root, "docs/table.csv", "a,b")
    csv = _tables_edit(tmp_path, lambda p: p["разрешённые_расширения"].append(".csv"))
    assert "docs/table.csv" in _build(root, files=[("docs/table.csv", "existing_evidence")], tables=csv).files
    assert _reason(root, [("docs/table.csv", "existing_evidence")]) == "путь_запрещён"
    no_md = _tables_edit(tmp_path / "b", lambda p: p["разрешённые_расширения"].remove(".md"))
    assert _reason(root, None, tables=no_md) == "путь_запрещён"

    _write(root, "docs/zzz.md", "ZZZ123")
    zzz = _tables_edit(tmp_path / "c", lambda p: p["признаки_секрета"].append("ZZZ[0-9]{3}"))
    assert _reason(root, [("docs/zzz.md", "existing_evidence")], tables=zzz) == "похоже_на_секрет"
    assert _build(root, files=[("docs/zzz.md", "existing_evidence")]).files

    short_ids = _tables_edit(tmp_path / "d", lambda p: p["форматы_полей"].update(area_id="[A-Z]{1}-[0-9]"))
    assert _build(root, registries=_with(области=[{"area_id": "A-1"}]), tables=short_ids).hash
    assert _reason(root, None, registries=_with(области=[{"area_id": "AREA-1"}]),
                   tables=short_ids) == "запись_вне_схемы"


def test_f_the_code_reads_the_kinds_and_the_registry_names_from_the_table(tmp_path, root):
    only_framing = _tables_edit(tmp_path, lambda p: p.update(виды_решений_в_реестре=["framing"]))
    assert _reason(root, None, registries=_with(решения=[_decision()]),
                   tables=only_framing) == "неизвестный_вид_решения"
    extra_ban = _tables_edit(tmp_path / "b", lambda p: p["не_попадает"].append("примечание"))
    assert _reason(root, None, sections={**SECTIONS, "примечание": "x"},
                   tables=extra_ban) == "раздел_вне_пакета"


def test_f_the_trace_threshold_boundary_is_exact(tmp_path, root):
    # a hidden text whose skeleton is exactly the window is found by a slice of
    # that length; one character shorter, only by its stem rules
    window = LIMITS["мин_длина_следа"]
    hidden_text = "б" * window
    sections = {**PLAIN, SHOWN[0]: "б" * window}
    _traced(root, sections=sections, withheld={**WITHHELD, "предложенное_решение": hidden_text})
    sections = {**PLAIN, SHOWN[0]: "б" * (window - 1) + "я"}
    assert _blind(root, sections=sections,
                  withheld={**WITHHELD, "предложенное_решение": hidden_text}).hash


def test_f_an_honest_blind_input_with_unrelated_texts_is_accepted(root):
    sections = {SHOWN[0]: "Сделать выгрузку отчётов по заказам за прошлый квартал",
                SHOWN[1]: "Срок две недели, бюджет не более трёх человеко-недель",
                SHOWN[2]: "Отчёт открывается у менеджера без ошибок",
                SHOWN[3]: "Формат выгрузки уже согласован с бухгалтерией"}
    assert _blind(root, sections=sections).hash


def test_f_the_size_is_settled_before_the_trace_search(tmp_path, root, monkeypatch):
    called = []
    monkeypatch.setattr(C, "_check_traces", lambda *a, **k: called.append(1))
    small = _tables_edit(tmp_path, lambda p: p.update(предел_пакета_байт=100, предел_файла_байт=50,
                                                     предел_раздела_байт=50))
    with pytest.raises(C.PackageRefused) as refused:
        C.build_package(root, [], PLAIN, BLIND_REGISTRIES, "идея", blind=True, tables=small,
                        withheld=WITHHELD)
    assert refused.value.reason == "превышение_размера" and not called
