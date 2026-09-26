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


def test_h06_claude_delivers_full_rules_in_bounded_parts(tmp_path):
    primary = _run(
        "session-start-context.sh",
        {"source": "startup"},
        tmp_path,
        HARNESS_NAME="claude",
    )
    extra = _run(
        "session-start-context-extra.sh",
        {"source": "startup"},
        tmp_path,
        HARNESS_NAME="claude",
    )
    assert primary.returncode == extra.returncode == 0
    contexts = []
    for result in (primary, extra):
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        context = payload["hookSpecificOutput"]["additionalContext"]
        assert len(context.encode()) < 9_000
        contexts.append(context)
    combined = "\n".join(contexts)
    assert "----- rules/behavior.md -----" in combined
    assert "----- rules/pev.md -----" in combined
    assert "----- rules/session.md -----" in combined
    assert "2–5 files" in combined
    assert "6+ files" in combined
    assert "Caveman only for read-only" in combined


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


def test_h18_first_touch_of_a_project_points_at_snapshot_without_blocking(tmp_path):
    """Ветка 2: обход каталогов ls/find/Read раньше проходил без единого указателя.

    Именно эта дыра дала «граф и снапшот собраны, но агент в них не смотрит»:
    ветка 1 стережёт только поиск по содержимому.
    """
    project = tmp_path / "projects" / "some-app"
    project.mkdir(parents=True)
    (project / "SNAPSHOT.md").write_text("# snapshot", encoding="utf-8")
    payload = {
        "tool_name": "Bash",
        "session_id": "behavior-entry",
        "tool_input": {"command": f"ls -la {project}"},
    }
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    marker = Path(f"/tmp/stc-projectfirst-behavior-entry-{slug}")
    marker.unlink(missing_ok=True)
    first = _run("graphify-first.sh", payload, tmp_path, USER_LANG="en")
    second = _run("graphify-first.sh", payload, tmp_path, USER_LANG="en")
    try:
        # подсказка, а не блок: чтение легитимно
        assert first.returncode == 0
        assert "project-first" in first.stdout
        assert "SNAPSHOT.md" in first.stdout
        assert json.loads(first.stdout)["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        # один раз на проект за сессию
        assert second.stdout == ""
    finally:
        marker.unlink(missing_ok=True)


def test_h18_missing_graph_gives_nonblocking_on_demand_pointer(tmp_path):
    project = tmp_path / "projects" / "missing-graph"
    project.mkdir(parents=True)
    (project / "SNAPSHOT.md").write_text("# snapshot", encoding="utf-8")
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    marker = Path(f"/tmp/stc-projectfirst-behavior-missing-{slug}")
    marker.unlink(missing_ok=True)
    result = _run(
        "graphify-first.sh",
        {
            "tool_name": "Bash",
            "session_id": "behavior-missing",
            "tool_input": {"command": f"rg symbol {project}"},
        },
        tmp_path,
        USER_LANG="en",
    )
    try:
        assert result.returncode == 0
        assert "graphify_on_demand.py" in result.stdout
        assert not (project / "graphify-out").exists()
    finally:
        marker.unlink(missing_ok=True)


def test_h18_grep_without_path_uses_event_cwd(tmp_path):
    project = tmp_path / "projects" / "cwd-project"
    project.mkdir(parents=True)
    (project / "SNAPSHOT.md").write_text("# snapshot", encoding="utf-8")
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    marker = Path(f"/tmp/stc-projectfirst-behavior-cwd-{slug}")
    marker.unlink(missing_ok=True)
    result = _run(
        "graphify-first.sh",
        {
            "tool_name": "Grep",
            "session_id": "behavior-cwd",
            "cwd": str(project),
            "tool_input": {"pattern": "symbol"},
        },
        tmp_path,
        USER_LANG="en",
    )
    try:
        assert result.returncode == 0
        assert "graphify_on_demand.py" in result.stdout
    finally:
        marker.unlink(missing_ok=True)


def test_h18_quoted_project_path_and_absolute_pattern(tmp_path):
    project = tmp_path / "projects" / "space project"
    project.mkdir(parents=True)
    (project / "SNAPSHOT.md").write_text("# snapshot", encoding="utf-8")
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    marker = Path(f"/tmp/stc-projectfirst-behavior-quoted-{slug}")
    marker.unlink(missing_ok=True)
    quoted = _run(
        "graphify-first.sh",
        {
            "tool_name": "Bash",
            "session_id": "behavior-quoted",
            "tool_input": {"command": f'rg symbol "{project}"'},
        },
        tmp_path,
        USER_LANG="en",
    )
    try:
        assert quoted.returncode == 0
        assert "graphify_on_demand.py" in quoted.stdout
    finally:
        marker.unlink(missing_ok=True)

    absolute_pattern = _run(
        "graphify-first.sh",
        {
            "tool_name": "Bash",
            "session_id": "behavior-quoted",
            "cwd": str(project),
            "tool_input": {"command": "rg /api/v1 ."},
        },
        tmp_path,
        USER_LANG="en",
    )
    try:
        assert absolute_pattern.returncode == 0
        assert "graphify_on_demand.py" in absolute_pattern.stdout
    finally:
        marker.unlink(missing_ok=True)


def test_h18_does_not_fire_when_the_snapshot_itself_is_being_read(tmp_path):
    """Чтение снапшота — это и есть нужное поведение, подсказка была бы шумом."""
    project = tmp_path / "projects" / "quiet-app"
    project.mkdir(parents=True)
    snapshot = project / "SNAPSHOT.md"
    snapshot.write_text("# snapshot", encoding="utf-8")
    result = _run(
        "graphify-first.sh",
        {
            "tool_name": "Read",
            "session_id": "behavior-quiet",
            "tool_input": {"file_path": str(snapshot)},
        },
        tmp_path,
        USER_LANG="en",
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_h18_grep_branch_still_blocks_after_the_entry_branch_was_added(tmp_path):
    """Страж против регресса: у веток отдельные маркеры.

    Если бы они делили один маркер, первое же чтение съедало бы блокировку
    grep-цепочки, и ветка 1 замолчала бы незаметно.
    """
    project = tmp_path / "projects" / "graphed-app"
    (project / "graphify-out").mkdir(parents=True)
    (project / "graphify-out" / "graph.json").write_text("{}", encoding="utf-8")
    (project / "SNAPSHOT.md").write_text("# snapshot", encoding="utf-8")
    slug = re.sub(r"[^a-zA-Z0-9]", "-", str(project))
    entry_marker = Path(f"/tmp/stc-projectfirst-behavior-both-{slug}")
    grep_marker = Path(f"/tmp/stc-graphify-behavior-both-{slug}")
    for m in (entry_marker, grep_marker):
        m.unlink(missing_ok=True)
    read_first = _run(
        "graphify-first.sh",
        {
            "tool_name": "Read",
            "session_id": "behavior-both",
            "tool_input": {"file_path": str(project / "app.ts")},
        },
        tmp_path,
        USER_LANG="en",
    )
    then_grep = _run(
        "graphify-first.sh",
        {
            "tool_name": "Grep",
            "session_id": "behavior-both",
            "tool_input": {"path": str(project)},
        },
        tmp_path,
        USER_LANG="en",
    )
    try:
        assert read_first.returncode == 0
        assert "project-first" in read_first.stdout
        assert then_grep.returncode == 2
        assert "graphify-first" in then_grep.stderr
    finally:
        for m in (entry_marker, grep_marker):
            m.unlink(missing_ok=True)


def test_h18_leaves_the_agents_own_infra_alone(tmp_path):
    """Инфра агента маршрутизируется своими правилами — H05/H09/session.md."""
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "SNAPSHOT.md").write_text("# infra snapshot", encoding="utf-8")
    result = _run(
        "graphify-first.sh",
        {
            "tool_name": "Read",
            "session_id": "behavior-infra",
            "tool_input": {"file_path": str(memory / "project_x.md")},
        },
        tmp_path,
        USER_LANG="en",
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_h22_is_additive_and_only_warns_on_underspecified_prompt(tmp_path):
    # Слово-градус при правке текста: осталось после снятия OPEN_VERB (2026-08-12)
    # и остаётся единственным классом с задокументированным реальным проколом.
    flagged = _run(
        "prompt-lens.sh",
        {"prompt": "стиль немного нейтральнее сделай"},
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


def test_codex_h04_requires_contract_for_explicit_terra_sol_astra_override(tmp_path):
    """Routine Luna stays un-escalated; stronger models need a full contract."""
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

    complete_prompt = (
        "reuse-before-reinvent; fork-protocol\n"
        "STC_ESCALATION_TRIGGER: contradictory architecture evidence\n"
        "STC_ESCALATION_WHY: Luna could not resolve the conflict\n"
        "STC_ESCALATION_SCOPE: review the two affected design documents\n"
        "STC_ESCALATION_CONTINUE: implementation remains with Luna\n"
        "STC_ESCALATION_RESULT: return DONE/FORK/BLOCKED/UNVERIFIED with evidence\n"
    )
    for model in ("gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-astra"):
        missing = _run(
            "agent-reuse-contract.sh", dict(base, model=model), tmp_path,
            HARNESS_NAME="codex",
        )
        slogan = _run(
            "agent-reuse-contract.sh",
            dict(base, model=model, prompt="reuse-before-reinvent; fork-protocol; bounded task status"),
            tmp_path, HARNESS_NAME="codex",
        )
        contracted = _run(
            "agent-reuse-contract.sh",
            dict(base, model=model, prompt=complete_prompt),
            tmp_path, HARNESS_NAME="codex",
        )
        assert missing.returncode == 2
        assert slogan.returncode == 2
        assert contracted.returncode == 0

    indented = _run(
        "agent-reuse-contract.sh",
        dict(base, model="gpt-6-astra", prompt="\n".join("  " + line for line in complete_prompt.splitlines())),
        tmp_path, HARNESS_NAME="codex",
    )
    fake_status = _run(
        "agent-reuse-contract.sh",
        dict(base, model="gpt-6-astra", prompt=complete_prompt.replace("DONE/FORK/BLOCKED/UNVERIFIED", "FORKED")),
        tmp_path, HARNESS_NAME="codex",
    )
    assert indented.returncode == 0
    assert fake_status.returncode == 2


def test_codex_qa_requires_a_linked_worktree_before_writing_tests(tmp_path):
    """A QA agent must not receive workspace-write in the shared checkout."""
    repo = tmp_path / "source"
    isolated = tmp_path / "qa-worktree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "baseline"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(isolated)], check=True)
    shared = _run(
        "agent-reuse-contract.sh",
        _codex_event(tmp_path, "SubagentStart", agent_type="qa", cwd=str(repo), prompt="Generate tests"),
        tmp_path, HARNESS_NAME="codex",
    )
    safe = _run(
        "agent-reuse-contract.sh",
        _codex_event(tmp_path, "SubagentStart", agent_type="qa", cwd=str(isolated), prompt="Generate tests"),
        tmp_path, HARNESS_NAME="codex",
    )
    assert shared.returncode == 2
    assert "worktree" in shared.stderr
    assert safe.returncode == 0


def test_h15_allows_bounded_output_and_child_agent_execution(tmp_path):
    """The suggested offload path must not be blocked by the same hook."""
    base = _codex_event(
        tmp_path, tool_name="Bash",
        tool_input={"command": "python3 scripts/sync.py --json"},
    )
    bounded = _run("exec-offload-guard.sh", base, tmp_path, HARNESS_NAME="codex")
    child = _run(
        "exec-offload-guard.sh",
        dict(base, agent_id="child-1", tool_input={"command": "python3 scripts/sync.py"}),
        tmp_path, HARNESS_NAME="codex",
    )
    main = _run(
        "exec-offload-guard.sh",
        dict(base, tool_input={"command": "python3 scripts/sync.py"}),
        tmp_path, HARNESS_NAME="codex",
    )
    assert bounded.returncode == 0
    assert child.returncode == 0
    assert main.returncode == 2


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


def _slice_layer(tmp_path, desc):
    """Крошечный отжатый слой: одна заметка, по которой хук должен сработать."""
    research = tmp_path / "mem" / "notes" / "research"
    research.mkdir(parents=True)
    (research / "prior-work.md").write_text(
        f'---\ndescription: "{desc}"\n---\n\n# {desc[:40]}\n', encoding="utf-8")
    return tmp_path / "mem"


def test_h19_serves_prior_work_when_a_plan_leaves_plan_mode(tmp_path):
    """Хук не напоминает искать, а подаёт найденное.

    Напоминание — это ровно тот advisory, который по defect_ledger
    рецидивирует: поиск по прошлым разговорам вызывался 15 раз за весь корпус.
    """
    mem = _slice_layer(tmp_path, "Ресёрч: движки памяти для агентов и аудит graphify")
    payload = {
        "tool_name": "ExitPlanMode",
        "session_id": "behavior-recall",
        "tool_input": {"plan": "Чиню цикл обучения graphify и подачу памяти агентам"},
    }
    res = _run("plan-recall.sh", payload, tmp_path,
               STC_CORE=str(REPO / "core"), STC_MEMORY_ROOT=str(mem), USER_LANG="ru")
    marker_glob = list(Path("/tmp").glob("stc-plan-recall-behavior-recall-*"))
    try:
        assert res.returncode == 0, res.stderr
        assert "plan-recall" in res.stdout
        assert "prior-work.md" in res.stdout
        body = json.loads(res.stdout)
        assert body["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    finally:
        for m in marker_glob:
            m.unlink(missing_ok=True)


def test_h19_stays_silent_when_the_topic_is_new(tmp_path):
    """Пустой результат — законный ответ, а не повод шуметь."""
    mem = _slice_layer(tmp_path, "Совершенно посторонняя тема про сроки доставки")
    res = _run("plan-recall.sh",
               {"tool_name": "ExitPlanMode", "session_id": "behavior-new",
                "tool_input": {"plan": "Внедряю квантовую криптографию в платёжный шлюз"}},
               tmp_path, STC_CORE=str(REPO / "core"), STC_MEMORY_ROOT=str(mem))
    for m in Path("/tmp").glob("stc-plan-recall-behavior-new-*"):
        m.unlink(missing_ok=True)
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_h19_does_not_repeat_itself_for_the_same_plan(tmp_path):
    mem = _slice_layer(tmp_path, "Ресёрч: движки памяти для агентов и аудит graphify")
    payload = {"tool_name": "ExitPlanMode", "session_id": "behavior-twice",
               "tool_input": {"plan": "Чиню цикл обучения graphify и подачу памяти агентам"}}
    env = {"STC_CORE": str(REPO / "core"), "STC_MEMORY_ROOT": str(mem)}
    first = _run("plan-recall.sh", payload, tmp_path, **env)
    second = _run("plan-recall.sh", payload, tmp_path, **env)
    for m in Path("/tmp").glob("stc-plan-recall-behavior-twice-*"):
        m.unlink(missing_ok=True)
    assert first.stdout.strip() != ""
    assert second.stdout.strip() == ""


def test_h19_ignores_subagents(tmp_path):
    """План предъявляет main, а не исполнитель."""
    mem = _slice_layer(tmp_path, "Ресёрч: движки памяти для агентов и аудит graphify")
    res = _run("plan-recall.sh",
               {"tool_name": "ExitPlanMode", "session_id": "behavior-sub",
                "agent_id": "builder-1",
                "tool_input": {"plan": "Чиню цикл обучения graphify"}},
               tmp_path, STC_CORE=str(REPO / "core"), STC_MEMORY_ROOT=str(mem))
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_h01_blocks_sweeping_add_but_allows_explicit_paths(tmp_path):
    """Сгребающая команда уносит чужое: индекс git общий на репозиторий.

    Так 2026-09-02 хук H19 с тестами уехал внутрь чужого коммита про
    Roundtable — историю чинить было уже нельзя, вторая сессия в ней писала.
    """
    sweep = _run("block-dangerous-git.sh",
                 {"session_id": "behavior-sweep", "tool_input": {"command": "git add -A"}},
                 tmp_path, USER_LANG="en")
    explicit = _run("block-dangerous-git.sh",
                    {"session_id": "behavior-sweep-2",
                     "tool_input": {"command": "git add core/hooks/one.sh core/hooks/two.sh"}},
                    tmp_path, USER_LANG="en")
    try:
        assert sweep.returncode == 2
        assert "sweeps the WHOLE tree" in sweep.stderr
        assert "worktree" in sweep.stderr
        assert explicit.returncode == 0
    finally:
        for s in ("behavior-sweep", "behavior-sweep-2"):
            Path(f"/tmp/stc-gitsweep-{s}").unlink(missing_ok=True)


def test_h01_sweeping_commit_flags_are_caught_too(tmp_path):
    """`commit -a` сгребает так же, как `add -A`, только в один шаг."""
    for command in ("git commit -a -m wip", "git commit -am wip"):
        session = f"behavior-{abs(hash(command))}"
        res = _run("block-dangerous-git.sh",
                   {"session_id": session, "tool_input": {"command": command}},
                   tmp_path, USER_LANG="en")
        Path(f"/tmp/stc-gitsweep-{session}").unlink(missing_ok=True)
        assert res.returncode == 2, command
        assert "sweeps the WHOLE tree" in res.stderr


def test_h01_sweep_block_is_acknowledge_once(tmp_path):
    """Первый коммит репозитория — законный случай; осознанный повтор проходит."""
    payload = {"session_id": "behavior-sweep-ack", "tool_input": {"command": "git add --all"}}
    first = _run("block-dangerous-git.sh", payload, tmp_path, USER_LANG="en")
    second = _run("block-dangerous-git.sh", payload, tmp_path, USER_LANG="en")
    Path("/tmp/stc-gitsweep-behavior-sweep-ack").unlink(missing_ok=True)
    assert first.returncode == 2
    assert second.returncode == 0


def test_h07_directs_to_a_worktree_instead_of_asking_whose_wip_it_is(tmp_path):
    """Сессия не может отличить свой WIP от чужого — значит и спрашивать нечего."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "someone-elses.txt").write_text("wip", encoding="utf-8")
    res = _run("dirty-tree-guard.sh",
               {"session_id": "behavior-worktree",
                "tool_input": {"file_path": str(repo / "mine.txt")}},
               tmp_path, USER_LANG="en", HARNESS_DIR=str(tmp_path / "nonexistent"))
    for m in Path("/tmp").glob("stc-dirty-check-behavior-worktree-*"):
        m.unlink(missing_ok=True)
    assert res.returncode == 2
    assert "git worktree add" in res.stderr
    assert "add -A" in res.stderr


def _repo_claim(repo):
    """Путь метки: тот же хеш пути, что считает хук."""
    digest = subprocess.run(["shasum"], input=str(repo), text=True,
                            capture_output=True).stdout[:12]
    return Path(f"/tmp/stc-repo-claim-{digest}")


def _fresh_repo(tmp_path, name="repo"):
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def test_h07_claims_the_repo_and_turns_away_a_second_session(tmp_path):
    """Замок H01 не даёт унести чужое, но не разводит сессии заранее.

    На чистом дереве проверка грязи молчит, и вторая сессия спокойно садится
    в то же дерево. Метка закрывает именно этот зазор.
    """
    repo = _fresh_repo(tmp_path)
    claim = _repo_claim(repo)
    claim.unlink(missing_ok=True)
    env = {"USER_LANG": "en", "HARNESS_DIR": str(tmp_path / "none")}
    first = _run("dirty-tree-guard.sh",
                 {"session_id": "session-one",
                  "tool_input": {"file_path": str(repo / "a.txt")}}, tmp_path, **env)
    second = _run("dirty-tree-guard.sh",
                  {"session_id": "session-two",
                   "tool_input": {"file_path": str(repo / "b.txt")}}, tmp_path, **env)
    try:
        assert first.returncode == 0, first.stderr
        assert claim.exists()
        assert claim.read_text().splitlines()[0] == "session-one"
        assert second.returncode == 2
        assert "another session is already working" in second.stderr
        assert "git worktree add" in second.stderr
    finally:
        claim.unlink(missing_ok=True)
        for m in Path("/tmp").glob("stc-dirty-check-session-*"):
            m.unlink(missing_ok=True)


def test_h07_claim_does_not_block_its_own_session(tmp_path):
    repo = _fresh_repo(tmp_path, "own")
    claim = _repo_claim(repo)
    claim.unlink(missing_ok=True)
    env = {"USER_LANG": "en", "HARNESS_DIR": str(tmp_path / "none")}
    payload = {"session_id": "same-session",
               "tool_input": {"file_path": str(repo / "a.txt")}}
    first = _run("dirty-tree-guard.sh", payload, tmp_path, **env)
    second = _run("dirty-tree-guard.sh", payload, tmp_path, **env)
    try:
        assert first.returncode == 0
        assert second.returncode == 0
    finally:
        claim.unlink(missing_ok=True)
        for m in Path("/tmp").glob("stc-dirty-check-same-session-*"):
            m.unlink(missing_ok=True)


def test_h07_stale_claim_is_taken_over(tmp_path):
    """Умершая сессия не должна держать репозиторий вечно."""
    repo = _fresh_repo(tmp_path, "stale")
    claim = _repo_claim(repo)
    claim.write_text("long-gone\n1\n", encoding="utf-8")  # отметка 1970 года
    res = _run("dirty-tree-guard.sh",
               {"session_id": "newcomer", "tool_input": {"file_path": str(repo / "a.txt")}},
               tmp_path, USER_LANG="en", HARNESS_DIR=str(tmp_path / "none"))
    try:
        assert res.returncode == 0, res.stderr
        assert claim.read_text().splitlines()[0] == "newcomer"
    finally:
        claim.unlink(missing_ok=True)
        for m in Path("/tmp").glob("stc-dirty-check-newcomer-*"):
            m.unlink(missing_ok=True)


def test_h07_subagent_neither_claims_nor_is_turned_away(tmp_path):
    """У субагента свой session_id, но работает он от имени основной сессии.

    Без этой ветки первый же builder блокировал бы сам себя меткой родителя.
    """
    repo = _fresh_repo(tmp_path, "withsub")
    claim = _repo_claim(repo)
    claim.unlink(missing_ok=True)
    env = {"USER_LANG": "en", "HARNESS_DIR": str(tmp_path / "none")}
    _run("dirty-tree-guard.sh",
         {"session_id": "main-session", "tool_input": {"file_path": str(repo / "a.txt")}},
         tmp_path, **env)
    sub = _run("dirty-tree-guard.sh",
               {"session_id": "builder-session", "agent_id": "builder-1",
                "tool_input": {"file_path": str(repo / "b.txt")}}, tmp_path, **env)
    try:
        assert sub.returncode == 0, sub.stderr
        assert claim.read_text().splitlines()[0] == "main-session"
    finally:
        claim.unlink(missing_ok=True)
        for m in Path("/tmp").glob("stc-dirty-check-*session-*"):
            m.unlink(missing_ok=True)


def _transcript(tmp_path, name, last_assistant_text):
    """Транскрипт, где последняя реплика ассистента — заданная."""
    p = tmp_path / name
    p.write_text("\n".join([
        json.dumps({"message": {"role": "user", "content": "погнали"}}),
        json.dumps({"message": {"role": "assistant",
                                "content": [{"type": "text",
                                             "text": last_assistant_text}]}}),
    ]) + "\n", encoding="utf-8")
    return p


def test_h23_asks_for_a_record_only_after_a_fork(tmp_path):
    """Приписка идёт, только если моя прошлая реплика несла маркер развилки.

    Молча отвергнутый вариант не остаётся нигде — ни в коде, ни в разговоре, —
    и через месяц предлагается заново. Но приписка на КАЖДОЕ сообщение была бы
    шумом: развилок по корпусу ~22 в месяц.
    """
    fork = _transcript(tmp_path, "fork.jsonl", "🗳️ Развилка: так или иначе?")
    plain = _transcript(tmp_path, "plain.jsonl", "Готово, посмотри.")

    after_fork = _run("decision-record.sh",
                      {"transcript_path": str(fork), "prompt": "вариант 1"},
                      tmp_path, USER_LANG="en")
    after_plain = _run("decision-record.sh",
                       {"transcript_path": str(plain), "prompt": "давай"},
                       tmp_path, USER_LANG="en")

    assert after_fork.returncode == 0
    assert "```decision" in after_fork.stdout
    assert "отклонено:" in after_fork.stdout
    assert after_plain.returncode == 0
    assert after_plain.stdout.strip() == ""


def test_h23_example_is_a_placeholder_the_counter_ignores(tmp_path):
    """Пример в приписке не должен засчитываться как настоящая запись.

    Иначе правило накручивается: показал формат — получил соблюдение.
    """
    import sys
    sys.path.insert(0, str(REPO / "core" / "scripts"))
    import decision_health as dh

    fork = _transcript(tmp_path, "fork.jsonl", "🗳️ выбор?")
    out = _run("decision-record.sh",
               {"transcript_path": str(fork), "prompt": "1"},
               tmp_path, USER_LANG="en").stdout
    body = re.search(r"```decision\n(.*?)```", out, re.S).group(1)
    assert dh.parse_block(body) == {"kept": [], "dropped": []}


def test_h23_is_silent_for_subagents_and_without_a_transcript(tmp_path):
    fork = _transcript(tmp_path, "fork.jsonl", "🗳️ выбор?")
    sub = _run("decision-record.sh",
               {"transcript_path": str(fork), "agent_id": "builder-1"},
               tmp_path, USER_LANG="en")
    nothing = _run("decision-record.sh", {"prompt": "x"}, tmp_path, USER_LANG="en")
    assert (sub.returncode, sub.stdout.strip()) == (0, "")
    assert (nothing.returncode, nothing.stdout.strip()) == (0, "")


def test_h23_ignores_a_toolonly_reply_and_looks_further_back(tmp_path):
    """Реплика без слов (только вызов инструмента) не гасит развилку."""
    p = tmp_path / "toolonly.jsonl"
    p.write_text("\n".join([
        json.dumps({"message": {"role": "assistant",
                                "content": [{"type": "text", "text": "🗳️ выбор?"}]}}),
        json.dumps({"message": {"role": "assistant",
                                "content": [{"type": "tool_use", "name": "Bash"}]}}),
    ]) + "\n", encoding="utf-8")
    res = _run("decision-record.sh", {"transcript_path": str(p), "prompt": "1"},
               tmp_path, USER_LANG="en")
    assert "```decision" in res.stdout


def test_h23_stays_silent_when_the_marker_is_only_mentioned(tmp_path):
    """Хук спрашивает правило у счётчика, а не держит свою копию.

    Разведённые копии одного правила уже расходились: в линзе аудит считал не
    то, что срабатывало. Здесь это проверяется поведением — разговор о
    маркере не должен открывать развилку.
    """
    mention = _transcript(tmp_path, "mention.jsonl",
                          "развилка без маркера 🗳️ в знаменатель не попадает")
    res = _run("decision-record.sh", {"transcript_path": str(mention), "prompt": "ок"},
               tmp_path, USER_LANG="en", STC_CORE=str(REPO / "core"))
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_h23_finds_the_counter_without_any_environment_variable(tmp_path):
    """В бою ${STC_CORE} подставляется в ТЕКСТ скрипта, в окружении его нет.

    Первая редакция читала os.environ и потому молчала ВСЕГДА. Тесты этого не
    увидели: они сами задавали переменную. Здесь она убрана, а путь по
    умолчанию ($HOME/.stc/core) подменён — как у развёрнутой копии.
    """
    fake_home = tmp_path / "home"
    (fake_home / ".stc").mkdir(parents=True)
    (fake_home / ".stc" / "core").symlink_to(REPO / "core")
    transcript = _transcript(tmp_path, "fork.jsonl", "## 🗳️ Развилка: A или B?")

    env = os.environ.copy()
    env.pop("STC_CORE", None)
    env["HOME"] = str(fake_home)
    env["USER_LANG"] = "en"
    res = subprocess.run(["bash", str(HOOKS / "decision-record.sh")],
                         input=json.dumps({"transcript_path": str(transcript)}),
                         text=True, capture_output=True, env=env)
    assert res.returncode == 0
    assert "```decision" in res.stdout, f"хук промолчал: {res.stderr[:200]}"


# --- Ревью 25.09: сторож и счётчик одинаково понимают ход и выбор ---


def _turns(tmp_path, name, records):
    """Транскрипт из пар (роль, текст); реплики человека — с origin, как в бою."""
    p = tmp_path / name
    rows = []
    for role, text in records:
        if role == "human":
            rows.append({"origin": {"kind": "human"},
                         "message": {"role": "user", "content": text}})
        else:
            rows.append({"message": {"role": "assistant",
                                     "content": [{"type": "text", "text": text}]}})
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                 encoding="utf-8")
    return p


def test_h23_is_silent_when_the_reply_is_a_question(tmp_path):
    """«Сколько будет стоить A?» — не выбор: просьба записать решение здесь
    рождала запись о решении, которого не было."""
    t = _turns(tmp_path, "q.jsonl", [("human", "что делаем?"),
                                     ("assistant", "🗳️ Развилка:\n1. A\n2. B")])
    res = _run("decision-record.sh", {"transcript_path": str(t),
                                      "prompt": "Сколько будет стоить A?"},
               tmp_path, USER_LANG="ru")
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_h23_sees_a_fork_earlier_in_the_same_turn(tmp_path):
    """Выбор → ещё моя реплика без значка → человек выбрал. Раньше сторож
    смотрел одну последнюю реплику и молчал, а счётчик развилку засчитывал."""
    t = _turns(tmp_path, "turn.jsonl", [("human", "что делаем?"),
                                        ("assistant", "🗳️ Развилка:\n1. A\n2. B"),
                                        ("assistant", "Подробности — выше.")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "1"},
               tmp_path, USER_LANG="ru")
    assert "```decision" in res.stdout


def test_h23_does_not_reach_into_an_earlier_turn(tmp_path):
    """Развилка из прошлого хода уже отвечена — новый ход без значка её не
    переоткрывает."""
    t = _turns(tmp_path, "old.jsonl", [("assistant", "🗳️ Развилка:\n1. A\n2. B"),
                                       ("human", "1"),
                                       ("assistant", "Сделал вариант 1.")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "спасибо, дальше"},
               tmp_path, USER_LANG="ru")
    assert res.stdout.strip() == ""


def test_h23_tells_the_agent_to_skip_the_block_when_nothing_was_chosen(tmp_path):
    """Семантику «выбрал или нет» видит только агент — приписка обязана
    разрешать НЕ ставить блок."""
    t = _turns(tmp_path, "f.jsonl", [("assistant", "🗳️ Развилка:\n1. A\n2. B")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "дай инструкцию"},
               tmp_path, USER_LANG="ru")
    assert "блок НЕ" in res.stdout and "причина:" in res.stdout


# --- Повторное ревью 26.09: боевой порядок записи и уточняющий вопрос ---


def test_h23_fires_when_the_reply_is_already_in_the_transcript(tmp_path):
    """В бою харнесс пишет сообщение человека в транскрипт РАНЬШЕ, чем зовёт
    сторожа. Если сторож не перешагнёт его, он примет свежее сообщение за
    границу хода и замолчит — а тесты, где сообщения в транскрипте нет, этого
    не видели (ревью 26.09: поломка проходила все проверки)."""
    t = _turns(tmp_path, "live.jsonl", [("human", "что делаем?"),
                                        ("assistant", "🗳️ Развилка:\n1. A\n2. B"),
                                        ("human", "1")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "1"},
               tmp_path, USER_LANG="ru")
    assert "```decision" in res.stdout


def test_h23_fires_on_a_choice_after_a_clarifying_question(tmp_path):
    """«🗳️ A или B?» → «Сколько стоит A?» → ответ без значка → «берём A»."""
    t = _turns(tmp_path, "clarify.jsonl", [("assistant", "🗳️ Развилка: A или B?"),
                                           ("human", "Сколько будет стоить A?"),
                                           ("assistant", "A — 5000 ₽, B — 3000 ₽."),
                                           ("human", "берём A")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "берём A"},
               tmp_path, USER_LANG="ru")
    assert "```decision" in res.stdout


def test_h23_sees_a_fork_at_the_start_of_a_very_long_turn(tmp_path):
    """Живой ход 24.09 весил 765 КБ, и значок лежал за пределом хвоста, который
    читал сторож (400 КБ): сторож молчал, счётчик развилку считал."""
    work = [("assistant", "Промежуточный шаг. " + "x" * 50_000) for _ in range(12)]
    t = _turns(tmp_path, "long.jsonl",
               [("assistant", "🗳️ Развилка:\n1. A\n2. B")] + work)
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "1"},
               tmp_path, USER_LANG="ru")
    assert "```decision" in res.stdout


def test_h23_is_silent_after_a_fork_already_answered_by_name(tmp_path):
    """Выбор названием + попутный вопрос → запись → «Ок»: сторож молчит."""
    fork = ("🗳️ Как поступим?\n- **Подключить оплату сейчас (советую)** — сразу.\n"
            "- **Отложить оплату на месяц** — вручную.")
    t = _turns(tmp_path, "done.jsonl", [
        ("assistant", fork),
        ("human", "Подключить оплату сейчас. Сколько времени займёт?"),
        ("assistant", "День.\n\n```decision\nпринято: оплата сейчас\nотклонено: отложить\n```"),
        ("human", "Ок")])
    res = _run("decision-record.sh", {"transcript_path": str(t), "prompt": "Ок"},
               tmp_path, USER_LANG="ru")
    assert res.stdout.strip() == ""
