"""Selected Codex H17 deployment tests using synthetic homes only."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "deploy.py"
SOURCE_REL = Path(".stc/core/hooks/block-secret-read.sh")
NATIVE_REL = Path(".codex/hooks/block-secret-read.stc.sh")
HOOKS_REL = Path(".codex/hooks.json")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _seed_home(home):
    source = home / SOURCE_REL
    native = home / NATIVE_REL
    hooks = home / HOOKS_REL
    source.parent.mkdir(parents=True)
    native.parent.mkdir(parents=True)
    source_bytes = b"synthetic prior H17 source\n"
    native_bytes = b"synthetic prior rendered H17\n"
    source.write_bytes(source_bytes)
    native.write_bytes(native_bytes)
    source.chmod(0o755)
    native.chmod(0o755)
    hooks_bytes = (
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Read|Glob|Grep|Bash|exec|unified_exec|unifiedExec",
                            "_stc_managed": True,
                            "_stc_cap": "H17_secret_read_guard",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": str(home / NATIVE_REL),
                                }
                            ],
                        }
                    ],
                    "PostToolUse": [{"matcher": "*", "hooks": []}],
                }
            },
            indent=2,
        )
        + "\n"
    ).encode()
    hooks.write_bytes(hooks_bytes)
    settings = home / ".codex/settings.json"
    settings.write_text('{"sentinel":"untouched"}\n', encoding="utf-8")
    return {
        "source": source,
        "native": native,
        "hooks": hooks,
        "settings": settings,
        "source_bytes": source_bytes,
        "native_bytes": native_bytes,
        "hooks_bytes": hooks_bytes,
        "source_hash": _digest(source_bytes),
        "native_hash": _digest(native_bytes),
    }


def _run_cli(home, *args):
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(DEPLOY), *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _apply_args(before, *, dry_run=False):
    args = [
        "apply-hook",
        "--target",
        "codex",
        "--hook",
        "H17",
        "--language",
        "ru",
        "--expected-source-sha256",
        before["source_hash"],
        "--expected-native-sha256",
        before["native_hash"],
    ]
    if dry_run:
        args.append("--dry-run")
    return args


def _hook_patch_module():
    deploy_dir = str(REPO / "deploy")
    if deploy_dir not in sys.path:
        sys.path.insert(0, deploy_dir)
    import hook_patch

    return hook_patch


def _inject_edit_during_target_temp_fsync(monkeypatch, patch, target, late_bytes):
    original_mkstemp = patch.tempfile.mkstemp
    original_fsync = patch.os.fsync
    temp_paths = {}
    injected = False

    def track_mkstemp(*args, **kwargs):
        fd, name = original_mkstemp(*args, **kwargs)
        temp_paths[fd] = Path(name)
        return fd, name

    def inject_after_fsync(fd):
        nonlocal injected
        result = original_fsync(fd)
        temp_path = temp_paths.get(fd)
        if (
            not injected
            and temp_path is not None
            and temp_path.name.startswith(f".{target.name}.")
        ):
            target.write_bytes(late_bytes)
            target.chmod(0o640)
            injected = True
        return result

    monkeypatch.setattr(patch.tempfile, "mkstemp", track_mkstemp)
    monkeypatch.setattr(patch.os, "fsync", inject_after_fsync)
    return lambda: injected


def test_apply_hook_dry_run_is_read_only_and_scoped_to_two_code_targets(tmp_path):
    before = _seed_home(tmp_path)

    result = _run_cli(
        tmp_path,
        "apply-hook",
        "--target",
        "codex",
        "--hook",
        "H17",
        "--language",
        "ru",
        "--dry-run",
        "--expected-source-sha256",
        before["source_hash"],
        "--expected-native-sha256",
        before["native_hash"],
    )

    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout
    assert str(before["source"]) in result.stdout
    assert str(before["native"]) in result.stdout
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]
    assert before["hooks"].read_bytes() == before["hooks_bytes"]
    assert before["settings"].read_text(encoding="utf-8") == '{"sentinel":"untouched"}\n'
    assert not (tmp_path / ".stc/backups/hook-patch").exists()


def test_apply_hook_writes_only_rendered_guard_targets_and_verified_backup(tmp_path):
    before = _seed_home(tmp_path)
    dry_run = _run_cli(tmp_path, *_apply_args(before, dry_run=True))
    assert dry_run.returncode == 0, dry_run.stderr
    rendered_hashes = re.findall(r"-> sha256 ([a-f0-9]{64}) mode ([0-7]{4})", dry_run.stdout)
    assert len(rendered_hashes) == 2

    result = _run_cli(tmp_path, *_apply_args(before))

    assert result.returncode == 0, result.stderr
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", result.stdout)
    assert match, result.stdout
    backup_id = match.group(1)
    backup = tmp_path / ".stc/backups/hook-patch" / backup_id
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "applied"
    assert manifest["targets"] == [
        {
            "name": "source",
            "path": str(before["source"]),
            "backup_file": "source.before",
            "before_sha256": before["source_hash"],
            "before_mode": 0o755,
            "after_sha256": _digest(before["source"].read_bytes()),
            "after_mode": 0o755,
        },
        {
            "name": "native",
            "path": str(before["native"]),
            "backup_file": "native.before",
            "before_sha256": before["native_hash"],
            "before_mode": 0o755,
            "after_sha256": rendered_hashes[1][0],
            "after_mode": int(rendered_hashes[1][1], 8),
        },
    ]
    assert before["source"].read_bytes() == (REPO / "core/hooks/block-secret-read.sh").read_bytes()
    assert _digest(before["native"].read_bytes()) == rendered_hashes[1][0]
    assert stat.S_IMODE(before["source"].stat().st_mode) == 0o755
    assert stat.S_IMODE(before["native"].stat().st_mode) == 0o755
    assert (backup / "source.before").read_bytes() == before["source_bytes"]
    assert (backup / "native.before").read_bytes() == before["native_bytes"]
    assert before["hooks"].read_bytes() == before["hooks_bytes"]
    assert before["settings"].read_text(encoding="utf-8") == '{"sentinel":"untouched"}\n'


def test_restore_hook_restores_exact_bytes_and_modes_after_read_only_dry_run(tmp_path):
    before = _seed_home(tmp_path)
    applied = _run_cli(tmp_path, *_apply_args(before))
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", applied.stdout)
    assert applied.returncode == 0, applied.stderr
    assert match, applied.stdout
    backup_id = match.group(1)
    after_source = before["source"].read_bytes()
    after_native = before["native"].read_bytes()

    dry_run = _run_cli(tmp_path, "restore-hook", backup_id, "--dry-run")

    assert dry_run.returncode == 0, dry_run.stderr
    assert "DRY-RUN" in dry_run.stdout
    assert before["source"].read_bytes() == after_source
    assert before["native"].read_bytes() == after_native

    restored = _run_cli(tmp_path, "restore-hook", backup_id)

    assert restored.returncode == 0, restored.stderr
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]
    assert stat.S_IMODE(before["source"].stat().st_mode) == 0o755
    assert stat.S_IMODE(before["native"].stat().st_mode) == 0o755
    manifest = json.loads(
        (tmp_path / ".stc/backups/hook-patch" / backup_id / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "restored"


def test_restore_hook_refuses_both_targets_if_one_was_changed_after_install(tmp_path):
    before = _seed_home(tmp_path)
    applied = _run_cli(tmp_path, *_apply_args(before))
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", applied.stdout)
    assert applied.returncode == 0, applied.stderr
    assert match, applied.stdout
    backup_id = match.group(1)
    installed_source = before["source"].read_bytes()
    installed_native = before["native"].read_bytes()
    before["source"].write_bytes(b"later outside edit\n")

    restored = _run_cli(tmp_path, "restore-hook", backup_id)

    assert restored.returncode != 0
    assert "restore conflict" in restored.stdout
    assert "restored H17" not in restored.stdout
    assert before["source"].read_bytes() == b"later outside edit\n"
    assert before["native"].read_bytes() == installed_native
    assert installed_source != before["source"].read_bytes()


def test_apply_hook_rerun_with_original_before_hashes_is_verified_noop(tmp_path):
    before = _seed_home(tmp_path)
    first = _run_cli(tmp_path, *_apply_args(before))
    assert first.returncode == 0, first.stderr
    backup_ids = list((tmp_path / ".stc/backups/hook-patch").glob("*/manifest.json"))
    assert len(backup_ids) == 1

    rerun = _run_cli(tmp_path, *_apply_args(before))

    assert rerun.returncode == 0, rerun.stderr
    assert "already current" in rerun.stdout
    assert list((tmp_path / ".stc/backups/hook-patch").glob("*/manifest.json")) == backup_ids


def test_second_target_write_failure_retains_backup_and_is_recoverable(tmp_path, monkeypatch):
    before = _seed_home(tmp_path)
    patch = _hook_patch_module()
    original_write = patch._atomic_write

    def fail_native_target(path, data, mode, **kwargs):
        if path == before["native"]:
            raise OSError("synthetic second target write failure")
        return original_write(path, data, mode, **kwargs)

    monkeypatch.setattr(patch, "_atomic_write", fail_native_target)
    with pytest.raises(patch.HookPatchError) as error:
        patch.apply_hook(
            repo_root=str(REPO),
            home=str(tmp_path),
            target="codex",
            hook="H17",
            language="ru",
            expected_source_sha256=before["source_hash"],
            expected_native_sha256=before["native_hash"],
        )

    backup_id = error.value.backup_id
    assert backup_id
    assert before["source"].read_bytes() == (REPO / "core/hooks/block-secret-read.sh").read_bytes()
    assert before["native"].read_bytes() == before["native_bytes"]
    manifest_path = tmp_path / ".stc/backups/hook-patch" / backup_id / "manifest.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "prepared"

    monkeypatch.setattr(patch, "_atomic_write", original_write)
    assert patch.restore_hook(home=str(tmp_path), backup_id=backup_id) == 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]


def test_missing_applied_marker_does_not_prevent_restore(tmp_path, monkeypatch):
    before = _seed_home(tmp_path)
    patch = _hook_patch_module()
    original_write = patch._atomic_write

    def lose_applied_marker(path, data, mode, **kwargs):
        if path.name == "manifest.json" and b'"status": "applied"' in data:
            raise OSError("synthetic lost success marker")
        return original_write(path, data, mode, **kwargs)

    monkeypatch.setattr(patch, "_atomic_write", lose_applied_marker)
    with pytest.raises(patch.HookPatchError) as error:
        patch.apply_hook(
            repo_root=str(REPO),
            home=str(tmp_path),
            target="codex",
            hook="H17",
            language="ru",
            expected_source_sha256=before["source_hash"],
            expected_native_sha256=before["native_hash"],
        )

    backup_id = error.value.backup_id
    assert backup_id
    manifest_path = tmp_path / ".stc/backups/hook-patch" / backup_id / "manifest.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "prepared"
    assert patch.restore_hook(home=str(tmp_path), backup_id=backup_id) == 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]


@pytest.mark.parametrize("corruption", ["backup-bytes", "manifest-json"])
def test_corrupt_backup_refuses_without_changing_targets(tmp_path, corruption):
    before = _seed_home(tmp_path)
    applied = _run_cli(tmp_path, *_apply_args(before))
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", applied.stdout)
    assert applied.returncode == 0, applied.stderr
    assert match, applied.stdout
    backup_dir = tmp_path / ".stc/backups/hook-patch" / match.group(1)
    if corruption == "backup-bytes":
        backup_file = backup_dir / "source.before"
        backup_file.write_bytes(b"truncated backup bytes\n")
    else:
        (backup_dir / "manifest.json").write_bytes(b'{"status":')
    current_source = before["source"].read_bytes()
    current_native = before["native"].read_bytes()

    restored = _run_cli(tmp_path, "restore-hook", match.group(1))

    assert restored.returncode != 0
    if corruption == "backup-bytes":
        assert "backup bytes or mode failed verification" in restored.stdout
    else:
        assert "backup manifest is invalid" in restored.stdout
    assert "restored H17" not in restored.stdout
    assert before["source"].read_bytes() == current_source
    assert before["native"].read_bytes() == current_native


def test_apply_hook_fails_closed_for_mismatched_binding_and_stale_hashes(tmp_path):
    before = _seed_home(tmp_path)
    before["hooks"].write_text('{"hooks":{}}\n', encoding="utf-8")
    mismatched_binding = _run_cli(tmp_path, *_apply_args(before))
    assert mismatched_binding.returncode != 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]

    before["hooks"].write_bytes(before["hooks_bytes"])
    stale_args = _apply_args(before)
    source_hash_index = stale_args.index("--expected-source-sha256") + 1
    stale_args[source_hash_index] = "0" * 64
    stale_hash = _run_cli(tmp_path, *stale_args)
    assert stale_hash.returncode != 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]


def test_apply_hook_fails_closed_on_symlink_target(tmp_path):
    before = _seed_home(tmp_path)
    outside = tmp_path / "outside-synthetic-hook"
    outside.write_bytes(b"outside sentinel\n")
    before["native"].unlink()
    before["native"].symlink_to(outside)

    result = _run_cli(tmp_path, *_apply_args(before))

    assert result.returncode != 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].is_symlink()
    assert outside.read_bytes() == b"outside sentinel\n"


def test_restore_hook_rejects_symlinked_backup_id_directory(tmp_path):
    before = _seed_home(tmp_path)
    applied = _run_cli(tmp_path, *_apply_args(before))
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", applied.stdout)
    assert applied.returncode == 0, applied.stderr
    assert match, applied.stdout
    backup_root = tmp_path / ".stc/backups/hook-patch"
    backup_dir = backup_root / match.group(1)
    moved_backup = tmp_path / "saved-synthetic-backup"
    backup_dir.rename(moved_backup)
    backup_dir.symlink_to(moved_backup, target_is_directory=True)
    installed_source = before["source"].read_bytes()
    installed_native = before["native"].read_bytes()

    restored = _run_cli(tmp_path, "restore-hook", match.group(1))

    assert restored.returncode != 0
    assert "unsafe non-directory path" in restored.stdout
    assert before["source"].read_bytes() == installed_source
    assert before["native"].read_bytes() == installed_native


def test_apply_preserves_target_edit_arriving_during_target_temp_fsync(tmp_path, monkeypatch):
    before = _seed_home(tmp_path)
    patch = _hook_patch_module()
    late_bytes = b"outside edit during apply\n"

    injected = _inject_edit_during_target_temp_fsync(monkeypatch, patch, before["source"], late_bytes)

    with pytest.raises(patch.HookPatchError) as error:
        patch.apply_hook(
            repo_root=str(REPO),
            home=str(tmp_path),
            target="codex",
            hook="H17",
            language="ru",
            expected_source_sha256=before["source_hash"],
            expected_native_sha256=before["native_hash"],
        )

    assert error.value.backup_id
    assert "precondition" in str(error.value)
    assert injected()
    assert before["source"].read_bytes() == late_bytes
    assert stat.S_IMODE(before["source"].stat().st_mode) == 0o640
    assert before["native"].read_bytes() == before["native_bytes"]


def test_restore_preserves_target_edit_arriving_during_target_temp_fsync(tmp_path, monkeypatch):
    before = _seed_home(tmp_path)
    applied = _run_cli(tmp_path, *_apply_args(before))
    match = re.search(r"backup_id=([0-9]{8}-[0-9]{6}-[a-f0-9]{12})", applied.stdout)
    assert applied.returncode == 0, applied.stderr
    assert match, applied.stdout
    backup_id = match.group(1)
    patch = _hook_patch_module()
    late_bytes = b"outside edit during restore\n"

    injected = _inject_edit_during_target_temp_fsync(monkeypatch, patch, before["source"], late_bytes)

    with pytest.raises(patch.HookPatchError) as error:
        patch.restore_hook(home=str(tmp_path), backup_id=backup_id)

    assert error.value.backup_id == backup_id
    assert "precondition" in str(error.value)
    assert injected()
    assert before["source"].read_bytes() == late_bytes
    assert stat.S_IMODE(before["source"].stat().st_mode) == 0o640
    assert before["native"].read_bytes() != before["native_bytes"]


@pytest.mark.parametrize(
    "unsupported",
    [
        ["apply-hook", "--target", "claude", "--hook", "H17", "--language", "ru"],
        ["apply-hook", "--target", "codex", "--hook", "H18", "--language", "ru"],
        ["restore-hook", "../outside"],
    ],
)
def test_scoped_cli_rejects_other_targets_hooks_and_backup_paths(tmp_path, unsupported):
    before = _seed_home(tmp_path)
    result = _run_cli(tmp_path, *unsupported)

    assert result.returncode != 0
    assert before["source"].read_bytes() == before["source_bytes"]
    assert before["native"].read_bytes() == before["native_bytes"]
