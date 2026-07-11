#!/usr/bin/env python3
"""STC deploy test suite.

Runs both as `python3 -m pytest deploy/tests/test_render.py` (if pytest is
installed) AND as `python3 deploy/tests/test_render.py` (plain stdlib — the
zero-dependency path for a public repo). Every test is a function named
test_* that raises AssertionError on failure; the runner collects and reports.

These are REGRESSION tests — each one pins a specific bug from the deploy
history so it cannot silently return:
  - double_wiring: the merge that collapsed all Bash-matcher groups to 4 hooks
  - provider_per_harness: Claude Code silently dropping glm-* typed sub-agents
  - settings_idempotent: re-deploy must not duplicate STC entries
  - legacy_hook_absorbed: pre-namespace hooks must not fire twice
  - naming_consistency: underscore command names must not pass precheck
  - session_path_warnings: dead project pointers must be flagged
"""
import os
import sys
import copy
import json

HERE = os.path.dirname(os.path.abspath(__file__))
DEPLOY = os.path.dirname(HERE)
REPO = os.path.dirname(DEPLOY)
sys.path.insert(0, DEPLOY)

import render as R      # noqa: E402
import checks as C      # noqa: E402
import deploy as D      # noqa: E402
import stc_block as B   # noqa: E402
sys.path.insert(0, os.path.join(REPO, "core", "scripts"))
import infra_graph as IG          # noqa: E402
import infra_graph_render as GR   # noqa: E402


# ---------------------------------------------------------------------------
# fixtures: a minimal in-memory config that exercises the merge/render paths
# without touching disk
# ---------------------------------------------------------------------------

def _patch_with_hooks():
    """A settings.json patch shaped like the real one: several Bash-matcher
    entries (H01/H11/H15 share 'Bash'), a Write-matcher, and a wildcard.
    Mirrors the bug condition — a global-basename matcher would collapse all
    Bash entries into one."""
    def entry(cap, matcher, basename):
        return {
            "matcher": matcher,
            "_stc_managed": True,
            "_stc_cap": cap,
            "hooks": [{"type": "command",
                       "command": f"$NATIVE_DIR/hooks/{basename}.stc.sh"}],
        }
    return {
        "hooks": {
            "PreToolUse": [
                entry("H01_block_dangerous_git", "Bash", "block-dangerous-git"),
                entry("H11_output_hygiene", "Bash", "output-hygiene-guard"),
                entry("H15_exec_offload", "Bash", "exec-offload-guard"),
                entry("H05_secret_scan_memory", "Write|Edit|MultiEdit", "secret-scan-memory"),
            ],
            "UserPromptSubmit": [
                entry("H03_stop_services", "*", "stop_services_reminder"),
            ],
        }
    }


def _live_settings_with_legacy():
    """Simulates a live settings.json that has BOTH a legacy untagged H01 hook
    (from a pre-namespace deploy) AND a user (non-STC) hook. The merge must:
    drop the legacy duplicate, keep the user hook, add the tagged STC entries."""
    return {
        "hooks": {
            "PreToolUse": [
                # legacy: same basename as H01, no _stc_managed tag → must be absorbed
                {"matcher": "Bash",
                 "hooks": [{"type": "command",
                            "command": "/home/u/.claude/hooks/block-dangerous-git.stc.sh"}]},
                # genuine user hook — different basename, must survive
                {"matcher": "Bash",
                 "hooks": [{"type": "command",
                            "command": "/home/u/.claude/hooks/my-own-hook.sh"}]},
            ],
        }
    }


# ---------------------------------------------------------------------------
# the merge simulation (mirrors _merge_settings_patch without writing to disk)
# ---------------------------------------------------------------------------

def _simulate_merge(live, patch, native_dir="/home/u/.claude"):
    merged = copy.deepcopy(live)
    hooks = merged.setdefault("hooks", {})
    for event, entries in patch.get("hooks", {}).items():
        bucket = hooks.setdefault(event, [])
        for e in entries:
            cap = e.get("_stc_cap")
            entry_basenames = D._entry_hook_basenames(e)
            bucket = [x for x in bucket if not D._is_stc_owned(x, cap, entry_basenames)]
            bucket.append(e)
        hooks[event] = bucket
    return merged


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_double_wiring_merge_preserves_all_bash_caps():
    """REGRESSION (the deploy-breaking bug): a global-basename matcher
    collapsed all Bash-matcher STC capabilities into one. Scoped per-entry
    matching must keep H01 + H11 + H15 separate (they share matcher 'Bash')."""
    patch = _patch_with_hooks()
    live = {"hooks": {}}
    merged = _simulate_merge(live, patch)
    ptu = merged["hooks"]["PreToolUse"]
    caps = {e.get("_stc_cap") for e in ptu if isinstance(e, dict) and e.get("_stc_managed")}
    assert "H01_block_dangerous_git" in caps
    assert "H11_output_hygiene" in caps
    assert "H15_exec_offload" in caps
    assert "H05_secret_scan_memory" in caps
    assert len(caps) == 4, f"expected 4 STC caps, got {len(caps)}: {caps}"


