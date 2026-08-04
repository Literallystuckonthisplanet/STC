"""Behavior tests for the safe memory-root migration utility."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import memory_root_migrate as MRM  # noqa: E402


def test_default_roots_match_canonical_and_legacy_contract():
    assert MRM.CANONICAL_ROOT == Path("/Users/xtoshin/Work/memory")
    assert MRM.LEGACY_ROOTS == (
        Path.home() / ".claude" / "projects" / "-Users-xtoshin-Work" / "memory",
        Path.home() / ".Codex" / "projects" / "-Users-xtoshin-Work" / "memory",
    )


def test_plan_classifies_identical_content_by_sha256(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    content = "same durable memory\n"
    (canonical / "project_demo.md").write_text(content, encoding="utf-8")
    (legacy / "project_demo.md").write_text(content, encoding="utf-8")

    plan = MRM.plan_migration(canonical, [legacy])

    entry = next(item for item in plan["files"] if item["relative_path"] == "project_demo.md")
    expected_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert entry["classification"] == "identical"
    assert entry["canonical"]["sha256"] == expected_sha256
    assert entry["legacy"]["legacy-1"]["sha256"] == expected_sha256


def test_plan_classifies_all_relative_path_states(tmp_path):
    canonical = tmp_path / "canonical"
    claude = tmp_path / ".claude" / "projects" / "memory"
    codex = tmp_path / ".Codex" / "projects" / "memory"
    canonical.mkdir()
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)

    (canonical / "same.md").write_text("same\n", encoding="utf-8")
    (claude / "same.md").write_text("same\n", encoding="utf-8")
    (canonical / "canonical-only.md").write_text("canonical\n", encoding="utf-8")
    (claude / "legacy-only.md").write_text("legacy\n", encoding="utf-8")
    (canonical / "conflict.md").write_text("canonical version\n", encoding="utf-8")
    (claude / "conflict.md").write_text("legacy version\n", encoding="utf-8")
    (codex / "legacy-conflict.md").write_text("one\n", encoding="utf-8")
    (claude / "legacy-conflict.md").write_text("two\n", encoding="utf-8")

    plan = MRM.plan_migration(canonical, [claude, codex])
    classifications = {
        item["relative_path"]: item["classification"]
        for item in plan["files"]
    }

    assert classifications == {
        "canonical-only.md": "canonical-only",
        "conflict.md": "conflict",
        "legacy-conflict.md": "conflict",
        "legacy-only.md": "legacy-only",
        "same.md": "identical",
    }
    assert plan["counts"] == {
        "identical": 1,
        "canonical-only": 1,
        "legacy-only": 1,
        "conflict": 2,
    }


def test_plan_does_not_follow_symlinked_files_into_another_root(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    outside = tmp_path / "outside"
    canonical.mkdir()
    legacy.mkdir()
    outside.mkdir()
    secret = outside / "not-in-memory-root.md"
    secret.write_text("outside body\n", encoding="utf-8")
    (legacy / "link.md").symlink_to(secret)

    plan = MRM.plan_migration(canonical, [legacy])

    assert plan["files"] == []


def test_plan_does_not_follow_symlinked_directories_into_another_root(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    outside = tmp_path / "outside"
    canonical.mkdir()
    legacy.mkdir()
    outside.mkdir()
    (outside / "secret.md").write_text("outside body\n", encoding="utf-8")
    (legacy / "linked-directory").symlink_to(outside, target_is_directory=True)

    plan = MRM.plan_migration(canonical, [legacy])

    assert plan["files"] == []


def test_plan_rejects_overlapping_roots_before_any_apply(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = canonical / "legacy"
    canonical.mkdir()
    legacy.mkdir()

    with pytest.raises(MRM.MigrationError, match="different|overlap"):
        MRM.plan_migration(canonical, [legacy])


def test_plan_rejects_symlinked_root_boundary(tmp_path):
    canonical = tmp_path / "canonical"
    real_legacy = tmp_path / "real-legacy"
    linked_legacy = tmp_path / "legacy-link"
    canonical.mkdir()
    real_legacy.mkdir()
    linked_legacy.symlink_to(real_legacy, target_is_directory=True)

    with pytest.raises(MRM.MigrationError, match="symlink"):
        MRM.plan_migration(canonical, [linked_legacy])


def test_plan_names_default_legacy_roots_for_archive_evidence(tmp_path):
    canonical = tmp_path / "canonical"
    claude = tmp_path / ".claude" / "projects" / "memory"
    codex = tmp_path / ".Codex" / "projects" / "memory"
    canonical.mkdir()
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    (claude / "legacy.md").write_text("from claude\n", encoding="utf-8")
    (codex / "legacy.md").write_text("from codex\n", encoding="utf-8")

    plan = MRM.plan_migration(canonical, [claude, codex])

    entry = next(item for item in plan["files"] if item["relative_path"] == "legacy.md")
    assert set(entry["legacy"]) == {"legacy-claude", "legacy-codex"}


def test_apply_quarantines_legacy_only_and_writes_atomic_manifest(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / ".claude" / "projects" / "memory"
    canonical.mkdir()
    legacy.mkdir(parents=True)
    source = legacy / "nested" / "project_demo.md"
    source.parent.mkdir()
    source.write_text("private memory evidence\n", encoding="utf-8")

    result = MRM.apply_migration(
        canonical,
        [legacy],
        timestamp="20260804T120000000000Z",
    )

    archive = Path(result["archive_root"])
    archived = archive / "legacy-only" / "legacy-claude" / "nested" / "project_demo.md"
    manifest = Path(result["manifest_path"])
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_entry = manifest_data["files"][0]
    assert archived.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert source.is_file()
    assert not (canonical / "nested" / "project_demo.md").exists()
    assert manifest.is_file()
    assert manifest_data["mode"] == "apply"
    assert manifest_entry["classification"] == "legacy-only"
    assert manifest_entry["legacy"]["legacy-claude"]["sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert manifest_entry["archived_paths"] == [
        "legacy-only/legacy-claude/nested/project_demo.md"
    ]
    assert "private memory evidence" not in manifest.read_text(encoding="utf-8")
    assert not list(archive.rglob("*.tmp"))


def test_apply_archives_conflict_evidence_without_overwriting_canonical(tmp_path):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / ".Codex" / "projects" / "memory"
    canonical.mkdir()
    legacy.mkdir(parents=True)
    canonical_file = canonical / "project_demo.md"
    legacy_file = legacy / "project_demo.md"
    canonical_file.write_text("canonical evidence\n", encoding="utf-8")
    legacy_file.write_text("legacy evidence\n", encoding="utf-8")

    result = MRM.apply_migration(
        canonical,
        [legacy],
        timestamp="20260804T120000000001Z",
    )

    archive = Path(result["archive_root"])
    canonical_evidence = archive / "conflicts" / "canonical" / "project_demo.md"
    legacy_evidence = archive / "conflicts" / "legacy-codex" / "project_demo.md"
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert canonical_file.read_text(encoding="utf-8") == "canonical evidence\n"
    assert canonical_evidence.read_text(encoding="utf-8") == "canonical evidence\n"
    assert legacy_evidence.read_text(encoding="utf-8") == "legacy evidence\n"
    assert manifest["files"][-1]["classification"] == "conflict"
    assert "canonical evidence" not in Path(result["manifest_path"]).read_text(encoding="utf-8")
    assert "legacy evidence" not in Path(result["manifest_path"]).read_text(encoding="utf-8")


def test_apply_preserves_each_matching_legacy_root_as_separate_evidence(tmp_path):
    canonical = tmp_path / "canonical"
    claude = tmp_path / ".claude" / "projects" / "memory"
    codex = tmp_path / ".Codex" / "projects" / "memory"
    canonical.mkdir()
    claude.mkdir(parents=True)
    codex.mkdir(parents=True)
    (claude / "project_demo.md").write_text("same legacy\n", encoding="utf-8")
    (codex / "project_demo.md").write_text("same legacy\n", encoding="utf-8")

    result = MRM.apply_migration(
        canonical,
        [claude, codex],
        timestamp="20260804T120000000002Z",
    )

    archive = Path(result["archive_root"])
    assert (archive / "legacy-only" / "legacy-claude" / "project_demo.md").is_file()
    assert (archive / "legacy-only" / "legacy-codex" / "project_demo.md").is_file()


def test_cli_without_apply_is_read_only_and_does_not_print_file_contents(tmp_path, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / ".claude" / "projects" / "memory"
    canonical.mkdir()
    legacy.mkdir(parents=True)
    (legacy / "project_demo.md").write_text("secret body must stay private\n", encoding="utf-8")

    assert MRM.main([
        "--canonical-root", str(canonical),
        "--legacy-root", str(legacy),
    ]) == 0

    output = capsys.readouterr().out
    assert "legacy-only" in output
    assert "project_demo.md" in output
    assert "secret body must stay private" not in output
    assert not (canonical / MRM.ARCHIVE_DIR_NAME).exists()


def test_cli_accepts_explicit_read_only_plan_action(tmp_path, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    canonical.mkdir()
    legacy.mkdir()
    (legacy / "project_demo.md").write_text("body\n", encoding="utf-8")

    assert MRM.main([
        "plan",
        "--canonical-root", str(canonical),
        "--legacy-root", str(legacy),
    ]) == 0

    assert "mode: plan (read-only)" in capsys.readouterr().out
    assert not (canonical / MRM.ARCHIVE_DIR_NAME).exists()


def test_cli_apply_requires_flag_and_writes_only_archive_metadata_to_stdout(tmp_path, capsys):
    canonical = tmp_path / "canonical"
    legacy = tmp_path / ".claude" / "projects" / "memory"
    canonical.mkdir()
    legacy.mkdir(parents=True)
    (legacy / "project_demo.md").write_text("another private body\n", encoding="utf-8")

    assert MRM.main([
        "--canonical-root", str(canonical),
        "--legacy-root", str(legacy),
        "--apply",
    ]) == 0

    output = capsys.readouterr().out
    assert "mode: apply" in output
    assert "another private body" not in output
    archives = list((canonical / MRM.ARCHIVE_DIR_NAME / "quarantine").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "manifest.json").is_file()
