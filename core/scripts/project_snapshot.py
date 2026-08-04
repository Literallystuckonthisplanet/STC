#!/usr/bin/env python3
"""Generate deterministic project snapshots and a central project index.

Snapshots are navigation artifacts, not a second memory store.  They contain
freshness and pointer metadata gathered from the filesystem, git, project
memory, and Graphify.  No LLM is involved and no project source is edited.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DOC_NAMES = (
    "README.md", "CLAUDE.md", "AGENTS.md", "CONTEXT.md", "STATUS.md",
    "DECISIONS.md", "PLAN.md", "DEPLOY.md",
)
GENERATED_STATUS_PREFIXES = ("graphify-out/",)
GENERATED_STATUS_FILES = {"SNAPSHOT.md"}
DEFERRED_EXIT = 75
DEFAULT_GRAPHIFY_STATE = Path("~/Work/memory/stc-scheduler/graphify-state.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def _run(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _status_paths(status: str) -> list[str]:
    paths: list[str] = []
    for line in status.splitlines():
        payload = line[3:] if len(line) >= 4 else ""
        candidates = payload.split(" -> ") if " -> " in payload else [payload]
        paths.extend(path.strip().lstrip("./") for path in candidates if path.strip())
    return paths


def _is_generated_path(path: str) -> bool:
    return path in GENERATED_STATUS_FILES or path.startswith(GENERATED_STATUS_PREFIXES)


def _git_info(project: Path) -> dict[str, Any]:
    if not (project / ".git").exists():
        return {"vcs": "none", "branch": "", "head": "", "dirty": None}
    status = _run(project, "status", "--porcelain", "--untracked-files=all")
    dirty_paths = [path for path in _status_paths(status) if not _is_generated_path(path)]
    return {
        "vcs": "git",
        "branch": _run(project, "branch", "--show-current"),
        "head": _run(project, "rev-parse", "HEAD"),
        "dirty": bool(dirty_paths),
    }


def _memory_file(memory_root: Path, name: str) -> Path:
    return memory_root / f"project_{name.replace('-', '_')}.md"


def _open_count(path: Path) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    inside = False
    count = 0
    for line in lines:
        if line.startswith("## "):
            inside = line[3:].strip().upper().startswith("OPEN")
            continue
        if inside and line.lstrip().startswith(("- ", "* ")):
            count += 1
    return count


def _docs(project: Path) -> list[str]:
    return [name for name in DOC_NAMES if (project / name).is_file()]


def _projects_for_snapshot(config_path: Path, workspace_root: Path) -> list[Path]:
    try:
        import graphify_maintenance as gm

        configured_root, names = gm.configured_projects(config_path)
    except Exception:  # pragma: no cover - fallback for standalone use
        configured_root, names = None, []
    if names:
        return gm._selected_projects(configured_root or workspace_root, names)
    return sorted(
        p for p in workspace_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    ) if workspace_root.is_dir() else []


def _read_state(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "graphify-state-missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "graphify-state-invalid"
    if not isinstance(data, dict):
        return None, "graphify-state-invalid"
    if data.get("status") != "success":
        return data, "graphify-state-not-successful"
    if not data.get("completed_at"):
        return data, "graphify-state-incomplete"
    return data, None


def _configured_state_path(config_path: Path) -> Path:
    try:
        import yaml

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        snapshot_scheduler = ((config.get("project_snapshot") or {}).get("scheduler") or {})
        graphify_scheduler = ((config.get("graphify") or {}).get("scheduler") or {})
        value = (
            snapshot_scheduler.get("state_file")
            if isinstance(snapshot_scheduler, dict)
            else None
        ) or (
            graphify_scheduler.get("state_file")
            if isinstance(graphify_scheduler, dict)
            else None
        ) or str(DEFAULT_GRAPHIFY_STATE)
    except (OSError, ValueError, TypeError):
        value = str(DEFAULT_GRAPHIFY_STATE)
    return Path(os.path.expandvars(str(value))).expanduser().resolve()


def plan_run(
    config_path: Path | str,
    state_file: Path | str | None = None,
    require_graphify_state: bool = False,
) -> dict[str, Any]:
    """Plan a snapshot run without writing any project or index artifacts."""
    state_path = (
        Path(state_file).expanduser().resolve()
        if state_file
        else _configured_state_path(Path(config_path))
    )
    if not require_graphify_state:
        return {"allowed": True, "reason": "graphify-state-not-required", "state": None}
    state, reason = _read_state(state_path)
    if reason is None:
        import yaml

        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        workspace = config.get("workspace") or {}
        root = Path(
            os.path.expandvars(str(workspace.get("root", "~/Work/projects")))
        ).expanduser().resolve()
        project_state = state.get("projects") if isinstance(state, dict) else None
        if not isinstance(project_state, dict):
            reason = "graphify-state-stale"
        else:
            for project in _projects_for_snapshot(Path(config_path), root):
                entry = project_state.get(str(project.resolve()))
                git = _git_info(project)
                head = git.get("head", "")
                invalid = not isinstance(entry, dict) or entry.get("state") not in {
                    "healthy", "unverified"
                }
                if git.get("vcs") == "git":
                    invalid = invalid or not head or entry.get("head") != head \
                        or entry.get("built_at_commit") != head
                else:
                    invalid = invalid or bool(entry.get("head")) \
                        or bool(entry.get("built_at_commit"))
                if invalid:
                    reason = "graphify-state-stale"
                    break
    return {
        "allowed": reason is None,
        "reason": reason or "graphify-state-ready",
        "state": state,
        "state_file": str(state_path),
    }


def _graph_status(project: Path, head: str) -> dict[str, Any]:
    try:
        import graphify_maintenance as gm

        record = gm.inspect_project(project, head=head)
    except Exception as exc:  # pragma: no cover - defensive scheduler boundary
        return {"status": "audit-error", "error": str(exc)}
    return {
        "status": record.get("state", "missing"),
        "path": "./graphify-out/graph.json",
        "viewer": "./graphify-out/GRAPH_TREE.html",
        "built_at_commit": record.get("built_at_commit", ""),
        "nodes": record.get("nodes", 0),
        "links": record.get("links", 0),
        "lessons": bool(record.get("lessons_present")),
        "semantic_status": record.get("semantic_status", "UNVERIFIED"),
        "query_status": record.get("query_status", "UNVERIFIED"),
        "health": record.get("health", record.get("state", "missing")),
    }


def inspect_project(project: Path | str, memory_root: Path | str, generated_at: str | None = None) -> dict[str, Any]:
    project = Path(project).expanduser().resolve()
    memory_root = Path(memory_root).expanduser().resolve()
    generated_at = generated_at or _now()
    git = _git_info(project)
    memory = _memory_file(memory_root, project.name)
    return {
        "name": project.name,
        "path": str(project),
        "project_type": "git" if git["vcs"] == "git" else "directory",
        **git,
        "memory": _short_path(memory),
        "memory_present": memory.is_file(),
        "open_count": _open_count(memory),
        "docs": _docs(project),
        "snapshot": _short_path(project / "SNAPSHOT.md"),
        "graph": _graph_status(project, git["head"]),
        "generated_at": generated_at,
        "source_commit": git["head"],
    }


def render_project_snapshot(status: dict[str, Any]) -> str:
    graph = status.get("graph") or {}
    docs = status.get("docs") or []
    dirty = status.get("dirty")
    dirty_text = "unknown" if dirty is None else str(bool(dirty)).lower()
    lines = [
        "---",
        "type: project-snapshot",
        "schema_version: 1",
        f"generated_at: {status.get('generated_at', '')}",
        f"source_commit: {status.get('source_commit', '')}",
        f"graph_status: {graph.get('status', 'missing')}",
        f"semantic_quality: {graph.get('semantic_status', 'UNVERIFIED')}",
        f"query_quality: {graph.get('query_status', 'UNVERIFIED')}",
        f"graphify_completed_at: {status.get('graphify_completed_at', '')}",
        "---",
        "",
        f"# {status.get('name', '')} — project snapshot",
        "",
        "> Read this snapshot first for generated status and navigation. Durable decisions live in project memory and repo docs.",
        "",
        "## Current pointers",
        "",
        f"- Repository: `{status.get('path', '')}`",
        f"- VCS: `{status.get('vcs', 'none')}`",
        f"- Branch: `{status.get('branch') or '—'}`",
        f"- HEAD: `{status.get('head') or '—'}`",
        f"- Dirty: `{dirty_text}`",
        f"- Project memory: `{status.get('memory', '')}` ({'present' if status.get('memory_present') else 'missing'})",
        f"- Open memory items: `{status.get('open_count', 0)}`",
        "",
        "## Read next",
        "",
        "- For current status: start with this snapshot; follow project memory for durable decisions and open questions.",
        "- For project documentation: open the files below.",
        "- For code structure, connections, or blast radius: use Graphify.",
        "",
        "### Project docs",
        "",
    ]
    lines.extend(f"- `{doc}`" for doc in docs) if docs else lines.append("- none discovered")
    lines.extend([
        "",
        "### Graphify",
        "",
        f"- Status: `{graph.get('status', 'missing')}`",
        f"- Health: `{graph.get('health', graph.get('status', 'missing'))}`",
        f"- Semantic quality: `{graph.get('semantic_status', 'UNVERIFIED')}`",
        f"- Query quality: `{graph.get('query_status', 'UNVERIFIED')}`",
        f"- Graph: `{graph.get('path', './graphify-out/graph.json')}`",
        f"- Viewer: `{graph.get('viewer', './graphify-out/GRAPH_TREE.html')}`",
        f"- Built at commit: `{graph.get('built_at_commit') or '—'}`",
        f"- Nodes / links: `{graph.get('nodes', 0)} / {graph.get('links', 0)}`",
        "",
        "Snapshot is generated by STC and must not be edited manually.",
        "",
    ])
    return "\n".join(lines)


def render_index(rows: Iterable[dict[str, Any]], generated_at: str | None = None) -> str:
    generated_at = generated_at or _now()
    rows = list(rows)
    lines = [
        "---",
        "type: project-index",
        "schema_version: 1",
        f"generated_at: {generated_at}",
        f"project_count: {len(rows)}",
        "---",
        "",
        "# Projects — index",
        "",
        "> First stop for project status and navigation. This is a generated pointer catalog, not the project Wiki.",
        "",
        "| Project | VCS | Branch | Dirty | Memory | Open | Graphify | Snapshot |",
        "|---|---|---|---:|---|---:|---|---|",
    ]
    for row in rows:
        graph = row.get("graph") or {}
        dirty = "—" if row.get("dirty") is None else ("yes" if row.get("dirty") else "no")
        lines.append(
            f"| {row.get('name', '')} | {row.get('vcs', 'none')} | "
            f"{row.get('branch') or '—'} | {dirty} | {row.get('memory', '')} | "
            f"{row.get('open_count', 0)} | {graph.get('status', 'missing')} | "
            f"{row.get('snapshot', '')} |"
        )
    lines.extend([
        "",
        "## Routing rules",
        "",
        "- Status / current state → open the project Snapshot first; then follow its memory pointer for durable details.",
        "- Project docs / decisions → follow the project docs listed in its snapshot.",
        "- Code relationships / impact → use the project's Graphify map.",
        "- Graphify does not contain project memory; these are separate layers.",
        "",
    ])
    return "\n".join(lines)


def ensure_git_exclude(project: Path | str) -> bool:
    """Keep the generated root snapshot out of git without editing .gitignore."""
    project = Path(project).expanduser().resolve()
    if not (project / ".git").exists():
        return False
    git_exclude = _run(project, "rev-parse", "--git-path", "info/exclude")
    if git_exclude:
        exclude = Path(git_exclude)
        if not exclude.is_absolute():
            exclude = (project / exclude).resolve()
    elif (project / ".git").is_dir():
        # Useful for a partially initialized repository and for the small
        # filesystem contract test; real worktrees use rev-parse above.
        exclude = project / ".git" / "info" / "exclude"
    else:
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    rules = ["/SNAPSHOT.md", "/graphify-out/"]
    missing = [rule for rule in rules if rule not in existing.splitlines()]
    if not missing:
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def _is_tracked(project: Path, relative_path: str) -> bool:
    return bool(_run(project, "ls-files", "--error-unmatch", "--", relative_path))


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def run(
    config_path: Path | str,
    output: Path | str | None = None,
    *,
    state_file: Path | str | None = None,
    require_graphify_state: bool = False,
) -> dict[str, Any]:
    import yaml

    config_path = Path(config_path).expanduser().resolve()
    plan = plan_run(config_path, state_file, require_graphify_state)
    if not plan["allowed"]:
        return {
            "status": "deferred",
            "reason": plan["reason"],
            "state_file": plan.get("state_file", ""),
        }
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    workspace = config.get("workspace") or {}
    root = Path(os.path.expandvars(str(workspace.get("root", "~/Work/projects")))).expanduser().resolve()
    memory_config = config.get("doc_backend") or {}
    memory_root = Path(os.path.expandvars(str(memory_config.get("root", "~/Work/memory")))).expanduser().resolve()
    generated_at = _now()
    projects = _projects_for_snapshot(Path(config_path), root)
    rows = [inspect_project(project, memory_root, generated_at) for project in projects]
    graphify_completed_at = (plan.get("state") or {}).get("completed_at", "")
    for row in rows:
        row["graphify_completed_at"] = graphify_completed_at
    for row in rows:
        project = Path(row["path"])
        if _is_tracked(project, "SNAPSHOT.md"):
            raise RuntimeError(f"refusing to overwrite tracked SNAPSHOT.md in {project}")
        _write_atomic(project / "SNAPSHOT.md", render_project_snapshot(row))
        ensure_git_exclude(project)
    index = Path(output).expanduser().resolve() if output else memory_root / "projects" / "SNAPSHOT.md"
    _write_atomic(index, render_index(rows, generated_at))
    return {
        "status": "success",
        "generated_at": generated_at,
        "graphify_completed_at": graphify_completed_at,
        "projects": len(rows),
        "index": str(index),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", default="run")
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[2] / "stc.yaml"))
    parser.add_argument("--output")
    parser.add_argument("--state-file")
    parser.add_argument("--require-graphify-state", action="store_true")
    args = parser.parse_args(argv)
    result = run(
        args.config,
        args.output,
        state_file=args.state_file,
        require_graphify_state=args.require_graphify_state,
    )
    print(json.dumps(result, ensure_ascii=False))
    return DEFERRED_EXIT if result.get("status") == "deferred" else 0


if __name__ == "__main__":
    raise SystemExit(main())
