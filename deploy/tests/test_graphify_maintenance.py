#!/usr/bin/env python3
"""Behavior tests for the local Graphify maintenance planner."""

import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import graphify_maintenance as GM  # noqa: E402


def _plist(name: str) -> dict:
    with (REPO / "deploy" / "launchd" / name).open("rb") as fh:
        return plistlib.load(fh)


def test_background_jobs_have_ordered_daily_run_at_load_contract(tmp_path):
    graphify = _plist("com.xtoshin.stc-graphify-maintenance.plist")
    snapshot = _plist("com.xtoshin.stc-project-snapshot.plist")

    assert graphify["RunAtLoad"] is True
    assert snapshot["RunAtLoad"] is True
    assert graphify["ProcessType"] == snapshot["ProcessType"] == "Background"
    assert graphify["LowPriorityIO"] is True
    assert snapshot["LowPriorityIO"] is True
    assert graphify["StartCalendarInterval"] == {"Hour": 10, "Minute": 5}
    assert snapshot["StartCalendarInterval"] == {"Hour": 10, "Minute": 15}
    assert "--state-file" in graphify["ProgramArguments"]
    assert "--require-graphify-state" in snapshot["ProgramArguments"]


def _graph(
    path: Path,
    built_at_commit: str = "old",
    semantic_status: str | None = None,
    query_status: str | None = None,
) -> None:
    out = path / "graphify-out"
    out.mkdir(parents=True)
    data = {
        "built_at_commit": built_at_commit,
        "nodes": [{"id": "n"}],
        "links": [{"source": "n", "target": "n"}],
    }
    if semantic_status is not None:
        data["semantic_status"] = semantic_status
    if query_status is not None:
        data["query_status"] = query_status
    (out / "graph.json").write_text(
        json.dumps(data),
        encoding="utf-8",
    )
    (out / "GRAPH_REPORT.md").write_text("# report\n", encoding="utf-8")


def test_inspect_project_distinguishes_missing_graph(tmp_path):
    status = GM.inspect_project(tmp_path, head="abc")

    assert status["state"] == "missing"
    assert status["graph_present"] is False
    assert "bootstrap" in GM.plan_actions(status)


def test_inspect_project_marks_stale_graph_and_missing_viewer(tmp_path):
    _graph(tmp_path, built_at_commit="old")

    status = GM.inspect_project(tmp_path, head="abc")

    assert status["state"] == "stale"
    assert status["graph_present"] is True
    assert status["nodes"] == 1
    assert status["links"] == 1
    actions = GM.plan_actions(status)
    assert "refresh" in actions
    assert "tree" in actions


def test_inspect_project_is_healthy_only_with_current_graph_and_viewer(tmp_path):
    _graph(
        tmp_path,
        built_at_commit="abc",
        semantic_status="VERIFIED",
        query_status="VERIFIED",
    )
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="abc")

    assert status["state"] == "healthy"
    assert GM.plan_actions(status) == []


def test_empty_git_head_is_not_healthy_even_with_current_graph(tmp_path):
    (tmp_path / ".git").mkdir()
    _graph(tmp_path, built_at_commit="")
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="")

    assert status["state"] == "unhealthy"


def test_non_git_graph_is_unverified_and_plans_daily_refresh(tmp_path):
    _graph(tmp_path, built_at_commit="")
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="")

    assert status["vcs"] == "directory"
    assert status["state"] == "unverified"
    assert "refresh" in GM.plan_actions(status)


def test_semantic_and_query_quality_are_unverified_not_healthy(tmp_path):
    _graph(tmp_path, built_at_commit="abc")
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="abc")

    assert status.get("semantic_status") == "UNVERIFIED"
    assert status.get("query_status") == "UNVERIFIED"
    assert status["state"] == "unverified"


def test_empty_built_commit_plans_refresh_when_git_head_exists(tmp_path):
    _graph(tmp_path, built_at_commit="")
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="abc")

    assert status["state"] == "unhealthy"
    assert "refresh" in GM.plan_actions(status)


def test_configured_projects_can_include_a_non_git_project(tmp_path):
    project = tmp_path / "personal-assistant"
    project.mkdir()

    selected = GM._selected_projects(tmp_path, ["personal-assistant"])

    assert selected == [project]


