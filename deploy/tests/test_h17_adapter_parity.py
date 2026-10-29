"""H17 payload parity across adapters that share the structured-read hook."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GENERIC_HOOK = ROOT / "core" / "hooks" / "secret-read-guard.sh"
CODEX_HOOK = ROOT / "core" / "hooks" / "block-secret-read.sh"
sys.path.insert(0, str(ROOT / "core" / "hooks"))
import secret_read_policy


def _run(harness, event, tmp_path):
    hook = CODEX_HOOK if harness == "codex" else GENERIC_HOOK
    env = os.environ.copy()
    env.update({"STC_CORE": str(ROOT / "core"), "HARNESS_NAME": harness, "USER_LANG": "en"})
    return subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=tmp_path,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("harness", ["claude", "zcode"])
def test_structured_grep_query_word_is_not_a_protected_target(tmp_path, harness):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("literal = '.env.local'\n", encoding="utf-8")
    event = {
        "tool_name": "Grep",
        "tool_input": {"pattern": ".env.local", "path": str(source)},
    }
    assert secret_read_policy.decide(event, harness) == ("safe", "")
    result = _run(harness, event, tmp_path)
    assert result.returncode == 0


def test_shared_policy_accepts_codex_query_text_for_plain_file(tmp_path):
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("credentials = 'synthetic only'\n", encoding="utf-8")
    event = {
        "tool_name": "exec",
        "tool_input": {"command": "rg -n credentials src/app.py"},
        "cwd": str(tmp_path),
    }
    assert secret_read_policy.decide(event, "codex") == ("safe", "")
    event_level_command = {
        "tool_name": "exec",
        "command": "rg -n credentials src/app.py",
        "cwd": str(tmp_path),
    }
    assert secret_read_policy.decide(event_level_command, "codex") == ("safe", "")


def test_shared_policy_checks_unified_exec_input_for_protected_hints():
    event = {"tool_name": "unifiedExec", "tool_input": {"input": "grep token credentials.json"}}
    assert secret_read_policy.decide(event, "codex") == ("blocked", "credentials")


@pytest.mark.parametrize("command_field", ["command", "cmd"])
def test_codex_exec_uses_tool_workdir_for_relative_targets(tmp_path, command_field):
    event_cwd = tmp_path / "context"
    workdir = event_cwd / "workspace"
    event_cwd.mkdir()
    workdir.mkdir()
    (event_cwd / "alias.txt").write_text("ordinary context file\n", encoding="utf-8")
    protected = workdir / ".env.sample"
    protected.write_text("synthetic only\n", encoding="utf-8")
    (workdir / "alias.txt").symlink_to(protected)
    (workdir / "ordinary.txt").write_text("ordinary workspace file\n", encoding="utf-8")

    protected_event = {
        "tool_name": "exec",
        "cwd": str(event_cwd),
        "tool_input": {command_field: "rg -n needle alias.txt", "workdir": "workspace"},
    }
    assert secret_read_policy.decide(protected_event, "codex") == ("blocked", ".env")

    ordinary_event = {
        "tool_name": "exec",
        "cwd": str(event_cwd),
        "tool_input": {command_field: "rg -n needle ordinary.txt", "workdir": "workspace"},
    }
    assert secret_read_policy.decide(ordinary_event, "codex") == ("safe", "")


def test_codex_exec_rejects_conflicting_cwd_and_workdir(tmp_path):
    event_cwd = tmp_path / "context"
    first = event_cwd / "one"
    second = event_cwd / "two"
    first.mkdir(parents=True)
    second.mkdir()
    event = {
        "tool_name": "exec",
        "cwd": str(event_cwd),
        "tool_input": {
            "command": "rg -n needle ordinary.txt",
            "cwd": str(first),
            "workdir": str(second),
        },
    }
    assert secret_read_policy.decide(event, "codex") == ("unparsed", "")


def test_structured_grep_does_not_use_unknown_workdir_field(tmp_path):
    event_cwd = tmp_path / "context"
    workdir = event_cwd / "workspace"
    event_cwd.mkdir()
    workdir.mkdir()
    (event_cwd / "alias.txt").write_text("ordinary context file\n", encoding="utf-8")
    protected = workdir / ".env.sample"
    protected.write_text("synthetic only\n", encoding="utf-8")
    (workdir / "alias.txt").symlink_to(protected)
    event = {
        "tool_name": "Grep",
        "cwd": str(event_cwd),
        "tool_input": {"pattern": "needle", "path": "alias.txt", "workdir": "workspace"},
    }
    assert secret_read_policy.decide(event, "codex") == ("safe", "")


@pytest.mark.parametrize("harness", ["claude", "codex", "zcode"])
def test_h17_structured_read_policy_parity(tmp_path, harness):
    src = tmp_path / "src"
    src.mkdir()
    ordinary = src / "app.py"
    ordinary.write_text("literal = '.env.local'\n", encoding="utf-8")
    protected = src / ".env.sample"
    protected.write_text("synthetic only\n", encoding="utf-8")
    alias = src / "alias.txt"
    alias.symlink_to(protected)

    plain_grep = _run(
        harness,
        {"tool_name": "Grep", "tool_input": {"pattern": ".env.local", "path": str(ordinary)}},
        tmp_path,
    )
    assert plain_grep.returncode == 0

    direct_read = _run(
        harness,
        {"tool_name": "Read", "tool_input": {"file_path": str(protected)}},
        tmp_path,
    )
    assert direct_read.returncode == 2
    assert ".env" in direct_read.stderr.lower()
    assert str(protected) not in direct_read.stderr

    parent_traversal = _run(
        harness,
        {"tool_name": "Read", "tool_input": {"file_path": "src/../src/.env.sample"}},
        tmp_path,
    )
    assert parent_traversal.returncode == 2
    assert ".env" in parent_traversal.stderr.lower()

    symlink_read = _run(
        harness,
        {"tool_name": "Grep", "tool_input": {"pattern": "needle", "path": str(alias)}},
        tmp_path,
    )
    assert symlink_read.returncode == 2
    assert ".env" in symlink_read.stderr.lower()

    folder_scan = _run(
        harness,
        {"tool_name": "Grep", "tool_input": {"pattern": "needle", "path": str(src)}},
        tmp_path,
    )
    assert folder_scan.returncode == 2
    assert "safely analyze" in folder_scan.stderr.lower()
    assert "needle" not in folder_scan.stderr.lower()

    missing_target = _run(
        harness,
        {"tool_name": "Grep", "tool_input": {"pattern": ".env.local"}},
        tmp_path,
    )
    assert missing_target.returncode == 2
    assert "safely analyze" in missing_target.stderr.lower()
    assert ".env.local" not in missing_target.stderr.lower()

    glob_target = _run(
        harness,
        {"tool_name": "Glob", "tool_input": {"pattern": "src/.env.sample"}},
        tmp_path,
    )
    assert glob_target.returncode == 2
    assert ".env" in glob_target.stderr.lower()

    # Glob only lists matching names; ordinary wildcards do not read contents.
    broad_glob = _run(
        harness,
        {"tool_name": "Glob", "tool_input": {"pattern": "**/*.md"}},
        tmp_path,
    )
    assert broad_glob.returncode == 0

    protected_glob = _run(
        harness,
        {"tool_name": "Glob", "tool_input": {"pattern": "**/.env*"}},
        tmp_path,
    )
    assert protected_glob.returncode == 2
    assert ".env" in protected_glob.stderr.lower()

    protected_glob_base = _run(
        harness,
        {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.md", "path": str(protected)},
        },
        tmp_path,
    )
    assert protected_glob_base.returncode == 2
    assert ".env" in protected_glob_base.stderr.lower()

    literal_glob = _run(
        harness,
        {"tool_name": "Glob", "tool_input": {"pattern": "src/app.py"}},
        tmp_path,
    )
    assert literal_glob.returncode == 0

    structured_write = _run(
        harness,
        {"tool_name": "Write", "tool_input": {"file_path": str(protected), "content": "synthetic only"}},
        tmp_path,
    )
    assert structured_write.returncode == 0
