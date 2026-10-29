"""Narrow, reversible installation of versioned H17 artifacts."""

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
_SUPPORTED_ADAPTERS = ("claude", "codex", "zcode")
_SHARED_ARTIFACTS = (
    ("policy", "secret_read_policy.py"),
    ("source_claude_zcode", "secret-read-guard.sh"),
    ("source_codex", "block-secret-read.sh"),
)


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
    varmap = R.resolve_vars(selected, {}, {})
    varmap["USER_LANG"] = language
    varmap["STC_CORE"] = str(native_target.parent.parent.parent / ".stc" / "core")
    varmap["HARNESS_NAME"] = "codex"
    try:
        R._render_hooks(
            str(repo_root / "core"),
            selected,
            varmap,
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
    policy_source = repo_root / "core" / "hooks" / "secret_read_policy.py"
    policy_target = home / ".stc" / "core" / "hooks" / "secret_read_policy.py"
    desired_policy, desired_policy_mode = _safe_regular_file(policy_source)
    try:
        installed_policy, installed_policy_mode = _safe_regular_file(policy_target)
    except HookPatchError as exc:
        raise HookPatchError(
            "legacy Codex apply-hook requires the exact shared H17 policy; "
            "use the explicit aggregate path --target claude,codex,zcode"
        ) from exc
    if installed_policy != desired_policy or installed_policy_mode != desired_policy_mode:
        raise HookPatchError(
            "legacy Codex apply-hook requires the exact shared H17 policy; "
            "use the explicit aggregate path --target claude,codex,zcode"
        )
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


def _safe_optional_regular_file(path: Path) -> tuple[bytes | None, int | None]:
    """Read a regular target or return (None, None) for a genuinely absent file."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise HookPatchError(f"target state unavailable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise HookPatchError(f"unsafe non-regular target: {path}")
    return _safe_regular_file(path)


def _expanded_native_dir(home: Path, adapter: dict, target: str) -> Path:
    value = str(adapter.get("native_dir", "")).replace("${HOME}", str(home))
    expected = home / {"claude": ".claude", "codex": ".codex", "zcode": ".zcode"}[target]
    if Path(os.path.normpath(value)) != expected:
        raise HookPatchError(f"{target} adapter native path is outside its supported target")
    _safe_directory(expected)
    return expected


def _adapter_h17_render(repo_root: Path, home: Path, target: str, adapter: dict) -> tuple[Path, bytes, int, Path, dict]:
    """Render one H17 native wrapper and return its installed binding location."""
    cap_name = _HOOKS["H17"]
    hooks = adapter.get("hooks") or {}
    capabilities = hooks.get("capabilities") or {}
    cap = capabilities.get(cap_name)
    facts = adapter.get("harness_facts") or {}
    delivery = facts.get("capability_delivery", "files")
    source_name = {
        "claude": "secret-read-guard.sh",
        "codex": "block-secret-read.sh",
        "zcode": "secret-read-guard.sh",
    }[target]
    config_name = facts.get("hook_config_file")
    if (
        adapter.get("harness") != target
        or delivery not in ("files", "plugin")
        or config_name != ("plugin hooks.json" if delivery == "plugin" else ("hooks.json" if target == "codex" else "settings.json"))
        or not isinstance(cap, dict)
        or cap.get("supported") is not True
        or (cap.get("binding") or {}).get("file") != source_name
    ):
        raise HookPatchError(f"versioned {target} adapter does not expose the supported H17 binding")
    native_dir = _expanded_native_dir(home, adapter, target)
    selected = copy.deepcopy(adapter)
    selected["hooks"]["capabilities"] = {cap_name: copy.deepcopy(cap)}
    selected["harness_facts"]["apply_patch_normalize"] = False
    varmap = R.resolve_vars(selected, {}, {})
    varmap["STC_CORE"] = str(home / ".stc" / "core")
    varmap["HARNESS_NAME"] = target
    native_hooks_rel = "hooks" if delivery == "files" else f"{R.PLUGIN_DIR}/hooks"
    result = R.RenderResult()
    try:
        R._render_hooks(str(repo_root / "core"), selected, varmap, result, native_hooks_rel, disabled=())
    except Exception as exc:
        raise HookPatchError(f"selected {target} H17 render failed") from exc
    wrapper_name = source_name.replace(".sh", ".stc.sh")
    rendered_rel = os.path.join(native_hooks_rel, wrapper_name)
    rendered = result.files.get(rendered_rel)
    if not isinstance(rendered, str):
        raise HookPatchError(f"selected {target} H17 renderer output is incomplete")
    # The H17 subset must emit only its native wrapper plus, for plugin delivery,
    # the routing metadata and plugin identity artifacts. Those metadata files
    # are inspected but never installed by this scoped operation.
    if delivery == "files":
        if set(result.files) != {rendered_rel} or set(result.json_patches) != {config_name}:
            raise HookPatchError(f"selected {target} H17 renderer produced unexpected artifacts")
        native_path = native_dir / rendered_rel
        binding_config = native_dir / config_name
        try:
            expected_entry = copy.deepcopy(result.json_patches[config_name]["hooks"]["PreToolUse"][0])
        except (KeyError, IndexError, TypeError) as exc:
            raise HookPatchError(f"selected {target} H17 renderer produced invalid routing") from exc
        for handler in expected_entry.get("hooks", []):
            if isinstance(handler, dict):
                handler["command"] = handler.get("command", "").replace("$NATIVE_DIR", str(native_dir))
    else:
        # ZCode's versioned plugin directory is a renderer constant. We only
        # touch the single wrapper inside the existing plugin cache.
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(R.PLUGIN_VERSION)):
            raise HookPatchError("ZCode plugin version is not a supported version string")
        if not str(R.PLUGIN_NAME).replace("-", "").isalnum():
            raise HookPatchError("ZCode plugin identity is not a supported name")
        native_path = native_dir / rendered_rel
        binding_config = native_dir / f"{R.PLUGIN_DIR}/hooks/hooks.json"
        try:
            plugin_json = json.loads(result.files[f"{R.PLUGIN_DIR}/hooks/hooks.json"])
            entries = plugin_json["hooks"]["PreToolUse"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HookPatchError("selected ZCode H17 renderer produced invalid plugin routing") from exc
        expected_entry = next(
            (entry for entry in entries if any(
                isinstance(handler, dict) and handler.get("command", "").endswith("/" + wrapper_name)
                for handler in entry.get("hooks", [])
            )),
            None,
        )
        if not isinstance(expected_entry, dict):
            raise HookPatchError("selected ZCode H17 renderer produced no wrapper binding")
        if not all(f"{R.PLUGIN_DIR}/{name}" in result.files for name in (".zcode-plugin-seed.json", "package.json")):
            raise HookPatchError("selected ZCode H17 renderer produced incomplete plugin metadata")
    source = repo_root / "core" / "hooks" / source_name
    source_bytes, source_mode = _safe_regular_file(source)
    return native_path, rendered.encode("utf-8"), source_mode | 0o111, binding_config, expected_entry


def _verify_adapter_binding(config_path: Path, target: str, expected_entry: dict) -> str:
    raw, _ = _safe_regular_file(config_path)
    try:
        config = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HookPatchError(f"{target} hook config is invalid; H17 binding was not changed") from exc
    hooks = config.get("hooks") if isinstance(config, dict) else None
    if not isinstance(hooks, dict):
        raise HookPatchError(f"{target} hook config has an invalid shape; H17 binding was not changed")
    matches = []
    expected_handlers = expected_entry.get("hooks", [])
    expected_commands = {
        handler.get("command") for handler in expected_handlers
        if isinstance(handler, dict) and isinstance(handler.get("command"), str)
    }
    expected_basenames = {Path(command).name for command in expected_commands}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if target == "zcode":
                handlers = entry.get("hooks", [])
                if any(isinstance(h, dict) and h.get("command", "").endswith("/secret-read-guard.stc.sh") for h in handlers):
                    matches.append((event, entry))
                continue
            handlers = entry.get("hooks", [])
            commands = {
                handler.get("command") for handler in handlers
                if isinstance(handler, dict) and isinstance(handler.get("command"), str)
            } if isinstance(handlers, list) else set()
            same_managed_cap = entry.get("_stc_cap") == _HOOKS["H17"]
            same_command = bool(commands & expected_commands)
            same_basename = any(Path(command).name in expected_basenames for command in commands)
            same_matcher = entry.get("matcher") == expected_entry.get("matcher")
            if same_managed_cap or same_command or (target == "claude" and same_matcher and same_basename):
                matches.append((event, entry))
    if len(matches) != 1:
        raise HookPatchError(f"existing {target} H17 binding is missing or mismatched")
    event, actual_entry = matches[0]
    tags = ("_stc_managed", "_stc_cap")
    expected_base = {key: value for key, value in expected_entry.items() if key not in tags}
    actual_base = {key: value for key, value in actual_entry.items() if key not in tags}
    tags_match = all(
        key not in actual_entry or actual_entry[key] == expected_entry.get(key)
        for key in tags
    )
    if (
        event != "PreToolUse"
        or actual_base != expected_base
        or not tags_match
        or (target == "codex" and not all(key in actual_entry for key in tags))
    ):
        raise HookPatchError(f"existing {target} H17 binding is missing or mismatched")
    # Digest only the selected binding, never disclose or hash unrelated config.
    return _sha256(json.dumps((event, actual_entry), sort_keys=True, separators=(",", ":")).encode())


def _multi_state_digest(plan: dict) -> str:
    projection = {
        "targets": [
            {
                "name": item["name"],
                "path": str(item["path"]),
                "exists": item["before"] is not None,
                "sha256": item["before_sha256"],
                "mode": item["before_mode"],
            }
            for item in plan["targets"]
        ],
        "bindings": plan["bindings"],
    }
    return _sha256(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode())


def _make_multi_plan(repo_root: Path, home: Path, targets: tuple[str, ...], language: str) -> dict:
    if not targets or len(set(targets)) != len(targets) or any(t not in _SUPPORTED_ADAPTERS for t in targets):
        raise HookPatchError("explicit targets must be a unique subset of claude,codex,zcode")
    if language not in ("en", "ru"):
        raise HookPatchError("only H17 language en or ru is supported")
    core_hooks = repo_root / "core" / "hooks"
    shared_dir = home / ".stc" / "core" / "hooks"
    _safe_directory(core_hooks)
    _safe_directory(home / ".stc")
    _safe_directory(home / ".stc" / "core")
    _safe_directory(shared_dir)
    targets_plan = []

    def add_target(name: str, path: Path, source: Path, *, mode_executable: bool = False, allow_absent: bool = False):
        source_bytes, source_mode = _safe_regular_file(source)
        if mode_executable:
            after_mode = source_mode | 0o111
        else:
            after_mode = source_mode
        before, before_mode = _safe_optional_regular_file(path)
        if before is None and not allow_absent:
            raise HookPatchError(f"required H17 target unavailable: {path}")
        if before_mode is not None and before_mode != after_mode:
            raise HookPatchError(f"pre-install mode does not match rendered H17 mode: {path}")
        targets_plan.append({
            "name": name, "path": path, "before": before,
            "before_sha256": _sha256(before) if before is not None else None,
            "before_mode": before_mode,
            "after": source_bytes, "after_sha256": _sha256(source_bytes), "after_mode": after_mode,
            "backup_file": f"target-{len(targets_plan):02d}.before",
        })

    helper_source = core_hooks / "secret_read_policy.py"
    helper_target = shared_dir / "secret_read_policy.py"
    # Install the shared policy first, then the source wrappers, then native wrappers.
    add_target("shared-policy", helper_target, helper_source, allow_absent=True)
    bindings = []
    adapters = {}
    for target in targets:
        try:
            adapters[target] = R.load_adapter(str(repo_root), target)
        except Exception as exc:
            raise HookPatchError(f"versioned {target} adapter is unavailable") from exc
        if target in ("claude", "zcode"):
            source_name = "secret-read-guard.sh"
        else:
            source_name = "block-secret-read.sh"
        source = core_hooks / source_name
        source_target = shared_dir / source_name
        # One shared source wrapper is sufficient for Claude+ZCode.
        if not any(item["path"] == source_target for item in targets_plan):
            add_target(f"shared-source-{source_name}", source_target, source)
    for target in targets:
        adapter = adapters[target]
        native_path, native_bytes, native_mode, binding_config, expected_entry = _adapter_h17_render(
            repo_root, home, target, adapter
        )
        # Compare the complete selected entry from files-mode adapters. ZCode
        # strips STC tags, so its generated exact entry is the plugin binding.
        binding_digest = _verify_adapter_binding(binding_config, target, expected_entry)
        bindings.append({
            "target": target, "config_path": str(binding_config),
            "binding_sha256": binding_digest,
            "native_path": str(native_path),
        })
        native_source = source
        # Use the selected renderer result, not a shell copy or substitution.
        existing, existing_mode = _safe_optional_regular_file(native_path)
        if existing is None:
            raise HookPatchError(f"required native H17 target unavailable: {native_path}")
        if existing_mode != native_mode:
            raise HookPatchError(f"pre-install mode does not match rendered H17 mode: {native_path}")
        targets_plan.append({
            "name": f"native-{target}", "path": native_path, "before": existing,
            "before_sha256": _sha256(existing), "before_mode": existing_mode,
            "after": native_bytes, "after_sha256": _sha256(native_bytes), "after_mode": native_mode,
            "backup_file": f"target-{len(targets_plan):02d}.before",
        })
    plan = {"home": home, "targets": targets_plan, "bindings": bindings, "target_set": list(targets)}
    plan["expected_before_state_sha256"] = _multi_state_digest(plan)
    return plan


def _multi_target_set(value: str) -> tuple[str, ...]:
    parts = tuple(value.split(","))
    if any(not part or part.strip() != part for part in parts):
        raise HookPatchError("targets must be an explicit comma-separated adapter list")
    if len(set(parts)) != len(parts) or any(part not in _SUPPORTED_ADAPTERS for part in parts):
        raise HookPatchError("explicit targets must be a unique subset of claude,codex,zcode")
    return parts


def _multi_targets_state(plan: dict, key: str) -> bool:
    for item in plan["targets"]:
        data, mode = _safe_optional_regular_file(item["path"])
        if key == "before":
            if item["before"] is None:
                if data is not None:
                    return False
            elif data is None or (_sha256(data), mode) != (item["before_sha256"], item["before_mode"]):
                return False
        else:
            if data is None or (_sha256(data), mode) != (item["after_sha256"], item["after_mode"]):
                return False
    return True


def _print_multi_plan(plan: dict, language: str) -> None:
    print(f"DRY-RUN apply-hook targets={','.join(plan['target_set'])} hook=H17 language={language}")
    print(f"expected-before-state-sha256={plan['expected_before_state_sha256']}")
    for binding in plan["bindings"]:
        print(f"binding verified read-only: {binding['target']} H17 ({binding['binding_sha256']})")
    for item in plan["targets"]:
        before = "absent" if item["before"] is None else f"sha256 {item['before_sha256']} mode {item['before_mode']:04o}"
        print(f"would write {item['path']}: {before} -> sha256 {item['after_sha256']} mode {item['after_mode']:04o}")


def _matching_multi_backup(root: Path, home: Path, plan: dict, before_state_sha256: str) -> str | None:
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
            _, manifest, _, _ = _read_multi_backup(root, backup_id, home)
        except HookPatchError:
            continue
        if manifest["before_state_sha256"] != before_state_sha256 or manifest["target_set"] != plan["target_set"]:
            continue
        if all(
            record["after_sha256"] == item["after_sha256"]
            and record["after_mode"] == item["after_mode"]
            for record, item in zip(manifest["targets"], plan["targets"])
        ):
            return backup_id
    return None


def _multi_manifest(plan: dict, backup_id: str, language: str) -> dict:
    return {
        "version": 2,
        "backup_id": backup_id,
        "target": ",".join(plan["target_set"]),
        "target_set": plan["target_set"],
        "hook": "H17",
        "language": language,
        "status": "prepared",
        "before_state_sha256": plan["expected_before_state_sha256"],
        "bindings": plan["bindings"],
        "targets": [
            {
                "name": item["name"], "path": str(item["path"]),
                "backup_file": item["backup_file"] if item["before"] is not None else None,
                "before_exists": item["before"] is not None,
                "before_sha256": item["before_sha256"], "before_mode": item["before_mode"],
                "after_sha256": item["after_sha256"], "after_mode": item["after_mode"],
            }
            for item in plan["targets"]
        ],
    }


def _new_multi_backup(plan: dict, language: str, root: Path) -> tuple[str, Path, dict]:
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
    manifest = _multi_manifest(plan, backup_id, language)
    try:
        _fsync_directory(root)
        for item in plan["targets"]:
            if item["before"] is None:
                continue
            backup_file = directory / item["backup_file"]
            _atomic_write(backup_file, item["before"], 0o600, replace=False)
            data, mode = _safe_regular_file(backup_file)
            if data != item["before"] or mode != 0o600:
                raise HookPatchError("backup verification failed")
        manifest_path = directory / _MANIFEST
        data = _manifest_bytes(manifest)
        _atomic_write(manifest_path, data, 0o600, replace=False)
        written, mode = _safe_regular_file(manifest_path)
        if written != data or mode != 0o600:
            raise HookPatchError("backup manifest verification failed")
        _fsync_directory(directory)
    except Exception as exc:
        if isinstance(exc, HookPatchError):
            raise HookPatchError(str(exc), backup_id) from exc
        raise HookPatchError("backup creation failed", backup_id) from exc
    return backup_id, directory, manifest


def _delete_state(path: Path, expected_state: tuple[bytes, int]) -> None:
    current = _safe_regular_file(path)
    if current != expected_state:
        raise HookPatchError(f"delete precondition failed at {path}; target unchanged")
    path.unlink()
    _fsync_directory(path.parent)


def _write_multi_state(plan: dict, manifest_path: Path, manifest: dict, backup_id: str) -> None:
    for index, item in enumerate(plan["targets"]):
        observed = []
        for target in plan["targets"]:
            data, mode = _safe_optional_regular_file(target["path"])
            observed.append(None if data is None else (_sha256(data), mode))
        expected = []
        for prior, target in enumerate(plan["targets"]):
            if prior < index:
                expected.append((target["after_sha256"], target["after_mode"]))
            elif target["before"] is None:
                expected.append(None)
            else:
                expected.append((target["before_sha256"], target["before_mode"]))
        if observed != expected:
            raise HookPatchError("H17 target changed during install; backup retained", backup_id)
        try:
            if item["before"] is None:
                _atomic_write(item["path"], item["after"], item["after_mode"], replace=False)
            else:
                _atomic_write(item["path"], item["after"], item["after_mode"], expected_state=(item["before"], item["before_mode"]))
            if _target_state(item) != (item["after_sha256"], item["after_mode"]):
                raise HookPatchError("installed target verification failed", backup_id)
        except Exception as exc:
            if isinstance(exc, HookPatchError) and exc.backup_id:
                raise
            raise HookPatchError("target write failed; backup retained", backup_id) from exc
    if not _multi_targets_state(plan, "after"):
        raise HookPatchError("installed target verification failed; backup retained", backup_id)
    old = _manifest_bytes(manifest)
    manifest["status"] = "applied"
    try:
        new = _manifest_bytes(manifest)
        _atomic_write(manifest_path, new, 0o600, expected_state=(old, 0o600))
        saved, mode = _safe_regular_file(manifest_path)
        if saved != new or mode != 0o600:
            raise HookPatchError("applied marker verification failed", backup_id)
    except Exception as exc:
        raise HookPatchError("targets applied; success marker not saved; backup retained", backup_id) from exc


def _apply_multi_hook(*, repo_root: str, home: str, target: str, hook: str, language: str,
                      expected_before_state_sha256: str | None, dry_run: bool) -> int:
    if hook != "H17":
        raise HookPatchError("only H17 is supported")
    targets = _multi_target_set(target)
    home_path = Path(home).absolute()
    plan = _make_multi_plan(Path(repo_root).resolve(), home_path, targets, language)
    if dry_run:
        if _multi_targets_state(plan, "after"):
            print(f"expected-before-state-sha256={plan['expected_before_state_sha256']}")
            matched_backup = _matching_multi_backup(
                _backup_root(home_path), home_path, plan, expected_before_state_sha256
            ) if expected_before_state_sha256 else None
            if expected_before_state_sha256 and expected_before_state_sha256 != plan["expected_before_state_sha256"] and not matched_backup:
                raise HookPatchError("expected-before aggregate does not match active H17 artifact set")
            print("DRY-RUN verified no-op: H17 artifacts already match rendered version")
            return 0
        if expected_before_state_sha256 and expected_before_state_sha256 != plan["expected_before_state_sha256"]:
            raise HookPatchError("expected-before aggregate does not match active H17 artifact set")
        if not _multi_targets_state(plan, "before"):
            raise HookPatchError("active H17 artifact set is neither expected before nor rendered after state")
        _print_multi_plan(plan, language)
        return 0
    if not _SHA256.fullmatch(expected_before_state_sha256 or ""):
        raise HookPatchError("--expected-before-state-sha256 from a matching dry-run is required")
    if _multi_targets_state(plan, "after"):
        matched_backup = _matching_multi_backup(_backup_root(home_path), home_path, plan, expected_before_state_sha256)
        if expected_before_state_sha256 == plan["expected_before_state_sha256"] or matched_backup:
            print("✓ already current: H17 artifact set matches rendered version; no backup created")
            return 0
        raise HookPatchError("already rendered state found, but expected-before aggregate is stale")
    if expected_before_state_sha256 != plan["expected_before_state_sha256"]:
        raise HookPatchError("expected-before aggregate does not match active H17 artifact set")
    root = _backup_root(home_path)
    try:
        with _operation_lock(root, create=True):
            plan = _make_multi_plan(Path(repo_root).resolve(), home_path, targets, language)
            if plan["expected_before_state_sha256"] != expected_before_state_sha256:
                raise HookPatchError("expected-before aggregate changed before backup; no targets changed")
            if not _multi_targets_state(plan, "before"):
                raise HookPatchError("active H17 artifact set changed before backup; no targets changed")
            backup_id, backup_dir, manifest = _new_multi_backup(plan, language, root)
            try:
                _write_multi_state(plan, backup_dir / _MANIFEST, manifest, backup_id)
            except HookPatchError as exc:
                if exc.backup_id:
                    raise
                raise HookPatchError(str(exc), backup_id) from exc
            print(f"✓ applied H17 artifact set; backup_id={backup_id}")
            return 0
    except HookPatchError:
        raise
    except Exception as exc:
        raise HookPatchError("selected H17 installation failed safely") from exc


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
    expected_before_state_sha256: str | None = None,
    dry_run: bool = False,
) -> int:
    if target != "codex" or expected_before_state_sha256 is not None or not expected_source_sha256 or not expected_native_sha256:
        return _apply_multi_hook(
            repo_root=repo_root,
            home=home,
            target=target,
            hook=hook,
            language=language,
            expected_before_state_sha256=expected_before_state_sha256,
            dry_run=dry_run,
        )
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


def _v2_expected_records(home: Path, target_set: list[str]) -> list[tuple[str, Path]]:
    if not isinstance(target_set, list) or not target_set or len(set(target_set)) != len(target_set):
        raise HookPatchError("backup manifest adapter set is invalid")
    if any(target not in _SUPPORTED_ADAPTERS for target in target_set):
        raise HookPatchError("backup manifest adapter set is unsupported")
    expected = [("shared-policy", home / ".stc/core/hooks/secret_read_policy.py")]
    if "claude" in target_set or "zcode" in target_set:
        expected.append(("shared-source-secret-read-guard.sh", home / ".stc/core/hooks/secret-read-guard.sh"))
    if "codex" in target_set:
        expected.append(("shared-source-block-secret-read.sh", home / ".stc/core/hooks/block-secret-read.sh"))
    for target in target_set:
        if target == "claude":
            expected.append(("native-claude", home / ".claude/hooks/secret-read-guard.stc.sh"))
        elif target == "codex":
            expected.append(("native-codex", home / ".codex/hooks/block-secret-read.stc.sh"))
        else:
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(R.PLUGIN_VERSION)):
                raise HookPatchError("ZCode plugin version is not a supported version string")
            expected.append(("native-zcode", home / f".zcode/{R.PLUGIN_DIR}/hooks/secret-read-guard.stc.sh"))
    return expected


def _read_multi_backup(root: Path, backup_id: str, home: Path) -> tuple[Path, dict, list[bytes | None], bytes]:
    if not _BACKUP_ID.fullmatch(backup_id or ""):
        raise HookPatchError("invalid hook-patch backup id")
    for directory in (home, home / ".stc", home / ".stc" / "backups"):
        _safe_directory(directory)
    _safe_private_directory(root)
    directory = root / backup_id
    _safe_private_directory(directory)
    if directory.parent != root or Path(os.path.realpath(directory)).parent != Path(os.path.realpath(root)):
        raise HookPatchError("backup path is outside the dedicated hook-patch root")
    raw, mode = _safe_regular_file(directory / _MANIFEST)
    if mode != 0o600 or len(raw) > 65536:
        raise HookPatchError("backup manifest has unsafe mode or size")
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HookPatchError("backup manifest is invalid") from exc
    target_set = manifest.get("target_set") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict) or manifest.get("version") != 2
        or manifest.get("backup_id") != backup_id or manifest.get("hook") != "H17"
        or manifest.get("target") != ",".join(target_set or [])
        or manifest.get("status") not in ("prepared", "applied", "restored")
        or not _SHA256.fullmatch(manifest.get("before_state_sha256", ""))
    ):
        raise HookPatchError("backup manifest is not a supported H17 record")
    expected = _v2_expected_records(home, target_set)
    records = manifest.get("targets")
    if not isinstance(records, list) or len(records) != len(expected):
        raise HookPatchError("backup manifest target set is incomplete")
    backup_bytes: list[bytes | None] = []
    for index, (record, (name, path)) in enumerate(zip(records, expected)):
        if not isinstance(record, dict) or record.get("name") != name or record.get("path") != str(path):
            raise HookPatchError("backup manifest target identity is invalid")
        before_exists = record.get("before_exists")
        if not isinstance(before_exists, bool):
            raise HookPatchError("backup manifest existence state is invalid")
        before_mode, after_mode = record.get("before_mode"), record.get("after_mode")
        if not isinstance(after_mode, int) or after_mode not in (0o644, 0o755):
            raise HookPatchError("backup manifest target mode is invalid")
        if before_exists:
            if record.get("backup_file") != f"target-{index:02d}.before" or not _SHA256.fullmatch(record.get("before_sha256", "")):
                raise HookPatchError("backup manifest backup reference is invalid")
            if not isinstance(before_mode, int) or before_mode not in (0o644, 0o755):
                raise HookPatchError("backup manifest before mode is invalid")
            data, backup_mode = _safe_regular_file(directory / record["backup_file"])
            if backup_mode != 0o600 or _sha256(data) != record["before_sha256"]:
                raise HookPatchError("backup bytes or mode failed verification")
            backup_bytes.append(data)
        else:
            if name != "shared-policy" or record.get("backup_file") is not None or record.get("before_sha256") is not None or before_mode is not None:
                raise HookPatchError("only a newly-created shared policy may have an absent before-state")
            backup_bytes.append(None)
        for parent in (path.parent.parent, path.parent):
            _safe_directory(parent)
    bindings = manifest.get("bindings")
    if not isinstance(bindings, list) or [b.get("target") for b in bindings if isinstance(b, dict)] != target_set:
        raise HookPatchError("backup manifest H17 binding identity is invalid")
    for binding in bindings:
        target = binding["target"]
        try:
            adapter = R.load_adapter(str(Path(__file__).resolve().parents[1]), target)
            _, _, _, config_path, expected_entry = _adapter_h17_render(Path(__file__).resolve().parents[1], home, target, adapter)
            digest = _verify_adapter_binding(config_path, target, expected_entry)
        except Exception as exc:
            raise HookPatchError(f"{target} H17 binding could not be verified for restore") from exc
        if binding.get("config_path") != str(config_path) or binding.get("binding_sha256") != digest:
            raise HookPatchError(f"{target} H17 binding changed since install; no targets changed")
    return directory, manifest, backup_bytes, raw


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


def _restore_multi_plan(root: Path, backup_id: str, home: Path) -> dict:
    directory, manifest, backup_bytes, manifest_bytes = _read_multi_backup(root, backup_id, home)
    targets = []
    current_states = []
    for record, before in zip(manifest["targets"], backup_bytes):
        path = Path(record["path"])
        current, mode = _safe_optional_regular_file(path)
        current_state = None if current is None else (_sha256(current), mode)
        before_state = (record["before_sha256"], record["before_mode"]) if record["before_exists"] else None
        after_state = (record["after_sha256"], record["after_mode"])
        if current_state not in (before_state, after_state):
            raise HookPatchError(f"restore conflict at {path}; no targets changed")
        targets.append({
            "name": record["name"], "path": path, "before": before,
            "before_exists": record["before_exists"], "before_sha256": record["before_sha256"],
            "before_mode": record["before_mode"], "after_sha256": record["after_sha256"],
            "after_mode": record["after_mode"],
        })
        current_states.append(current_state)
    return {
        "directory": directory, "manifest": manifest, "manifest_bytes": manifest_bytes,
        "manifest_path": directory / _MANIFEST, "targets": targets, "current_states": current_states,
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


def _restore_multi_targets(plan: dict, backup_id: str) -> None:
    targets = plan["targets"]
    # Restore native entrypoints first; remove a newly-created shared policy last.
    for index in range(len(targets) - 1, -1, -1):
        observed = []
        for target in targets:
            data, mode = _safe_optional_regular_file(target["path"])
            observed.append(None if data is None else (_sha256(data), mode))
        allowed = []
        for target in targets:
            before = (target["before_sha256"], target["before_mode"]) if target["before_exists"] else None
            allowed.append((before, (target["after_sha256"], target["after_mode"])))
        if any(state not in pair for state, pair in zip(observed, allowed)):
            raise HookPatchError("restore state changed during operation; no unsafe overwrite", backup_id)
        item = targets[index]
        before_state = (item["before_sha256"], item["before_mode"]) if item["before_exists"] else None
        after_state = (item["after_sha256"], item["after_mode"])
        if observed[index] == before_state:
            continue
        try:
            if item["before_exists"]:
                _atomic_write(item["path"], item["before"], item["before_mode"], expected_state=_safe_regular_file(item["path"]))
            else:
                _delete_state(item["path"], _safe_regular_file(item["path"]))
        except Exception as exc:
            if isinstance(exc, HookPatchError) and exc.backup_id:
                raise
            reason = str(exc) if isinstance(exc, HookPatchError) else "restore write failed"
            raise HookPatchError(f"{reason}; backup retained", backup_id) from exc
    for target in targets:
        current, mode = _safe_optional_regular_file(target["path"])
        state = None if current is None else (_sha256(current), mode)
        before = (target["before_sha256"], target["before_mode"]) if target["before_exists"] else None
        if state != before:
            raise HookPatchError("restore verification failed; backup retained", backup_id)
    manifest = plan["manifest"]
    manifest["status"] = "restored"
    try:
        expected = _manifest_bytes(manifest)
        _atomic_write(plan["manifest_path"], expected, 0o600, expected_state=(plan["manifest_bytes"], 0o600))
        saved, mode = _safe_regular_file(plan["manifest_path"])
        if saved != expected or mode != 0o600:
            raise HookPatchError("restored marker verification failed", backup_id)
    except Exception as exc:
        raise HookPatchError("targets restored; status marker not saved; backup retained", backup_id) from exc


def restore_hook(*, home: str, backup_id: str, dry_run: bool = False) -> int:
    home_path = Path(home).absolute()
    root = _backup_root(home_path)

    def show(plan: dict, prefix: str) -> None:
        print(f"{prefix} restore-hook backup_id={backup_id} status={plan['manifest']['status']}")
        for item, current in zip(plan["targets"], plan["current_states"]):
            before_state = (item["before_sha256"], item["before_mode"]) if item.get("before_exists", True) else None
            state = "before" if current == before_state else "after"
            action = "leave" if state == "before" else "restore"
            before_display = "absent" if before_state is None else f"sha256 {before_state[0]} mode {before_state[1]:04o}"
            current_display = "absent" if current is None else f"sha256 {current[0]} mode {current[1]:04o}"
            print(
                f"{action} {item['path']}: current {state} {current_display} -> {before_display}"
            )

    def build_plan() -> dict:
        # Version is read only from the bounded manifest file; v1 remains on its
        # original strict Codex-only reader for compatibility.
        if not _BACKUP_ID.fullmatch(backup_id or ""):
            raise HookPatchError("invalid hook-patch backup id")
        manifest_path = root / backup_id / _MANIFEST
        raw, mode = _safe_regular_file(manifest_path)
        if mode != 0o600 or len(raw) > 65536:
            raise HookPatchError("backup manifest has unsafe mode or size")
        try:
            version = json.loads(raw).get("version")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise HookPatchError("backup manifest is invalid") from exc
        if version == 2:
            return _restore_multi_plan(root, backup_id, home_path)
        return _restore_plan(root, backup_id, home_path)

    try:
        if dry_run:
            plan = build_plan()
            show(plan, "DRY-RUN")
            return 0
        for directory in (home_path, home_path / ".stc", home_path / ".stc" / "backups"):
            _safe_directory(directory)
        _safe_private_directory(root)
        with _operation_lock(root, create=False):
            plan = build_plan()
            show(plan, "RESTORE")
            if plan["manifest"].get("version") == 2:
                _restore_multi_targets(plan, backup_id)
            else:
                _restore_targets(plan, backup_id)
            print(f"✓ restored H17; backup_id={backup_id}")
            return 0
    except HookPatchError:
        raise
    except Exception as exc:
        raise HookPatchError("selected H17 restore failed safely", backup_id) from exc

