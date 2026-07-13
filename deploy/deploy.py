#!/usr/bin/env python3
"""deploy.py — the STC deploy orchestrator (CLI).

Consumes the Stage-3 contracts (adapter.yaml × core/models × registry.yaml ×
stc.yaml) and renders the harness form. Non-destructive: every markdown
artifact is *.stc.md (collision-proof); settings/.mcp JSON are merged under
the stc-* namespace; the ONLY user file touched is the always-context file,
via one marker @import line.

Commands:
  render   --target <h[,...]> [--dry-run]   render into deploy/_rendered/<h>/ (no live writes)
  apply    --target <h[,...]> [--overwrite] [--skip-collisions]
                                            render + write to ~/.stc/ + the native dir
                                            (REFUSES on JSON collisions unless a flag is given)
  uninstall --target <h[,...]>              remove *.stc.md, the marker block, stc-* JSON keys
  check                              validate config without writing
  restore  <backup-id>               roll back JSON from a backup snapshot

  --target accepts one harness id OR a comma-separated list (claude,zcode).
  Unknown names fail fast with the list of available adapters. When --target
  is absent, all targets from stc.yaml deploy.targets are used.

Defaults: dry-run / preview everywhere; ~/.claude and ~/.zcode are never
written until the Stage 5/6 consent gate. apply writes to ~/.stc/ + the native
dir only when invoked explicitly.

Usage:
  python3 deploy/deploy.py render --target claude --dry-run
  python3 deploy/deploy.py render --target claude,zcode --dry-run
  python3 deploy/deploy.py apply --target claude
  python3 deploy/deploy.py check
"""

import argparse
import json
import os
import re
import sys

# make the sibling modules importable when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R          # noqa: E402
import checks as C          # noqa: E402
import stc_block as B       # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
CORE = os.path.join(REPO, "core")
STC_YAML = os.path.join(REPO, "stc.yaml")
STC_EXAMPLE = os.path.join(REPO, "stc.example.yaml")
RENDERED_ROOT = os.path.join(REPO, "deploy", "_rendered")
STC_HOME = os.path.join(os.path.expanduser("~"), ".stc")
BACKUPS = os.path.join(STC_HOME, "backups")
MANIFEST = os.path.join(REPO, "deploy", "_manifest.json")


# ---------------------------------------------------------------------------
# config loading
# ---------------------------------------------------------------------------

def _resolve_targets(arg_target, adapters, stc):
    """Resolve the deploy target list from --target (one or many, comma-
    separated) or fall back to stc.yaml deploy.targets.

    --target accepts a single value OR a comma-separated list:
        --target claude
        --target claude,zcode
    Whitespace around commas is tolerated; empty tokens are dropped. When the
    flag is absent, all targets from stc.yaml deploy.targets are used.

    Validation is FAIL-FAST: every named target must have an adapter, else the
    deploy aborts with the bad name(s) and the list of available adapters — an
    unknown name is almost always a typo and must not silently pass.
    """
    if arg_target:
        # split on comma, strip whitespace, drop empties, dedupe preserving order
        seen, targets = set(), []
        for tok in str(arg_target).split(","):
            t = tok.strip()
            if t and t not in seen:
                seen.add(t)
                targets.append(t)
        explicit = True
    else:
        targets = list(stc.get("deploy", {}).get("targets", []))
        explicit = False
    unknown = [t for t in targets if t not in adapters]
    if unknown:
        avail = ", ".join(sorted(adapters))
        raise SystemExit(
            f"✗ unknown target(s): {', '.join(unknown)}\n"
            f"  available adapters: {avail}"
        )
    # Frozen adapters (adapter.yaml `frozen: true`): kept in-tree so the adapter
    # architecture stays proven and resuming is trivial, but not deployed by
    # default. Skipped when they come from the stc.yaml default list; deployed
    # (with a warning) only when named explicitly via --target, so a deliberate
    # resume works without friction.
    frozen = [t for t in targets if adapters[t].get("frozen")]
    if frozen:
        if explicit:
            print(f"⚠ {', '.join(frozen)}: FROZEN adapter(s) — deploying because "
                  f"you named them explicitly (adapters/<name>/ is preserved but "
                  f"not actively maintained).")
        else:
            print(f"⏸ skipping frozen target(s): {', '.join(frozen)} — re-add to "
                  f"stc.yaml deploy.targets, or run --target {frozen[0]} to resume.")
            targets = [t for t in targets if t not in frozen]
    return targets


