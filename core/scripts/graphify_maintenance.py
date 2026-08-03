#!/usr/bin/env python3
"""Audit and refresh local Graphify artifacts without semantic auto-labeling.

The maintenance boundary is deliberately small:

* ``audit`` is read-only and reports missing/stale/incomplete project maps;
* ``refresh`` updates an existing graph with ``--no-cluster``, regenerates the
  tree viewer, and folds existing feedback memory into deterministic lessons;
* a missing graph is only bootstrapped when ``--bootstrap-missing`` is given.

Semantic ``extract``/``label`` work is never started implicitly by a regular
refresh.  This keeps the recurring local process free of surprise model cost.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


# A scheduled maintenance run must be able to create a useful structural map
# even when no semantic-extraction backend is configured.  These are the file
# classes graphify sends to an LLM; code files remain locally AST-extractable.
SEMANTIC_EXCLUDES = (
    "*.md", "*.mdx", "*.qmd", "*.txt", "*.rst", "*.html",
    "*.yaml", "*.yml", "*.pdf", "*.png", "*.jpg", "*.jpeg",
    "*.gif", "*.webp", "*.svg", "*.docx", "*.xlsx",
)


def _graph_file(project: Path) -> Path:
    return project / "graphify-out" / "graph.json"


def _read_head(project: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect_project(project: Path | str, head: str | None = None) -> dict:
    """Return a stable, JSON-friendly health record for one project."""
    project = Path(project).expanduser().resolve()
    out = project / "graphify-out"
    graph = out / "graph.json"
    head = _read_head(project) if head is None else head
    record = {
        "project": str(project),
        "name": project.name,
        "head": head,
        "graph_present": graph.is_file(),
        "report_present": (out / "GRAPH_REPORT.md").is_file(),
        "viewer_present": (out / "graph.html").is_file(),
        "tree_present": (out / "GRAPH_TREE.html").is_file(),
        "memory_present": (out / "memory").is_dir(),
        "lessons_present": (out / "reflections" / "LESSONS.md").is_file(),
        "built_at_commit": "",
        "nodes": 0,
        "links": 0,
        "state": "missing",
    }
    if not graph.is_file():
        return record

    try:
        data = json.loads(graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        record["state"] = "invalid"
        record["error"] = str(exc)
        return record

    record["built_at_commit"] = str(data.get("built_at_commit") or "")
    record["nodes"] = len(data.get("nodes") or [])
    record["links"] = len(data.get("links") or [])
    if record["built_at_commit"] and head and record["built_at_commit"] != head:
        record["state"] = "stale"
    elif not record["viewer_present"] or not record["tree_present"]:
        record["state"] = "incomplete"
    else:
        record["state"] = "healthy"
    return record


def plan_actions(status: dict) -> list[str]:
    """Return idempotent maintenance actions for an inspection record."""
    state = status.get("state")
    if state in {"missing", "invalid"}:
        return ["bootstrap"]
    actions: list[str] = []
    if state == "stale":
        actions.append("refresh")
    if not status.get("viewer_present") or not status.get("tree_present"):
        actions.append("tree")
    if status.get("memory_present") and not status.get("lessons_present"):
        actions.append("reflect")
    return actions


def discover_projects(root: Path | str) -> list[Path]:
    """Discover direct git projects, including projects with a graph only."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and ((p / ".git").exists() or (p / "graphify-out").exists())
    )


def configured_projects(config_path: Path | str) -> tuple[Path | None, list[str]]:
    """Read the explicit project registry, if the local STC config has one."""
    path = Path(config_path).expanduser()
    if not path.is_file():
        return None, []
    try:
        import yaml
    except ImportError:
        return None, []
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None, []
    graphify = config.get("graphify") or {}
    projects = graphify.get("projects") or {}
    names = projects.get("names") if isinstance(projects, dict) else projects
    if not isinstance(names, list):
        names = []
    root = None
    if isinstance(projects, dict) and projects.get("root"):
        root = Path(os.path.expandvars(str(projects["root"]))).expanduser()
    return root, [str(name) for name in names if str(name).strip()]