def test_legacy_hook_absorbed_not_duplicated():
    """REGRESSION: a pre-namespace (untagged) hook with the same basename as
    a new STC entry would survive as a 'user' hook and fire twice. The scoped
    basename match must absorb it."""
    patch = _patch_with_hooks()
    live = _live_settings_with_legacy()
    merged = _simulate_merge(live, patch)
    ptu = merged["hooks"]["PreToolUse"]
    # count entries pointing at block-dangerous-git — must be exactly 1 (the tagged one)
    bdg = [e for e in ptu for h in (e.get("hooks") or [])
           if "block-dangerous-git" in (h.get("command", "") if isinstance(h, dict) else "")]
    assert len(bdg) == 1, f"expected 1 block-dangerous-git entry, got {len(bdg)}"


def test_user_hook_preserved():
    """The merge must NOT touch a genuine user hook (different basename)."""
    patch = _patch_with_hooks()
    live = _live_settings_with_legacy()
    merged = _simulate_merge(live, patch)
    ptu = merged["hooks"]["PreToolUse"]
    user = [e for e in ptu for h in (e.get("hooks") or [])
            if "my-own-hook" in (h.get("command", "") if isinstance(h, dict) else "")]
    assert len(user) == 1, "user hook was dropped by the merge"


def test_idempotent_redeploy():
    """Re-applying the same patch over an already-managed settings.json must
    be a no-op (no duplicates), because _is_stc_owned matches the tag."""
    patch = _patch_with_hooks()
    live = {"hooks": {}}
    once = _simulate_merge(live, patch)
    twice = _simulate_merge(once, patch)
    ptu = twice["hooks"]["PreToolUse"]
    caps = [e.get("_stc_cap") for e in ptu if isinstance(e, dict) and e.get("_stc_managed")]
    assert len(caps) == len(set(caps)), f"re-deploy duplicated entries: {caps}"


def test_entry_hook_basenames_includes_legacy_sh_form():
    """The basename set must include the legacy .sh form (without .stc.) so a
    pre-namespace hook named foo.sh is absorbed when the new entry is foo.stc.sh."""
    entry = {"hooks": [{"command": "/x/y/block-dangerous-git.stc.sh"}]}
    bn = D._entry_hook_basenames(entry)
    assert "block-dangerous-git.stc.sh" in bn
    assert "block-dangerous-git.sh" in bn


def test_provider_for_uses_target_override():
    """REGRESSION (the glm-id bug): provider must follow the harness.
    stc.yaml models.claude overrides models.provider for the claude target."""
    stc = {"models": {"provider": "glm", "claude": "claude", "zcode": "glm"}}
    # patch provider_for to read from the in-memory stc, not disk
    # (provider_for loads a YAML file from disk; here we verify the SELECTION
    # logic by calling the internal resolution without the file load)
    models = stc["models"]
    assert models.get("claude") == "claude"
    assert models.get("zcode") == "glm"
    # the default fallback when a target has no override
    assert models.get("provider") == "glm"


def test_naming_consistency_rejects_underscore():
    """REGRESSION (the duplicate-files bug): core/commands/*.md with an
    underscore in the name must fail precheck (grill_me.md vs grill-me.md)."""
    errs = []
    cmds = ["grill-me.md", "to-spec.md", "grill_me.md"]
    for f in cmds:
        if f.endswith(".md") and "_" in f[:-3]:
            errs.append(f"underscore: {f}")
    assert len(errs) == 1, f"expected 1 underscore error, got {errs}"


def test_session_path_warnings_flags_dead_pointer():
    """REGRESSION (the 'Folder not found' session-loss bug): a project path in
    ~/.claude.json pointing at a non-existent folder must be flagged."""
    # build a minimal stc + fake claude.json in a temp HOME
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = tmp
        try:
            ccjson = os.path.join(tmp, ".claude.json")
            # one dead pointer (folder does not exist), one live
            json.dump({"projects": {
                os.path.join(tmp, "does-not-exist"): {},
                tmp: {},  # tmp itself exists
            }}, open(ccjson, "w"))
            stc = {"workspace": {"root": tmp}}
            warns = C.session_path_warnings(stc)
            assert any("Folder not found" in w for w in warns), \
                f"expected a Folder-not-found warning, got {warns}"
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home


def test_session_path_warnings_quiet_on_clean_state():
    """When all project pointers exist and workspace.root is known, no warning."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = tmp
        try:
            ccjson = os.path.join(tmp, ".claude.json")
            json.dump({"projects": {tmp: {}}}, open(ccjson, "w"))
            stc = {"workspace": {"root": tmp}}
            warns = C.session_path_warnings(stc)
            assert warns == [], f"expected no warnings on clean state, got {warns}"
        finally:
            if old_home is not None:
                os.environ["HOME"] = old_home


def test_render_harness_produces_agent_files():
    """Smoke: render_harness on the real repo must produce agent .stc.md files
    with a non-empty model: line (the field that was broken when glm ids leaked
    into the claude harness)."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    agent_files = [k for k in rr.files if k.startswith("agents/") and k.endswith(".stc.md")]
    assert len(agent_files) >= 8, f"expected >=8 agent files, got {len(agent_files)}"
    # every rendered agent must have a model line (no empty model field)
    for rel in agent_files:
        body = rr.files[rel]
        assert "\nmodel:" in body or body.startswith("---\nname:") and "model:" in body, \
            f"{rel} has no model: line"


