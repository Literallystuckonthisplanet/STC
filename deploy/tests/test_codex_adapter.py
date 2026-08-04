#!/usr/bin/env python3
"""STC deploy test suite — Codex adapter.

Runs as `python3 -m pytest deploy/tests/test_codex_adapter.py` AND as
`python3 deploy/tests/test_codex_adapter.py` (plain stdlib — the zero-dependency
path). Every test is a function named test_* that raises AssertionError on
failure; the runner collects and reports.

These pin the Codex-adapter contract:
  - render emits hooks.json (NOT settings.json), config.toml TOML patch, *.stc.toml agents
  - apply_patch_normalize is injected into file-edit hooks
  - TOML merge is add-only + idempotent; uninstall strips stc-* cleanly
  - H08 gating: Stop runs, regular prompt no-ops, session-end trigger runs
  - skills land in ~/.agents/skills (outside ~/.codex)
"""
import os
import sys
import json
import tempfile
import subprocess
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
REPO = os.path.dirname(DEPLOY)
sys.path.insert(0, DEPLOY)

import render as R      # noqa: E402
import checks as C      # noqa: E402
import deploy as D      # noqa: E402
import stc_block as B   # noqa: E402
import toml_merge as T  # noqa: E402


def _load_codex():
    """Render the codex adapter against the live stc.yaml + registry."""
    stc_path = D.STC_YAML if os.path.exists(D.STC_YAML) else D.STC_EXAMPLE
    stc, registry, _ = R.load_inputs(stc_path, D.CORE, REPO)
    adapter = R.load_adapter(REPO, "codex")
    provider = R.provider_for(stc, "codex", REPO)
    rr = R.render_harness(stc, registry, provider, adapter, D.CORE, REPO)
    return stc, registry, adapter, rr


# ---------------------------------------------------------------------------
# render: the codex adapter emits the RIGHT artifact types
# ---------------------------------------------------------------------------

def test_codex_emits_hooks_json_not_settings():
    """Codex hook_config_file = hooks.json, so the hooks patch must land there,
    NOT in settings.json. A regression here would silently drop all hooks."""
    _, _, _, rr = _load_codex()
    assert "hooks.json" in rr.json_patches, "hooks wiring must target hooks.json"
    assert "settings.json" not in rr.json_patches, "codex has no settings.json"
    # the wiring has the Claude-shape {"hooks": {<Event>: [...]}}
    wiring = rr.json_patches["hooks.json"]
    assert "hooks" in wiring and isinstance(wiring["hooks"], dict)
    assert "PreToolUse" in wiring["hooks"], "PreToolUse events missing"


def test_codex_emits_toml_config_patch():
    """MCP servers render into config.toml (TOML), NOT .mcp.json (JSON)."""
    _, _, _, rr = _load_codex()
    assert "config.toml" in rr.toml_patches, "MCP must render as a TOML patch"
    assert ".mcp.json" not in rr.json_patches, "codex has no .mcp.json"
    toml_text = rr.toml_patches["config.toml"]
    # only stc-* namespaced servers; stdio (command, no url)
    assert "[mcp_servers.stc-" in toml_text, "servers must be stc-* namespaced"
    assert "url =" not in toml_text, "codex is stdio-only — url key forbidden (ECC #2224)"


def test_codex_toml_patch_only_enabled_servers():
    """stc.yaml enables only context7 + playwright; others must not render."""
    _, _, _, rr = _load_codex()
    toml_text = rr.toml_patches["config.toml"]
    assert "stc-context7" in toml_text
    assert "stc-playwright" in toml_text
    # github/gsheets are disabled in stc.yaml mcp block → must NOT appear
    assert "stc-github" not in toml_text
    assert "stc-gsheets" not in toml_text


def test_codex_agents_are_toml():
    """Typed agents render as *.stc.toml (name/description/developer_instructions),
    NOT *.stc.md frontmatter. First wave = 4 roles."""
    _, _, _, rr = _load_codex()
    agent_files = [p for p in rr.files if p.startswith("agents/") and p.endswith(".stc.toml")]
    names = {os.path.basename(p).replace(".stc.toml", "") for p in agent_files}
    assert {"builder", "code-reviewer", "qa", "research"} <= names, \
        f"first-wave agents missing; got {names}"
    # no markdown agent files on codex
    md_agents = [p for p in rr.files if p.startswith("agents/") and p.endswith(".stc.md")]
    assert not md_agents, f"codex agents must be .stc.toml, not .stc.md: {md_agents}"