def test_configured_registry_includes_explicit_paths_outside_root(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    external = tmp_path / "STC"
    external.mkdir()
    config = tmp_path / "stc.yaml"
    config.write_text(
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n"
        f"    paths: [{external}]\n",
        encoding="utf-8",
    )

    configured_root, names = GM.configured_projects(config)

    assert configured_root == root
    assert str(external) in names


def test_refresh_cli_publishes_success_state_after_project_pass(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "demo"
    project.mkdir()
    state = tmp_path / "graphify-state.json"
    config = tmp_path / "stc.yaml"
    config.write_text(
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n"
        "  scheduler:\n"
        f"    state_file: {state}\n",
        encoding="utf-8",
    )

    def fake_refresh(path, bootstrap_missing=False):
        return {
            "project": str(path.resolve()),
            "head": "abc",
            "built_at_commit": "abc",
            "state": "unverified",
            "semantic_status": "UNVERIFIED",
            "query_status": "UNVERIFIED",
        }

    monkeypatch.setattr(GM, "refresh_project", fake_refresh)

    exit_code = GM.main(["refresh", "--config", str(config)])

    assert exit_code == 0
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["projects"][str(project.resolve())]["built_at_commit"] == "abc"


def test_refresh_rejects_non_generated_repository_changes(tmp_path, monkeypatch):
    project = tmp_path / "demo"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _graph(project, built_at_commit="old")

    def unsafe_run(command, cwd):
        if command[1] == "update":
            (cwd / "graphify-out" / "graph.json").write_text(
                json.dumps(
                    {
                        "built_at_commit": head,
                        "nodes": [{"id": "n"}],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
        elif command[1] == "tree":
            (cwd / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")
        elif command[1] == "cluster-only":
            (cwd / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
        (cwd / "tracked-by-mistake.txt").write_text("not allowed", encoding="utf-8")

    monkeypatch.setattr(GM, "_run", unsafe_run)

    with pytest.raises(RuntimeError, match="non-generated repository state"):
        GM.refresh_project(project)


def test_tracked_diff_ignores_generated_graphify_and_snapshot_files(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "graphify-out").mkdir()
    (project / "graphify-out" / "graph.json").write_text("old graph\n", encoding="utf-8")
    (project / "SNAPSHOT.md").write_text("old snapshot\n", encoding="utf-8")
    (project / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True, text=True)

    (project / "graphify-out" / "graph.json").write_text("new graph\n", encoding="utf-8")
    (project / "SNAPSHOT.md").write_text("new snapshot\n", encoding="utf-8")
    assert GM._tracked_diff(project) == ""

    (project / "README.md").write_text("source changed\n", encoding="utf-8")
    assert "README.md" in GM._tracked_diff(project)


def test_refresh_updates_graph_when_built_commit_is_empty(tmp_path, monkeypatch):
    project = tmp_path / "demo"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _graph(project, built_at_commit="")
    calls = []

    def fake_run(command, cwd):
        calls.append(command)
        if command[1] == "update":
            (cwd / "graphify-out" / "graph.json").write_text(
                json.dumps(
                    {
                        "built_at_commit": head,
                        "nodes": [{"id": "n"}],
                        "links": [],
                    }
                ),
                encoding="utf-8",
            )
        elif command[1] == "tree":
            (cwd / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")
        elif command[1] == "cluster-only":
            (cwd / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")

    monkeypatch.setattr(GM, "_run", fake_run)

    GM.refresh_project(project)

    assert any(command[1] == "update" for command in calls)


def test_daily_refresh_updates_current_graph_to_include_working_tree_changes(tmp_path, monkeypatch):
    project = tmp_path / "demo"
    project.mkdir()
    _graph(project, built_at_commit="abc")
    (project / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (project / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")
    calls = []

    monkeypatch.setattr(GM, "_read_head", lambda _project: "abc")
    monkeypatch.setattr(GM, "_repo_status_paths", lambda _project: set())
    monkeypatch.setattr(GM, "_tracked_diff", lambda _project: "")
    monkeypatch.setattr(GM, "_run", lambda command, _cwd: calls.append(command))

    GM.refresh_project(project)

    assert any(command[1] == "update" for command in calls)


def test_bootstrap_missing_graph_is_structural_only(tmp_path, monkeypatch):
    project = tmp_path / "demo"
    project.mkdir()
    calls = []

    def fake_run(command, cwd):
        calls.append(command)
        if command[1] == "extract":
            out = cwd / "graphify-out"
            out.mkdir(exist_ok=True)
            (out / "graph.json").write_text(
                json.dumps({"built_at_commit": "", "nodes": [], "links": []}),
                encoding="utf-8",
            )
        elif command[1] == "tree":
            (cwd / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")
        elif command[1] == "cluster-only":
            (cwd / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")

    monkeypatch.setattr(GM, "_run", fake_run)

    GM.refresh_project(project, bootstrap_missing=True)

    extract = next(command for command in calls if command[1] == "extract")
    assert "--no-cluster" in extract
    assert "--exclude" in extract