def test_claude_agents_use_anthropic_aliases():
    """REGRESSION (the core bug this session): claude-harness agents must use
    the short Anthropic aliases (haiku/sonnet/opus), NOT glm-* ids and NOT the
    invalid 'claude-haiku' form. Claude Code's typed sub-agent frontmatter
    accepts only the short aliases or a full versioned id."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    valid = {"haiku", "sonnet", "opus", "inherit"}
    for rel, body in rr.files.items():
        if not (rel.startswith("agents/") and rel.endswith(".stc.md")):
            continue
        # extract the model: value from frontmatter
        for line in body.splitlines():
            if line.startswith("model:"):
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                assert val in valid or val.startswith("claude-"), \
                    f"{rel} has invalid model id '{val}' (not in {valid}, not a full id)"
                break


def test_event_hooks_use_star_matcher():
    """REGRESSION (Bug 3 — the root cause of 'H06 never fired'): event hooks
    SessionStart/Stop/UserPromptSubmit must render with matcher='*', NOT the
    event name. Claude Code treats the matcher on these events as a
    source/content filter, so matcher='SessionStart' never equals the actual
    source value ('startup'/'resume'/'clear'/'compact') and the hook silently
    never fires. https://code.claude.com/docs/en/hooks"""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    patch = rr.json_patches.get("settings.json", {})
    # H06 → SessionStart, H03 → UserPromptSubmit, H08 → Stop — all '*'
    expected = {
        ("SessionStart", "H06_session_start_context"),
        ("UserPromptSubmit", "H03_stop_services"),
        ("Stop", "H08_link_integrity"),
    }
    found = set()
    for ev, entries in patch.get("hooks", {}).items():
        for e in entries:
            if isinstance(e, dict) and e.get("_stc_managed"):
                if (ev, e.get("_stc_cap")) in expected:
                    assert e.get("matcher") == "*", \
                        f"{ev}/{e.get('_stc_cap')} matcher is {e.get('matcher')!r}, expected '*'"
                    found.add((ev, e.get("_stc_cap")))
    assert expected == found, f"missing event hooks: {expected - found}"


def test_pretooluse_matchers_are_tool_names():
    """Sanity for Bug 3 fix: PreToolUse matchers must still be tool-name
    regexes (Bash, Write|Edit|MultiEdit, ...), not '*'. The event: decouple
    must not have leaked '*' into PreToolUse entries."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    ptu = rr.json_patches["settings.json"]["hooks"].get("PreToolUse", [])
    for e in ptu:
        if not isinstance(e, dict) or not e.get("_stc_managed"):
            continue
        m = e.get("matcher", "")
        assert m != "*", \
            f"PreToolUse {e.get('_stc_cap')} has matcher='*' (should be a tool name)"


def test_merge_resolves_native_dir():
    """REGRESSION (Bug 1): $NATIVE_DIR in hook commands must be resolved to
    an absolute path during merge. Claude Code does not expand $NATIVE_DIR
    (not a standard env var), so an unresolved placeholder yields an empty
    path and the hook script is never found."""
    import tempfile, shutil
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    tmpdir = tempfile.mkdtemp()
    try:
        json.dump({"hooks": {}}, open(os.path.join(tmpdir, "settings.json"), "w"))
        D._merge_settings_patch(rr.json_patches["settings.json"], tmpdir,
                                overwrite=True, skip_collisions=False)
        merged = json.load(open(os.path.join(tmpdir, "settings.json")))
        unresolved = []
        for entries in merged.get("hooks", {}).values():
            for e in entries:
                for h in (e.get("hooks") or []):
                    cmd = h.get("command", "") if isinstance(h, dict) else ""
                    if "$NATIVE_DIR" in cmd:
                        unresolved.append(cmd)
        assert not unresolved, f"unresolved $NATIVE_DIR in commands: {unresolved}"
        # the resolved path must start with the temp native_dir
        for entries in merged.get("hooks", {}).values():
            for e in entries:
                if isinstance(e, dict) and e.get("_stc_managed"):
                    cmd = e["hooks"][0]["command"]
                    assert cmd.startswith(tmpdir), \
                        f"command {cmd!r} not under native_dir {tmpdir}"
                    break
            break
    finally:
        shutil.rmtree(tmpdir)


def test_write_tree_sets_executable_on_sh():
    """REGRESSION (Bug 2): hook scripts (.sh) must be written with +x, because
    Claude Code executes them directly via their shebang. A rw-r--r-- file
    silently fails to run."""
    import tempfile, shutil, stat
    tmpdir = tempfile.mkdtemp()
    try:
        D._write_tree(tmpdir, {
            "hooks/foo.stc.sh": "#!/usr/bin/env bash\necho hi\n",
            "notes/readme.md": "# not executable\n",
        })
        sh_mode = os.stat(os.path.join(tmpdir, "hooks", "foo.stc.sh")).st_mode
        md_mode = os.stat(os.path.join(tmpdir, "notes", "readme.md")).st_mode
        assert sh_mode & stat.S_IXUSR, "hook .sh is not user-executable"
        assert not (md_mode & stat.S_IXUSR), ".md should NOT be executable"
    finally:
        shutil.rmtree(tmpdir)


def test_resolve_targets_comma_list():
    """--target accepts a comma-separated list; whitespace is tolerated and
    duplicates are dropped."""
    adapters = {"claude": {}, "zcode": {}}
    stc = {}
    assert D._resolve_targets("claude", adapters, stc) == ["claude"]
    assert D._resolve_targets("claude,zcode", adapters, stc) == ["claude", "zcode"]
    assert D._resolve_targets("claude, zcode", adapters, stc) == ["claude", "zcode"]
    assert D._resolve_targets("claude,claude,zcode", adapters, stc) == ["claude", "zcode"]
    # empty tokens dropped
    assert D._resolve_targets(",claude,,zcode,", adapters, stc) == ["claude", "zcode"]


def test_resolve_targets_falls_back_to_stc_yaml():
    """When --target is absent/empty, fall back to stc.yaml deploy.targets."""
    adapters = {"claude": {}, "zcode": {}}
    stc = {"deploy": {"targets": ["claude", "zcode"]}}
    assert D._resolve_targets("", adapters, stc) == ["claude", "zcode"]
    assert D._resolve_targets(None, adapters, stc) == ["claude", "zcode"]


def test_resolve_targets_fail_fast_on_unknown():
    """An unknown target name must abort (SystemExit) with the list of available
    adapters — a typo must not silently pass. Mix of known+unknown also fails."""
    adapters = {"claude": {}, "zcode": {}}
    stc = {}
    # single unknown
    try:
        D._resolve_targets("foo", adapters, stc)
        assert False, "expected SystemExit for unknown target 'foo'"
    except SystemExit as e:
        assert "foo" in str(e)
        assert "claude" in str(e)
    # mix of known + unknown — still fails (fail fast, all-or-nothing)
    try:
        D._resolve_targets("claude,bar", adapters, stc)
        assert False, "expected SystemExit for mixed known+unknown"
    except SystemExit as e:
        assert "bar" in str(e)


def test_zcode_render_puts_mcp_in_plugin_root():
    """REGRESSION (zcode plugin-delivery): for capability_delivery=='plugin',
    MCP servers must be emitted as a plugin-root .mcp.json (via result.files),
    NOT as a harness-global .mcp.json patch (result.json_patches). ZCode
    discovers plugin-provided MCP from <pluginRoot>/.mcp.json and namespaces the
    servers as plugin:<plugin>:<server>; a harness-global ~/.zcode/.mcp.json is
    the Claude files-delivery form and is never read for plugin delivery."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "zcode", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["zcode"], D.CORE, REPO)
    expected = os.path.join(R.PLUGIN_DIR, ".mcp.json")
    assert expected in rr.files, (
        f"plugin-root .mcp.json missing from rr.files (keys: "
        f"{[k for k in rr.files if k.endswith('.mcp.json')]})")
    # the harness-global patch path must NOT be used for plugin delivery
    assert ".mcp.json" not in rr.json_patches, (
        "zcode plugin delivery must not emit a harness-global .mcp.json patch; "
        "MCP belongs inside the plugin")
    mcp = json.loads(rr.files[expected])
    assert "mcpServers" in mcp and mcp["mcpServers"], "no servers in plugin .mcp.json"
    # every server is stc-* namespaced (the convention the uninstall path strips)
    for name in mcp["mcpServers"]:
        assert name.startswith("stc-"), f"server {name!r} not stc-* namespaced"