def test_codex_defaults_route_luna_max_and_agent_sandbox_policies():
    """Rendered Codex behavior is Luna-first and least-privilege by role.

    This uses the actual render output consumed by deploy.py, not only adapter
    metadata: the main config defaults must be Luna/max, every custom agent
    must pin Luna explicitly, and read-only roles must not inherit write access.
    """
    _, _, _, rr = _load_codex()
    config = tomllib.loads(rr.toml_patches["config.toml"])
    assert config["model"] == "gpt-5.6-luna"
    assert config["model_reasoning_effort"] == "max"

    read_only = {
        "code-reviewer", "security-arch", "qa", "security-deps", "e2e",
        "research", "docs", "harness-docs",
    }
    write_roles = {"builder", "cleanup"}
    for path, body in rr.files.items():
        if not (path.startswith("agents/") and path.endswith(".stc.toml")):
            continue
        data = tomllib.loads(body)
        assert data["model"] == "gpt-5.6-luna", f"{path} is not Luna-pinned"
        assert "terra" not in data["model"] and "sol" not in data["model"]
        assert "tools" not in data, "Codex custom-agent TOML has no supported tools field"
        assert data["sandbox_mode"] in {"read-only", "workspace-write"}
        name = data["name"]
        if name in read_only:
            assert data["sandbox_mode"] == "read-only", f"{path} can write"
        elif name in write_roles:
            assert data["sandbox_mode"] == "workspace-write", f"{path} cannot write"


def test_caveman_is_embedded_only_in_approved_read_only_agent_prompts():
    _, _, _, rr = _load_codex()
    rendered = {
        tomllib.loads(body)["name"]: tomllib.loads(body)["developer_instructions"]
        for path, body in rr.files.items()
        if path.startswith("agents/") and path.endswith(".stc.toml")
    }
    for name in ("research", "docs", "harness-docs"):
        assert "CAVEMAN_PIPELINE" in rendered[name]
    for name in ("builder", "cleanup", "code-reviewer", "qa", "security-arch", "e2e"):
        assert "CAVEMAN_PIPELINE" not in rendered[name]


def test_codex_native_routing_and_hook_bindings_are_explicit():
    """Codex-specific routing uses supported native fields and both agent paths.

    The event/payload distinction is intentional: current Codex exposes a
    SubagentStart lifecycle event while direct Agent dispatch remains a
    PreToolUse payload. H04 must be reachable from both paths; H17 must cover
    shell-shaped reads without inventing a TOML ``tools`` field.
    """
    _, _, adapter, rr = _load_codex()
    routing = adapter["routing"]
    assert routing["default_model"] == "gpt-5.6-luna"
    assert routing["default_reasoning_effort"] == "max"
    assert routing["subagent_compression"] == "none"
    for name in ("terra", "sol"):
        escalation = routing["escalations"][name]
        assert escalation["explicit_only"] is True
        assert escalation["model"] in {"gpt-5.6-terra", "gpt-5.6-sol"}

    hooks = rr.json_patches["hooks.json"]["hooks"]
    h04 = [
        (event, entry)
        for event, entries in hooks.items()
        for entry in entries
        if entry.get("_stc_cap") == "H04_agent_reuse_contract"
    ]
    assert {event for event, _ in h04} == {"PreToolUse", "SubagentStart"}
    assert {event: entry["matcher"] for event, entry in h04} == {
        "PreToolUse": "Agent",
        "SubagentStart": ".*",
    }

    h17 = [
        entry
        for entries in hooks.values()
        for entry in entries
        if entry.get("_stc_cap") == "H17_secret_read_guard"
    ]
    assert len(h17) == 1
    assert {"Bash", "exec", "unified_exec", "unifiedExec"} <= set(h17[0]["matcher"].split("|"))
    assert h17[0]["hooks"][0]["command"].endswith("/block-secret-read.stc.sh")


