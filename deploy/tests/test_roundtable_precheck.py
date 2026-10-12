"""Б15 -- the programmatic precheck: five codes, four outcomes, zero calls.

Every code has a negative fixture AND a close sound control, and the reason is compared
(not only the code). The expected results live in `fixtures/roundtable/precheck/expected.json`.
"""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "core" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from roundtable import context as C  # noqa: E402
from roundtable import precheck as P  # noqa: E402
from roundtable import tables as T  # noqa: E402

TABLES = T.load()
FIXTURES = ROOT / "deploy" / "tests" / "fixtures" / "roundtable" / "precheck"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
CASES = {case["имя"]: case for case in EXPECTED["случаи"]}
CODES = [row.code for row in TABLES.precheck_codes]


def _facts(raw):
    if "отказ" in raw:
        return P.PrecheckFacts(refusal=raw["отказ"]["причина"], refusal_detail=raw["отказ"]["деталь"])
    entries = tuple(C.ManifestEntry(row["путь"], row["класс"], row["хеш"], None) for row in raw["записи"])
    return P.PrecheckFacts(entries=entries, revision=raw["редакция"])


def _run(case):
    text = P.split_frontmatter((FIXTURES / case["документ"]).read_text(encoding="utf-8"))
    return P.precheck(text, _facts(case["факты"]), TABLES)


def _shape(result):
    return {"статус": result.status,
            "находки": [{"код": f.code, "где": f.where, "причина": f.reason} for f in result.findings]}


def _document(**fields):
    base = {"revision": "r1", "sections": [], "references": [], "lists": [],
            "evidence": [], "active_capabilities": [], "forbidden_capabilities": []}
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)       # JSON is YAML: one parser for both


MINIMAL_FACTS = P.PrecheckFacts(entries=(), revision="r1")


# -- Б15-1 / Б15-6: five codes, fixture + control, reason compared -----------------------

@pytest.mark.parametrize("name", sorted(CASES))
def test_every_fixture_case_gives_exactly_the_expected_result(name):
    case = CASES[name]
    if case["статус"] == "недопустимый_вход":
        result = _run(case)
        assert result.status == P.BAD_INPUT and not result.findings
        assert result.reason.startswith(("факты: неизвестный класс файла", "пакет не собран: "))
        return
    assert _shape(_run(case)) == {"статус": case["статус"], "находки": case["находки"]}


def test_there_are_exactly_five_codes_each_with_its_fixture_and_control():
    assert len(CODES) == 5
    for row in TABLES.precheck_codes:
        assert (FIXTURES / row.fixture).exists(), row.fixture
        fired = {f["код"] for case in CASES.values() for f in case["находки"]}
        assert row.code in fired, f"{row.code}: нет отрицательного случая"
        assert f"{Path(row.fixture).stem}-control" in CASES, f"{row.code}: нет исправного контроля"


@pytest.mark.parametrize("code, name", [
    ("BROKEN_ANCHOR", "broken-section-target"), ("MISSING_EXISTING_EVIDENCE", "removed-block-refused"),
    ("DECLARED_COUNT_MISMATCH", "count-mismatch"), ("REVISION_MISMATCH", "revision-mismatch"),
    ("FORBIDDEN_CAPABILITY_PRESENT", "forbidden-capability")])
def test_each_code_fires_on_its_own_fixture_alone(code, name):
    assert [f.code for f in _run(CASES[name]).findings] == [code]


def test_a_missing_file_and_a_hash_mismatch_are_two_different_findings():
    missing = _run(CASES["removed-block-not-in-manifest"]).findings[0]
    refused = _run(CASES["removed-block-refused"]).findings[0]
    mismatch = _run(CASES["hash-mismatch"]).findings[0]
    assert missing.code == refused.code == mismatch.code == "MISSING_EXISTING_EVIDENCE"
    assert mismatch.reason.startswith("хеш не совпал") and missing.reason.startswith("нет файла")
    assert refused.reason.startswith("нет файла") and mismatch.reason != missing.reason


def test_the_forbidden_capability_is_a_set_intersection_not_a_word_search():
    # "write-docs" contains the word "write"; the sets do not intersect.
    assert _run(CASES["forbidden-capability-control"]).status == P.CLEAN
    text = _document(active_capabilities=["Write "], forbidden_capabilities=["write"])
    assert [f.code for f in P.precheck(text, MINIMAL_FACTS, TABLES).findings] == ["FORBIDDEN_CAPABILITY_PRESENT"]


