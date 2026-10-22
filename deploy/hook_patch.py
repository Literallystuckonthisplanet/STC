"""Narrow, reversible installation of Codex H17 from the versioned renderer."""

from __future__ import annotations

import copy
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import time
from pathlib import Path

import render as R


_HOOKS = {
    "H17": "H17_secret_read_guard",
}
_BACKUP_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-f0-9]{12}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SOURCE_NAME = "block-secret-read.sh"
_NATIVE_NAME = "block-secret-read.stc.sh"
_HOOKS_FILE = "hooks.json"
_MANIFEST = "manifest.json"
_LOCK = ".lock"


class HookPatchError(RuntimeError):
    """A fail-closed refusal containing only sanitized status text."""

    def __init__(self, message: str, backup_id: str | None = None):
        super().__init__(message)
        self.backup_id = backup_id


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_regular_file(path: Path) -> tuple[bytes, int]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise HookPatchError(f"required file unavailable: {path}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise HookPatchError(f"unsafe non-regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise HookPatchError(f"could not safely open file: {path}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise HookPatchError(f"file changed during read: {path}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), stat.S_IMODE(opened.st_mode)
    finally:
        os.close(fd)


def _safe_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise HookPatchError(f"required directory unavailable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise HookPatchError(f"unsafe non-directory path: {path}")


def _safe_private_directory(path: Path) -> None:
    _safe_directory(path)
    if stat.S_IMODE(path.lstat().st_mode) != 0o700:
        raise HookPatchError(f"hook-patch directory is not private: {path}")


def _backup_root(home: Path) -> Path:
    return home / ".stc" / "backups" / "hook-patch"


def _ensure_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _safe_directory(path)
        return
    _ensure_directory(path.parent)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    _safe_directory(path)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(
    path: Path,
    data: bytes,
    mode: int,
    *,
    replace: bool = True,
    expected_state: tuple[bytes, int] | None = None,
) -> None:
    """Stage a file, then compare its destination immediately before replace."""
    _safe_directory(path.parent)
    if replace and expected_state is None:
        raise HookPatchError("replacement requires an expected content and mode state")
    if not replace and expected_state is not None:
        raise HookPatchError("create-only write cannot have a replacement precondition")
    if replace:
        try:
            current_state = _safe_regular_file(path)
        except HookPatchError as exc:
            raise HookPatchError(f"replacement precondition unavailable at {path}") from exc
        if current_state != expected_state:
            raise HookPatchError(f"replacement precondition failed at {path}; target unchanged")
    elif path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise HookPatchError(f"unsafe write destination: {path}")
        raise HookPatchError(f"unexpected existing backup file: {path}")
    token = secrets.token_hex(8)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.{token}.", dir=path.parent)
    tmp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        if replace:
            try:
                current_state = _safe_regular_file(path)
            except HookPatchError as exc:
                raise HookPatchError(f"replacement precondition unavailable at {path}") from exc
            if current_state != expected_state:
                raise HookPatchError(f"replacement precondition failed at {path}; target unchanged")
        elif path.exists() or path.is_symlink():
            raise HookPatchError(f"unexpected existing backup file: {path}")
        # This compare narrows the staging race but is not an OS-level CAS.
        # The runbook requires unrelated writers to stay inactive here.
        os.replace(tmp_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def _operation_lock(root: Path, *, create: bool):
    if create:
        _ensure_directory(root)
        _safe_private_directory(root)
    else:
        _safe_private_directory(root)
    lock_path = root / _LOCK
    if create:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    else:
        flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise HookPatchError("hook-patch lock is unavailable or unsafe") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise HookPatchError("hook-patch lock is not a private regular file")
        if create:
            os.fsync(fd)
            _fsync_directory(root)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _target_paths(repo_root: Path, home: Path, adapter: dict) -> tuple[Path, Path, Path, Path]:
    native_dir_value = str(adapter.get("native_dir", ""))
    native_dir = native_dir_value.replace("${HOME}", str(home))
    expected_native_dir = home / ".codex"
    if Path(os.path.normpath(native_dir)) != expected_native_dir:
        raise HookPatchError("Codex adapter native path is outside the supported target")

    source = repo_root / "core" / "hooks" / _SOURCE_NAME
    stc_target = home / ".stc" / "core" / "hooks" / _SOURCE_NAME
    native_target = expected_native_dir / "hooks" / _NATIVE_NAME
    hooks_json = expected_native_dir / _HOOKS_FILE
    for directory in (
        repo_root / "core" / "hooks",
        home / ".stc",
        home / ".stc" / "core",
        home / ".stc" / "core" / "hooks",
        expected_native_dir,
        expected_native_dir / "hooks",
    ):
        _safe_directory(directory)
    return source, stc_target, native_target, hooks_json


def _render_selected(repo_root: Path, source: Path, native_target: Path, adapter: dict, language: str) -> tuple[bytes, dict]:
    cap_name = _HOOKS["H17"]
    hooks = adapter.get("hooks") or {}
    capabilities = hooks.get("capabilities") or {}
    cap = capabilities.get(cap_name)
    if (
        adapter.get("harness") != "codex"
        or adapter.get("harness_facts", {}).get("capability_delivery") != "files"
        or adapter.get("harness_facts", {}).get("hook_config_file") != _HOOKS_FILE
        or not isinstance(cap, dict)
        or cap.get("supported") is not True
        or (cap.get("binding") or {}).get("file") != _SOURCE_NAME
    ):
        raise HookPatchError("versioned Codex adapter does not expose the supported H17 binding")

    selected = copy.deepcopy(adapter)
    selected["hooks"]["capabilities"] = {cap_name: copy.deepcopy(cap)}
    # H17 has no apply_patch input. The Codex-wide normalizer is unrelated and
    # must not create a second artifact in this exact two-file operation.
    selected["harness_facts"]["apply_patch_normalize"] = False
    result = R.RenderResult()
    try:
        R._render_hooks(
            str(repo_root / "core"),
            selected,
            {"USER_LANG": language},
            result,
            "hooks",
            disabled=(),
        )
    except Exception as exc:
        raise HookPatchError("selected H17 render failed") from exc

    rendered_rel = "hooks/" + _NATIVE_NAME
    body = result.files.get(rendered_rel)
    patch = result.json_patches.get(_HOOKS_FILE)
    if not isinstance(body, str) or not isinstance(patch, dict):
        raise HookPatchError("selected H17 renderer output is incomplete")
    if set(result.files) != {rendered_rel} or set(result.json_patches) != {_HOOKS_FILE}:
        raise HookPatchError("selected H17 renderer produced an unexpected artifact")
    events = patch.get("hooks")
    entries = events.get("PreToolUse") if isinstance(events, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or len(events) != 1:
        raise HookPatchError("selected H17 renderer produced unexpected hook routing")
    expected_entry = copy.deepcopy(entries[0])
    for handler in expected_entry.get("hooks", []):
        if isinstance(handler, dict):
            handler["command"] = handler.get("command", "").replace(
                "$NATIVE_DIR", str(native_target.parent.parent)
            )
    return body.replace("$NATIVE_DIR", str(native_target.parent.parent)).encode("utf-8"), expected_entry


def _verify_binding(hooks_json: Path, expected_entry: dict) -> None:
    raw, _ = _safe_regular_file(hooks_json)
    try:
        config = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HookPatchError("Codex hooks.json is invalid; H17 binding was not changed") from exc
    if not isinstance(config, dict) or not isinstance(config.get("hooks"), dict):
        raise HookPatchError("Codex hooks.json has an invalid shape; H17 binding was not changed")
    matches = []
    for event, entries in config["hooks"].items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("_stc_cap") == _HOOKS["H17"]:
                matches.append((event, entry))
    if len(matches) != 1 or matches[0] != ("PreToolUse", expected_entry):
        raise HookPatchError("existing Codex H17 binding is missing or mismatched")


def _make_plan(
    repo_root: Path,
    home: Path,
    target: str,
    hook: str,
    language: str,
    expected_source_sha256: str,
    expected_native_sha256: str,
) -> dict:
    if target != "codex" or hook != "H17" or language not in ("en", "ru"):
        raise HookPatchError("only --target codex --hook H17 --language en|ru is supported")
    if not _SHA256.fullmatch(expected_source_sha256 or "") or not _SHA256.fullmatch(expected_native_sha256 or ""):
        raise HookPatchError("expected-before SHA-256 arguments are required")
    try:
        adapter = R.load_adapter(str(repo_root), "codex")
    except Exception as exc:
        raise HookPatchError("versioned Codex adapter is unavailable") from exc
    source, stc_target, native_target, hooks_json = _target_paths(repo_root, home, adapter)
    source_after, source_mode = _safe_regular_file(source)
    stc_before, stc_mode = _safe_regular_file(stc_target)
    native_before, native_mode = _safe_regular_file(native_target)
    expected_native_mode = source_mode | 0o111
    if source_mode != expected_native_mode or stc_mode != source_mode or native_mode != expected_native_mode:
        raise HookPatchError("pre-install file modes do not match the versioned executable-hook mode")
    native_after, expected_entry = _render_selected(repo_root, source, native_target, adapter, language)
    _verify_binding(hooks_json, expected_entry)
    expected_before_matches = (
        _sha256(stc_before) == expected_source_sha256
        and _sha256(native_before) == expected_native_sha256
    )
    return {
        "home": home,
        "source": source,
        "hooks_json": hooks_json,
        "expected_before_matches": expected_before_matches,
        "targets": [
            {
                "name": "source",
                "path": stc_target,
                "before": stc_before,
                "before_sha256": _sha256(stc_before),
                "before_mode": stc_mode,
                "after": source_after,
                "after_sha256": _sha256(source_after),
                "after_mode": source_mode,
                "backup_file": "source.before",
            },
            {
                "name": "native",
                "path": native_target,
                "before": native_before,
                "before_sha256": _sha256(native_before),
                "before_mode": native_mode,
                "after": native_after,
                "after_sha256": _sha256(native_after),
                "after_mode": expected_native_mode,
                "backup_file": "native.before",
            },
        ],
    }


def _print_plan(plan: dict, language: str) -> None:
    print(f"DRY-RUN apply-hook target=codex hook=H17 language={language}")
    print(f"binding verified read-only: {plan['hooks_json']}")
    print(f"backup metadata root: {_backup_root(plan['home'])}")
    for item in plan["targets"]:
        print(
            f"would write {item['path']}: "
            f"sha256 {item['before_sha256']} mode {item['before_mode']:04o} -> "
            f"sha256 {item['after_sha256']} mode {item['after_mode']:04o}"
        )


def apply_hook(
    *,
    repo_root: str,
    home: str,
    target: str,
    hook: str,
    language: str,
    expected_source_sha256: str,
    expected_native_sha256: str,
    dry_run: bool = False,
) -> int:
    home_path = Path(home).absolute()
    if dry_run:
        plan = _make_plan(
            Path(repo_root).resolve(),
            home_path,
            target,
            hook,
            language,
            expected_source_sha256,
            expected_native_sha256,
        )
        if _states_match(plan, "after"):
            if not plan["expected_before_matches"] and not _matching_backup_for_plan(
                _backup_root(home_path), home_path, plan, expected_source_sha256, expected_native_sha256
            ):
                raise HookPatchError("already rendered state found, but expected-before hashes are stale")
            print("DRY-RUN verified no-op: H17 is already at the rendered version")
            return 0
        if not plan["expected_before_matches"]:
            raise HookPatchError("expected-before hash does not match the active H17 files")
        if not _states_match(plan, "before"):
            raise HookPatchError("active H17 target is neither the expected before nor rendered after state")
        _print_plan(plan, language)
        return 0

    root = _backup_root(home_path)
    try:
        with _operation_lock(root, create=True):
            plan = _make_plan(
                Path(repo_root).resolve(),
                home_path,
                target,
                hook,
                language,
                expected_source_sha256,
                expected_native_sha256,
            )
            if _states_match(plan, "after"):
                if plan["expected_before_matches"] or _matching_backup_for_plan(
                    root, home_path, plan, expected_source_sha256, expected_native_sha256
                ):
                    print("✓ already current: H17 target bytes and modes match; no backup created")
                    return 0
                raise HookPatchError("already rendered state found, but expected-before hashes are stale")
            if not plan["expected_before_matches"]:
                if _states_are_mixed_before_after(plan):
                    matching = _matching_backup_for_plan(
                        root, home_path, plan, expected_source_sha256, expected_native_sha256
                    )
                    if matching:
                        raise HookPatchError(
                            f"partial H17 state detected; recover with restore-hook {matching}", matching
                        )
                    raise HookPatchError("partial H17 state detected without a matching recovery backup")
                raise HookPatchError("expected-before hash does not match the active H17 files")
            if not _states_match(plan, "before"):
                raise HookPatchError("active H17 target is neither the expected before nor rendered after state")

            backup_id, backup_dir, manifest = _new_backup(plan, language, root)
            try:
                _write_state(plan, backup_dir / _MANIFEST, manifest, backup_id)
            except HookPatchError as exc:
                if exc.backup_id:
                    raise
                raise HookPatchError(str(exc), backup_id) from exc
            print(f"✓ applied H17; backup_id={backup_id}")
            for item in plan["targets"]:
                print(
                    f"updated {item['path']}: sha256 {item['before_sha256']} -> "
                    f"{item['after_sha256']} mode {item['before_mode']:04o} -> {item['after_mode']:04o}"
                )
            return 0
    except HookPatchError:
        raise
    except Exception as exc:
        raise HookPatchError("selected H17 installation failed safely") from exc


def _target_state(item: dict) -> tuple[str, int]:
    data, mode = _safe_regular_file(item["path"])
    return _sha256(data), mode


def _states_match(plan: dict, key: str) -> bool:
    return all(
        _target_state(item) == (item[f"{key}_sha256"], item[f"{key}_mode"])
        for item in plan["targets"]
    )


def _states_are_mixed_before_after(plan: dict) -> bool:
    states = [_target_state(item) for item in plan["targets"]]
    allowed = [
        (item["before_sha256"], item["before_mode"])
        for item in plan["targets"]
    ]
    after = [
        (item["after_sha256"], item["after_mode"])
        for item in plan["targets"]
    ]
    return all(state in (before, new) for state, before, new in zip(states, allowed, after)) and any(
        state == new for state, new in zip(states, after)
    ) and any(state == before for state, before in zip(states, allowed))


def _manifest_for(plan: dict, backup_id: str, language: str) -> dict:
    return {
        "version": 1,
        "backup_id": backup_id,
        "target": "codex",
        "hook": "H17",
        "language": language,
        "status": "prepared",
        "targets": [
            {
                "name": item["name"],
                "path": str(item["path"]),
                "backup_file": item["backup_file"],
                "before_sha256": item["before_sha256"],
                "before_mode": item["before_mode"],
                "after_sha256": item["after_sha256"],
                "after_mode": item["after_mode"],
            }
            for item in plan["targets"]
        ],
    }


def _manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _new_backup(plan: dict, language: str, root: Path) -> tuple[str, Path, dict]:
    _safe_private_directory(root)
    for _ in range(5):
        backup_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(6)
        directory = root / backup_id
        try:
            os.mkdir(directory, 0o700)
            break
        except FileExistsError:
            continue
    else:
        raise HookPatchError("could not allocate a unique hook-patch backup")

    manifest = _manifest_for(plan, backup_id, language)
    try:
        _safe_private_directory(directory)
        _fsync_directory(root)
        for item in plan["targets"]:
            backup_file = directory / item["backup_file"]
            _atomic_write(backup_file, item["before"], 0o600, replace=False)
            backup_data, backup_mode = _safe_regular_file(backup_file)
            if backup_data != item["before"] or backup_mode != 0o600:
                raise HookPatchError("backup verification failed")
        manifest_path = directory / _MANIFEST
        expected_manifest = _manifest_bytes(manifest)
        _atomic_write(manifest_path, expected_manifest, 0o600, replace=False)
        written_manifest, written_mode = _safe_regular_file(manifest_path)
        if written_manifest != expected_manifest or written_mode != 0o600:
            raise HookPatchError("backup manifest verification failed")
        _fsync_directory(directory)
    except Exception as exc:
        if isinstance(exc, HookPatchError):
            raise HookPatchError(str(exc), backup_id) from exc
        raise HookPatchError("backup creation failed", backup_id) from exc
    return backup_id, directory, manifest


def _write_state(plan: dict, manifest_path: Path, manifest: dict, backup_id: str) -> None:
    for index, item in enumerate(plan["targets"]):
        current_expected = [
            (target["after_sha256"], target["after_mode"])
            if prior < index
            else (target["before_sha256"], target["before_mode"])
            for prior, target in enumerate(plan["targets"])
        ]
        observed = [_target_state(target) for target in plan["targets"]]
        if observed != current_expected:
            raise HookPatchError("H17 target changed during install; backup retained", backup_id)
        try:
            _atomic_write(
                item["path"],
                item["after"],
                item["after_mode"],
                expected_state=(item["before"], item["before_mode"]),
            )
            if _target_state(item) != (item["after_sha256"], item["after_mode"]):
                raise HookPatchError("installed target verification failed", backup_id)
        except Exception as exc:
            if isinstance(exc, HookPatchError):
                if exc.backup_id:
                    raise
                raise HookPatchError(str(exc), backup_id) from exc
            raise HookPatchError("target write failed; backup retained", backup_id) from exc

    if not _states_match(plan, "after"):
        raise HookPatchError("installed target verification failed; backup retained", backup_id)
    expected_manifest_before = _manifest_bytes(manifest)
    manifest["status"] = "applied"
    try:
        expected_manifest = _manifest_bytes(manifest)
        _atomic_write(
            manifest_path,
            expected_manifest,
            0o600,
            expected_state=(expected_manifest_before, 0o600),
        )
        written_manifest, written_mode = _safe_regular_file(manifest_path)
        if written_manifest != expected_manifest or written_mode != 0o600:
            raise HookPatchError("applied marker verification failed", backup_id)
    except Exception as exc:
        raise HookPatchError("targets applied; success marker not saved; backup retained", backup_id) from exc


def _read_backup(root: Path, backup_id: str, home: Path) -> tuple[Path, dict, list[bytes], bytes]:
    if not _BACKUP_ID.fullmatch(backup_id or ""):
        raise HookPatchError("invalid hook-patch backup id")
    for directory in (home, home / ".stc", home / ".stc" / "backups"):
        _safe_directory(directory)
    _safe_private_directory(root)
    directory = root / backup_id
    _safe_private_directory(directory)
    if directory.parent != root or Path(os.path.realpath(directory)).parent != Path(os.path.realpath(root)):
        raise HookPatchError("backup path is outside the dedicated hook-patch root")
    manifest_path = directory / _MANIFEST
    raw_manifest, manifest_mode = _safe_regular_file(manifest_path)
    if manifest_mode != 0o600 or len(raw_manifest) > 65536:
        raise HookPatchError("backup manifest has unsafe mode or size")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HookPatchError("backup manifest is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or manifest.get("backup_id") != backup_id
        or manifest.get("target") != "codex"
        or manifest.get("hook") != "H17"
        or manifest.get("status") not in ("prepared", "applied", "restored")
    ):
        raise HookPatchError("backup manifest is not a supported H17 record")
    expected_paths = [
        home / ".stc" / "core" / "hooks" / _SOURCE_NAME,
        home / ".codex" / "hooks" / _NATIVE_NAME,
    ]
    records = manifest.get("targets")
    if not isinstance(records, list) or len(records) != 2:
        raise HookPatchError("backup manifest target set is incomplete")
    names = ["source", "native"]
    backup_names = ["source.before", "native.before"]
    backup_bytes = []
    for index, (record, expected_path) in enumerate(zip(records, expected_paths)):
        if (
            not isinstance(record, dict)
            or record.get("name") != names[index]
            or record.get("path") != str(expected_path)
            or record.get("backup_file") != backup_names[index]
            or not _SHA256.fullmatch(record.get("before_sha256", ""))
            or not _SHA256.fullmatch(record.get("after_sha256", ""))
            or not isinstance(record.get("before_mode"), int)
            or not isinstance(record.get("after_mode"), int)
            or record["before_mode"] < 0
            or record["before_mode"] != 0o755
            or record["after_mode"] != 0o755
        ):
            raise HookPatchError("backup manifest target record is invalid")
        for parent in (expected_path.parent.parent, expected_path.parent):
            _safe_directory(parent)
        data, mode = _safe_regular_file(directory / backup_names[index])
        if mode != 0o600 or _sha256(data) != record["before_sha256"]:
            raise HookPatchError("backup bytes or mode failed verification")
        backup_bytes.append(data)
    return directory, manifest, backup_bytes, raw_manifest


def _matching_backup_for_plan(
    root: Path,
    home: Path,
    plan: dict,
    expected_source_sha256: str,
    expected_native_sha256: str,
) -> str | None:
    if not root.exists() and not root.is_symlink():
        return None
    for parent in (home, home / ".stc", home / ".stc" / "backups", root):
        _safe_directory(parent)
    for entry in root.iterdir():
        backup_id = entry.name
        if not _BACKUP_ID.fullmatch(backup_id):
            continue
        _safe_directory(entry)
        try:
            _, manifest, _, _ = _read_backup(root, backup_id, home)
        except HookPatchError:
            continue
        records = manifest["targets"]
        before_expected = [expected_source_sha256, expected_native_sha256]
        if all(
            record["before_sha256"] == before
            and record["after_sha256"] == item["after_sha256"]
            and record["after_mode"] == item["after_mode"]
            for record, before, item in zip(records, before_expected, plan["targets"])
        ):
            return backup_id
    return None


def _restore_plan(root: Path, backup_id: str, home: Path) -> dict:
    directory, manifest, backup_bytes, manifest_bytes = _read_backup(root, backup_id, home)
    targets = []
    current_states = []
    for record, before in zip(manifest["targets"], backup_bytes):
        path = Path(record["path"])
        data, mode = _safe_regular_file(path)
        before_sha = record["before_sha256"]
        after_sha = record["after_sha256"]
        current = (_sha256(data), mode)
        before_state = (before_sha, record["before_mode"])
        after_state = (after_sha, record["after_mode"])
        if current not in (before_state, after_state):
            raise HookPatchError(f"restore conflict at {path}; no targets changed")
        targets.append(
            {
                "name": record["name"],
                "path": path,
                "before": before,
                "before_sha256": before_sha,
                "before_mode": record["before_mode"],
                "after_sha256": after_sha,
                "after_mode": record["after_mode"],
            }
        )
        current_states.append(current)
    return {
        "directory": directory,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_path": directory / _MANIFEST,
        "targets": targets,
        "current_states": current_states,
    }


def _restore_targets(plan: dict, backup_id: str) -> None:
    targets = plan["targets"]
    for index, item in enumerate(targets):
        current_files = [_safe_regular_file(target["path"]) for target in targets]
        observed = [(_sha256(data), mode) for data, mode in current_files]
        allowed = [
            (
                (target["before_sha256"], target["before_mode"]),
                (target["after_sha256"], target["after_mode"]),
            )
            for target in targets
        ]
        if any(state not in pair for state, pair in zip(observed, allowed)):
            raise HookPatchError("restore state changed during operation; no unsafe overwrite", backup_id)
        before_state = (item["before_sha256"], item["before_mode"])
        after_state = (item["after_sha256"], item["after_mode"])
        if observed[index] == before_state:
            continue
        if observed[index] != after_state:
            raise HookPatchError("restore state changed during operation; no unsafe overwrite", backup_id)
        try:
            _atomic_write(
                item["path"],
                item["before"],
                item["before_mode"],
                expected_state=current_files[index],
            )
            if _target_state(item) != (item["before_sha256"], item["before_mode"]):
                raise HookPatchError("restored target verification failed", backup_id)
        except Exception as exc:
            if isinstance(exc, HookPatchError) and exc.backup_id:
                raise
            reason = str(exc) if isinstance(exc, HookPatchError) else "restore write failed"
            raise HookPatchError(f"{reason}; backup retained", backup_id) from exc

    if any(
        _target_state(item) != (item["before_sha256"], item["before_mode"])
        for item in targets
    ):
        raise HookPatchError("restore verification failed; backup retained", backup_id)
    manifest = plan["manifest"]
    manifest["status"] = "restored"
    try:
        expected_manifest = _manifest_bytes(manifest)
        _atomic_write(
            plan["manifest_path"],
            expected_manifest,
            0o600,
            expected_state=(plan["manifest_bytes"], 0o600),
        )
        written_manifest, written_mode = _safe_regular_file(plan["manifest_path"])
        if written_manifest != expected_manifest or written_mode != 0o600:
            raise HookPatchError("restored marker verification failed", backup_id)
    except Exception as exc:
        # Target state is authoritative, so a later retry remains a safe no-op.
        raise HookPatchError("targets restored; status marker not saved; backup retained", backup_id) from exc


def restore_hook(*, home: str, backup_id: str, dry_run: bool = False) -> int:
    home_path = Path(home).absolute()
    root = _backup_root(home_path)

    def show(plan: dict, prefix: str) -> None:
        print(f"{prefix} restore-hook backup_id={backup_id} status={plan['manifest']['status']}")
        for item, current in zip(plan["targets"], plan["current_states"]):
            state = "before" if current == (item["before_sha256"], item["before_mode"]) else "after"
            action = "leave" if state == "before" else "restore"
            print(
                f"{action} {item['path']}: current {state} sha256 {current[0]} mode {current[1]:04o} -> "
                f"sha256 {item['before_sha256']} mode {item['before_mode']:04o}"
            )

    try:
        if dry_run:
            plan = _restore_plan(root, backup_id, home_path)
            show(plan, "DRY-RUN")
            return 0
        for directory in (home_path, home_path / ".stc", home_path / ".stc" / "backups"):
            _safe_directory(directory)
        _safe_private_directory(root)
        with _operation_lock(root, create=False):
            plan = _restore_plan(root, backup_id, home_path)
            show(plan, "RESTORE")
            _restore_targets(plan, backup_id)
            print(f"✓ restored H17; backup_id={backup_id}")
            return 0
    except HookPatchError:
        raise
    except Exception as exc:
        raise HookPatchError("selected H17 restore failed safely", backup_id) from exc