def test_codex_agent_toml_has_required_fields():
    """Each *.stc.toml has name/description/developer_instructions and NO tools field."""
    _, _, _, rr = _load_codex()
    body = rr.files["agents/builder.stc.toml"]
    assert body.startswith('name = "builder"')
    assert 'description = ' in body
    assert 'developer_instructions = ' in body
    assert "\ntools =" not in body and "\ntools = " not in body, \
        "codex TOML schema has no tools field"


def test_codex_agent_toml_parses_with_tomllib():
    """Every rendered Codex agent TOML must be parseable by tomllib."""
    _, _, _, rr = _load_codex()
    agent_files = sorted(
        p for p in rr.files
        if p.startswith("agents/") and p.endswith(".stc.toml")
    )
    assert agent_files, "expected rendered Codex agents"
    for path in agent_files:
        try:
            data = tomllib.loads(rr.files[path])
        except tomllib.TOMLDecodeError as e:
            raise AssertionError(f"{path} is not valid TOML: {e}") from e
        source = os.path.join(D.CORE, "agents", f"{data['name']}.md")
        expected = open(source, encoding="utf-8").read().rstrip()
        rendered = data["developer_instructions"]
        assert rendered == expected or rendered.startswith(expected + "\n\n"), \
            f"{path} changed base developer_instructions while serializing TOML"
        if rendered != expected:
            assert rendered[len(expected):].startswith("\n\n<!-- CAVEMAN_PIPELINE -->\n"), \
                f"{path} added an unexpected developer_instructions suffix"


def test_toml_multiline_quote_round_trips_special_chars():
    """Multiline agent instructions preserve quotes and trailing backslashes."""
    body = 'line "quoted"\npath C:\\tmp\\\ntrailing\\'
    parsed = tomllib.loads(
        "developer_instructions = " + R._toml_multiline_quote(body) + "\n"
    )
    assert parsed["developer_instructions"] == body


def test_codex_rendered_hooks_have_no_unresolved_deploy_vars():
    """Rendered hooks must not leak STC-owned ${VAR} placeholders."""
    _, _, _, rr = _load_codex()
    unresolved = {}
    for path, body in rr.files.items():
        if not path.startswith("hooks/") or not path.endswith(".stc.sh"):
            continue
        names = R._unresolved_deploy_vars(body)
        if names:
            unresolved[path] = sorted(names)
    assert not unresolved, f"unresolved deploy vars in rendered hooks: {unresolved}"


def test_hook_declaration_parser_keeps_prose_continuations():
    """A prose line inside a declaration block must not hide later vars."""
    path = os.path.join(D.CORE, "hooks", "block-dangerous-git.sh")
    declared = R._hook_declared_vars(open(path, encoding="utf-8").read())
    assert {"RELEASE_ACK_FILE", "USER_LANG"} <= declared


def test_codex_skills_target_agents_dir():
    """Skills render to ~/.agents/skills (Codex global path), NOT ~/.codex/skills."""
    _, _, adapter, rr = _load_codex()
    skill_files = [p for p in rr.files if "/SKILL.md" in p or p.startswith("skills/")]
    assert skill_files, "no skills rendered"
    # the rendered paths must start with the expanded ~/.agents/skills (absolute),
    # not a relative "skills/" under native_dir
    expanded = os.path.expanduser("~/.agents/skills")
    for p in skill_files:
        assert p.startswith(expanded) or p.startswith(os.path.join(expanded, "")), \
            f"skill {p} not under ~/.agents/skills"


# ---------------------------------------------------------------------------
# apply_patch normalize injection
# ---------------------------------------------------------------------------

def test_apply_patch_normalize_shipped():
    """The normalizer script is rendered into the hooks dir."""
    _, _, _, rr = _load_codex()
    norm = [p for p in rr.files if "apply_patch_normalize" in p]
    assert norm, "_apply_patch_normalize.stc.sh must ship with the hooks"


