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
import tempfile
from datetime import datetime, timezone
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
DEFAULT_STATE_FILE = Path("~/Work/memory/stc-scheduler/graphify-state.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quality_status(value: object) -> str:
    value = str(value or "").strip().upper()
    return value if value in {"VERIFIED", "UNVERIFIED"} else "UNVERIFIED"


def _set_health(record: dict) -> dict:
    state = record.get("state", "missing")
    record["health"] = state
    record["health_status"] = str(state).upper()
    record["healthy"] = state == "healthy"
    return record


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


def scheduler_settings(config_path: Path | str) -> dict[str, object]:
    """Return scheduler settings with safe defaults for standalone CLI use."""
    settings: dict[str, object] = {
        "frequency": "daily",
        "hour": 10,
        "minute": 5,
        "state_file": DEFAULT_STATE_FILE.expanduser().resolve(),
    }
    path = Path(config_path).expanduser()
    try:
        import yaml

        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        scheduler = ((config.get("graphify") or {}).get("scheduler") or {})
        if isinstance(scheduler, dict):
            for key in ("frequency", "hour", "minute"):
                if key in scheduler:
                    settings[key] = scheduler[key]
            if scheduler.get("state_file"):
                settings["state_file"] = Path(
                    os.path.expandvars(str(scheduler["state_file"]))
                ).expanduser().resolve()
    except (OSError, ValueError, TypeError):
        pass
    return settings


def maintenance_state_path(
    config_path: Path | str,
    override: Path | str | None = None,
) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return Path(scheduler_settings(config_path)["state_file"])


def inspect_project(project: Path | str, head: str | None = None) -> dict:
    """Return a stable, JSON-friendly health record for one project."""
    project = Path(project).expanduser().resolve()
    out = project / "graphify-out"
    graph = out / "graph.json"
    head = _read_head(project) if head is None else head
    is_git = bool(head) or (project / ".git").exists()
    record = {
        "project": str(project),
        "name": project.name,
        "head": head,
        "vcs": "git" if is_git else "directory",
        "graph_present": graph.is_file(),
        "report_present": (out / "GRAPH_REPORT.md").is_file(),
        "viewer_present": (out / "graph.html").is_file(),
        "tree_present": (out / "GRAPH_TREE.html").is_file(),
        "memory_present": (out / "memory").is_dir(),
        "lessons_present": (out / "reflections" / "LESSONS.md").is_file(),
        "built_at_commit": "",
        "nodes": 0,
        "links": 0,
        "semantic_status": "UNVERIFIED",
        "query_status": "UNVERIFIED",
        "semantic_quality": "UNVERIFIED",
        "query_quality": "UNVERIFIED",
        "state": "missing",
    }
    if not graph.is_file():
        return _set_health(record)

    try:
        data = json.loads(graph.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        record["state"] = "invalid"
        record["error"] = str(exc)
        return _set_health(record)

    record["built_at_commit"] = str(data.get("built_at_commit") or "")
    record["nodes"] = len(data.get("nodes") or [])
    record["links"] = len(data.get("links") or [])
    record["semantic_status"] = _quality_status(data.get("semantic_status"))
    record["query_status"] = _quality_status(data.get("query_status"))
    record["semantic_quality"] = record["semantic_status"]
    record["query_quality"] = record["query_status"]
    if is_git:
        if not head or not record["built_at_commit"]:
            record["state"] = "unhealthy"
        elif record["built_at_commit"] != head:
            record["state"] = "stale"
        elif not record["viewer_present"] or not record["tree_present"]:
            record["state"] = "incomplete"
        elif record["semantic_status"] != "VERIFIED" or record["query_status"] != "VERIFIED":
            record["state"] = "unverified"
        else:
            record["state"] = "healthy"
    elif not record["viewer_present"] or not record["tree_present"]:
        record["state"] = "incomplete"
    else:
        # A directory project has no immutable git commit to stamp. Its daily
        # refresh is therefore explicit and its quality remains UNVERIFIED,
        # never falsely healthy.
        record["state"] = "unverified"
    return _set_health(record)


def plan_actions(status: dict) -> list[str]:
    """Return idempotent maintenance actions for an inspection record."""
    state = status.get("state")
    if state in {"missing", "invalid"}:
        return ["bootstrap"]
    actions: list[str] = []
    if (
        state == "stale"
        or (state == "unhealthy" and status.get("head"))
        or (status.get("vcs") == "directory" and status.get("graph_present"))
    ):
        actions.append("refresh")
    if not status.get("viewer_present") or not status.get("tree_present"):
        actions.append("tree")
    if status.get("memory_present") and not status.get("lessons_present"):
        actions.append("reflect")
    return actions


def build_state(
    statuses: Iterable[dict],
    *,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    error: str | None = None,
) -> dict:
    projects: dict[str, dict] = {}
    for record in statuses:
        project = record.get("project")
        if not project:
            continue
        projects[str(Path(project).expanduser().resolve())] = {
            "head": record.get("head", ""),
            "built_at_commit": record.get("built_at_commit", ""),
            "state": record.get("state", "missing"),
            "semantic_status": record.get("semantic_status", "UNVERIFIED"),
            "query_status": record.get("query_status", "UNVERIFIED"),
        }
    payload = {
        "schema_version": 1,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at or "",
        "projects": projects,
    }
    if error:
        payload["error"] = error
    return payload


def write_state(path: Path | str, payload: dict) -> None:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


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
    paths = projects.get("paths", []) if isinstance(projects, dict) else []
    if not isinstance(paths, list):
        paths = []
    root = None
    if isinstance(projects, dict) and projects.get("root"):
        root = Path(os.path.expandvars(str(projects["root"]))).expanduser()
    configured = [*names, *paths]
    return root, [str(name) for name in configured if str(name).strip()]


def _run(command: list[str], cwd: Path) -> None:
    actual = command
    if command and command[0] == "graphify":
        actual = [os.environ.get("GRAPHIFY_CLI", "graphify"), *command[1:]]
    print("$", " ".join(actual))
    subprocess.run(actual, cwd=str(cwd), check=True)


def _repo_status_paths(project: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        payload = line[3:] if len(line) >= 4 else ""
        candidates = payload.split(" -> ") if " -> " in payload else [payload]
        paths.update(path.strip().lstrip("./") for path in candidates if path.strip())
    return paths


def _tracked_diff(project: Path) -> str:
    result = subprocess.run(
        [
            "git", "-C", str(project), "diff", "--no-ext-diff", "--binary",
            "HEAD", "--", ".", ":(exclude)graphify-out/**", ":(exclude)SNAPSHOT.md",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _generated_repo_path(path: str) -> bool:
    path = path.replace(os.sep, "/")
    return path == "SNAPSHOT.md" or path.startswith("graphify-out/")


def _assert_background_scope(
    project: Path,
    before_paths: set[str],
    before_diff: str,
) -> None:
    after_paths = _repo_status_paths(project)
    changed_paths = {
        path for path in before_paths ^ after_paths if not _generated_repo_path(path)
    }
    if changed_paths or before_diff != _tracked_diff(project):
        changed = ", ".join(sorted(changed_paths)) or "tracked content"
        raise RuntimeError(
            f"background maintenance changed non-generated repository state: {changed}"
        )


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
    project = Path(project).expanduser().resolve()
    before_paths = _repo_status_paths(project)
    before_diff = _tracked_diff(project)
    before = inspect_project(project)
    graph = _graph_file(project)
    if before["state"] in {"missing", "invalid"}:
        if not bootstrap_missing:
            return before
        _bootstrap_structural_graph(project)
    else:
        # The daily job refreshes even a commit-current graph so uncommitted
        # working-tree edits are reflected. HEAD equality alone cannot prove
        # that a local development map is current.
        _run(["graphify", "update", ".", "--no-cluster"], project)

    if not graph.is_file():
        _assert_background_scope(project, before_paths, before_diff)
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
    _assert_background_scope(project, before_paths, before_diff)
    return inspect_project(project)


def _selected_projects(root: Path, names: Iterable[str]) -> list[Path]:
    names = list(names)
    if not names:
        return discover_projects(root)
    # An explicit registry is authoritative.  It may include a project that
    # is intentionally not a git checkout (for example a local assistant or a
    # document/code workspace); maintenance can still build a structural map.
    selected: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        candidate = Path(os.path.expandvars(str(name))).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if candidate.is_dir() and candidate not in seen:
            selected.append(candidate)
            seen.add(candidate)
    return selected


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
    parser.add_argument("--state-file")
    args = parser.parse_args(argv)

    configured_root, configured_names = configured_projects(args.config)
    root = Path(args.projects_root or configured_root or "~/Work/projects").expanduser()
    names = args.project or configured_names
    projects = _selected_projects(root, names)
    if not projects:
        print(f"No projects found under {root}", file=sys.stderr)
        return 1

    started_at = _now()
    statuses: list[dict] = []
    state_path = maintenance_state_path(args.config, args.state_file)
    if args.action == "refresh":
        write_state(
            state_path,
            build_state(statuses, status="running", started_at=started_at),
        )
    try:
        for project in projects:
            status = (
                inspect_project(project)
                if args.action == "audit"
                else refresh_project(project, args.bootstrap_missing)
            )
            status["actions"] = plan_actions(status)
            statuses.append(status)
            print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    except Exception as exc:
        if args.action == "refresh":
            write_state(
                state_path,
                build_state(
                    statuses,
                    status="failed",
                    started_at=started_at,
                    completed_at=_now(),
                    error=str(exc),
                ),
            )
        raise
    if args.action == "refresh":
        write_state(
            state_path,
            build_state(
                statuses,
                status="success",
                started_at=started_at,
                completed_at=_now(),
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