def _load_targets(adapters, args):
    # deprecated shim — kept for any external caller; _resolve_targets is the
    # current path. Returns the stc.yaml fallback only (no validation).
    if getattr(args, "target", None):
        return [args.target]
    try:
        stc = R._load_yaml(STC_YAML)
        return stc.get("deploy", {}).get("targets", [])
    except FileNotFoundError:
        return []


def _gather():
    """Load stc.yaml (or the example if real one absent) + all adapters.

    Provider is NOT loaded here — it is per-target now (a harness speaks one
    model family). Callers resolve it via R.provider_for(stc, target, REPO)
    inside the per-target loop. See render.provider_for for the rationale.
    """
    stc_path = STC_YAML if os.path.exists(STC_YAML) else STC_EXAMPLE
    stc, registry, _ = R.load_inputs(stc_path, CORE, REPO)
    adapter_dirs = os.path.join(REPO, "adapters")
    adapters = {}
    for d in os.listdir(adapter_dirs):
        ap = os.path.join(adapter_dirs, d, "adapter.yaml")
        if os.path.isfile(ap) and d != "_template":
            adapters[d] = R.load_adapter(REPO, d)
    return stc, registry, adapters, stc_path


# ---------------------------------------------------------------------------
# write helpers
# ---------------------------------------------------------------------------

