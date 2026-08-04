import importlib.util
import plistlib
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "launchd_install.py"
SPEC = importlib.util.spec_from_file_location("launchd_install", SCRIPT)
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


def _plist(path: Path, label: str) -> None:
    with path.open("wb") as handle:
        plistlib.dump({
            "Label": label,
            "ProgramArguments": ["/usr/bin/true"],
            "RunAtLoad": True,
        }, handle)


def test_inventory_rejects_filename_label_mismatch(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _plist(source / "com.xtoshin.stc-good.plist", "com.xtoshin.stc-wrong")

    with pytest.raises(ValueError, match="Label|filename"):
        INSTALL.inventory(source)


def test_apply_backs_up_changed_plist_and_bootstraps_exact_targets(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "LaunchAgents"
    backup = tmp_path / "backups"
    source.mkdir()
    destination.mkdir()
    name = "com.xtoshin.stc-demo.plist"
    _plist(source / name, "com.xtoshin.stc-demo")
    (destination / name).write_text("old live plist\n")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    result = INSTALL.apply(
        source,
        destination,
        backup,
        uid=501,
        runner=runner,
    )

    assert plistlib.loads((destination / name).read_bytes())["Label"] == "com.xtoshin.stc-demo"
    assert (backup / name).read_text() == "old live plist\n"
    assert result["installed"] == [name]
    assert calls == [
        ["launchctl", "bootout", "gui/501/com.xtoshin.stc-demo"],
        ["launchctl", "bootstrap", "gui/501", str(destination / name)],
    ]


def test_status_compares_source_and_live_without_writing(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "dest"
    source.mkdir()
    destination.mkdir()
    _plist(source / "com.xtoshin.stc-a.plist", "com.xtoshin.stc-a")
    _plist(source / "com.xtoshin.stc-b.plist", "com.xtoshin.stc-b")
    (destination / "com.xtoshin.stc-a.plist").write_bytes(
        (source / "com.xtoshin.stc-a.plist").read_bytes()
    )

    status = INSTALL.status(source, destination)

    assert status == {"current": ["com.xtoshin.stc-a.plist"], "missing": ["com.xtoshin.stc-b.plist"], "drifted": []}


def test_apply_retries_transient_bootstrap_failure(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "LaunchAgents"
    source.mkdir()
    name = "com.xtoshin.stc-demo.plist"
    _plist(source / name, "com.xtoshin.stc-demo")
    bootstrap_attempts = 0
    delays = []

    def runner(command, **kwargs):
        nonlocal bootstrap_attempts
        if command[1] == "bootstrap":
            bootstrap_attempts += 1
            code = 5 if bootstrap_attempts == 1 else 0
            return type("Result", (), {"returncode": code, "stdout": "", "stderr": "I/O"})()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    INSTALL.apply(
        source,
        destination,
        tmp_path / "backups",
        uid=501,
        runner=runner,
        sleeper=delays.append,
    )

    assert bootstrap_attempts == 2
    assert delays == [0.25]