def test_apply_patch_normalize_injected_into_file_hooks():
    """File-edit hooks (H05/H07/H09/H10/H16) carry the source line; a Bash-only
    hook (H01) does NOT."""
    _, _, _, rr = _load_codex()
    for hook in ["secret-scan-memory", "dirty-tree-guard", "memory-guard",
                 "read-first-router", "integration-docs-gate"]:
        body = rr.files[f"hooks/{hook}.stc.sh"]
        assert "apply_patch_normalize" in body, f"{hook} missing normalize injection"
    # H01 reads .command only → no normalize needed
    h01 = rr.files["hooks/block-dangerous-git.stc.sh"]
    assert "apply_patch_normalize" not in h01, "H01 should not carry normalize"


def test_normalize_extract_apply_patch_path():
    """The normalizer surfaces file_path from an apply_patch patch text."""
    norm = os.path.join(D.CORE, "hooks", "_apply_patch_normalize.sh")
    patch_input = json.dumps({
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** Update File: src/secret.md\n@@\n-x\n+sk-abc\n*** End Patch"}
    })
    env = dict(os.environ)
    proc = subprocess.run(
        ["bash", "-c", f'INPUT=$(cat); source "{norm}" 2>/dev/null; '
                       f'printf "%s" "$INPUT" | jq -r ".tool_input.file_path"'],
        input=patch_input, capture_output=True, text=True, env=env)
    assert proc.stdout.strip() == "src/secret.md", \
        f"normalize failed: {proc.stdout!r}"


# ---------------------------------------------------------------------------
# TOML merge: add-only, idempotent, uninstall
# ---------------------------------------------------------------------------

def test_toml_merge_add_only_then_idempotent():
    """Merge appends missing servers; a re-merge is a no-op."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    open(p, "w").write('model = "gpt-5.6-luna"\n\n[mcp_servers.user-srv]\ncommand = "x"\n')
    patch = '[mcp_servers.stc-context7]\ncommand = "npx"\nargs = ["-y", "@upstash/context7-mcp"]\n'
    a1, c1 = T.merge_toml(p, patch, overwrite=False)
    assert a1 == "appended" and c1
    out = open(p).read()
    assert "[mcp_servers.stc-context7]" in out
    assert "[mcp_servers.user-srv]" in out, "user server clobbered!"
    assert 'model = "gpt-5.6-luna"' in out
    # re-merge → noop
    a2, c2 = T.merge_toml(p, patch, overwrite=False)
    assert a2 == "noop" and not c2


def test_toml_merge_updates_codex_managed_top_level_defaults():
    """Rendered main model defaults must reach live config, not be ignored."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(
            '# user comment\nmodel = "gpt-5.6-sol"\n'
            'model_reasoning_effort = "high"\npersonality = "pragmatic"\n\n'
            '[features]\nweb_search = true\n'
        )
    patch = (
        'model = "gpt-5.6-luna"\nmodel_reasoning_effort = "max"\n\n'
        '[mcp_servers.stc-context7]\ncommand = "npx"\n'
    )

    action, changed = T.merge_toml(p, patch)

    assert changed is True
    assert action == "updated"
    with open(p, "rb") as fh:
        data = tomllib.load(fh)
    assert data["model"] == "gpt-5.6-luna"
    assert data["model_reasoning_effort"] == "max"
    assert data["personality"] == "pragmatic"
    assert data["features"]["web_search"] is True
    assert data["mcp_servers"]["stc-context7"]["command"] == "npx"
    text = open(p, encoding="utf-8").read()
    assert "# user comment" in text


def test_toml_uninstall_strips_only_stc():
    """remove_stc_sections strips stc-* but leaves user content."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    open(p, "w").write(
        'model = "x"\n\n'
        '[mcp_servers.stc-context7]\ncommand = "npx"\nargs = ["a"]\n\n'
        '[mcp_servers.stc-context7.env]\nKEY = "v"\n\n'
        '[mcp_servers.user-srv]\ncommand = "y"\n')
    a, c = T.remove_stc_sections(p)
    assert a == "removed" and c
    out = open(p).read()
    assert "stc-" not in out, "stc-* not fully removed"
    assert "[mcp_servers.user-srv]" in out, "user server removed!"
    assert 'model = "x"' in out


def test_toml_merge_refuses_corrupt():
    """A corrupt TOML raises ValueError (never silently clobbers)."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    open(p, "w").write('model = \n[broken\n')
    patch = '[mcp_servers.stc-x]\ncommand = "n"\n'
    try:
        T.merge_toml(p, patch, overwrite=False)
        assert False, "should have raised"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# H08 event gating
