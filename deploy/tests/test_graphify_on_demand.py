"""On-demand graph bootstrap for structural code questions."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "scripts"))
import graphify_on_demand as ON_DEMAND


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init")
    return repo


def test_existing_graph_is_returned_without_refresh(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    graph = repo / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    monkeypatch.setattr(ON_DEMAND, "refresh_project", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected refresh")))

    assert ON_DEMAND.ensure_graph(repo) == graph


def test_missing_graph_bootstraps_once(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    graph = repo / "graphify-out" / "graph.json"
    calls = []

    def bootstrap(path, bootstrap_missing=False):
        calls.append((path, bootstrap_missing))
        graph.parent.mkdir()
        graph.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")

    monkeypatch.setattr(ON_DEMAND, "refresh_project", bootstrap)

    assert ON_DEMAND.ensure_graph(repo) == graph
    assert ON_DEMAND.ensure_graph(repo) == graph
    assert calls == [(repo, True)]


def test_invalid_graph_is_rebuilt(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    graph = repo / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text("null", encoding="utf-8")
    calls = []

    def bootstrap(path, bootstrap_missing=False):
        calls.append((path, bootstrap_missing))
        graph.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")

    monkeypatch.setattr(ON_DEMAND, "refresh_project", bootstrap)

    assert ON_DEMAND.ensure_graph(repo) == graph
    assert calls == [(repo, True)]


def test_linked_worktree_reuses_primary_checkout_graph(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    worktree = tmp_path / "task-worktree"
    _git(repo, "worktree", "add", "-qb", "task", str(worktree))
    graph = repo / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
    monkeypatch.setattr(ON_DEMAND, "refresh_project", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected refresh")))

    assert ON_DEMAND.ensure_graph(worktree) == graph
    assert not (worktree / "graphify-out").exists()


def test_cli_returns_graph_path_for_structural_use(tmp_path, monkeypatch, capsys):
    graph = tmp_path / "graph.json"
    monkeypatch.setattr(ON_DEMAND, "ensure_graph", lambda _path: graph)

    assert ON_DEMAND.main(["--project", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == str(graph)
