#!/usr/bin/env python3
"""Plan and safely quarantine files while consolidating memory roots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ARCHIVE_DIR_NAME = ".stc-memory-root-migrate"
CANONICAL_ROOT = Path("/Users/xtoshin/Work/memory")
LEGACY_ROOTS = (
    Path.home() / ".claude" / "projects" / "-Users-xtoshin-Work" / "memory",
    Path.home() / ".Codex" / "projects" / "-Users-xtoshin-Work" / "memory",
)
CLASSIFICATIONS = ("identical", "canonical-only", "legacy-only", "conflict")


class MigrationError(RuntimeError):
    """Raised when a migration cannot be completed without guessing."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_root(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative_path = path.relative_to(root).as_posix()
        is_migration_archive = (
            relative_path == ARCHIVE_DIR_NAME
            or relative_path.startswith(f"{ARCHIVE_DIR_NAME}/")
        )
        if is_migration_archive:
            continue
        records[relative_path] = {
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        }
    return records


def _legacy_label(root: Path, index: int, used: set[str]) -> str:
    parts = {part.casefold() for part in root.parts}
    if ".claude" in parts:
        base = "legacy-claude"
    elif ".codex" in parts:
        base = "legacy-codex"
    else:
        base = f"legacy-{index + 1}"
    label = base
    suffix = 2
    while label in used:
        label = f"{base}-{suffix}"
        suffix += 1
    used.add(label)
    return label


def _legacy_labels(roots: list[Path]) -> list[str]:
    used: set[str] = set()
    return [_legacy_label(root, index, used) for index, root in enumerate(roots)]