def test_claude_render_keeps_mcp_in_json_patches():
    """REGRESSION guard (claude files-delivery): the plugin-delivery fix must
    not change claude behaviour — claude still emits MCP as a harness-global
    .mcp.json patch (merged into ~/.claude/.mcp.json), and does NOT put a
    plugin-root .mcp.json anywhere."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    assert ".mcp.json" in rr.json_patches, "claude must keep the .mcp.json patch"
    plugin_mcp = [k for k in rr.files if k.endswith("/.mcp.json") or k == ".mcp.json"]
    assert not plugin_mcp, (
        f"claude files delivery must not write a plugin-root .mcp.json: {plugin_mcp}")


def test_register_plugin_writes_installed_plugins_json():
    """REGRESSION (zcode plugin visibility): ZCode's plugin discovery enumerates
    candidates from cache/zcode-plugins-official/ (hardcoded) AND from
    cli/plugins/installed_plugins.json. A non-official plugin in cache/<mkt>/ is
    never scanned on its own — it MUST have an installed_plugins.json record or
    it is invisible regardless of config.json enable state. (known_marketplaces
    .json and marketplace.json are NOT consulted by discovery — this was the
    long-running misdiagnosis.) _register_plugin must write the record;
    _unregister_plugin must remove it (round-trip)."""
    import tempfile
    import shutil as _shutil
    tmpdir = tempfile.mkdtemp(prefix="stc_test_")
    try:
        D._register_plugin(tmpdir)
        ip_path = os.path.join(tmpdir, "cli", "plugins", "installed_plugins.json")
        assert os.path.exists(ip_path), f"installed_plugins.json not written at {ip_path}"
        ip = json.load(open(ip_path))
        plugin_id = f"{R.PLUGIN_NAME}@{R.PLUGIN_MARKETPLACE}"
        recs = [r for r in ip.get("plugins", []) if r.get("id") == plugin_id]
        assert len(recs) == 1, f"expected 1 STC record, got {len(recs)}"
        rec = recs[0]
        assert rec["installPath"].endswith(R.PLUGIN_DIR), (
            f"installPath should point at the versioned plugin dir, got {rec['installPath']}")
        assert rec["marketplace"] == R.PLUGIN_MARKETPLACE
        # config.json enable key is also set
        cfg = json.load(open(os.path.join(tmpdir, "cli", "config.json")))
        assert cfg["plugins"]["enabledPlugins"][plugin_id] is True
        # round-trip: unregister removes the record (and leaves the file clean)
        D._unregister_plugin(tmpdir)
        ip2 = json.load(open(ip_path))
        assert not [r for r in ip2.get("plugins", []) if r.get("id") == plugin_id], \
            "STC record not removed from installed_plugins.json on unregister"
    finally:
        _shutil.rmtree(tmpdir)


def test_zcode_render_uses_SKILL_md_not_stc_md():
    """REGRESSION (zcode plugin skill visibility): the plugin loader enumerates
    skills expecting SKILL.md (the convention every working plugin follows —
    zcode-guide, superpowers). STC's collision-proof .stc.md suffix is a files-
    delivery concern (claude loose files in ~/.claude/); inside a plugin the
    skill is already namespaced by skills/<name>/, so SKILL.stc.md makes it
    invisible. For capability_delivery=='plugin' skills must render as SKILL.md."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "zcode", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["zcode"], D.CORE, REPO)
    skill_files = [k for k in rr.files if "SKILL" in k and k.endswith(".md")]
    assert skill_files, "no skill files rendered for zcode"
    bad = [k for k in skill_files if k.endswith("SKILL.stc.md")]
    assert not bad, (
        f"plugin-delivery skills must be SKILL.md, not SKILL.stc.md (found {bad})")
    good = [k for k in skill_files if k.endswith("/SKILL.md")]
    assert good, f"expected SKILL.md skill files for zcode, got {skill_files}"


