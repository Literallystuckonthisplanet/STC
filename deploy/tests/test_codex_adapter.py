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


def test_codex_agent_toml_has_required_fields():
    """Each *.stc.toml has name/description/developer_instructions and NO tools field."""
    _, _, _, rr = _load_codex()
    body = rr.files["agents/builder.stc.toml"]
    assert body.startswith('name = "builder"')
    assert 'description = ' in body
    assert 'developer_instructions = ' in body
    assert "\ntools =" not in body and "\ntools = " not in body, \
        "codex TOML schema has no tools field"


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
    patch = '[mcp_servers.stc-context7]\ncommand = "npx"\nargs = ["-y", "@context7/mcp"]\n'
    a1, c1 = T.merge_toml(p, patch, overwrite=False)
    assert a1 == "appended" and c1
    out = open(p).read()
    assert "[mcp_servers.stc-context7]" in out
    assert "[mcp_servers.user-srv]" in out, "user server clobbered!"
    assert 'model = "gpt-5.6-luna"' in out
    # re-merge → noop
    a2, c2 = T.merge_toml(p, patch, overwrite=False)
    assert a2 == "noop" and not c2


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
    """A user squatting the stc-* namespace in config.toml is flagged."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "config.toml")
    open(p, "w").write("[mcp_servers.stc-context7]\ncommand = \"x\"\n")
    colls = C._toml_collisions(p)
    assert any("stc-context7" in c for c in colls), "stc-* squat not flagged"


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
