"""Behavior tests for the generated project Snapshot/index contract."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "scripts"))

import project_snapshot as PS  # noqa: E402


def test_project_snapshot_is_navigation_only_and_has_freshness_metadata(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    status = {
        "name": "demo",
        "path": str(project),
        "head": "abc123",
        "branch": "main",
        "dirty": False,
        "memory": "~/Work/memory/project_demo.md",
        "graph": {
            "status": "healthy",
            "path": "./graphify-out/graph.json",
            "built_at_commit": "abc123",
        },
        "docs": ["README.md"],
        "generated_at": "2026-08-03T20:00:00+00:00",
        "source_commit": "abc123",
    }

    text = PS.render_project_snapshot(status)

    assert text.startswith("---\n")
    assert "type: project-snapshot" in text
    assert "source_commit: abc123" in text
    assert "graph_status: healthy" in text
    assert "README.md" in text
    assert "Read this snapshot first" in text
    assert "full history" not in text.lower()


def test_project_snapshot_exposes_unverified_graph_quality_explicitly():
    text = PS.render_project_snapshot(
        {
            "name": "demo",
            "graph": {
                "status": "unverified",
                "semantic_status": "UNVERIFIED",
                "query_status": "UNVERIFIED",
            },
        }
    )

    assert "semantic_quality: UNVERIFIED" in text
    assert "query_quality: UNVERIFIED" in text
    assert "Semantic quality: `UNVERIFIED`" in text
    assert "Query quality: `UNVERIFIED`" in text


def test_index_lists_projects_and_marks_stale_graphs(tmp_path):
    rows = [
        {
            "name": "demo",
            "path": str(tmp_path / "demo"),
            "status": "active",
            "branch": "main",
            "dirty": True,
            "graph": {"status": "stale"},
            "memory": "~/Work/memory/project_demo.md",
            "snapshot": "~/Work/projects/demo/SNAPSHOT.md",
            "open_count": 2,
            "generated_at": "2026-08-03T20:00:00+00:00",
        }
    ]

    text = PS.render_index(rows, generated_at="2026-08-03T20:00:00+00:00")

    assert "type: project-index" in text
    assert "| demo |" in text
    assert "stale" in text
    assert "project_demo.md" in text
    assert "SNAPSHOT.md" in text
    assert "project Snapshot first" in text


def test_git_exclude_is_idempotent_and_does_not_duplicate_snapshot_rule(tmp_path):
    git_dir = tmp_path / ".git"
    info = git_dir / "info"
    info.mkdir(parents=True)
    exclude = info / "exclude"
    exclude.write_text("# local excludes\n", encoding="utf-8")

    assert PS.ensure_git_exclude(tmp_path) is True
    assert PS.ensure_git_exclude(tmp_path) is False
    assert exclude.read_text(encoding="utf-8").count("/SNAPSHOT.md") == 1
    assert exclude.read_text(encoding="utf-8").count("/graphify-out/") == 1


def test_generated_graphify_and_snapshot_artifacts_do_not_make_git_dirty(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True, text=True)

    (project / "graphify-out").mkdir()
    (project / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
    (project / "SNAPSHOT.md").write_text("generated", encoding="utf-8")

    status = PS.inspect_project(project, tmp_path / "memory")

    assert status["dirty"] is False

    (project / "source.py").write_text("print('dirty')\n", encoding="utf-8")
    assert PS.inspect_project(project, tmp_path / "memory")["dirty"] is True


def test_snapshot_resolves_canonical_uppercase_project_memory(tmp_path):
    project = tmp_path / "STC"
    project.mkdir()
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "project_STC.md").write_text("## OPEN\n- one\n", encoding="utf-8")

    status = PS.inspect_project(project, memory)

    assert status["memory"].endswith("project_STC.md")
    assert status["memory_present"] is True
    assert status["open_count"] == 1


def test_run_uses_central_registry_paths_for_project_index(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    demo = root / "demo"
    demo.mkdir()
    external = tmp_path / "STC"
    external.mkdir()
    (demo / "README.md").write_text("# Demo\n", encoding="utf-8")
    (external / "README.md").write_text("# STC\n", encoding="utf-8")
    memory = tmp_path / "memory"
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "doc_backend:\n"
        f"  root: {memory}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n"
        f"    paths: [{external}]\n",
        encoding="utf-8",
    )

    result = PS.run(config, tmp_path / "index.md")

    assert result["projects"] == 2
    index = (tmp_path / "index.md").read_text(encoding="utf-8")
    assert "| demo |" in index
    assert "| STC |" in index


def test_snapshot_cli_defers_without_successful_graphify_state(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    (root / "demo").mkdir()
    memory = tmp_path / "memory"
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "doc_backend:\n"
        f"  root: {memory}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n",
        encoding="utf-8",
    )
    output = tmp_path / "index.md"
    state = tmp_path / "graphify-state.json"

    result = subprocess.run(
        [
            sys.executable,
            str(Path(PS.__file__).resolve()),
            "run",
            "--config",
            str(config),
            "--output",
            str(output),
            "--state-file",
            str(state),
            "--require-graphify-state",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 75
    assert "graphify" in result.stdout.lower()
    assert not output.exists()


def test_snapshot_plan_defers_when_graphify_state_is_stale_for_project(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "demo"
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
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n",
        encoding="utf-8",
    )
    state = tmp_path / "graphify-state.json"
    state.write_text(
        json.dumps(
            {
                "status": "success",
                "completed_at": "2026-08-04T10:05:00+00:00",
                "projects": {
                    str(project.resolve()): {
                        "head": "old-head",
                        "built_at_commit": "old-head",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    plan = PS.plan_run(config, state, require_graphify_state=True)

    assert head != "old-head"
    assert plan["allowed"] is False
    assert plan["reason"] == "graphify-state-stale"


def test_snapshot_records_graphify_completion_from_success_state(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "demo"
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
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "doc_backend:\n"
        f"  root: {tmp_path / 'memory'}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n",
        encoding="utf-8",
    )
    completed_at = "2026-08-04T10:05:00+00:00"
    state = tmp_path / "graphify-state.json"
    state.write_text(
        json.dumps(
            {
                "status": "success",
                "completed_at": completed_at,
                "projects": {
                    str(project.resolve()): {
                        "head": head,
                        "built_at_commit": head,
                        "state": "unverified",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = PS.run(
        config,
        tmp_path / "index.md",
        state_file=state,
        require_graphify_state=True,
    )

    assert result.get("status") == "success"
    snapshot = (project / "SNAPSHOT.md").read_text(encoding="utf-8")
    assert f"graphify_completed_at: {completed_at}" in snapshot


def test_non_git_project_accepts_successful_unverified_graphify_state(tmp_path):
    root = tmp_path / "projects"
    project = root / "personal-assistant"
    graph_out = project / "graphify-out"
    graph_out.mkdir(parents=True)
    (graph_out / "graph.json").write_text(
        json.dumps({"nodes": [], "links": [], "built_at_commit": ""}),
        encoding="utf-8",
    )
    (graph_out / "graph.html").write_text("viewer", encoding="utf-8")
    (graph_out / "GRAPH_TREE.html").write_text("tree", encoding="utf-8")
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "doc_backend:\n"
        f"  root: {tmp_path / 'memory'}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [personal-assistant]\n",
        encoding="utf-8",
    )
    state = tmp_path / "graphify-state.json"
    state.write_text(
        json.dumps({
            "status": "success",
            "completed_at": "2026-08-04T10:05:00+00:00",
            "projects": {
                str(project.resolve()): {
                    "head": "",
                    "built_at_commit": "",
                    "state": "unverified",
                }
            },
        }),
        encoding="utf-8",
    )

    result = PS.run(
        config,
        tmp_path / "index.md",
        state_file=state,
        require_graphify_state=True,
    )

    assert result["status"] == "success"
    assert (project / "SNAPSHOT.md").is_file()


def test_snapshot_does_not_overwrite_tracked_snapshot(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    project = root / "demo"
    project.mkdir()
    subprocess.run(["git", "init", str(project)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Test"], check=True)
    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project / "SNAPSHOT.md").write_text("tracked snapshot\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "README.md", "SNAPSHOT.md"], check=True)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], check=True, capture_output=True, text=True)
    config = tmp_path / "stc.yaml"
    config.write_text(
        "workspace:\n"
        f"  root: {root}\n"
        "graphify:\n"
        "  projects:\n"
        f"    root: {root}\n"
        "    names: [demo]\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="tracked SNAPSHOT.md"):
        PS.run(config, tmp_path / "index.md")

    assert (project / "SNAPSHOT.md").read_text(encoding="utf-8") == "tracked snapshot\n"
