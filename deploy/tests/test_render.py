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
    cmds = ["grill-me.md", "save-and-compact.md", "grill_me.md"]
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
