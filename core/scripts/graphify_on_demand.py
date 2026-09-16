#!/usr/bin/env python3
"""Return one project's code graph, bootstrapping it only when absent.

Call this for a code-relationship or impact question. It is deliberately not
part of the first-search hook: a literal lookup does not require a graph.
Linked worktrees reuse their primary checkout's derived graph.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

from graphify_maintenance import inspect_project, refresh_project


def primary_checkout(project: Path) -> Path:
    """Resolve a linked worktree to the first checkout of its Git repository."""
    project = project.expanduser().resolve()
    top = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if top.returncode != 0:
        return project
    current = Path(top.stdout.strip()).resolve()
    listing = subprocess.run(
        ["git", "-C", str(current), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    if listing.returncode != 0:
        return current
    first = listing.stdout.splitlines()[0] if listing.stdout else ""
    if not first.startswith("worktree "):
        return current
    primary = Path(first.removeprefix("worktree ")).resolve()
    return primary if primary.is_dir() else current


def _usable_graph(project: Path) -> bool:
    return inspect_project(project)["state"] not in {"missing", "invalid"}


def ensure_graph(project: Path | str) -> Path:
    """Reuse a graph or perform one serialized structural bootstrap."""
    root = primary_checkout(Path(project))
    graph = root / "graphify-out" / "graph.json"
    if _usable_graph(root):
        return graph

    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:20]
    lock_path = Path(tempfile.gettempdir()) / f"stc-graphify-bootstrap-{digest}.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not _usable_graph(root):
            refresh_project(root, bootstrap_missing=True)
        if not _usable_graph(root):
            raise RuntimeError(f"Graphify did not create a usable graph in {root}")
    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        print(ensure_graph(args.project))
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Graphify on demand failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