def test_the_prose_of_the_document_is_never_read():
    # clean.md carries `ref:fake` and the word write in its body: still clean.
    assert "ref:fake" in (FIXTURES / "clean.md").read_text(encoding="utf-8")
    assert _run(CASES["clean"]).status == P.CLEAN


def test_a_reference_that_is_not_ref_something_is_a_bad_input():
    result = P.precheck(_document(references=["§13"]), MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT and result.reason == "ссылка: ожидалось ref:<имя>"


# -- Б15-3: clean is empty; planned_output by absence does not fail ----------------------

def test_a_clean_document_is_empty_and_allows_continuation():
    result = _run(CASES["clean"])
    assert result.status == P.CLEAN and result.findings == () and result.allows_continuation


def test_planned_output_absent_does_not_fail():
    assert _run(CASES["planned-output-absent-is-fine"]).status == P.CLEAN


def test_an_unknown_file_class_is_neither_planned_output_nor_silence():
    result = _run(CASES["unknown-class-in-facts"])
    assert result.status == P.BAD_INPUT and result.reason == "факты: неизвестный класс файла, запись 1"
    assert "может_быть" not in result.reason and not result.allows_continuation
    refused = _run(CASES["unknown-class-refusal"])
    assert refused.status == P.BAD_INPUT and refused.reason == "пакет не собран: неизвестный_класс_файла"


def test_a_builder_refusal_is_kept_and_never_clean(tmp_path):
    (tmp_path / "docs").mkdir()
    with pytest.raises(C.PackageRefused) as caught:
        C.build_package(tmp_path, [("docs/gone.md", "existing_evidence")], {"задача": "x"},
                        {"решения": [], "области": [], "журнал_доказательств": []}, "план",
                        tables=TABLES, revision="r1")
    facts = P.facts_from_refusal(caught.value)
    result = P.precheck(_document(evidence=[{"path": "docs/gone.md", "sha256": "a" * 64}]), facts, TABLES)
    assert result.status == P.FINDINGS and result.findings[0].code == "MISSING_EXISTING_EVIDENCE"
    with pytest.raises(C.PackageRefused) as other:
        C.build_package(tmp_path, [("docs/gone.md", "может_быть")], {"задача": "x"},
                        {"решения": [], "области": [], "журнал_доказательств": []}, "план", tables=TABLES)
    refused = P.precheck(_document(), P.facts_from_refusal(other.value), TABLES)
    assert refused.status == P.BAD_INPUT and refused.reason.startswith("пакет не собран: ")


# -- Б15-2 / Б15-7: facts come from the package; revision sides ---------------------------

def _package(tmp_path, revision="r1", text="# План\n"):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "plan.md").write_text(text, encoding="utf-8")
    return C.build_package(tmp_path, [("docs/plan.md", "existing_evidence"), ("out/new.md", "planned_output")],
                           {"задача": "x"}, {"решения": [], "области": [], "журнал_доказательств": []},
                           "план", tables=TABLES, revision=revision)


def test_facts_from_a_real_package_pass_a_matching_header(tmp_path):
    package = _package(tmp_path)
    real_hash = next(e.sha256 for e in package.manifest if e.path == "docs/plan.md")
    facts = P.facts_from_package(package)
    assert facts.revision == "r1" and len(facts.entries) == 2
    good = _document(evidence=[{"path": "docs/plan.md", "sha256": real_hash}])
    assert P.precheck(good, facts, TABLES).status == P.CLEAN
    bad = _document(evidence=[{"path": "docs/plan.md", "sha256": "0" * 64}])
    assert P.precheck(bad, facts, TABLES).findings[0].reason.startswith("хеш не совпал")


def test_a_draft_that_is_not_committed_is_checked_from_the_working_tree(tmp_path):
    # tmp_path is no git repository at all: the facts come from the files read at build time.
    package = _package(tmp_path, text="черновик, ещё не закоммичен\n")
    assert P.precheck(_document(), P.facts_from_package(package), TABLES).status == P.CLEAN