# ---------------------------------------------------------------------------

def _run_h08(stdin_json, memdir):
    h08 = os.path.join(D.CORE, "hooks", "link-integrity-guard.sh")
    env = dict(os.environ)
    env["MEMORY_DIR"] = memdir
    proc = subprocess.run(["bash", h08], input=stdin_json,
                          capture_output=True, text=True, env=env)
    return proc.returncode, proc.stderr


def _memdir_with_broken_link():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "project_x.md"), "w").write(
        "name: project-x\n\n# Project\nSee [[feedback-missing]] for details.\n")
    return d


def test_h08_stop_runs():
    """On Stop (Claude), H08 checks links and blocks on a broken one."""
    d = _memdir_with_broken_link()
    os.environ.pop  # ensure no stale marker
    rc, err = _run_h08('{"hook_event_name":"Stop","session_id":"h08stop","stop_hook_active":false}', d)
    try:
        assert rc == 2 and "Broken" in err
    finally:
        os.remove(f"/tmp/stc-linkcheck-h08stop") if os.path.exists(f"/tmp/stc-linkcheck-h08stop") else None


def test_h08_regular_prompt_noop():
    """On UserPromptSubmit with a regular prompt, H08 must no-op (Codex)."""
    d = _memdir_with_broken_link()
    rc, err = _run_h08(
        '{"hook_event_name":"UserPromptSubmit","session_id":"h08reg","prompt":"fix the bug"}', d)
    assert rc == 0 and "Broken" not in err


def test_h08_session_end_trigger_runs():
    """On UserPromptSubmit + session-end phrase, H08 checks links (Codex)."""
    d = _memdir_with_broken_link()
    rc, err = _run_h08(
        '{"hook_event_name":"UserPromptSubmit","session_id":"h08end","prompt":"завершаем сессию"}', d)
    try:
        assert rc == 2 and "Broken" in err
    finally:
        if os.path.exists("/tmp/stc-linkcheck-h08end"):
            os.remove("/tmp/stc-linkcheck-h08end")


# ---------------------------------------------------------------------------
# collision detection
# ---------------------------------------------------------------------------

def test_collision_detection_covers_toml():
    """A stc-* server the render does NOT emit = namespace squat (flagged);
    a stc-* server the render DOES emit = STC's own prior install (not flagged)."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    # live has stc-context7 (this render emits it → not a collision) and
    # stc-github (this render does NOT emit it → squat → collision)
    open(p, "w").write(
        "[mcp_servers.stc-context7]\ncommand = \"x\"\n\n"
        "[mcp_servers.stc-github]\ncommand = \"y\"\n")
    managed = "[mcp_servers.stc-context7]\ncommand = \"x\"\n"  # render emits only context7
    colls = C._toml_collisions(p, managed)
    assert any("stc-github" in c for c in colls), "stc-* squat not flagged"
    assert not any("stc-context7" in c for c in colls), \
        "STC's own prior install must not be a collision (update-in-place)"


# ---------------------------------------------------------------------------
# H08 regression: ensure it still works on a clean registry (no false positive)
# ---------------------------------------------------------------------------

def test_h08_clean_registry_no_block():
    """A memory with all links resolving → no block, exit 0."""
    d = tempfile.mkdtemp()
    open(os.path.join(d, "project_x.md"), "w").write(
        "name: project-x\n\n# Project\nSee [[feedback-pev]] for details.\n")
    open(os.path.join(d, "feedback_pev.md"), "w").write("name: feedback-pev\n\nPEV notes.\n")
    rc, err = _run_h08(
        '{"hook_event_name":"Stop","session_id":"h08clean","stop_hook_active":false}', d)
    assert rc == 0, f"false positive on clean registry: {err}"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ✗ {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
