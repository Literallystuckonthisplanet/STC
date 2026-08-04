"""Behavior matrix for the high-impact harness-neutral hooks.

The contract smoke test proves that every hook starts. This file proves the
important branches: allow, block, one-shot acknowledgement, and additive
diagnostics without leaking the protected value.
"""

import json
import os
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "core" / "hooks"


def _env(tmp_path, **extra):
    env = os.environ.copy()
    env.update(
        {
            "STC_CORE": str(REPO / "core"),
            "HARNESS_DIR": str(tmp_path / "harness"),
            "MEMORY_DIR": str(tmp_path / "memory"),
            "PROJECTS_ROOT": str(tmp_path / "projects"),
            "RELEASE_ACK_FILE": str(tmp_path / "release-ack"),
            "NATIVE_DIR": str(tmp_path / "native"),
            "USER_LANG": "en",
        }
    )
    env.update(extra)
    return env


def _run(name, payload, tmp_path, **env_overrides):
    return subprocess.run(
        ["bash", str(HOOKS / name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=_env(tmp_path, **env_overrides),
        cwd=tmp_path,
        check=False,
    )


def _codex_event(tmp_path, event="PreToolUse", **fields):
    """A realistic current Codex hook envelope, with event-specific fields."""
    payload = {
        "cwd": str(tmp_path),
        "hook_event_name": event,
        "model": "gpt-5.6-luna",
        "permission_mode": "default",
        "session_id": f"codex-{tmp_path.name}",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
        "turn_id": "turn-1",
    }
    payload.update(fields)
    return payload


def test_h01_dangerous_git_blocks_but_safe_command_passes(tmp_path):
    blocked = _run(
        "block-dangerous-git.sh",
        {"tool_input": {"command": "git  reset   --hard HEAD"}},
        tmp_path,
    )
    allowed = _run(
        "block-dangerous-git.sh",
        {"tool_input": {"command": "git status --short"}},
        tmp_path,
    )
    assert blocked.returncode == 2
    assert "reset" in blocked.stderr
    assert allowed.returncode == 0


def test_h01_release_ack_is_one_shot(tmp_path):
    payload = {"session_id": "behavior-release", "tool_input": {"command": "git push origin main"}}
    first = _run("block-dangerous-git.sh", payload, tmp_path)
    assert first.returncode == 2
    assert "RELEASE" in first.stderr

    ack = tmp_path / "release-ack"
    ack.touch()
    second = _run("block-dangerous-git.sh", payload, tmp_path)
    third = _run("block-dangerous-git.sh", payload, tmp_path)
    assert second.returncode == 0
    assert third.returncode == 2
    assert not ack.exists()


def test_h01_commit_no_verify_is_a_hard_block(tmp_path):
    for command in ("git commit --no-verify -m checked", "git commit -n -m checked"):
        blocked = _run(
            "block-dangerous-git.sh",
            {"tool_input": {"command": command}},
            tmp_path,
        )
        assert blocked.returncode == 2
        assert "no-verify" in blocked.stderr
        assert blocked.stdout == ""


def test_h05_memory_secret_blocks_without_echoing_value(tmp_path):
    memory_file = tmp_path / "memory" / "project_demo.md"
    secret = "sk-" + "A" * 24
    blocked = _run(
        "secret-scan-memory.sh",
        {"tool_input": {"file_path": str(memory_file), "content": f"key={secret}"}},
        tmp_path,
    )
    allowed = _run(
        "secret-scan-memory.sh",
        {"tool_input": {"file_path": str(memory_file), "content": "key is in ${API_KEY}"}},
        tmp_path,
    )
    assert blocked.returncode == 2
    assert secret not in blocked.stderr
    assert allowed.returncode == 0


def test_h06_injects_startup_but_not_compact(tmp_path):
    startup = _run("session-start-context.sh", {"source": "startup"}, tmp_path)
    compact = _run("session-start-context.sh", {"source": "compact"}, tmp_path)
    assert startup.returncode == 0
    assert "rules/behavior.md" in startup.stdout
    assert "rules/pev.md" in startup.stdout
    assert "rules/session.md" in startup.stdout
    assert compact.returncode == 0
    assert compact.stdout == ""


def test_h17_secret_read_guard_has_allow_and_block_branches(tmp_path):
    blocked = _run(
        "secret-read-guard.sh",
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/project/.env"}},
        tmp_path,
    )
    allowed = _run(
        "secret-read-guard.sh",
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp/project/README.md"}},
        tmp_path,
    )
    assert blocked.returncode == 2
    assert ".env" in blocked.stderr
    assert allowed.returncode == 0


def test_h18_graphify_first_blocks_once_then_allows_exact_retry(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
    payload = {
        "tool_name": "Bash",
        "session_id": "behavior-graphify",
        "tool_input": {"command": "rg target ."},
    }
    marker = Path("/tmp/stc-graphify-behavior-graphify-" + str(tmp_path).replace("/", "-").lstrip("-"))
    first = _run("graphify-first.sh", payload, tmp_path, USER_LANG="en")
    second = _run("graphify-first.sh", payload, tmp_path, USER_LANG="en")
    try:
        assert first.returncode == 2
        assert "graphify-first" in first.stderr
        assert second.returncode == 0
    finally:
        marker.unlink(missing_ok=True)


def test_h22_is_additive_and_only_warns_on_underspecified_prompt(tmp_path):
    flagged = _run(
        "prompt-lens.sh",
        {"prompt": "проверь"},
        tmp_path,
        STC_LENS_RULES=str(REPO / "core" / "scripts" / "lens_rules.py"),
    )
    precise = _run(
        "prompt-lens.sh",
        {"prompt": "проверь `README.md`, готово когда тесты зелёные"},
        tmp_path,
        STC_LENS_RULES=str(REPO / "core" / "scripts" / "lens_rules.py"),
    )
    assert flagged.returncode == 0
    assert "additive hint" in flagged.stdout
    assert precise.returncode == 0
    assert precise.stdout == ""


def test_h21_plan_gate_blocks_incomplete_then_accepts_complete_plan(tmp_path):
    session = f"behavior-plan-{tmp_path.name}"
    marker = Path(f"/tmp/stc-exitplan-gate-{session}")
    incomplete = _run(
        "exit-plan-grill.sh",
        {"session_id": session, "tool_input": {"plan": "## Plan\nDo the work."}},
        tmp_path,
    )
    complete = _run(
        "exit-plan-grill.sh",
        {
            "session_id": f"{session}-complete",
            "tool_input": {
                "plan": (
                    "AC/DoD: tests pass. builder executes the block. "
                    "развилки: открытых нет. Правила проекта: задача → модель → режим."
                )
            },
        },
        tmp_path,
    )
    try:
        assert incomplete.returncode == 2
        assert "missing" in incomplete.stderr
        assert complete.returncode == 0
    finally:
        marker.unlink(missing_ok=True)
        Path(f"/tmp/stc-exitplan-gate-{session}-complete").unlink(missing_ok=True)


def test_codex_h04_binds_subagent_start_and_agent_payloads(tmp_path):
    """H04 reads current top-level SubagentStart and direct Agent payloads."""
    start = _run(
        "agent-reuse-contract.sh",
        _codex_event(
            tmp_path,
            "SubagentStart",
            agent_id="agent-1",
            agent_type="builder",
            agent_transcript_path=str(tmp_path / "agent.jsonl"),
            prompt="Implement the block.",
            reason="spawn",
        ),
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert start.returncode == 2
    assert "reuse-before-reinvent" in start.stderr

    direct = _run(
        "agent-reuse-contract.sh",
        _codex_event(
            tmp_path,
            tool_name="Agent",
            tool_input={
                "subagent_type": "builder",
                "prompt": "reuse-before-reinvent; fork-protocol; implement the block.",
            },
        ),
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert direct.returncode == 0


def test_codex_h04_requires_contract_only_for_explicit_terra_sol_override(tmp_path):
    """Routine Luna production stays un-escalated; explicit Terra needs a contract."""
    base = _codex_event(
        tmp_path,
        "SubagentStart",
        agent_type="builder",
        prompt="reuse-before-reinvent; fork-protocol; implement the block.",
    )
    routine = _run(
        "agent-reuse-contract.sh",
        base,
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert routine.returncode == 0

    terra = _run(
        "agent-reuse-contract.sh",
        dict(base, model="gpt-5.6-terra"),
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert terra.returncode == 2
    assert "output contract" in terra.stderr

    contracted = _run(
        "agent-reuse-contract.sh",
        dict(
            base,
            model="gpt-5.6-terra",
            prompt=(
                "reuse-before-reinvent; fork-protocol; escalation: trigger; "
                "why Luna is insufficient; bounded scope; continuation on Luna; "
                "status FORK."
            ),
        ),
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert contracted.returncode == 0


def test_codex_h14_reads_apply_patch_payload_without_plan_escalation(tmp_path):
    """A normal Codex apply_patch gets the buy-vs-build reminder, not a tier jump."""
    payload = _codex_event(
        tmp_path,
        tool_name="apply_patch",
        permission_mode="default",
        tool_input={
            "input": (
                "*** Begin Patch\n"
                "*** Add File: src/new_module.py\n"
                "+def run():\n"
                "+    return 1\n"
                "*** End Patch"
            )
        },
    )
    marker = Path(f"/tmp/stc-buyvsbuild-{payload['session_id']}")
    marker.unlink(missing_ok=True)
    try:
        result = _run(
            "buy-vs-build-reminder.sh",
            payload,
            tmp_path,
            HARNESS_NAME="codex",
        )
        assert result.returncode == 0
        assert "buy-vs-build" in result.stdout
        assert not re.search(r"\b(?:terra|sol)\b", result.stdout, re.IGNORECASE)
    finally:
        marker.unlink(missing_ok=True)


def test_codex_h21_apply_patch_plan_mode_does_not_read_claude_plans(tmp_path):
    """Codex plan mode is gated from the real apply_patch event, independently."""
    fake_home = tmp_path / "home"
    claude_plans = fake_home / ".claude" / "plans"
    claude_plans.mkdir(parents=True)
    (claude_plans / "complete.md").write_text(
        "AC/DoD: complete. builder executes. развилки: открытых нет. "
        "Правила проекта: задача → модель → режим.",
        encoding="utf-8",
    )
    payload = _codex_event(
        tmp_path,
        tool_name="apply_patch",
        permission_mode="plan",
        tool_input={
            "input": "*** Begin Patch\n*** Add File: src/x.py\n+pass\n*** End Patch"
        },
    )
    marker = Path(f"/tmp/stc-exitplan-gate-{payload['session_id']}")
    default_marker = Path(f"/tmp/stc-exitplan-gate-{payload['session_id']}-default")
    marker.unlink(missing_ok=True)
    default_marker.unlink(missing_ok=True)
    try:
        blocked = _run(
            "exit-plan-grill.sh",
            payload,
            tmp_path,
            HARNESS_NAME="codex",
            HOME=str(fake_home),
        )
        assert blocked.returncode == 2
        assert "Codex" in blocked.stderr
        assert "complete.md" not in blocked.stderr

        allowed = _run(
            "exit-plan-grill.sh",
            dict(payload, permission_mode="default", session_id=payload["session_id"] + "-default"),
            tmp_path,
            HARNESS_NAME="codex",
            HOME=str(fake_home),
        )
        assert allowed.returncode == 0
    finally:
        marker.unlink(missing_ok=True)
        default_marker.unlink(missing_ok=True)


def test_codex_h17_blocks_secret_reads_from_read_and_exec_tools_without_leaks(tmp_path):
    """H17 protects shell/unified-exec paths and emits only a pattern label."""
    cases = [
        ("Bash", {"command": "cat .env && printf TOP_SECRET_SENTINEL"}, ".env"),
        ("exec", {"command": 'python3 -c \'open("client.pem").read()\''}, "pem"),
        ("unifiedExec", {"input": "grep token credentials.json"}, "credentials"),
    ]
    for tool_name, tool_input, label in cases:
        result = _run(
            "block-secret-read.sh",
            _codex_event(tmp_path, tool_name=tool_name, tool_input=tool_input),
            tmp_path,
            HARNESS_NAME="codex",
        )
        assert result.returncode == 2
        assert label in result.stderr.lower()
        assert "TOP_SECRET_SENTINEL" not in result.stderr
        assert tool_input.get("command", tool_input.get("input")) not in result.stderr

    allowed = _run(
        "block-secret-read.sh",
        _codex_event(tmp_path, tool_name="exec", tool_input={"command": "cat README.md"}),
        tmp_path,
        HARNESS_NAME="codex",
    )
    assert allowed.returncode == 0