def test_changing_only_the_header_side_gives_a_finding_equal_sides_pass(tmp_path):
    facts = P.facts_from_package(_package(tmp_path, revision="r1"))
    assert P.precheck(_document(revision="r1"), facts, TABLES).status == P.CLEAN
    result = P.precheck(_document(revision="r2"), facts, TABLES)
    assert [f.code for f in result.findings] == ["REVISION_MISMATCH"]


def test_changing_only_the_package_side_gives_a_finding(tmp_path):
    facts = P.facts_from_package(_package(tmp_path, revision="r2"))
    result = P.precheck(_document(revision="r1"), facts, TABLES)
    assert [f.code for f in result.findings] == ["REVISION_MISMATCH"]


def test_the_two_sides_do_not_come_from_one_field():
    # A header that claims the same edition inside its own text cannot make the package side match:
    # the package side is the facts' field, which the frontmatter has no way to write.
    text = _document(revision="forged", sections=[{"id": "s", "anchors": ["ref:revision=r1"]}])
    result = P.precheck(text, P.PrecheckFacts(entries=(), revision="r1"), TABLES)
    assert [f.code for f in result.findings] == ["REVISION_MISMATCH"]
    # facts that carry no edition are an unusable input, not a pass
    no_edition = P.precheck(_document(), P.PrecheckFacts(entries=()), TABLES)
    assert no_edition.status == P.BAD_INPUT and no_edition.reason.startswith("факты: у пакета нет редакции")


def test_facts_are_immutable_and_come_only_from_the_package_type():
    facts = P.PrecheckFacts(entries=(), revision="r1")
    with pytest.raises(Exception):
        facts.revision = "r2"
    for stranger in ({"revision": "r1"}, None, "r1"):
        result = P.precheck(_document(), stranger, TABLES)
        assert result.status == P.BAD_INPUT and result.reason.startswith("факты: нужен PrecheckFacts")
    with pytest.raises(TypeError):
        P.facts_from_package({"редакция": "r1"})


def test_the_precheck_reads_no_path_from_disk(monkeypatch, tmp_path):
    def forbidden(*a, **k):
        raise AssertionError("предпроверка полезла на диск")
    facts = P.PrecheckFacts(entries=(C.ManifestEntry("docs/plan.md", "existing_evidence", "a" * 64, 1),), revision="r1")
    text = _document(evidence=[{"path": "docs/plan.md", "sha256": "a" * 64}])
    # the schema is read once, up front; only the checks themselves are fenced off from the disk
    schema = P.contracts.load_schema(P.SCHEMA_NAME)
    monkeypatch.setattr(P.contracts, "load_schema", lambda *a, **k: schema)
    with monkeypatch.context() as fence:
        for target in ("read_text", "read_bytes", "open", "stat", "exists", "is_file", "resolve"):
            fence.setattr(Path, target, forbidden)
        fence.setattr(os, "stat", forbidden)
        fence.setattr(os, "open", forbidden)
        fence.setattr("builtins.open", forbidden)
        result = P.precheck(text, facts, TABLES)
    assert result.status == P.CLEAN


# -- Б15-5: four different outcomes -------------------------------------------------------

@pytest.mark.parametrize("text", [None, "", "   \n", "\n"])
def test_no_or_empty_frontmatter_is_a_bad_input_not_a_clean_pass(text):
    result = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT and result.findings == () and not result.allows_continuation
    assert result.reason in ("фронтматтер: нет текста", "фронтматтер: пусто")


def test_a_document_without_fences_has_no_frontmatter():
    assert P.split_frontmatter("# просто текст\n") is None
    assert P.split_frontmatter("---\nrevision: r1\n") is None            # never closed
    assert P.split_frontmatter(None) is None
    assert P.split_frontmatter("---\nrevision: r1\n---\nтекст") == "revision: r1"


@pytest.mark.parametrize("text", [
    "revision: [unclosed",                     # does not parse
    "- just\n- a list",                        # wrong type of the whole
    "revision: 5\nsections: []",               # wrong type of a field
    "revision: r1\nrevision: r2",              # duplicate key
    "a: &x [1]\nb: *x",                        # alias
    "x: " + "y" * (P.FRONTMATTER_LIMIT + 1),   # oversize
])
def test_a_broken_or_wrongly_typed_frontmatter_is_a_bad_input(text):
    result = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT and result.findings == ()
    assert result.reason.startswith(("фронтматтер: не разбирается", "фронтматтер: ожидалась карта",
                                     "фронтматтер не по схеме: $",
                                     "фронтматтер: ссылки-алиасы", "фронтматтер: длиннее"))


