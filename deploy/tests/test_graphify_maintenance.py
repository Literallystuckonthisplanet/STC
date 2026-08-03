#!/usr/bin/env python3
"""Behavior tests for the local Graphify maintenance planner."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import graphify_maintenance as GM  # noqa: E402


def _graph(path: Path, built_at_commit: str = "old") -> None:
    out = path / "graphify-out"
    out.mkdir(parents=True)
    (out / "graph.json").write_text(
        json.dumps({"built_at_commit": built_at_commit, "nodes": [{"id": "n"}], "links": [{"source": "n", "target": "n"}]}),
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
    _graph(tmp_path, built_at_commit="abc")
    (tmp_path / "graphify-out" / "graph.html").write_text("viewer", encoding="utf-8")
    (tmp_path / "graphify-out" / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")

    status = GM.inspect_project(tmp_path, head="abc")

    assert status["state"] == "healthy"
    assert GM.plan_actions(status) == []
