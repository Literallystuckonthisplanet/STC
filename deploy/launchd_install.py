#!/usr/bin/env python3
"""Install and reload STC launchd jobs from the versioned plist directory."""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "deploy" / "launchd"
DESTINATION = Path("~/Library/LaunchAgents").expanduser()


def inventory(source: Path | str) -> list[tuple[Path, str]]:
    directory = Path(source).expanduser().resolve()
    records = []
    for path in sorted(directory.glob("com.xtoshin.stc-*.plist")):
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException) as exc:
            raise ValueError(f"invalid plist {path}: {exc}") from exc
        label = payload.get("Label")
        if not isinstance(label, str) or label != path.stem:
            raise ValueError(f"plist Label must match filename: {path.name} -> {label!r}")
        if not isinstance(payload.get("ProgramArguments"), list):
            raise ValueError(f"plist has no ProgramArguments list: {path.name}")
        records.append((path, label))
    if not records:
        raise ValueError(f"no STC launchd plists in {directory}")
    return records


def status(source: Path | str, destination: Path | str) -> dict[str, list[str]]:
    destination = Path(destination).expanduser().resolve()
    result = {"current": [], "missing": [], "drifted": []}
    for source_path, _ in inventory(source):
        live = destination / source_path.name
        if not live.is_file():
            result["missing"].append(source_path.name)
        elif live.read_bytes() == source_path.read_bytes():
            result["current"].append(source_path.name)
        else:
            result["drifted"].append(source_path.name)
    return result


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temp_path = Path(temporary)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def apply(
    source: Path | str,
    destination: Path | str,
    backup_dir: Path | str,
    *,
    uid: int | None = None,
    runner: Callable = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, list[str]]:
    records = inventory(source)
    destination = Path(destination).expanduser().resolve()
    backup_dir = Path(backup_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    installed, unchanged, backed_up = [], [], []
    domain = f"gui/{os.getuid() if uid is None else uid}"

    for source_path, label in records:
        live = destination / source_path.name
        if live.is_file() and live.read_bytes() == source_path.read_bytes():
            unchanged.append(source_path.name)
        else:
            if live.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_target = backup_dir / source_path.name
                if backup_target.exists():
                    raise FileExistsError(f"backup already exists: {backup_target}")
                shutil.copy2(live, backup_target)
                backed_up.append(source_path.name)
            _atomic_copy(source_path, live)
            installed.append(source_path.name)

        runner(
            ["launchctl", "bootout", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )
        loaded = None
        for attempt in range(3):
            loaded = runner(
                ["launchctl", "bootstrap", domain, str(live)],
                capture_output=True,
                text=True,
                check=False,
            )
            if loaded.returncode == 0:
                break
            if attempt < 2:
                sleeper(0.25 * (attempt + 1))
        assert loaded is not None
        if loaded.returncode != 0:
            raise RuntimeError(
                f"launchctl bootstrap failed for {label}: "
                f"{(loaded.stderr or loaded.stdout).strip()}"
            )
    return {"installed": installed, "unchanged": unchanged, "backed_up": backed_up}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--destination", default=str(DESTINATION))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if not args.apply:
        result = status(args.source, args.destination)
        for name in ("current", "missing", "drifted"):
            print(f"{name}: {len(result[name])}")
            for path in result[name]:
                print(f"  {path}")
        return 1 if result["missing"] or result["drifted"] else 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path("~/.stc/backups/launchd").expanduser() / stamp
    result = apply(args.source, args.destination, backup)
    print(f"installed: {len(result['installed'])}")
    print(f"unchanged: {len(result['unchanged'])}")
    print(f"backed_up: {len(result['backed_up'])}")
    if result["backed_up"]:
        print(f"backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