def test_a_missing_required_field_or_an_extra_one_is_a_bad_input():
    base = json.loads(_document())
    for field in base:
        cut = {k: v for k, v in base.items() if k != field}
        result = P.precheck(json.dumps(cut), MINIMAL_FACTS, TABLES)
        assert result.status == P.BAD_INPUT, field
        assert result.reason == f"фронтматтер не по схеме: $: нет обязательного поля {field}", field
    extra = P.precheck(json.dumps({**base, "extra": 1}), MINIMAL_FACTS, TABLES)
    assert extra.status == P.BAD_INPUT and extra.reason == "фронтматтер не по схеме: $: лишнее поле"


def test_the_minimal_valid_document_is_the_positive_control():
    assert P.precheck(_document(), MINIMAL_FACTS, TABLES).status == P.CLEAN
    assert _run(CASES["minimal-valid"]).status == P.CLEAN


def test_an_unavailable_or_damaged_schema_is_a_failed_check_never_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "SCHEMA_DIR", tmp_path)                            # no schema there
    gone = P.precheck(_document(), MINIMAL_FACTS, TABLES)
    assert gone.status == P.CHECK_FAILED and not gone.allows_continuation and gone.findings == ()
    (tmp_path / "precheck_frontmatter.json").write_text("{не json", encoding="utf-8")
    assert P.precheck(_document(), MINIMAL_FACTS, TABLES).status == P.CHECK_FAILED
    (tmp_path / "precheck_frontmatter.json").write_text('{"type":"object","pattern":"x"}', encoding="utf-8")
    assert P.precheck(_document(), MINIMAL_FACTS, TABLES).status == P.CHECK_FAILED   # outside the closed subset


def test_a_bug_inside_a_check_is_a_failed_check(monkeypatch):
    def boom(front, facts, found):
        raise RuntimeError("поломка")
    monkeypatch.setitem(P.CHECKS, "BROKEN_ANCHOR", boom)
    result = P.precheck(_document(), MINIMAL_FACTS, TABLES)
    assert result.status == P.CHECK_FAILED and result.reason == "сбой проверки: RuntimeError"


def test_only_clean_allows_continuation_and_the_result_cannot_lie():
    assert [s for s in P.STATUSES if P.PrecheckResult(s, (P.Finding("X", "w", "r"),) if s == P.FINDINGS else (),
                                                      "" if s in (P.CLEAN, P.FINDINGS) else "p").allows_continuation] == [P.CLEAN]
    with pytest.raises(ValueError):
        P.PrecheckResult(P.CHECK_FAILED)                      # a failure with no reason
    with pytest.raises(ValueError):
        P.PrecheckResult(P.FINDINGS)                          # findings with none
    with pytest.raises(ValueError):
        P.PrecheckResult(P.CLEAN, (P.Finding("X", "w", "r"),))


def test_the_check_code_set_equals_the_table_code_set():
    assert set(P.CHECKS) == set(CODES)


# -- Б15-4 / Б15-6: no calls; same input, same ordered result ----------------------------

def test_zero_network_and_zero_process_calls(monkeypatch):
    def trap(*a, **k):
        raise AssertionError("сетевой или процессный вызов в предпроверке")
    for target in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, target, trap)
    for target in ("Popen", "run", "call", "check_output", "check_call"):
        monkeypatch.setattr(subprocess, target, trap)
    for target in ("system", "popen", "execv", "execvp", "fork", "spawnv"):
        if hasattr(os, target):
            monkeypatch.setattr(os, target, trap)
    for name in sorted(CASES):
        _run(CASES[name])
    assert P.precheck(_document(), MINIMAL_FACTS, TABLES).status == P.CLEAN


