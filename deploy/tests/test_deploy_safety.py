"""Safety regressions for deploy manifests and orphan pruning."""

import json
import os
import sys
from pathlib import Path


DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
import deploy as D  # noqa: E402


def test_prune_rejects_absolute_and_parent_escape_manifest_entries(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    absolute_victim = outside / "absolute.stc.md"
    parent_victim = outside / "SKILL.md"
    absolute_victim.write_text("keep", encoding="utf-8")
    parent_victim.write_text("keep", encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "codex": {
                    "files": [
                        str(absolute_victim),
                        os.path.join("..", "outside", "SKILL.md"),
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    old_manifest = D.MANIFEST
    D.MANIFEST = str(manifest)
    try:
        pruned = D._prune_orphans("codex", str(native), [])
    finally:
        D.MANIFEST = old_manifest

    assert pruned == []
    assert absolute_victim.read_text(encoding="utf-8") == "keep"
    assert parent_victim.read_text(encoding="utf-8") == "keep"


def test_prune_allows_absolute_paths_only_under_configured_skill_root(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    skill_root = tmp_path / "agents" / "skills"
    skill_root.mkdir(parents=True)
    retired = skill_root / "source-command-old-stc" / "SKILL.md"
    retired.parent.mkdir()
    retired.write_text("old", encoding="utf-8")
    outside = tmp_path / "outside" / "SKILL.md"
    outside.parent.mkdir()
    outside.write_text("keep", encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"codex": {"files": [str(retired), str(outside)]}}),
        encoding="utf-8",
    )
    old_manifest = D.MANIFEST
    D.MANIFEST = str(manifest)
    try:
        pruned = D._prune_orphans(
            "codex", str(native), [], allowed_roots=[str(skill_root)]
        )
    finally:
        D.MANIFEST = old_manifest

    assert str(retired) in pruned
    assert not retired.exists(), "retired skill under the configured root remains"
    assert outside.exists(), "absolute path outside the configured root was removed"


def test_uninstall_allows_absolute_paths_only_under_configured_skill_root(tmp_path):
    native = tmp_path / "native"
    native.mkdir()
    skill_root = tmp_path / "agents" / "skills"
    skill_root.mkdir(parents=True)
    installed = skill_root / "source-command-old-stc" / "SKILL.md"
    installed.parent.mkdir()
    installed.write_text("old", encoding="utf-8")
    outside = tmp_path / "outside" / "SKILL.md"
    outside.parent.mkdir()
    outside.write_text("keep", encoding="utf-8")

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "codex": {
                    "native_dir": str(native),
                    "files": [str(installed), str(outside)],
                    "json": [],
                    "toml": [],
                }
            }
        ),
        encoding="utf-8",
    )
    old_manifest = D.MANIFEST
    D.MANIFEST = str(manifest)
    try:
        D._uninstall_one(
            "codex", json.loads(manifest.read_text(encoding="utf-8")),
            allowed_roots=[str(skill_root)],
        )
    finally:
        D.MANIFEST = old_manifest

    assert not installed.exists(), "installed skill under the configured root remains"
    assert outside.exists(), "uninstall removed an absolute path outside the configured root"


def test_backup_keeps_private_sources_but_never_secrets(tmp_path):
    """REGRESSION (external review 2026-09-23): user/ is gitignored, so the
    profile and the glossary had no history anywhere — a promised «roll back in
    one command» could not restore them. The snapshot keeps the markdown
    sources; secrets.env must never ride along."""
    import checks as C

    repo = tmp_path / "repo"
    (repo / "user").mkdir(parents=True)
    (repo / "user" / "profile.md").write_text("профиль", encoding="utf-8")
    (repo / "user" / "secrets.env").write_text("TOKEN=нельзя", encoding="utf-8")
    backups = tmp_path / "backups"

    saved = C.backup_private_sources(str(repo), str(backups), "20260924-000000")

    assert saved == ["user/profile.md"]
    assert (backups / "20260924-000000" / "user" / "profile.md").exists()
    assert not (backups / "20260924-000000" / "user" / "secrets.env").exists()


def test_restore_does_not_dump_private_sources_into_the_harness_dir(tmp_path, capsys):
    """The user/ snapshot belongs to the repo, not to ~/.claude — restore must
    skip it instead of copying (or crashing on) a directory."""
    import checks as C

    backups = tmp_path / "backups"
    snapshot = backups / "20260924-000000"
    (snapshot / "user").mkdir(parents=True)
    (snapshot / "user" / "profile.md").write_text("профиль", encoding="utf-8")
    (snapshot / "settings.json").write_text("{}", encoding="utf-8")
    native = tmp_path / "native"
    native.mkdir()

    C.restore("20260924-000000", str(native), str(backups))

    assert (native / "settings.json").exists()
    assert not (native / "user").exists()
    assert "kept user/" in capsys.readouterr().out