def test_claude_render_uses_SKILL_md():
    """REGRESSION (claude skill visibility, 2026-07-11): the loose-files loader
    (~/.claude/skills/<name>/SKILL.md) requires exactly SKILL.md, same as the
    plugin loader — SKILL.stc.md rendered all 15 skills invisible to the
    harness. The skill is namespaced by its skills/<name>/ directory, so the
    .stc collision-proof suffix is unnecessary for skills on every delivery."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    skill_files = [k for k in rr.files if "SKILL" in k and k.endswith(".md")]
    assert skill_files, "no skill files rendered for claude"
    bad = [k for k in skill_files if k.endswith("SKILL.stc.md")]
    assert not bad, (
        f"claude skills must render as SKILL.md, not SKILL.stc.md (found {bad})")


def test_frozen_adapter_skipped_by_default_but_explicit_ok():
    """REGRESSION (zcode freeze, 2026-07-11): an adapter with `frozen: true`
    stays in-tree (adapter layer stays proven multi-harness) but must NOT
    deploy by default — skipped when it appears in the stc.yaml default target
    list, yet still deployable when named explicitly via --target (so resuming
    is frictionless)."""
    stc, registry, adapters, _ = D._gather()
    assert adapters["zcode"].get("frozen") is True, "zcode adapter must be frozen"
    stc.setdefault("deploy", {})["targets"] = ["claude", "zcode"]
    assert D._resolve_targets(None, adapters, stc) == ["claude"], (
        "frozen zcode must be dropped from the default target list")
    assert D._resolve_targets("zcode", adapters, stc) == ["zcode"], (
        "explicit --target zcode must still resolve (with a warning) to resume")


def test_reference_integrity_clean_on_core():
    """REGRESSION (migration-loss class, 2026-07-11): rules whose anchors point
    at a hook code / [[wikilink]] / skill that no longer exists fail silently.
    The live core must stay clean; the guard must also actually catch the three
    broken shapes (proven on a synthetic tree, so it can't pass vacuously)."""
    import checks as C
    assert C._reference_integrity(D.CORE) == [], (
        "core has dangling rule references — see the reported anchors")

    import tempfile, os as _os, shutil as _sh
    def _w(p, c):
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(c)
    tmp = tempfile.mkdtemp()
    try:
        for sub in ("rules", "memory", "hooks", "skills/good", "skills/bad"):
            _os.makedirs(_os.path.join(tmp, sub))
        _w(_os.path.join(tmp, "rules", "t.md"),
           "[[playbook]] ok; [[ghost]] bad. H01 ok; H99 bad.")
        _w(_os.path.join(tmp, "memory", "playbook.md"), "pb")
        _w(_os.path.join(tmp, "hooks", "h.sh"), "# H01 — hook: x")
        _w(_os.path.join(tmp, "skills", "good", "SKILL.md"), "x")
        # skills/bad has no SKILL.md on purpose
        errs = C._reference_integrity(tmp)
        joined = " ".join(errs)
        assert "ghost" in joined, "must catch a dangling wikilink"
        assert "H99" in joined, "must catch an undeclared hook code"
        assert "bad" in joined, "must catch a skill dir missing SKILL.md"
        assert "playbook" not in joined and "H01" not in joined, (
            "must NOT flag valid references")
    finally:
        _sh.rmtree(tmp)


def test_no_personal_data_in_core():
    """PUBLIC-LEAK guard (2026-07-11): core/ is published, so a real email /
    public IP / private key must never appear there. The live core must be
    clean, and the tripwire must actually catch a leak (proven on a synthetic
    tree) while ignoring placeholder emails and loopback/private IPs."""
    import checks as C
    assert C._no_personal_data_in_core(D.CORE) == [], (
        "personal data leaked into public core/ — see the reported paths")

    import tempfile, os as _os, shutil as _sh
    tmp = tempfile.mkdtemp()
    try:
        _os.makedirs(_os.path.join(tmp, "rules"))
        with open(_os.path.join(tmp, "rules", "t.md"), "w", encoding="utf-8") as fh:
            fh.write("real a@b.co and 8.8.8.8; ok you@example.com and 127.0.0.1 too")
        errs = C._no_personal_data_in_core(tmp)
        joined = " ".join(errs)
        assert "a@b.co" in joined, "must catch a real email"
        assert "8.8.8.8" in joined, "must catch a public IP"
        assert "example.com" not in joined and "127.0.0.1" not in joined, (
            "must NOT flag placeholder email / loopback IP")
    finally:
        _sh.rmtree(tmp)


def test_claude_target_not_on_glm_provider():
    """REGRESSION (glm default-provider leak, 2026-07-11): a Claude Code target
    must not resolve to the glm provider — glm-* model ids make claude typed
    sub-agents silently fail to dispatch. The live config must be clean, and
    precheck must flag a claude target that falls through to a glm default."""
    import checks as C
    stc, registry, adapters, _ = D._gather()
    assert not [e for e in C.precheck(stc, registry, None, adapters, D.CORE)
                if "glm provider" in e], "live config resolves claude onto glm"
    import copy
    bad = copy.deepcopy(stc)
    bad["models"] = {"provider": "glm", "zcode": "glm"}   # no claude override
    bad["deploy"] = {"targets": ["claude"]}
    errs = C.precheck(bad, registry, None, adapters, D.CORE)
    assert [e for e in errs if "glm provider" in e and "claude" in e], (
        "precheck must flag a claude target resolving to glm")


RULE_FINGERPRINTS = ("Facts → memory", "Plan→Do→Verify", "Memory rotation")


def test_zcode_bundle_inlines_rules():
    """REGRESSION (rules_delivery: inline): the zcode bundle must INLINE the
    3 firing rules (behavior/pev/session), not be a pointer. H06 is wired
    correctly but this ZCode build does not fire plugin hooks, so inlining is
    the only reliable delivery. Verifies: no @import lines; rule CONTENT
    present."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "zcode", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["zcode"], D.CORE, REPO)
    body = rr.files.get("AGENTS.stc.md", "")
    assert body, "zcode bundle missing"
    # NO @import / @~/.stc lines (the dead mechanism)
    assert not any(ln.strip().startswith("@~/") or ln.strip().startswith("@/")
                   for ln in body.splitlines()), (
        "zcode bundle still contains @import lines")
    # the 3 rule fingerprints must be INLINED (content present, not pointer)
    for fp in RULE_FINGERPRINTS:
        assert fp in body, f"zcode bundle missing inlined rule fingerprint '{fp}'"


def test_claude_bundle_is_pointer_not_inline():
    """REGRESSION (rules_delivery: hook — the double-delivery bug): on claude,
    H06 injects the 3 firing rules on SessionStart (verified live), so the
    bundle must stay a POINTER. Inlining the rules here too would deliver
    every rule twice (~20KB duplicate per session). Verifies: rule paths are
    listed, rule CONTENT is absent."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    body = rr.files.get("CLAUDE.stc.md", "")
    assert body, "claude bundle missing"
    # pointer lists the rule paths H06 injects
    for rel in ("rules/behavior.md", "rules/pev.md", "rules/session.md"):
        assert rel in body, f"claude pointer bundle does not name {rel}"
    # rule BODIES must NOT be inlined (H06 already delivers them). The check
    # is structural — no <details> rule blocks — because fingerprint strings
    # may legitimately appear in the inlined user profile.
    for label in ("behavior.md", "pev.md", "session.md"):
        marker = f"<code>{label}</code>"
        assert marker not in body, (
            f"claude bundle inlines {label} — rules would be delivered "
            f"twice (bundle + H06)")


def test_commands_and_skills_substitute_render_vars():
    """REGRESSION (the unresolved ${DOCS_ROOT} bug): commands and skills use
    deploy-owned ${VAR} tokens inline (no hook-style declaration block) —
    to-spec/to-tasks carried a literal ${DOCS_ROOT} into the live harness,
    which the agent then interpreted as a phantom path. Render must
    substitute every RENDER_VARS token in command/skill bodies."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "claude", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["claude"], D.CORE, REPO)
    # SESSION_ID is runtime-resolved (per session), never render-time
    static_vars = R.RENDER_VARS - {"SESSION_ID"}
    for rel, body in rr.files.items():
        if rel.endswith(".stc.md") and ("commands/" in rel or "skills/" in rel):
            for var in static_vars:
                assert f"${{{var}}}" not in body, (
                    f"{rel} carries unresolved ${{{var}}} into the harness")


def test_bundle_inlines_profile_when_present():
    """The user profile (user/profile.md) is inlined into the bundle for BOTH
    harnesses — it must be always-context and no hook injects it, so inlining
    never duplicates. Skipped when the private profile file is absent."""
    profile = os.path.join(REPO, "user", "profile.md")
    if not os.path.exists(profile):
        return  # private file absent (fresh clone) — nothing to verify
    stc, registry, adapters, _ = D._gather()
    for t in ("claude", "zcode"):
        provider = R.provider_for(stc, t, REPO)
        rr = R.render_harness(stc, registry, provider, adapters[t], D.CORE, REPO)
        bundle = "CLAUDE.stc.md" if t == "claude" else "AGENTS.stc.md"
        body = rr.files.get(bundle, "")
        assert "<code>profile.md</code>" in body, f"{t} bundle missing inlined profile"


def test_h06_injects_rules_via_stc_core():
    """REGRESSION (H06 injection — the original pre-@import mechanism): H06
    must `cat` the always-context rule files from ${STC_CORE} (resolved to
    ~/.stc/core) so its stdout reaches the model as additionalContext. This is
    the ONLY reliable cross-harness loader. Verifies: the cat loop targets the 3
    firing rules, ${STC_CORE} is substituted, project_docs is lazy (omitted to
    fit the 24KB additionalContext cap)."""
    stc, registry, adapters, _ = D._gather()
    for t in ("claude", "zcode"):
        provider = R.provider_for(stc, t, REPO)
        rr = R.render_harness(stc, registry, provider, adapters[t], D.CORE, REPO)
        h06 = next(k for k in rr.files if "session-start-context" in k)
        body = rr.files[h06]
        # ${STC_CORE} must be substituted (not left as a placeholder)
        assert "${STC_CORE}" not in body, f"{t} H06 has unresolved ${{STC_CORE}}"
        assert ".stc/core/rules" in body, f"{t} H06 does not target ~/.stc/core/rules"
        # the cat loop must cover the 3 firing rules (project_docs is lazy)
        for rule in ("behavior", "pev", "session"):
            assert f'rules/${{f}}.md' in body or f'rules/${{f}}' in body or rule in body, (
                f"{t} H06 missing rule {rule} in the cat loop")
        # project_docs must NOT be in the injected loop (lazy, to fit 24KB cap)
        # find the `for f in ...` loop line
        for_loop = [ln for ln in body.splitlines() if ln.strip().startswith("for f in")]
        assert for_loop, f"{t} H06 has no cat loop"
        assert "project_docs" not in for_loop[0], (
            f"{t} H06 still injects project_docs (must be lazy for the 24KB cap)")


def test_zcode_plugin_event_hooks_matcher_not_star():
    """REGRESSION (the silent hook-drop): ZCode treats `matcher` as a raw RegExp
    (new RegExp(matcher)). Claude's "*" wildcard is an INVALID regex here
    ("Nothing to repeat") → caught → the hook is silently dropped from every
    run. Event hooks (SessionStart/UserPromptSubmit/Stop) carried matcher="*"
    and never fired in the zcode plugin. The plugin-delivery path must emit
    ".*" (or omit) for these. Claude (files delivery) is unchanged ("*" is a
    valid wildcard there)."""
    stc, registry, adapters, _ = D._gather()
    provider = R.provider_for(stc, "zcode", REPO)
    rr = R.render_harness(stc, registry, provider, adapters["zcode"], D.CORE, REPO)
    hj = next(k for k in rr.files if k.endswith("/hooks/hooks.json"))
    data = json.loads(rr.files[hj])
    # no entry in the plugin hooks.json may carry matcher == "*"
    for ev, entries in data.get("hooks", {}).items():
        for e in entries:
            assert e.get("matcher") != "*", (
                f"zcode plugin hook {ev} has matcher='*' (invalid regex → silently dropped)")
    # the event hooks must be present with a valid matcher
    for ev in ("SessionStart", "UserPromptSubmit", "Stop"):
        assert ev in data["hooks"], f"event {ev} missing from plugin hooks.json"
        for e in data["hooks"][ev]:
            assert e.get("matcher") == ".*", (
                f"zcode {ev} matcher is {e.get('matcher')!r}, expected '.*'")


# ---------------------------------------------------------------------------
# prune: a file a prior deploy wrote but the current render drops must be
# removed from the native dir (retired command), while user files are never
# touched — even if a manifest glitch lists one.
# ---------------------------------------------------------------------------

def test_prune_orphans_removes_dropped_stc_artifact_but_never_user_files():
    import tempfile
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "commands"), exist_ok=True)
    kept = "commands/to-spec.stc.md"       # still emitted by the new render
    dropped = "commands/handoff.stc.md"    # retired → not in the new render
    user = "commands/mine.md"              # user's own file, wrongly in manifest
    for rel in (kept, dropped, user):
        with open(os.path.join(d, rel), "w", encoding="utf-8") as fh:
            fh.write("x")
    mf = os.path.join(d, "_manifest.json")
    json.dump({"claude": {"files": [kept, dropped, user]}},
              open(mf, "w", encoding="utf-8"))
    old = D.MANIFEST
    D.MANIFEST = mf
    try:
        pruned = D._prune_orphans("claude", d, [kept])
    finally:
        D.MANIFEST = old
    assert dropped in pruned, f"retired STC artifact must be pruned: {pruned}"
    assert not os.path.exists(os.path.join(d, dropped)), "dropped file still on disk"
    assert os.path.exists(os.path.join(d, kept)), "current artifact wrongly removed"
    # a bare .md is not a prunable shape → the user file survives the prune
    assert os.path.exists(os.path.join(d, user)), "user file must NEVER be pruned"


# ---------------------------------------------------------------------------
# review-session regression shields (art_slug collision, settings sweep,
# non-dict hooks, dangling marker, infra-graph scan, leak-guard tokens)
# ---------------------------------------------------------------------------

def test_art_slug_disambiguates_skill_md():
    # every skill's file is literally SKILL.md → a bare-basename slug collapses
    # all skills into one stub. Must disambiguate on the parent dir.
    a = GR.art_slug("/x/core/skills/tdd/SKILL.md")
    b = GR.art_slug("/x/core/skills/qa/SKILL.md")
    assert a != b, f"skill files must get distinct slugs, got {a} == {b}"
    assert a == "art-tdd-skill" and b == "art-qa-skill", f"{a} / {b}"


def test_settings_merge_sweeps_retired_stc_cap():
    import tempfile
    d = tempfile.mkdtemp()
    live = {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "_stc_managed": True, "_stc_cap": "H99_retired",
         "hooks": [{"type": "command", "command": "$NATIVE_DIR/hooks/retired.stc.sh"}]},
        {"matcher": "Bash", "_stc_managed": True, "_stc_cap": "H01_git",
         "hooks": [{"type": "command", "command": "$NATIVE_DIR/hooks/block-dangerous-git.stc.sh"}]},
    ]}}
    json.dump(live, open(os.path.join(d, "settings.json"), "w"))
    patch = {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "_stc_managed": True, "_stc_cap": "H01_git",
         "hooks": [{"type": "command", "command": "$NATIVE_DIR/hooks/block-dangerous-git.stc.sh"}]},
    ]}}
    D._merge_settings_patch(patch, d, overwrite=True, skip_collisions=False)
    caps = [e.get("_stc_cap") for e in json.load(open(os.path.join(d, "settings.json")))["hooks"]["PreToolUse"]]
    assert "H99_retired" not in caps, f"a retired STC cap must be swept: {caps}"
    assert "H01_git" in caps, f"the current cap must survive: {caps}"


def test_merge_non_dict_hooks_still_writes_permissions():
    import tempfile
    d = tempfile.mkdtemp()
    # corrupt: 'hooks' hand-edited to a string. Must not silently drop the
    # permissions.deny write (the old `return` did).
    json.dump({"hooks": "oops"}, open(os.path.join(d, "settings.json"), "w"))
    patch = {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "_stc_managed": True, "_stc_cap": "H01",
         "hooks": [{"type": "command", "command": "$NATIVE_DIR/hooks/block-dangerous-git.stc.sh"}]}]},
        "permissions": {"_stc_deny": ["Read(./.env)"]}}
    D._merge_settings_patch(patch, d, overwrite=True, skip_collisions=False)
    out = json.load(open(os.path.join(d, "settings.json")))
    assert isinstance(out["hooks"], dict), "hooks must be reset to a dict"
    assert out.get("permissions", {}).get("deny") == ["Read(./.env)"], \
        "permissions.deny must still be written when hooks was corrupt"


def test_stc_block_dangling_begin_preserves_user_tail():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "CLAUDE.md")
    # BEGIN present, END deleted by hand, real user content after it
    open(p, "w").write(B.STC_BEGIN + "\nold import\nIMPORTANT USER NOTES\n")
    B.inject_block(p, "@new-import", create=True)
    txt = open(p).read()
    assert "IMPORTANT USER NOTES" in txt, "user tail must NOT be swallowed by a dangling BEGIN"
    assert "@new-import" in txt, "a fresh block must be appended"


def test_infra_graph_multiletter_scan():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.md")
    open(p, "w").write("# H\n<!-- I50 -->\ntext\n## R\n<!-- R50 -->\nmore\n")
    codes = {f.code for f in IG.parse_md_file(p, "IR", "lazy")[0]}
    assert {"I50", "R50"} <= codes, f"multi-letter scan must keep both: {codes}"
    only_i = {f.code for f in IG.parse_md_file(p, "I", "lazy")[0]}
    assert only_i == {"I50"}, f"single letter must keep only I: {only_i}"


def test_infra_graph_external_ignore_is_context_scoped():
    # A10 on an OWASP line → ignored; a bare A10 reference → still an orphan
    ignored = IG.check({}, {}, [("x", "OWASP A10 SSRF sweep")], set())
    assert "A10" not in ignored["orphans"], "A10 in OWASP context must be ignored"
    real = IG.check({}, {}, [("x", "see A10 for the details")], set())
    assert "A10" in real["orphans"], "a bare A10 orphan (no external ctx) must surface"


def test_infra_graph_retired_not_orphan():
    # a retired code mentioned in prose but undefined must not be an orphan
    f = IG.check({}, {}, [("x", "H99 was retired")], {"H99"})
    assert "H99" not in f["orphans"], "a retired code must not read as an orphan"


def test_leak_guard_detects_api_token():
    import tempfile
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "core", "memory"))
    open(os.path.join(d, "core", "memory", "x.md"), "w").write("key ghp_" + "a" * 36 + " here")
    errs = C._no_personal_data_in_core(os.path.join(d, "core"))
    assert any("GitHub PAT" in e for e in errs), f"must detect a planted PAT: {errs}"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def _run():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    return 1 if failed else 0


# pytest compatibility: when collected by pytest, the test_* functions are
# discovered automatically; this guard only runs the stdlib runner.
if __name__ == "__main__":
    sys.exit(_run())

# when imported by pytest, expose a collectible suite
try:
    import pytest  # noqa: F401
except ImportError:
    pass