def _run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=str(cwd), check=True)


def _stamp_commit(project: Path, graph: Path) -> None:
    """Normalize graphify's commit marker after raw/watch output.

    Some graphify 0.9.x raw/watch paths leave ``built_at_commit`` empty. An
    empty marker cannot prove freshness, so the maintenance boundary records
    the actual project HEAD after the graph has been rebuilt.
    """
    try:
        data = json.loads(graph.read_text(encoding="utf-8"))
        head = _read_head(project)
        if head and data.get("built_at_commit") != head:
            data["built_at_commit"] = head
            graph.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        return


def _bootstrap_structural_graph(project: Path) -> None:
    """Create a code-only graph when full extraction has no LLM backend.

    This is a deliberate degraded result, not silent data loss: semantic files
    remain in the project and are picked up later when an explicit backend is
    configured.  The regular maintenance process must not fail the entire
    project fleet because one project contains Markdown documentation.
    """
    command = ["graphify", "extract", ".", "--no-cluster"]
    for pattern in SEMANTIC_EXCLUDES:
        command.extend(("--exclude", pattern))
    _run(command, project)


def refresh_project(project: Path, bootstrap_missing: bool = False) -> dict:
    """Refresh one project and return its post-refresh inspection record."""
    before = inspect_project(project)
    graph = _graph_file(project)
    if before["state"] in {"missing", "invalid"}:
        if not bootstrap_missing:
            return before
        try:
            _run(["graphify", "extract", ".", "--no-cluster"], project)
        except subprocess.CalledProcessError:
            print(
                f"[graphify] full bootstrap unavailable for {project.name}; "
                "retrying structural code-only bootstrap (semantic extraction "
                "remains explicit)",
                file=sys.stderr,
            )
            _bootstrap_structural_graph(project)
    elif before["state"] == "stale":
        _run(["graphify", "update", ".", "--no-cluster"], project)

    if not graph.is_file():
        return inspect_project(project)
    out = graph.parent
    _stamp_commit(project, graph)
    _run([
        "graphify", "tree", "--graph", str(graph), "--output",
        str(out / "GRAPH_TREE.html"), "--root", str(project),
        "--label", project.name,
    ], project)

    # ``--no-cluster`` is the safe, fast graph refresh mode, but it does not
    # emit graph.html.  Rebuild the deterministic viewer/report only when it
    # is absent; ``--no-label`` guarantees no semantic naming call.
    if not (out / "graph.html").is_file():
        _run(["graphify", "cluster-only", ".", "--no-label"], project)

    memory = out / "memory"
    if memory.is_dir() and any(memory.iterdir()):
        _run([
            "graphify", "reflect", "--memory-dir", str(memory),
            "--out", str(out / "reflections" / "LESSONS.md"),
            "--graph", str(graph),
        ], project)
    return inspect_project(project)


def _selected_projects(root: Path, names: Iterable[str]) -> list[Path]:
    discovered = discover_projects(root)
    if not names:
        return discovered
    wanted = set(names)
    return [p for p in discovered if p.name in wanted]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "refresh"))
    parser.add_argument(
        "--projects-root",
        default=os.environ.get("STC_PROJECTS_ROOT"),
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[2] / "stc.yaml"),
    )
    parser.add_argument("--project", action="append", default=[])
    parser.add_argument("--bootstrap-missing", action="store_true")
    args = parser.parse_args(argv)

    configured_root, configured_names = configured_projects(args.config)
    root = Path(args.projects_root or configured_root or "~/Work/projects").expanduser()
    names = args.project or configured_names
    projects = _selected_projects(root, names)
    if not projects:
        print(f"No projects found under {root}", file=sys.stderr)
        return 1

    for project in projects:
        status = (
            inspect_project(project)
            if args.action == "audit"
            else refresh_project(project, args.bootstrap_missing)
        )
        status["actions"] = plan_actions(status)
        print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