def _atomic_copy(source: Path, destination: Path) -> None:
    """Publish a complete copy, never exposing a partially written file."""
    if not source.is_file() or source.is_symlink():
        raise MigrationError(f"source is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise MigrationError(f"archive target already exists: {destination}")
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            shutil.copyfileobj(origin, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _atomic_write_json(destination: Path, payload: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            text=True,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _archive_root(canonical: Path, timestamp: str | None) -> Path:
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if Path(stamp).name != stamp or not stamp:
        raise MigrationError("timestamp must be a single safe path component")
    root = canonical / ARCHIVE_DIR_NAME / "quarantine" / stamp
    if root.exists():
        suffix = 2
        while (candidate := root.with_name(f"{stamp}-{suffix}")).exists():
            suffix += 1
        root = candidate
    return root


def _record_source(path: Path, expected: dict[str, Any]) -> None:
    if not path.is_file() or path.is_symlink():
        raise MigrationError(f"source changed or disappeared: {path}")
    if _sha256(path) != expected["sha256"]:
        raise MigrationError(f"source changed during migration plan: {path}")


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False


def _resolve_root(value: Path | str) -> Path:
    path = Path(value).expanduser()
    if path.is_symlink():
        raise MigrationError(f"root boundary must not be a symlink: {path}")
    return path.resolve()


def plan_migration(canonical_root: Path | str, legacy_roots: Iterable[Path | str]) -> dict[str, Any]:
    """Return a read-only SHA256 comparison plan for the supplied roots."""
    canonical = _resolve_root(canonical_root)
    legacy = [_resolve_root(root) for root in legacy_roots]
    all_roots = [canonical, *legacy]
    for index, first in enumerate(all_roots):
        for second in all_roots[index + 1:]:
            if _paths_overlap(first, second):
                raise MigrationError(
                    "canonical and legacy roots must be different and non-overlapping"
                )
    canonical_files = _inventory_root(canonical)
    legacy_files = [_inventory_root(root) for root in legacy]
    labels = _legacy_labels(legacy)
    relative_paths = sorted(
        set(canonical_files).union(*(files for files in legacy_files))
    )

    entries: list[dict[str, Any]] = []
    for relative_path in relative_paths:
        canonical_record = canonical_files.get(relative_path)
        legacy_records = {
            labels[index]: files[relative_path]
            for index, files in enumerate(legacy_files)
            if relative_path in files
        }
        hashes = {
            record["sha256"]
            for record in ([canonical_record] if canonical_record else [])
            + list(legacy_records.values())
        }
        if canonical_record and legacy_records and len(hashes) == 1:
            classification = "identical"
        elif canonical_record and not legacy_records:
            classification = "canonical-only"
        elif not canonical_record and legacy_records and len(hashes) == 1:
            classification = "legacy-only"
        else:
            classification = "conflict"
        entries.append({
            "relative_path": relative_path,
            "classification": classification,
            "canonical": canonical_record,
            "legacy": legacy_records,
        })

    counts = {name: 0 for name in CLASSIFICATIONS}
    for entry in entries:
        counts[entry["classification"]] += 1
    return {
        "schema_version": 1,
        "canonical_root": str(canonical),
        "legacy_roots": [str(root) for root in legacy],
        "files": entries,
        "counts": counts,
    }


def apply_migration(
    canonical_root: Path | str,
    legacy_roots: Iterable[Path | str],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Quarantine legacy evidence and write an atomic manifest.

    The canonical and legacy roots are never deleted or overwritten.  A fresh
    plan is taken immediately before copying, and every source is re-hashed
    before it is archived.
    """
    plan = plan_migration(canonical_root, legacy_roots)
    canonical = Path(plan["canonical_root"])
    legacy = [Path(root) for root in plan["legacy_roots"]]
    labels = _legacy_labels(legacy)
    sources_by_label = dict(zip(labels, legacy, strict=True))
    archive = _archive_root(canonical, timestamp)
    canonical.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=False)

    archived_paths: dict[str, list[str]] = {}
    for entry in plan["files"]:
        classification = entry["classification"]
        if classification not in {"legacy-only", "conflict"}:
            continue
        relative_path = Path(entry["relative_path"])
        targets = []
        if classification == "conflict" and entry["canonical"]:
            source = canonical / relative_path
            _record_source(source, entry["canonical"])
            target = archive / "conflicts" / "canonical" / relative_path
            _atomic_copy(source, target)
            targets.append(str(target.relative_to(archive)))
        for label, record in entry["legacy"].items():
            source = sources_by_label[label] / relative_path
            _record_source(source, record)
            folder = "conflicts" if classification == "conflict" else "legacy-only"
            target = archive / folder / label / relative_path
            _atomic_copy(source, target)
            targets.append(str(target.relative_to(archive)))
        archived_paths[entry["relative_path"]] = targets

    manifest = {
        "schema_version": 1,
        "mode": "apply",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonical_root": plan["canonical_root"],
        "legacy_roots": [
            {"label": label, "path": str(root)}
            for label, root in zip(labels, legacy, strict=True)
        ],
        "archive_root": str(archive),
        "counts": plan["counts"],
        "files": [
            {**entry, "archived_paths": archived_paths.get(entry["relative_path"], [])}
            for entry in plan["files"]
        ],
    }
    manifest_path = archive / "manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return {
        "plan": plan,
        "archive_root": str(archive),
        "manifest_path": str(manifest_path),
        "manifest": manifest,
    }


def _print_plan(plan: dict[str, Any]) -> None:
    print("mode: plan (read-only)")
    print(f"canonical_root: {plan['canonical_root']}")
    for classification in CLASSIFICATIONS:
        print(f"{classification}: {plan['counts'][classification]}")
    for entry in plan["files"]:
        print(f"{entry['classification']}\t{entry['relative_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        choices=("plan", "inventory"),
        default="plan",
    )
    parser.add_argument("--canonical-root", default=str(CANONICAL_ROOT))
    parser.add_argument(
        "--legacy-root",
        action="append",
        dest="legacy_roots",
        help="legacy root; repeat for more than one root",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write quarantine copies and a manifest",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the metadata-only plan/result as JSON",
    )
    args = parser.parse_args(argv)
    legacy_roots = args.legacy_roots or [str(root) for root in LEGACY_ROOTS]

    try:
        if args.apply:
            result = apply_migration(args.canonical_root, legacy_roots)
            payload = {
                "mode": "apply",
                "manifest_path": result["manifest_path"],
                "archive_root": result["archive_root"],
                "counts": result["manifest"]["counts"],
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print("mode: apply")
                print(f"archive_root: {result['archive_root']}")
                print(f"manifest_path: {result['manifest_path']}")
                for classification in CLASSIFICATIONS:
                    print(f"{classification}: {result['manifest']['counts'][classification]}")
            return 0

        plan = plan_migration(args.canonical_root, legacy_roots)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            _print_plan(plan)
        return 0
    except (MigrationError, OSError, ValueError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