def _write_tree(base, files, native_dir=None):
    """Write {relpath: text} under base/, substituting $NATIVE_DIR / $<native_dir>.

    Shell scripts (.sh / .stc.sh) are written with the executable bit set:
    hook scripts carry a shebang and Claude Code executes them directly, so a
    rw-r--r-- file (the default umask for open()) silently fails to run.
    """
    for rel, text in files.items():
        body = text
        if native_dir:
            body = body.replace("$NATIVE_DIR", native_dir)
        path = os.path.join(base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        if rel.endswith(".sh"):
            # rwxr-xr-x: user-read-write-execute, group/other read-execute.
            # Hook scripts are executed, not sourced — they must be +x.
            cur = os.stat(path).st_mode
            os.chmod(path, cur | 0o111)


def _merge_settings_patch(patch, native_dir, overwrite, skip_collisions):
    """Merge the STC settings patch into the live settings.json (idempotent).

    Before adding each STC entry, drop any prior entry that is STC-owned:
      (a) tagged entries (_stc_managed + _stc_cap match) — the idempotent update
          path when re-deploying over an already-managed settings.json;
      (b) UNTAGGED legacy entries whose hook command basename matches THIS
          entry's hook filename (with or without the .stc.sh suffix). This
          catches hooks from a pre-namespace deploy — they carry no tag, so
          without this check they'd survive as "user" entries and fire twice.
    The basename match is SCOPED TO THIS ENTRY ONLY (not a global set): each
    patch entry is one capability with its own script, so matching must compare
    against that entry's basename, else all Bash-matcher groups would collapse.
    Genuine user hooks never match STC hook filenames and are preserved verbatim.
    """
    path = os.path.join(native_dir, "settings.json")
    live = C._load_json(path) or {}
    # resolve $NATIVE_DIR in every hook command BEFORE merge. Render emits
    # "$NATIVE_DIR/hooks/foo.stc.sh" (disk-agnostic, testable); Claude Code does
    # NOT expand $NATIVE_DIR — it is not a standard env var — so an unresolved
    # placeholder produces an empty path and the hook script is never found.
    # Substituting the absolute native_dir here keeps render disk-agnostic and
    # avoids needing an `env: {NATIVE_DIR: ...}` block in settings.json.
    for entries in patch.get("hooks", {}).values():
        for e in entries:
            for h in (e.get("hooks") or []):
                if isinstance(h, dict):
                    h["command"] = h.get("command", "").replace("$NATIVE_DIR", native_dir)
    hooks = live.get("hooks")
    if not isinstance(hooks, dict):
        # A non-dict hooks key (hand-edited / corrupt). We cannot merge into it,
        # but silently returning here would also drop the statusLine and
        # permissions.deny writes below — losing them with a "✓ applied" report.
        # Reset to a fresh dict (STC hooks are required) and warn loudly instead.
        if hooks is not None:
            print(f"   ⚠ settings.json 'hooks' was not an object "
                  f"({type(hooks).__name__}); STC reset it — restore from a backup "
                  f"if you had custom hooks there.")
        hooks = {}
        live["hooks"] = hooks

    # Every capability THIS render emits (across the whole patch). Used to sweep
    # STALE STC-managed entries whose capability was fully removed from the render
    # (a dropped hook, not just a renamed one): a per-entry match only replaces
    # caps still present, so a removed cap's wiring would linger forever — pointing
    # at a hook script _prune_orphans just deleted. Mirrors _uninstall_one's sweep.
    current_caps = {e.get("_stc_cap")
                    for entries in patch.get("hooks", {}).values() for e in entries}

    for event, entries in patch.get("hooks", {}).items():
        bucket = hooks.setdefault(event, [])
        for e in entries:
            cap = e.get("_stc_cap")
            # the basenames THIS entry installs (scoped, not global)
            entry_basenames = _entry_hook_basenames(e)
            bucket = [x for x in bucket if not _is_stc_owned(x, cap, entry_basenames)]
            bucket.append(e)
        hooks[event] = bucket
    # sweep stale STC-managed entries across ALL events (cap no longer rendered).
    # Guarded on a non-empty patch so an empty/failed render can't wipe the wiring.
    if patch.get("hooks"):
        for event in list(hooks.keys()):
            hooks[event] = [x for x in hooks[event]
                            if not (isinstance(x, dict)
                                    and x.get("_stc_managed") is True
                                    and x.get("_stc_cap") not in current_caps)]
            if not hooks[event]:
                del hooks[event]
    if "_stc_statusline" in patch and overwrite:
        live["statusLine"] = {"type": "command",
                              "command": f"{native_dir}/{patch['_stc_statusline']}"}
    # permissions.deny — STC static read-guards. Merged into the user's existing
    # deny list (dedup), never replacing user rules. Tagged so uninstall strips
    # only the STC-contributed ones.
    stc_deny = patch.get("permissions", {}).get("_stc_deny")
    if stc_deny:
        perms = live.setdefault("permissions", {})
        user_deny = [d for d in perms.get("deny", []) if d not in stc_deny]
        perms["deny"] = user_deny + stc_deny
    # session defaults (FR-28) — STC-owned start mode + main-session model.
    # Written unconditionally (STC owns these keys while session_defaults is
    # configured); the pre-apply backup snapshot covers restore, and uninstall
    # removes them only if still equal to what STC wrote.
    sd = patch.get("_stc_session_defaults") or {}
    if sd.get("defaultMode"):
        live.setdefault("permissions", {})["defaultMode"] = sd["defaultMode"]
    if sd.get("model"):
        live["model"] = sd["model"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(live, fh, indent=2, ensure_ascii=False)


def _entry_hook_basenames(entry):
    """Basenames of the hook scripts a patch entry installs, plus the legacy
    .sh form (so 'block-dangerous-git.stc.sh' also matches 'block-dangerous-git.sh').
    """
    out = set()
    if not isinstance(entry, dict):
        return out
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else ""
        b = os.path.basename(cmd)
        if b:
            out.add(b)
            out.add(re.sub(r"\.stc\.sh$", ".sh", b))
    return out


def _is_stc_owned(entry, cap, entry_basenames):
    """True if a live hook entry belongs to STC and should be replaced/updated.

    Recognises two shapes:
      - tagged:   _stc_managed is True AND _stc_cap matches (idempotent re-deploy)
      - legacy:   untagged, but its hook command basename matches one of THIS
                  entry's hook scripts (with or without .stc.sh). Catches
                  pre-namespace deploys where entries carry no tag.
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("_stc_managed") is True and entry.get("_stc_cap") == cap:
        return True
    if entry_basenames:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "") if isinstance(h, dict) else ""
            if os.path.basename(cmd) in entry_basenames:
                return True
    return False


def _merge_mcp_patch(patch, native_dir):
    path = os.path.join(native_dir, ".mcp.json")
    live = C._load_json(path) or {}
    servers = live.setdefault("mcpServers", {})
    incoming = patch.get("mcpServers") or {}
    for name, cfg in incoming.items():
        servers[name] = cfg  # stc-* names → update in place (idempotent)
    # prune STC-managed servers (stc-*) this render no longer emits — a server
    # removed from stc.yaml's mcp block would otherwise linger in .mcp.json
    # forever (same gap the hooks-sweep fixed). Only stc-* keys; user servers
    # untouched. Guarded on a non-empty patch so a failed render can't wipe them.
    if incoming:
        for name in [n for n in servers if n.startswith("stc-") and n not in incoming]:
            del servers[name]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(live, fh, indent=2, ensure_ascii=False)


def _register_plugin(native_dir):
    """Register the STC plugin so a plugin-delivery harness discovers it.

    ZCode's plugin discovery (resolveCandidates in the CLI) gathers candidates
    from exactly two sources: a hardcoded scan of cache/zcode-plugins-official/,
    and the records in cli/plugins/installed_plugins.json. A non-official plugin
    in cache/<marketplace>/ is NEVER scanned on its own — it must have an
    installed_plugins.json entry, else it is invisible regardless of config.json
    enable state or known_marketplaces.json. The bug this fixes: STC was enabled
    in config.json but had no installed_plugins.json record, so discovery never
    reached it. Idempotent: re-apply updates the record in place.
    """
    mp = R.PLUGIN_MARKETPLACE
    pn = R.PLUGIN_NAME
    plugin_id = f"{pn}@{mp}"
    # 1. enable the plugin in cli/config.json
    cfg_path = os.path.join(native_dir, "cli", "config.json")
    cfg = C._load_json(cfg_path) or {}
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.setdefault("enabledPlugins", {})
    if enabled.get(plugin_id) is not True:
        enabled[plugin_id] = True
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    # 2. register the filesystem marketplace in known_marketplaces.json (kept
    #    for the marketplace/dependency-resolution flows and GUI display; note
    #    this file is NOT consulted by discovery — installed_plugins.json is).
    km_path = os.path.join(native_dir, "cli", "plugins", "known_marketplaces.json")
    km = C._load_json(km_path) or {"version": 1, "marketplaces": []}
    marketplaces = km.setdefault("marketplaces", [])
    if not any(m.get("id") == mp for m in marketplaces):
        marketplaces.append({
            "id": mp,
            "source": {"source": "filesystem", "path": f"cli/plugins/cache/{mp}"},
            "name": mp,
            "description": "STC Core — local filesystem marketplace",
            "pluginCount": 1,
        })
        os.makedirs(os.path.dirname(km_path), exist_ok=True)
        with open(km_path, "w", encoding="utf-8") as fh:
            json.dump(km, fh, indent=2, ensure_ascii=False)
    # 3. installed_plugins.json — THE discovery record. Without it the plugin
    #    tree in cache/stc-core/ is never enumerated, and config.json's
    #    "stc@stc-core": true has nothing to enable. installPath points at the
    #    versioned plugin dir so the harness reads .zcode-plugin/plugin.json,
    #    skills/, hooks/, agents/, commands/ from there.
    ip_path = os.path.join(native_dir, "cli", "plugins", "installed_plugins.json")
    ip = C._load_json(ip_path) or {"version": 1, "plugins": []}
    ip.setdefault("version", 1)
    recs = ip.setdefault("plugins", [])
    install_path = os.path.join(native_dir, R.PLUGIN_DIR)
    # upsert by id: replace any prior STC record (idempotent re-deploy / version bump)
    recs = [r for r in recs if r.get("id") != plugin_id]
    recs.append({
        "id": plugin_id,
        "name": pn,
        "marketplace": mp,
        "version": R.PLUGIN_VERSION,
        "installPath": install_path,
        "installedAt": "2026-07-08T00:00:00.000Z",
        "updatedAt": "2026-07-08T00:00:00.000Z",
        "scope": "user",
    })
    ip["plugins"] = recs
    os.makedirs(os.path.dirname(ip_path), exist_ok=True)
    with open(ip_path, "w", encoding="utf-8") as fh:
        json.dump(ip, fh, indent=2, ensure_ascii=False)


def _unregister_plugin(native_dir):
    """Reverse _register_plugin on uninstall (idempotent)."""
    mp = R.PLUGIN_MARKETPLACE
    pn = R.PLUGIN_NAME
    plugin_id = f"{pn}@{mp}"
    cfg_path = os.path.join(native_dir, "cli", "config.json")
    cfg = C._load_json(cfg_path) or {}
    enabled = (cfg.get("plugins") or {}).get("enabledPlugins") or {}
    if plugin_id in enabled:
        del enabled[plugin_id]
        (cfg.setdefault("plugins", {}))["enabledPlugins"] = enabled
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    km_path = os.path.join(native_dir, "cli", "plugins", "known_marketplaces.json")
    km = C._load_json(km_path) or {"version": 1, "marketplaces": []}
    km["marketplaces"] = [m for m in km.get("marketplaces", []) if m.get("id") != mp]
    with open(km_path, "w", encoding="utf-8") as fh:
        json.dump(km, fh, indent=2, ensure_ascii=False)
    # remove the installed_plugins.json record _register_plugin wrote (mirror of
    # step 3) — the discovery entry without which the plugin was invisible.
    ip_path = os.path.join(native_dir, "cli", "plugins", "installed_plugins.json")
    ip = C._load_json(ip_path)
    if ip:
        ip["plugins"] = [r for r in ip.get("plugins", []) if r.get("id") != plugin_id]
        if not ip["plugins"]:
            del ip["plugins"]
        with open(ip_path, "w", encoding="utf-8") as fh:
            json.dump(ip, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_render(args):
    stc, registry, adapters, _ = _gather()
    targets = _resolve_targets(args.target, adapters, stc)
    for t in targets:
        provider = R.provider_for(stc, t, REPO)
        rr = R.render_harness(stc, registry, provider, adapters[t], CORE, REPO)
        out = os.path.join(RENDERED_ROOT, t)
        _write_tree(out, rr.files)
        # also dump the json patches for inspection
        for jn, jp in rr.json_patches.items():
            with open(os.path.join(out, jn + ".stc.patch.json"), "w", encoding="utf-8") as fh:
                json.dump(jp, fh, indent=2, ensure_ascii=False)
        print(f"✓ rendered {t} → deploy/_rendered/{t}/ "
              f"({len(rr.files)} files, {len(rr.json_patches)} JSON patches)")


def cmd_apply(args):
    stc, registry, adapters, _ = _gather()
    errs = C.precheck(stc, registry, None, adapters, CORE)
    if errs:
        print("✗ precheck failed:"); [print("   " + e) for e in errs]; return 1
    # non-blocking warnings: session-path drift can orphan project memory and
    # sessions (the 'Folder not found' condition). Printed, never blocks deploy.
    for w in C.session_path_warnings(stc):
        print("   ⚠ " + w)
    targets = _resolve_targets(args.target, adapters, stc)
    for t in targets:
        adapter = adapters[t]  # _resolve_targets already validated t ∈ adapters
        native_dir = adapter["native_dir"].replace("${HOME}", os.path.expanduser("~"))
        provider = R.provider_for(stc, t, REPO)
        rr = R.render_harness(stc, registry, provider, adapter, CORE, REPO)

        collisions = C.detect_collisions(rr, native_dir, t)
        if collisions and not args.overwrite and not args.skip_collisions:
            C.report_collisions(collisions); return 1

        # backup JSON we are about to touch
        json_files = list(rr.json_patches.keys())
        if json_files and os.path.isdir(native_dir):
            ts, dest, saved = C.backup_snapshot(native_dir, json_files, BACKUPS)
            if saved:
                _record_backup(ts, t, native_dir, saved)
                print(f"✓ backup {ts} → {dest}/ (target={t}; restore: deploy.py restore {ts})")

        # 1. ~/.stc/core/ (the shared, harness-neutral source — one update, all harnesses)
        _sync_stc_home()
        # 2. *.stc.md + hook scripts into the native dir
        _write_tree(native_dir, rr.files, native_dir=native_dir)
        # 2a. prune artifacts a PRIOR deploy wrote that this render no longer emits
        #     (e.g. a retired command like handoff.stc.md) — deploy used to only
        #     ever write, never clean, so a dropped file lingered forever.
        pruned = _prune_orphans(t, native_dir, rr.files.keys())
        if pruned:
            print(f"   🧹 pruned {len(pruned)} orphaned artifact(s): {', '.join(pruned)}")
        # 2b. plugin-delivery harnesses need the plugin REGISTERED to be visible:
        #     the cache dir alone is not discovered. enable in cli/config.json and
        #     add the filesystem marketplace to known_marketplaces.json (idempotent).
        delivery = adapter.get("harness_facts", {}).get("capability_delivery", "files")
        if delivery == "plugin":
            _register_plugin(native_dir)
        # 3. JSON merges
        for jn, jp in rr.json_patches.items():
            if jn == "settings.json":
                _merge_settings_patch(jp, native_dir, args.overwrite, args.skip_collisions)
            elif jn == ".mcp.json":
                _merge_mcp_patch(jp, native_dir)
        # 4. the single marker @import into the user's always-context file.
        # Render owns the marker content (single source of truth); here we just
        # resolve the $NATIVE_DIR placeholder and inject it.
        ac_file, marker_line = _marker_for(rr, native_dir)
        B.inject_block(os.path.join(native_dir, ac_file), marker_line, create=True)

        _write_manifest(rr, t, native_dir)
        warns = C.postcheck(rr)
        for w in warns:
            print("   ⚠ " + w)
        print(f"✓ applied {t} → {native_dir} + ~/.stc/")
    return 0


def cmd_uninstall(args):
    if not os.path.exists(MANIFEST):
        print("✗ no manifest — nothing STC recorded to uninstall."); return 1
    try:
        manifest = json.load(open(MANIFEST, encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"✗ manifest at {MANIFEST} is corrupt; remove it manually."); return 1
    # --target accepts a single value OR comma-separated list (e.g. "claude,zcode").
    # Every name must have a recorded manifest entry, else fail fast — uninstall
    # is destructive and a typo must not silently pass.
    raw = str(args.target)
    seen, targets = set(), []
    for tok in raw.split(","):
        t = tok.strip()
        if t and t not in seen:
            seen.add(t); targets.append(t)
    unknown = [t for t in targets if t not in manifest]
    if unknown:
        avail = ", ".join(sorted(manifest))
        print(f"✗ no manifest entry for: {', '.join(unknown)}")
        if avail:
            print(f"  installed targets: {avail}")
        return 1
    for target in targets:
        manifest = _uninstall_one(target, manifest)
    # ~/.stc/core/ is shared across harnesses — only remove it when the LAST
    # harness is uninstalled, so a partial uninstall keeps core for the rest.
    if not manifest:
        _purge_stc_home()
        print(f"✓ uninstalled {', '.join(targets)} (last harness(es) — "
              f"~/.stc/core/ removed; user content + backup snapshots retained)")
    else:
        print(f"✓ uninstalled {', '.join(targets)} (user content preserved; "
              f"~/.stc/core/ kept — still in use by: {', '.join(manifest)})")
    return 0


def _uninstall_one(target, manifest):
    """Remove a single target's STC artifacts (recorded in the manifest) from
    its native dir. Returns the updated manifest (target deleted). The caller
    decides when to purge the shared ~/.stc/core/ (only when manifest is empty).
    """
    entry = manifest[target]
    native_dir = entry["native_dir"]
    # detect plugin-delivery from the file paths the manifest recorded (any path
    # under cli/plugins/cache/<mkt>/ means plugin form)
    is_plugin = any("/plugins/cache/" in rel for rel in entry.get("files", []))
    # 1. remove *.stc.md / *.stc.sh files listed in the manifest for THIS target
    for rel in entry.get("files", []):
        p = os.path.join(native_dir, rel)
        if os.path.exists(p):
            os.remove(p)
    # 1b. plugin-delivery: unregister (config.json + known_marketplaces) and
    #     remove the versioned plugin dir entirely (manifest lists individual
    #     files, but plugin dirs may also hold harness-generated state).
    if is_plugin:
        _unregister_plugin(native_dir)
        import shutil
        plugin_dir = os.path.join(native_dir, R.PLUGIN_DIR)
        if os.path.isdir(plugin_dir):
            shutil.rmtree(plugin_dir)
    # 2. remove the marker block from the always-context file
    ac_file = entry.get("always_context", "CLAUDE.md")
    B.remove_block(os.path.join(native_dir, ac_file))
    # 3. strip stc-* keys from JSON (use the JSON list the manifest recorded,
    #    so new patch types added later are cleaned too — not a hardcoded list)
    for jn in entry.get("json", ("settings.json", ".mcp.json")):
        p = os.path.join(native_dir, jn)
        live = C._load_json(p)
        if not live:
            continue
        if jn == "settings.json" and isinstance(live.get("hooks"), dict):
            # build the set of STC hook basenames the manifest recorded, so a
            # legacy untagged entry pointing at the same script is also stripped.
            stc_basenames = set()
            for rel in entry.get("files", []):
                b = os.path.basename(rel)
                stc_basenames.add(b)
                stc_basenames.add(re.sub(r"\.stc\.sh$", ".sh", b))
            for ev in list(live["hooks"]):
                kept = []
                for x in live["hooks"][ev]:
                    drop = False
                    if isinstance(x, dict):
                        if x.get("_stc_managed") is True:
                            drop = True
                        else:
                            for h in x.get("hooks", []):
                                cmd = h.get("command", "") if isinstance(h, dict) else ""
                                if os.path.basename(cmd) in stc_basenames:
                                    drop = True; break
                    kept.append(x) if not drop else None
                live["hooks"][ev] = kept
                if not kept:
                    del live["hooks"][ev]
            if not live["hooks"]:
                del live["hooks"]
        # strip STC-contributed permissions.deny rules (user's own stay)
        if jn == "settings.json" and isinstance(live.get("permissions"), dict):
            stc_deny = set(entry.get("permissions_deny") or [])
            if live["permissions"].get("deny"):
                live["permissions"]["deny"] = [d for d in live["permissions"]["deny"] if d not in stc_deny]
                if not live["permissions"]["deny"]:
                    del live["permissions"]["deny"]
            if not live["permissions"]:
                del live["permissions"]
        # strip STC session defaults (FR-28) — only if still the value STC wrote
        # (a hand-changed value after deploy belongs to the user; leave it).
        if jn == "settings.json":
            _strip_session_defaults(live, entry.get("session_defaults") or {})
        if jn == ".mcp.json" and live.get("mcpServers"):
            live["mcpServers"] = {k: v for k, v in live["mcpServers"].items() if not k.startswith("stc-")}
            if not live["mcpServers"]:
                del live["mcpServers"]
        json.dump(live, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    del manifest[target]
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"), indent=2)
    return manifest


def _strip_session_defaults(live, sd):
    """Remove STC-written session defaults (FR-28) from a live settings dict —
    but ONLY while each value still equals what STC wrote. A value the user
    re-pointed after deploy belongs to the user and survives uninstall.
    Mutates `live` in place."""
    perms = live.get("permissions")
    if sd.get("defaultMode") and isinstance(perms, dict) \
            and perms.get("defaultMode") == sd["defaultMode"]:
        del perms["defaultMode"]
        if not perms:
            del live["permissions"]
    if sd.get("model") and live.get("model") == sd["model"]:
        del live["model"]


def _purge_stc_home():
    """Remove ~/.stc/core/ (the shared mirror). Guarded like _sync_stc_home."""
    import shutil
    dst = os.path.join(STC_HOME, "core")
    if os.path.islink(dst) or (os.path.exists(dst) and not os.path.realpath(dst).startswith(os.path.realpath(STC_HOME))):
        raise RuntimeError(f"refusing to remove {dst}: outside STC_HOME or a symlink")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    return 0


def cmd_check(args):
    if not C.onboarding(os.path.exists(STC_YAML)):
        return 1
    stc, registry, adapters, _ = _gather()
    errs = C.precheck(stc, registry, None, adapters, CORE)
    if errs:
        print("✗ config problems:"); [print("   " + e) for e in errs]; return 1
    print("✓ config valid")
    for w in C.session_path_warnings(stc):
        print("   ⚠ " + w)
    for t in stc.get("deploy", {}).get("targets", []):
        adapter = adapters.get(t)
        if not adapter:
            continue
        native_dir = adapter["native_dir"].replace("${HOME}", os.path.expanduser("~"))
        provider = R.provider_for(stc, t, REPO)
        rr = R.render_harness(stc, registry, provider, adapter, CORE, REPO)
        cols = C.detect_collisions(rr, native_dir, t)
        n = len(rr.files)
        print(f"   {t}: {n} files, {len(rr.json_patches)} JSON patches, {len(cols)} collision(s)")
        for c in cols:
            print(f"      ⚠ {c}")
    return 0


def cmd_restore(args):
    """Restore a backup snapshot into the SAME native_dir it came from.

    The backup id is tied to a target via the backup ledger (~/.stc/backups/
    _ledger.json), so restore knows where to put files — never guesses ~/.
    """
    native_dir = _native_dir_for_backup(args.backup_id)
    if not native_dir:
        print(f"✗ backup '{args.backup_id}' not found in ledger ({BACKUPS}/_ledger.json)")
        return 1
    C.restore(args.backup_id, native_dir, BACKUPS)
    print(f"✓ restored {args.backup_id} → {native_dir}")
    return 0


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _sync_stc_home():
    """Mirror core/ into ~/.stc/core/ so all harnesses share one source.

    Guarded: only ever removes a path INSIDE STC_HOME, and refuses to follow a
    symlink (rmtree on a symlinked dir would destroy the link target).
    """
    import shutil
    dst = os.path.join(STC_HOME, "core")
    # safety: dst must be strictly under STC_HOME, and not a symlink target
    if os.path.islink(dst) or (os.path.exists(dst) and not os.path.realpath(dst).startswith(os.path.realpath(STC_HOME))):
        raise RuntimeError(f"refusing to remove {dst}: outside STC_HOME or a symlink")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(CORE, dst)


def _marker_for(rr, native_dir):
    """Resolve the render-produced marker into (ac_file, @import line).

    result.marker is { <ac_file>: <@import line with $NATIVE_DIR placeholder> }.
    We substitute the placeholder and return the single (file, line) pair.
    """
    if not rr.marker:
        ac = "CLAUDE.md"
        return ac, f"@{native_dir}/{re.sub(r'.md$', '.stc.md', ac)}"
    ac_file, line = next(iter(rr.marker.items()))
    return ac_file, line.replace("$NATIVE_DIR", native_dir)


def _record_backup(ts, target, native_dir, files):
    """Append a backup entry to the ledger so restore knows its target.

    The ledger ties a backup id (timestamp) to the target harness + native_dir
    it came from — restore reads it instead of guessing (the D9 bug).
    """
    os.makedirs(BACKUPS, exist_ok=True)
    ledger_path = os.path.join(BACKUPS, "_ledger.json")
    ledger = {}
    if os.path.exists(ledger_path):
        try:
            ledger = json.load(open(ledger_path, encoding="utf-8"))
        except json.JSONDecodeError:
            ledger = {}
    ledger[ts] = {"target": target, "native_dir": native_dir, "files": files}
    json.dump(ledger, open(ledger_path, "w", encoding="utf-8"), indent=2)


def _native_dir_for_backup(ts):
    ledger_path = os.path.join(BACKUPS, "_ledger.json")
    if not os.path.exists(ledger_path):
        return None
    try:
        ledger = json.load(open(ledger_path, encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return (ledger.get(ts) or {}).get("native_dir")


def _prunable(rel):
    """A relpath deploy may safely delete during prune. Scoped to STC-owned
    shapes as a safety net: the collision-proof suffixes (.stc.md / .stc.sh) and
    the skill manifest file (skills/<name>/SKILL.md — the one STC artifact that
    keeps its bare name). Anything else is left untouched even if the manifest
    somehow lists it, so a user file can never be removed.
    """
    return rel.endswith((".stc.md", ".stc.sh")) or os.path.basename(rel) == "SKILL.md"


def _prune_orphans(target, native_dir, new_files):
    """Remove STC artifacts a prior deploy wrote that this render no longer emits.

    Compares the previous manifest's file list for THIS target against the
    current render and unlinks the difference (filtered by `_prunable`). Called
    in cmd_apply BEFORE _write_manifest overwrites the record. Returns the list
    of pruned relpaths (for the apply log).
    """
    if not os.path.exists(MANIFEST):
        return []
    try:
        manifest = json.load(open(MANIFEST, encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    old_files = set(manifest.get(target, {}).get("files", []))
    orphans = sorted(rel for rel in (old_files - set(new_files)) if _prunable(rel))
    pruned = []
    for rel in orphans:
        p = os.path.join(native_dir, rel)
        if os.path.isfile(p):
            os.remove(p)
            pruned.append(rel)
    return pruned


def _write_manifest(rr, target, native_dir):
    """Record what deploy created, so uninstall is precise + idempotent.

    Reads the marker contract directly (ac_file is the marker key); never
    calls .get() on a string (the old crash, D8).
    """
    manifest = {}
    if os.path.exists(MANIFEST):
        try:
            manifest = json.load(open(MANIFEST, encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}  # corrupt manifest → start fresh rather than crash
    ac_file, _ = _marker_for(rr, native_dir)
    # the STC deny rules we contributed, so uninstall can strip exactly those
    # (not the user's own deny rules).
    stc_deny = (rr.json_patches.get("settings.json", {}).get("permissions", {}) or {}).get("_stc_deny") or []
    session_defaults = rr.json_patches.get("settings.json", {}).get("_stc_session_defaults") or {}
    manifest[target] = {
        "native_dir": native_dir,
        "files": list(rr.files.keys()),
        "json": list(rr.json_patches.keys()),
        "always_context": ac_file,
        "permissions_deny": stc_deny,
        "session_defaults": session_defaults,
    }
    json.dump(manifest, open(MANIFEST, "w", encoding="utf-8"), indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(prog="deploy.py", description="STC deploy orchestrator")
    sub = p.add_subparsers(dest="cmd", required=True)

    _target_help = ("one or more harness ids, comma-separated (e.g. claude or "
                    "claude,zcode); default: stc.yaml deploy.targets")
    pr = sub.add_parser("render", help="render into deploy/_rendered/ (no live writes)")
    pr.add_argument("--target", help=_target_help)
    pr.add_argument("--dry-run", action="store_true")
    pr.set_defaults(func=cmd_render)

    pa = sub.add_parser("apply", help="render + write to ~/.stc/ + native dir")
    pa.add_argument("--target", required=False, help=_target_help)
    pa.add_argument("--overwrite", action="store_true", help="back up + let STC take precedence on JSON collisions")
    pa.add_argument("--skip-collisions", action="store_true", help="keep user config; STC capability absent there")
    pa.set_defaults(func=cmd_apply)

    pu = sub.add_parser("uninstall", help="remove STC artifacts from one or more harnesses")
    pu.add_argument("--target", required=True, help=_target_help)
    pu.set_defaults(func=cmd_uninstall)

    pc = sub.add_parser("check", help="validate config without writing")
    pc.set_defaults(func=cmd_check)

    pst = sub.add_parser("restore", help="roll back JSON from a backup snapshot")
    pst.add_argument("backup_id")
    pst.set_defaults(func=cmd_restore)

    args = p.parse_args(argv)
    rc = args.func(args)
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