def test_the_module_does_not_import_a_model_or_transport_layer():
    import ast
    tree = ast.parse((SCRIPTS / "roundtable" / "precheck.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = ("." * node.level) + (node.module or "")
            imported |= {base.lstrip(".").split(".")[0]} if node.module else {alias.name for alias in node.names}
            imported |= {alias.name for alias in node.names} if node.level else set()
    banned = {"adapters", "subprocess", "socket", "urllib", "http", "requests", "asyncio", "ssl", "os"}
    assert not imported & banned, imported & banned


def test_a_repeat_gives_the_same_ordered_result():
    text = _document(
        sections=[{"id": "s", "anchors": ["ref:a"]}], references=["ref:z", "ref:b", "ref:a"],
        lists=[{"name": "n2", "declared_count": 1, "items": []}, {"name": "n1", "declared_count": 2, "items": ["x"]}],
        active_capabilities=["w", "d"], forbidden_capabilities=["d", "w"], revision="r9")
    first = P.precheck(text, MINIMAL_FACTS, TABLES)
    second = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert first == second and first.findings == second.findings
    codes = [f.code for f in first.findings]
    assert codes == sorted(codes, key=CODES.index), "order: the code order of precheck.yaml"
    within = [f.where for f in first.findings if f.code == "BROKEN_ANCHOR"]
    assert within == ["references[0]", "references[1]"], "inside a code: by place"



# -- QA regressions (items 1-4 of the rework) ----------------------------------------------

SECRET = "sk-" + "live-" + "AbCd" + "1234" + "-QA"      # built from parts


@pytest.mark.parametrize("active, forbidden", [
    ("exеc", "exec"), ("exec", "exеc"), ("еxес", "exec"),       # Cyrillic twins
    ("exec​", "exec"), ("ex​ec", "exec"), ("exec\xad", "exec"),                # invisible, soft hyphen
    ("exec⁠", "exec"), ("exec﻿", "exec"), ("‮exec", "exec"),
    ("exec͏", "exec"), ("EXЕC", "exec"),
    ("net‐work", "net-work"), ("ınstall", "install"),                         # Unicode hyphen, dotless i
    ("write", "wrіte"), ("οs", "os"),                                          # Ukrainian i, Greek omicron
])
def test_capability_names_are_compared_under_the_packages_own_fold(active, forbidden):
    text = _document(active_capabilities=[active], forbidden_capabilities=[forbidden])
    result = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert [f.code for f in result.findings] == ["FORBIDDEN_CAPABILITY_PRESENT"], (active, forbidden)


def test_a_name_with_nothing_visible_is_a_bad_input_not_a_match_or_a_pass():
    text = _document(active_capabilities=["--"], forbidden_capabilities=["\u2010"])
    result = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT and result.reason == "имя возможности без видимых знаков"


def test_the_capability_fold_is_the_packages_fold_not_a_copy():
    import inspect
    source = inspect.getsource(P)
    assert "fold_name" in source and "CONFUSABLES" not in source and "NFKC" not in source


@pytest.mark.parametrize("revision", ["р1", "r 1", "r\n1", "x" * 65, "*a", "r1​"])
def test_a_revision_outside_the_package_alphabet_is_a_bad_input_even_when_equal(revision):
    both = P.precheck(_document(revision=revision), P.PrecheckFacts(entries=(), revision=revision), TABLES)
    assert both.status == P.BAD_INPUT and both.reason.startswith(("редакция в ", "фронтматтер не по схеме: $.revision"))
    on_header = P.precheck(_document(revision=revision), MINIMAL_FACTS, TABLES)
    assert on_header.status == P.BAD_INPUT and on_header.reason in (
        "редакция в шапке вне допустимой длины или алфавита", "фронтматтер не по схеме: $.revision: нарушен предел или форма")
    on_facts = P.precheck(_document(), P.PrecheckFacts(entries=(), revision=revision), TABLES)
    assert on_facts.status == P.BAD_INPUT and on_facts.reason == "редакция в фактах пакета вне допустимой длины или алфавита"


def test_the_precheck_uses_the_builders_own_revision_rule():
    assert P.check_revision is C.check_revision


@pytest.mark.parametrize("shape", [
    lambda n: "[" * n + "]" * n,
    lambda n: "{a: " * n + "1" + "}" * n,
    lambda n: "revision: " + "[" * n + "]" * n,
    lambda n: "\n".join(["a:"] + [" " * i + "b:" for i in range(1, n)]),
    lambda n: "- " * n + "x",
])
def test_deep_nesting_is_refused_fast_before_the_parser_and_is_a_bad_input(shape):
    import time
    started = time.monotonic()
    result = P.precheck(shape(20000)[:P.FRONTMATTER_LIMIT], MINIMAL_FACTS, TABLES)
    assert time.monotonic() - started < 2.0
    assert result.status == P.BAD_INPUT and result.reason.startswith("фронтматтер: ")


def test_a_recursion_error_inside_the_parser_is_a_bad_input(monkeypatch):
    def deep(*a, **k):
        raise RecursionError
    monkeypatch.setattr(P.yaml, "load", deep)
    result = P.precheck(_document(), MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT and result.reason == "фронтматтер: вложенность глубже допустимой"


@pytest.mark.parametrize("text", [
    'revision: r1\nsections: []\nreferences: []\nlists:\n  - {name: n, declared_count: 1, items: ["' + "[" * 100 + '"]}\n'
    'evidence: []\nactive_capabilities: []\nforbidden_capabilities: []',
    _document().replace("{", "{") + "\n# " + "[" * 200 + "{" * 200,
    "revision: r1  # [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{{\n"
    "sections: []\nreferences: []\nlists: []\nevidence: []\nactive_capabilities: []\nforbidden_capabilities: []",
    'revision: r1\nsections: []\nreferences: ["ref:' + "{" * 100 + '"]\nlists: []\nevidence: []\n'
    'active_capabilities: []\nforbidden_capabilities: []',
])
def test_brackets_in_strings_and_comments_are_not_structure(text):
    result = P.precheck(text, MINIMAL_FACTS, TABLES)
    assert result.status in (P.CLEAN, P.FINDINGS), result      # not a depth refusal
    assert result.reason == ""


def test_the_real_depth_is_what_is_limited():
    level = P.DEPTH_LIMIT
    inside = "revision: r1\n" + "x: " + "[" * (level + 5) + "]" * (level + 5)
    assert P.precheck(inside, MINIMAL_FACTS, TABLES).reason == "фронтматтер: вложенность глубже допустимой"
    block = "\n".join("  " * i + "k:" for i in range(level + 5)) + " 1"
    assert P.precheck(block, MINIMAL_FACTS, TABLES).reason == "фронтматтер: вложенность глубже допустимой"
    ok = "revision: r1\nx: " + "[" * (level - 2) + "]" * (level - 2)       # deep but allowed: then refused by the schema
    assert P.precheck(ok, MINIMAL_FACTS, TABLES).reason.startswith("фронтматтер не по схеме")


def _everything(result):
    return " ".join([result.reason] + [f"{f.code} {f.where} {f.reason}" for f in result.findings])


def test_the_raw_input_never_travels_into_a_result():
    base = json.loads(_document())
    cases = [
        P.precheck(json.dumps({**base, SECRET: 1}), MINIMAL_FACTS, TABLES),                      # unknown field
        P.precheck(_document(references=[SECRET]), MINIMAL_FACTS, TABLES),                       # malformed reference
        P.precheck(_document(), P.PrecheckFacts(entries=(C.ManifestEntry("a", SECRET, None, None),), revision="r1"), TABLES),
        P.precheck(_document(revision=SECRET[:60]), MINIMAL_FACTS, TABLES),                      # alien revision
        P.precheck(_document(), P.PrecheckFacts(refusal=SECRET), TABLES),                        # refusal text
        P.precheck(_document(revision={"k": SECRET}), MINIMAL_FACTS, TABLES),                    # wrong type
        P.precheck("revision: [" + SECRET, MINIMAL_FACTS, TABLES),                               # syntax error
        P.precheck(f"{SECRET}: 1\n{SECRET}: 2\n", MINIMAL_FACTS, TABLES),                        # duplicate key
        P.precheck(f"revision: !{SECRET} x", MINIMAL_FACTS, TABLES),                             # tag
        P.precheck(_document(active_capabilities=[SECRET + " x"], forbidden_capabilities=[SECRET + " x"]),
                   MINIMAL_FACTS, TABLES),                                                       # name with a space
        P.precheck(_document(lists=[{"name": SECRET + " ", "declared_count": 1, "items": []}]),
                   MINIMAL_FACTS, TABLES),
    ]
    for result in cases:
        assert SECRET not in _everything(result) and SECRET[:12] not in _everything(result), result


def test_a_raw_exception_text_never_travels_into_a_result(monkeypatch):
    def boom(front, facts, found):
        raise RuntimeError(SECRET)
    monkeypatch.setitem(P.CHECKS, "REVISION_MISMATCH", boom)
    result = P.precheck(_document(), MINIMAL_FACTS, TABLES)
    assert result.status == P.CHECK_FAILED and SECRET not in result.reason


def test_a_revision_finding_does_not_show_either_side():
    result = P.precheck(_document(revision="r2"), P.PrecheckFacts(entries=(), revision="r1"), TABLES)
    assert result.findings[0].reason == "редакция в шапке не равна редакции пакета"


MARKER = "REVIEW" + "_MARKER_" + "ALPHA"          # alphanumeric, no spaces: the "safe-looking" kind of input


def test_no_value_of_the_input_is_echoed_on_any_branch():
    existing = C.ManifestEntry(MARKER + "/a.md", "existing_evidence", "a" * 64, 1)
    ok_facts = P.PrecheckFacts(entries=(existing,), revision="r1")
    claim = {"path": MARKER + "/b.md", "sha256": "0" * 64}
    cases = [
        # facts: unknown class, repeated path, alien class, alien revision, every kind of refusal
        P.precheck(_document(), P.PrecheckFacts(entries=(C.ManifestEntry(MARKER, MARKER, None, None),), revision="r1"), TABLES),
        P.precheck(_document(), P.PrecheckFacts(entries=(existing, C.ManifestEntry(MARKER + "/a.md", "planned_output", None, None)),
                                                revision="r1"), TABLES),
        P.precheck(_document(), P.PrecheckFacts(entries=(), revision=MARKER), TABLES),
        P.precheck(_document(), P.PrecheckFacts(refusal=MARKER, refusal_detail=MARKER), TABLES),
        P.precheck(_document(), P.PrecheckFacts(refusal="файл_нечитаем", refusal_detail=MARKER), TABLES),
        P.precheck(_document(evidence=[claim]), P.PrecheckFacts(refusal=P.MISSING_FILE_REFUSAL, refusal_detail=MARKER), TABLES),
        # the header: unknown field, wrong type, alien revision, malformed reference, empty name
        P.precheck(json.dumps({**json.loads(_document()), MARKER: 1}), ok_facts, TABLES),
        P.precheck(_document(revision={MARKER: MARKER}), ok_facts, TABLES),
        P.precheck(_document(revision=MARKER), ok_facts, TABLES),
        P.precheck(_document(references=[MARKER]), ok_facts, TABLES),
        P.precheck(_document(active_capabilities=["--"], forbidden_capabilities=[MARKER]), ok_facts, TABLES),
        P.precheck(MARKER + ": [", ok_facts, TABLES),
        P.precheck(f"{MARKER}: 1\n{MARKER}: 2", ok_facts, TABLES),
        # findings of all five codes, with the marker in every name the header carries
        P.precheck(_document(
            revision="r2", sections=[{"id": MARKER, "anchors": [MARKER + "_a"]}],
            references=["ref:" + MARKER], lists=[{"name": MARKER, "declared_count": 7, "items": [MARKER]}],
            evidence=[claim, {"path": MARKER + "/a.md", "sha256": "1" * 64}],
            active_capabilities=[MARKER], forbidden_capabilities=[MARKER]), ok_facts, TABLES),
    ]
    assert [c.status for c in cases[-1:]] == [P.FINDINGS]
    assert {f.code for f in cases[-1].findings} == set(CODES)
    for result in cases:
        assert MARKER not in _everything(result), result
        assert "MARKER" not in _everything(result), result


def test_a_place_is_a_machine_locator_with_a_number_never_a_name():
    result = P.precheck(_document(
        references=["ref:gone", "ref:gone2"], lists=[{"name": "n", "declared_count": 1, "items": []}],
        active_capabilities=["x", "y"], forbidden_capabilities=["y"]), MINIMAL_FACTS, TABLES)
    assert [(f.code, f.where) for f in result.findings] == [
        ("BROKEN_ANCHOR", "references[0]"), ("BROKEN_ANCHOR", "references[1]"),
        ("DECLARED_COUNT_MISMATCH", "lists[0]"), ("FORBIDDEN_CAPABILITY_PRESENT", "active_capabilities[1]")]


def test_places_sort_by_number_not_by_text():
    refs = [f"ref:r{n}" for n in range(12)]
    result = P.precheck(_document(references=refs), MINIMAL_FACTS, TABLES)
    assert [f.where for f in result.findings] == [f"references[{n}]" for n in range(12)]


def test_a_repeated_entry_is_named_by_its_number():
    twice = P.PrecheckFacts(entries=(C.ManifestEntry("a", "existing_evidence", "a" * 64, 1),
                                     C.ManifestEntry("b", "planned_output", None, None),
                                     C.ManifestEntry("a", "planned_output", None, None)), revision="r1")
    result = P.precheck(_document(), twice, TABLES)
    assert result.status == P.BAD_INPUT and result.reason == "факты: путь повторяется, запись 3"


def test_every_refusal_literal_of_the_builder_is_known_to_the_precheck():
    import ast
    tree = ast.parse((SCRIPTS / "roundtable" / "context.py").read_text(encoding="utf-8"))
    literals = {node.args[0].value for node in ast.walk(tree)
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PackageRefused"
                and isinstance(node.args[0], ast.Constant)}
    assert literals <= P.KNOWN_REFUSALS and set(TABLES.vocabulary["пакет"]["отвергается"]) <= P.KNOWN_REFUSALS
    assert P.precheck(_document(), P.PrecheckFacts(refusal="чужой_текст"), TABLES).reason == "пакет не собран: причина скрыта"


# -- item 5: a manifest evidence the header does not mention --------------------------------

def test_an_existing_evidence_the_header_does_not_mention_is_fine():
    facts = P.PrecheckFacts(entries=(C.ManifestEntry("docs/other.md", "existing_evidence", "a" * 64, 1),), revision="r1")
    assert P.precheck(_document(), facts, TABLES).status == P.CLEAN


# -- item 7: runtime branches of the failed check ----------------------------------------------

def test_a_code_removed_from_the_checks_is_a_failed_check(monkeypatch):
    monkeypatch.delitem(P.CHECKS, "BROKEN_ANCHOR")
    result = P.precheck(_document(), MINIMAL_FACTS, TABLES)
    assert result.status == P.CHECK_FAILED and result.reason == "схема или таблицы недоступны: ContractError"


def test_tables_that_cannot_be_loaded_are_a_failed_check(monkeypatch):
    def broken():
        raise OSError(SECRET)
    monkeypatch.setattr(P.tables_module, "load", broken)
    result = P.precheck(_document(), MINIMAL_FACTS)
    assert result.status == P.CHECK_FAILED and result.reason == "схема или таблицы недоступны: OSError"


def test_tables_without_the_file_classes_are_a_failed_check():
    class NoClasses:
        precheck_codes = TABLES.precheck_codes
        precheck = {}
    result = P.precheck(_document(), MINIMAL_FACTS, NoClasses())
    assert result.status == P.CHECK_FAILED and result.reason == "схема или таблицы недоступны: KeyError"


# -- item 8: hashes ----------------------------------------------------------------------------

def test_an_existing_evidence_entry_without_a_hash_is_a_missing_file():
    facts = P.PrecheckFacts(entries=(C.ManifestEntry("docs/plan.md", "existing_evidence", None, None),), revision="r1")
    result = P.precheck(_document(evidence=[{"path": "docs/plan.md", "sha256": "a" * 64}]), facts, TABLES)
    assert [(f.code, f.reason) for f in result.findings] == [
        ("MISSING_EXISTING_EVIDENCE", "нет файла: у записи манифеста нет хеша")]


def test_fixture_hashes_are_real_sha256_and_case_does_not_matter():
    import re
    for case in CASES.values():
        for row in case["факты"].get("записи", []):
            assert row["хеш"] is None or re.fullmatch(r"[0-9a-f]{64}", row["хеш"]), case["имя"]
    assert _run(CASES["hash-uppercase"]).status == P.CLEAN
    assert "A" in (FIXTURES / "hash-uppercase.md").read_text(encoding="utf-8").split("---")[1].upper()


# -- item 10: a non-string scalar gets a hint ---------------------------------------------------

@pytest.mark.parametrize("raw", ["revision: 1.2", "revision: 2026-10-11", "revision: on"])
def test_a_non_string_yaml_scalar_gets_a_quote_hint(raw):
    text = _document().replace('"revision": "r1"', raw.replace("revision: ", '"revision": ')) if False else None
    front = json.loads(_document())
    lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in front.items() if k != "revision")
    result = P.precheck(raw + "\n" + lines, MINIMAL_FACTS, TABLES)
    assert result.status == P.BAD_INPUT
    assert result.reason.startswith("фронтматтер не по схеме: $.revision: неверный тип")
    assert "возьми значение в кавычки" in result.reason
