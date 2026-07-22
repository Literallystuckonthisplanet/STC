#!/usr/bin/env python3
"""render.py — the 7-layer STC renderer (harness-neutral core → harness form).

Pure function: render_harness(stc, core_dir, provider, adapter) -> RenderResult.
It NEVER writes to disk — the orchestrator (deploy.py) owns the write step, so
render is testable in isolation and safe to dry-run.

The result is four things:
  files        — { native_relpath: text }    markdown/script artifacts to write
  json_patches — { "settings.json" | ".mcp.json" | "hooks.json": <dict> }  namespaces to merge
  toml_patches — { "config.toml": <str> }    STC-owned TOML tables to merge (add-only)
  marker       — { filepath: content }       the single @import block to inject
                                              into the user's always-context file
  manifest     — list of {path, kind, source} for uninstall + idempotent re-deploy

Non-destructive model (every artifact is collision-proof):
  - all markdown artifacts carry a `.stc.md` suffix (never touch user files)
  - hooks are `.stc.sh` scripts + a settings.json patch (merged, not overwritten)
  - the ONLY user-owned file touched is the always-context file, via ONE marker
    block pointing at the harness's always-context bundle (.stc.md)

Model composition: registry.yaml[agent].model_tier × core/models/<provider>.yaml
→ concrete model id. The harness does not pick the model; stc.yaml does.
"""

import os
import re
import shlex
import hashlib
import yaml

# The plugin identity for plugin-delivery harnesses (zcode). Versioned dir
# convention (cache/<marketplace>/<plugin>/<version>/) mirrors official plugins;
# "current" is NOT a version zcode recognises. Single source for paths + manifest.
# marketplace ≠ plugin name (official convention: "zcode-plugins-official"/
# "superpowers"); here the marketplace is the human-facing product name, the
# plugin is its machine id → "stc-core"/"stc" (not "stc"/"stc").
PLUGIN_MARKETPLACE = "stc-core"
PLUGIN_NAME = "stc"
PLUGIN_VERSION = "0.1.2"
PLUGIN_DIR = f"cli/plugins/cache/{PLUGIN_MARKETPLACE}/{PLUGIN_NAME}/{PLUGIN_VERSION}"

# The 13 render-time vars (ground truth from each hook's own header block).
# A hook declares which it needs under a "# Render-time vars (...)" comment;
# render substitutes exactly those tokens and leaves all other ${...} (script
# locals: SESSION, BROKEN, HITS, …) to bash. See _hook_declared_vars().
RENDER_VARS = {
    "CDP_PORT", "COMPACT_CMD", "DEPLOY_SCRIPT", "DEV_PORTS", "E2E_CLI_CMD",
    "HARNESS_DIR", "HARNESS_LIST", "MEMORY_DIR", "RELEASE_ACK_FILE",
    "SECRETS_ENV", "SESSION_ID", "STC_CORE", "USER_LANG", "USER_NAME", "DOCS_ROOT",
}


class RenderResult:
    def __init__(self):
        self.files = {}        # native_relpath -> text
        self.json_patches = {} # "<harness json file>" -> dict (to merge)
        self.toml_patches = {} # "config.toml" -> str (STC tables to merge, add-only)
        self.marker = {}       # abs filepath -> block content
        self.manifest = []     # {path, kind, source}


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def load_inputs(stc_path, core_dir, repo_dir):
    """Load stc.yaml + registry + return them (no provider yet — that is per-target).

    repo_dir is the STC repo root (for adapters/ + core/models/).
    Provider resolution moved to provider_for(stc, target, repo_dir) so each
    harness gets the right model ids (claude harness → Anthropic ids,
    zcode harness → GLM ids). Back-compat: models.provider remains the default
    when a target has no override.
    """
    stc = _load_yaml(stc_path)
    registry = _load_yaml(os.path.join(core_dir, "agents", "registry.yaml"))
    return stc, registry, None


def provider_for(stc, target, repo_dir):
    """Resolve the model provider YAML for a specific deploy target.

    stc.yaml may declare per-target overrides under models.<target>:
        models:
          provider: glm          # default (back-compat, used when no override)
          claude: claude         # Claude Code on Anthropic subscription → sonnet/haiku/opus
          zcode:   glm           # ZCode → glm-5.2/glm-5-turbo
    A harness speaks one model family: Claude Code on an Anthropic subscription
    cannot resolve glm-* ids (typed sub-agents with model: glm-5.2 silently fail
    to dispatch), and ZCode maps Anthropic names onto GLM ids. So the provider
    follows the harness, not a single global choice.
    """
    models = stc.get("models", {}) or {}
    # per-target override wins; fall back to the legacy global provider
    provider_name = models.get(target) or models.get("provider")
    if not provider_name:
        raise ValueError(
            f"stc.yaml: no model provider for target '{target}' "
            f"(set models.{target} or models.provider)"
        )
    provider_path = os.path.join(repo_dir, "core", "models", f"{provider_name}.yaml")
    if not os.path.exists(provider_path):
        raise FileNotFoundError(f"model provider not found: {provider_path}")
    return _load_yaml(provider_path)


def load_adapter(repo_dir, harness):
    path = os.path.join(repo_dir, "adapters", harness, "adapter.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"adapter not found: {path}")
    return _load_yaml(path)


# ---------------------------------------------------------------------------
# Var resolution
# ---------------------------------------------------------------------------

def resolve_vars(adapter, stc, provider):
    """Build the {VAR_NAME: value} map from adapter.vars + stc.yaml + provider.

    Adapter declares the harness-specific values (paths, commands); stc.yaml
    supplies user/workspace values; provider supplies nothing to hooks directly
    (model ids go into agent frontmatter, not hook vars).
    Expands ${HOME} and ${workspace.root}.
    """
    home = os.path.expanduser("~")
    ws_root = stc.get("workspace", {}).get("root", os.path.join(home, "projects"))
    ws_root = ws_root.replace("${HOME}", home)

    v = dict(adapter.get("vars", {}))
    # expand common env-style refs inside adapter var values
    for k, val in list(v.items()):
        if isinstance(val, str):
            v[k] = val.replace("${HOME}", home).replace("${workspace.root}", ws_root)

    # stc.yaml-sourced vars (override/complete adapter defaults)
    v["USER_LANG"] = stc.get("user", {}).get("language", "en")
    v["USER_NAME"] = stc.get("user", {}).get("name", "")
    v["DEV_PORTS"] = " ".join(str(p) for p in stc.get("workspace", {}).get("dev_ports", []))
    v["CDP_PORT"] = str(stc.get("mcp", {}).get("playwright", {}).get("cdp_port", "9222"))
    v["DOCS_ROOT"] = stc.get("doc_backend", {}).get("root", os.path.join(ws_root, ".stc-docs"))
    v["DOCS_ROOT"] = v["DOCS_ROOT"].replace("${workspace.root}", ws_root).replace("${HOME}", home)
    v["COMPACT_CMD"] = v.get("COMPACT_CMD", "/compact")
    v["E2E_CLI_CMD"] = stc.get("e2e_cli_cmd", "")
    v["USER_LANG"] = stc.get("user", {}).get("language", v.get("USER_LANG", "en"))
    # DEPLOY_SCRIPT — the path to deploy.py, for session-end infra re-apply.
    # Derived from STC_CORE (the shared core root): deploy.py is a sibling's
    # child at <repo>/deploy/deploy.py, i.e. ${STC_CORE}/../deploy/deploy.py.
    # Pre-2026-07-09 this was a phantom token the agent interpreted literally;
    # now it resolves to a real path.
    stc_core = v.get("STC_CORE", os.path.join(home, ".stc", "core"))
    v["DEPLOY_SCRIPT"] = os.path.join(os.path.dirname(stc_core), "deploy", "deploy.py")
    # HARNESS_LIST — comma-separated harness ids for `deploy.py apply --target`.
    # Defaults to this adapter's harness; a multi-harness deploy overrides it.
    if "HARNESS_LIST" not in v:
        v["HARNESS_LIST"] = adapter.get("harness", "claude,zcode")
    return v


# ---------------------------------------------------------------------------
# Hook rendering (the var-substitution core)
# ---------------------------------------------------------------------------

_DECL_BLOCK = re.compile(r"#\s*Render-time vars.*?\n((?:#\s*\$\{[\w]+\}.*\n?)+)", re.IGNORECASE)
_DECL_TOKEN = re.compile(r"\$\{(\w+)\}")


def _hook_declared_vars(hook_text):
    """The set of RENDER_VARS this hook declares in its header block.

    We intersect with RENDER_VARS so a hook can't trick us into substituting an
    arbitrary token; we only ever touch the 13 deploy-owned vars.
    """
    declared = set()
    for block in _DECL_BLOCK.findall(hook_text):
        for tok in _DECL_TOKEN.findall(block):
            if tok in RENDER_VARS:
                declared.add(tok)
    # Also substitute any in-body ${VAR} whose name is in RENDER_VARS — the
    # declaration block lists the vars; their use anywhere in the file is the
    # substitution site. (e.g. H06 declares MEMORY_DIR, uses it in the body.)
    return declared


def _substitute_vars(text, varmap, declared):
    """Replace ${VAR} with varmap[VAR] for each VAR in `declared`.

    Other ${...} tokens (script locals) are left intact for bash. Missing
    values are left as-is too (the hook's own default handles them).
    """
    def repl(m):
        name = m.group(1)
        if name in declared and name in varmap and varmap[name] != "":
            return str(varmap[name])
        return m.group(0)
    return re.sub(r"\$\{(\w+)\}", repl, text)


# Hooks whose body reads .tool_input.file_path / .tool_input.content and so
# needs the apply_patch normalize line on Codex (path lives in the patch text).
_APPLY_PATCH_HOOKS = {
    "block-dangerous-git.sh": False,   # reads .tool_input.command, not file_path
    "secret-scan-memory.sh": True,
    "dirty-tree-guard.sh": True,
    "memory-guard.sh": True,
    "read-first-router.sh": True,
    "integration-docs-gate.sh": True,
    "buy-vs-build-reminder.sh": True,
    "exit-plan-grill.sh": True,
}


def _inject_apply_patch_normalize(hook_text, fname):
    """Insert a `source _apply_patch_normalize.sh` line right after the hook's
    first `INPUT=$(cat)` so apply_patch's path-in-patch-text is surfaced as
    .tool_input.file_path before the body reads it. No-op if the hook doesn't
    read stdin, or already carries the line (idempotent re-render).
    """
    if not _APPLY_PATCH_HOOKS.get(fname):
        return hook_text
    marker = 'INPUT=$(cat)'
    inject = (
        f'{marker}\n'
        f'source "${{STC_NORMALIZE:-$NATIVE_DIR/hooks/_apply_patch_normalize.sh}}" 2>/dev/null || true'
    )
    if 'apply_patch_normalize' in hook_text:
        return hook_text  # already injected (idempotent)
    # replace only the FIRST occurrence (the stdin read); leave any later $(cat) alone
    return hook_text.replace(marker, inject, 1)


def _render_hooks(core_dir, adapter, varmap, result, native_hooks_dir):
    """Render the 16 hook scripts + the matcher wiring.

    Wiring shape depends on capability_delivery:
      - "files"    → a settings.json patch (merged under _stc_* tags, idempotent)
      - "plugin"   → a self-contained plugin hooks.json (one file per plugin),
                     using ${CLAUDE_PLUGIN_ROOT} (the harness-native placeholder),
                     PLUS a .zcode-plugin-seed.json + package.json so the harness
                     recognises STC as a plugin and loads the hooks.
    Hooks scripts always carry the .stc.sh suffix (collision-proof).
    """
    facts = adapter.get("harness_facts", {})
    delivery = facts.get("capability_delivery", "files")
    # the path prefix used inside hook commands. For plugins the harness
    # expands ${CLAUDE_PLUGIN_ROOT} → the plugin's own dir at load time.
    cmd_prefix = "${CLAUDE_PLUGIN_ROOT}/hooks" if delivery == "plugin" else "$NATIVE_DIR/hooks"

    hooks_layer = adapter.get("hooks", {})
    caps = hooks_layer.get("capabilities", {})
    wiring = {"hooks": {}}   # event → [{matcher, hooks:[{type,command}]}]

    for cap_name, cap in caps.items():
        if cap.get("supported") is False:
            continue  # inert on this harness
        fname = (cap.get("binding") or {}).get("file")
        if not fname:
            continue
        src = os.path.join(core_dir, "hooks", fname)
        if not os.path.exists(src):
            continue
        text = _read(src)
        declared = _hook_declared_vars(text)
        text = _substitute_vars(text, varmap, declared)
        # Codex apply_patch normalize: hooks that read .tool_input.file_path /
        # .tool_input.content get a source line injected after the first
        # `INPUT=$(cat)` so apply_patch's path-in-patch-text is surfaced as the
        # Claude-shape fields the body expects. Only when the adapter asks for it.
        if facts.get("apply_patch_normalize"):
            text = _inject_apply_patch_normalize(text, fname)
        out_name = re.sub(r"\.sh$", ".stc.sh", fname)
        rel = os.path.join(native_hooks_dir, out_name)
        result.files[rel] = text
        result.manifest.append({"path": rel, "kind": "hook", "source": f"core/hooks/{fname}"})

        matchers = cap.get("matcher", [])
        # the event bucket: an explicit `event:` on the cap wins (needed for
        # SessionStart/Stop/UserPromptSubmit, where matcher="*" carries no
        # event info); otherwise infer from the matcher tool-names.
        explicit_event = cap.get("event")
        events = [explicit_event] if explicit_event else _matcher_events(matchers)
        for ev in events:
            wiring["hooks"].setdefault(ev, []).append({
                "matcher": "|".join(matchers),
                "_stc_managed": True,          # tags this as STC-owned (idempotent
                "_stc_cap": cap_name,          #   update + uninstall strip)
                "hooks": [{"type": "command", "command": f"{cmd_prefix}/{out_name}"}],
            })

    if not wiring["hooks"]:
        return

    # when the adapter asks for apply_patch normalization, ship the shared
    # normalizer script alongside the hooks (it is sourced, not a registered hook).
    if facts.get("apply_patch_normalize"):
        norm_src = os.path.join(core_dir, "hooks", "_apply_patch_normalize.sh")
        if os.path.exists(norm_src):
            norm_rel = os.path.join(native_hooks_dir, "_apply_patch_normalize.stc.sh")
            result.files[norm_rel] = _substitute_vars(_read(norm_src), varmap, set())
            result.manifest.append({"path": norm_rel, "kind": "hook", "source": "core/hooks/_apply_patch_normalize.sh"})

    if delivery == "plugin":
        # self-contained hooks.json LIVES INSIDE the plugin dir; no merge needed.
        plugin_root = os.path.dirname(native_hooks_dir)  # .../stc/current
        # strip the _stc_* tags before emitting — they're a files-mode concern
        clean = {"hooks": {}}
        for ev, entries in wiring["hooks"].items():
            emitted = []
            for e in entries:
                ee = {k: v for k, v in e.items() if not k.startswith("_stc_")}
                # ZCode treats `matcher` as a raw RegExp (new RegExp(matcher));
                # Claude's "*" wildcard is an INVALID regex here ("Nothing to
                # repeat" → caught → hook silently dropped). Normalise the bare
                # "*" (the SessionStart/UserPromptSubmit/Stop wildcard) to ".*"
                # so event-hooks actually fire in the plugin-delivery harness.
                if ee.get("matcher") == "*":
                    ee["matcher"] = ".*"
                emitted.append(ee)
            clean["hooks"][ev] = emitted
        result.files[os.path.join(plugin_root, "hooks", "hooks.json")] = \
            _json_dump(clean)
        _render_plugin_meta(adapter, plugin_root, result)
    else:
        # target filename is harness-specific (claude: settings.json; codex: hooks.json)
        hook_target = facts.get("hook_config_file", "settings.json")
        result.json_patches[hook_target] = wiring


def _json_dump(obj):
    import json
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _render_plugin_meta(adapter, plugin_root, result):
    """Emit the plugin manifest files a plugin-delivery harness scans for.

    Three artifacts, matching the shape official plugins use (verified against
    document-skills / superpowers):
      .zcode-plugin/plugin.json  — the MANIFEST (name/version/description/...).
                                   This is what the harness reads to recognise
                                   and load the plugin; without it the plugin is
                                   invisible. seed.json alone is NOT enough.
      .zcode-plugin-seed.json    — discovery cache key (marketplace/plugin/
                                   version/source). `hash` is filled in by
                                   _finalize_plugin_seed() AFTER all files are
                                   rendered (it hashes the plugin tree).
      package.json               — conventional npm-shaped manifest.
    Capabilities are discovered by the harness scanning the plugin dir; the
    manifest only declares identity + where skills/hooks live.
    """
    harness = adapter.get("harness", "zcode")
    version = PLUGIN_VERSION
    seed = {
        # hash filled by _finalize_plugin_seed() (post-render); placeholder empty
        # keeps JSON shape stable so a later patch only touches one key.
        "hash": "",
        "marketplace": PLUGIN_MARKETPLACE,
        "plugin": PLUGIN_NAME,
        "pluginVersion": version,
        "source": "filesystem",
        "version": 1,
    }
    result.files[os.path.join(plugin_root, ".zcode-plugin-seed.json")] = _json_dump(seed)
    pkg = {
        "name": f"@{PLUGIN_NAME}/{harness}-plugin",
        "version": version,
        "private": True,
        "description": f"STC Core capabilities delivered as a {harness} plugin.",
    }
    result.files[os.path.join(plugin_root, "package.json")] = _json_dump(pkg)
    # THE manifest the harness actually reads. Mirrors official plugin.json shape.
    manifest = {
        "name": PLUGIN_NAME,
        "version": version,
        "description": "STC Core — Standard Template Construct: hooks, typed agents, skills, commands.",
        "author": {"name": "STC Core"},
        "license": "MIT",
        "skills": "skills",
        "hooks": "hooks",
        "agents": "agents",
        "commands": "commands",
    }
    result.files[os.path.join(plugin_root, ".zcode-plugin", "plugin.json")] = _json_dump(manifest)
    for kind, fname in [("plugin-manifest", ".zcode-plugin/plugin.json"),
                        ("plugin-seed", ".zcode-plugin-seed.json")]:
        result.manifest.append({"path": os.path.join(plugin_root, fname),
                                "kind": kind, "source": "generated"})


def _finalize_plugin_seed(result):
    """Stamp the content hash into the plugin seed (after all files rendered).

    The seed's `hash` mirrors official plugins: a digest over the plugin's file
    tree (sorted paths + content), so tampering or partial deploys are detected.
    Computed last because it depends on every rendered file being present.
    """
    seed_path = None
    plugin_prefix = f"{PLUGIN_DIR}/"
    plugin_files = []
    for rel in sorted(result.files):
        if rel.startswith(plugin_prefix) and ".zcode-plugin-seed.json" not in rel:
            plugin_files.append((rel, result.files[rel]))
        if rel.endswith(".zcode-plugin-seed.json"):
            seed_path = rel
    if not seed_path:
        return
    h = hashlib.sha256()
    for rel, content in plugin_files:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(content.encode("utf-8"))
        h.update(b"\0")
    import json
    seed = json.loads(result.files[seed_path])
    seed["hash"] = h.hexdigest()
    result.files[seed_path] = _json_dump(seed)


def _matcher_events(matchers):
    """Map adapter matcher strings to hook-event buckets for the patch.

    The adapter already declares the matcher on the right event; here we group
    by the event a command-matcher belongs to. PreToolUse covers Bash/Write/
    Task/WebSearch/mcp__*/EnterPlanMode; the special events are named directly.
    """
    pre_tools = {"Bash", "Write", "Edit", "MultiEdit", "Task", "Agent",
                 "WebSearch", "WebFetch", "Read", "Glob", "Grep", "EnterPlanMode"}
    events = set()
    for m in matchers:
        head = m.split("|")[0].split("(")[0]
        if head.startswith("mcp__") or head in pre_tools:
            events.add("PreToolUse")
        elif head == "UserPromptSubmit":
            events.add("UserPromptSubmit")
        elif head == "SessionStart":
            events.add("SessionStart")
        elif head == "SessionEnd":
            events.add("SessionEnd")
        elif head == "Stop":
            events.add("Stop")
        else:
            events.add("PreToolUse")
    return events


# ---------------------------------------------------------------------------
# Markdown layer renderers (all .stc.md)
# ---------------------------------------------------------------------------

def _model_id_for(registry, provider, agent_name):
    tier = registry["agents"].get(agent_name, {}).get("model_tier", "mid")
    tiers = provider.get("tiers", {})
    return tiers.get(tier, tiers.get("mid", ""))


def _frontmatter(d):
    """Serialise a frontmatter dict as a YAML block with --- fences."""
    body = yaml.safe_dump(d, sort_keys=False, allow_unicode=True, default_flow_style=False).strip()
    return f"---\n{body}\n---\n\n"


def _resolve_tools(tools, tool_map):
    """Expand neutral tool names to this harness's native tool ids.

    A name absent from tool_map passes through (the neutral name IS the native
    one — Read, Bash, ...). A name mapped to "*" cannot be bound statically
    (MCP server id assigned at connect time); "*" is returned as a sentinel and
    the caller then OMITS the `tools:` key, which is how a harness spells
    inherit-all. Note "*" is not a value: Claude Code reads `tools` as a list of
    literal names, so a literal "*" resolves to nothing and the agent refuses to
    spawn — the same zero-tools failure this map exists to prevent.
    """
    if not tools or not isinstance(tools, list):
        return tools
    resolved = []
    for t in tools:
        native = tool_map.get(t, t)
        if native == "*":
            return "*"
        resolved.extend(native if isinstance(native, list) else [native])
    return resolved


def _render_subagents(core_dir, registry, provider, adapter, result, native_agents_dir):
    caps = adapter.get("subagents", {}).get("capabilities", {})
    tool_map = adapter.get("subagents", {}).get("tool_map", {}) or {}
    facts = adapter.get("harness_facts", {})
    agent_format = facts.get("subagent_format", "markdown")  # "markdown" | "toml"
    for name, cap in caps.items():
        sup = cap.get("supported")
        if sup is False:
            continue  # inert (e.g. harness-docs on zcode)

        binding = cap.get("binding", {}) or {}
        tier = binding.get("model_tier")
        model_id = ""
        if tier and provider.get("tiers"):
            model_id = provider["tiers"].get(tier, "")
        tools = _resolve_tools(binding.get("tools"), tool_map)
        dispatch = registry["agents"].get(name, {}).get("dispatches", cap.get("native", ""))

        if sup is True or sup == "true":
            # native typed agent file: generate frontmatter + body from core/
            src = os.path.join(core_dir, "agents", f"{name}.md")
            body = _read(src) if os.path.exists(src) else f"# {name}\n"

            if agent_format == "toml":
                # Codex ~/.codex/agents/*.toml: name/description/developer_instructions.
                # No `tools` field (Codex TOML schema has none — tool access is via
                # sandbox_mode, not a tools list). model omitted → inherits parent.
                # model_reasoning_effort optional; emit when the provider maps a tier.
                toml_lines = [
                    f'name = {_toml_quote(name)}',
                    f'description = {_toml_quote(dispatch)}',
                ]
                effort_tier = registry["agents"].get(name, {}).get("effort_tier")
                if effort_tier:
                    toml_lines.append(
                        f'model_reasoning_effort = {_toml_quote({"low": "low", "mid": "medium", "high": "high"}[effort_tier])}')
                toml_lines.append(f'developer_instructions = {_toml_quote(body.rstrip())}')
                rel = os.path.join(native_agents_dir, f"{name}.stc.toml")
                result.files[rel] = "\n".join(toml_lines) + "\n"
                result.manifest.append({"path": rel, "kind": "agent", "source": f"core/agents/{name}.md"})
                continue

            fm = {"name": name, "description": dispatch}
            if model_id:
                fm["model"] = model_id
            # effort_tier (registry, neutral low|mid|high) → harness knob
            # `effort:` (per-agent reasoning effort; unknown fields are
            # ignored by harnesses without the knob)
            effort_tier = registry["agents"].get(name, {}).get("effort_tier")
            if effort_tier:
                fm["effort"] = {"low": "low", "mid": "medium", "high": "high"}[effort_tier]
            # tools == "*" → inherit-all: OMIT the key (no harness spells this
            # as a value). Anything the agent must NOT get goes in the binding's
            # disallowed_tools, which is how least-privilege survives inherit-all.
            if isinstance(tools, list) and tools:
                fm["tools"] = ", ".join(tools)
            elif tools == "*":
                denied = binding.get("disallowed_tools")
                if denied:
                    fm["disallowedTools"] = ", ".join(denied)
            rel = os.path.join(native_agents_dir, f"{name}.stc.md")
            result.files[rel] = _frontmatter(fm) + body.rstrip() + "\n"
            result.manifest.append({"path": rel, "kind": "agent", "source": f"core/agents/{name}.md"})
        else:
            # degrade: dispatch-instruction .stc.md (skill + general-purpose)
            skill = binding.get("skill_link")
            note = cap.get("fallback", "")
            lines = [
                f"---",
                f"name: {name}",
                f"description: {dispatch}",
                f"---",
                f"",
                f"# {name} (degraded dispatch on {adapter.get('harness', 'this harness')})",
                f"",
                f"This STC agent has no native typed form here; it runs as a "
                f"`general-purpose` dispatch carrying the methodology skill.",
                f"",
            ]
            if skill:
                lines.append(f"**Load skill:** `{skill}` (core/skills/{skill}/SKILL.md).")
            lines.append("")
            lines.append(f"**Resolution:** {note}")
            lines.append("")
            rel = os.path.join(native_agents_dir, f"{name}.stc.md")
            result.files[rel] = "\n".join(lines)
            result.manifest.append({"path": rel, "kind": "agent-degrade", "source": f"core/agents/{name}.md"})


def _render_commands(core_dir, adapter, varmap, result, native_commands_dir):
    caps = adapter.get("commands", {}).get("capabilities", {})
    for name, cap in caps.items():
        if cap.get("supported") is False:
            continue
        binding = cap.get("binding") or {}
        # source path is relative to repo root (e.g. "core/commands/grill-me.md");
        # the capability key `name` is the command's slash-id and now matches the
        # source filename convention (both use hyphens) — no underscore rewrite.
        source = binding.get("source") or f"core/commands/{name}.md"
        src = os.path.join(os.path.dirname(core_dir), source) if not os.path.isabs(source) else source
        if not os.path.exists(src):
            continue
        # Commands use deploy-owned ${VAR} tokens inline (e.g. ${DOCS_ROOT} in
        # to-spec/to-tasks) without a hook-style declaration block — substitute
        # every RENDER_VARS token found in the body. Non-deploy ${...} stays.
        body = _substitute_vars(_read(src), varmap, RENDER_VARS)
        rel = os.path.join(native_commands_dir, f"{name}.stc.md")
        result.files[rel] = body
        result.manifest.append({"path": rel, "kind": "command", "source": source})


def _render_skills(core_dir, adapter, varmap, result, native_skills_dir):
    caps = adapter.get("skills", {}).get("capabilities", {})
    # Every skill loader (plugin AND loose files in ~/.claude/skills/)
    # enumerates skills expecting exactly SKILL.md — any other filename makes
    # the skill invisible. The skill is already namespaced by its skills/<name>/
    # directory, so the .stc collision-proof suffix is unnecessary here (and
    # was the bug that hid all 15 skills from the claude harness, 2026-07-11).
    skill_file = "SKILL.md"
    for name, cap in caps.items():
        if cap.get("supported") is False:
            continue
        skill_dir = os.path.join(core_dir, "skills", name)
        skillmd = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skillmd):
            continue
        # same inline-token substitution as commands (e.g. ${E2E_CLI_CMD},
        # ${CDP_PORT} in the e2e skill)
        body = _substitute_vars(_read(skillmd), varmap, RENDER_VARS)
        rel = os.path.join(native_skills_dir, name, skill_file)
        result.files[rel] = body
        result.manifest.append({"path": rel, "kind": "skill", "source": f"core/skills/{name}/SKILL.md"})


def _render_always_context(core_dir, adapter, result, native_dir, harness):
    """Generate the always-context .stc.md bundle with INLINE rule content.

    Rule delivery is per-harness (harness_facts.rules_delivery):
      - "hook" (claude): the bundle is a POINTER. Hook H06
        (session-start-context) injects the 3 firing rules on SessionStart —
        native and verified live. Inlining them here too would deliver every
        rule twice (~20KB duplicate per session).
      - "inline" (zcode) — WORKAROUND (2026-07-08): this ZCode build registers
        plugin hooks but does not fire them, so H06 never reaches the model;
        the rules are inlined into the bundle instead. H06 stays wired as the
        future mechanism.
        TODO(harness-bugfix): flip to "hook" when plugin hooks fire.

    The user profile is inlined for BOTH: it must be always-context and no
    hook injects it, so inlining never duplicates.
    """
    facts = adapter.get("harness_facts", {})
    rules_delivery = facts.get("rules_delivery", "inline")
    ac_file = facts.get("always_context_file", "CLAUDE.md")  # CLAUDE.md | AGENTS.md
    bundle_name = re.sub(r"\.md$", ".stc.md", ac_file)
    bundle_rel = bundle_name  # at native dir root, like the user file

    lines = [
        f"# STC always-context ({harness})",
        f"",
        f"Managed by `deploy.py`. Do not edit — regenerate with "
        f"`deploy.py render --target {harness}`.",
        f"",
        f"## Always-context rules (firing rules — apply in the moment)",
        f"",
    ]

    rule_files = (("behavior", "rules/behavior.md"),
                  ("pev",      "rules/pev.md"),
                  ("session",  "rules/session.md"))

    if rules_delivery == "hook":
        # Pointer: H06 injects these on session start; the bundle only names
        # them so the agent can fall back to a manual read if the hook did
        # not fire.
        lines.append("Hook H06 (`session-start-context`) injects these rule "
                     "files into context on startup/compact/clear — they "
                     "should already be present:")
        lines.append("")
        for label, rel in rule_files:
            lines.append(f"- `~/.stc/core/{rel}`")
        lines.extend([
            "- `~/.stc/core/rules/project_docs.md` — lazy (read by anchor "
            "`[[project-docs]]` when writing ADRs/specs)",
            "",
            "If any are MISSING (hook did not fire) — read them manually as "
            "a fallback before acting.",
            "",
        ])
    else:
        # Inline the 3 firing rules (behavior/pev/session). project_docs
        # stays lazy (read by anchor [[project-docs]] when writing ADRs/specs).
        for label, rel in rule_files:
            rule_path = os.path.join(core_dir, rel)
            body = _read(rule_path).strip() if os.path.exists(rule_path) else ""
            if body:
                lines.append(f"<details><summary><code>{label}.md</code></summary>")
                lines.append("")
                lines.append(body)
                lines.append("")
                lines.append("</details>")
                lines.append("")

    # Inline the user profile. The profile is private per-user data that lives
    # OUTSIDE core/ (it is never deployed to ~/.stc/ — the deployer copies only
    # core/). But its CONTENT is safe (no secrets — the file's own guard forbids
    # them; values are referenced by env-var NAME only) and is rendered into the
    # always-context bundle so the agent knows the user without lazy reads.
    # Cross-user: each user renders their own user/profile.md. Cross-harness:
    # the inline lands in both CLAUDE.stc.md and AGENTS.stc.md.
    profile_path = os.path.join(os.path.dirname(core_dir), "user", "profile.md")
    profile_body = _read(profile_path).strip() if os.path.exists(profile_path) else ""
    if profile_body:
        lines.append(f"<details><summary><code>profile.md</code></summary>")
        lines.append("")
        lines.append(profile_body)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.extend([
        f"## Lazy memory (read on demand, not at start)",
        f"",
        f"- `~/.stc/core/memory/MEMORY.md` — the index/map. Read it when you "
        f"need the catalog of references; wiki-links `[[name]]` point at the "
        f"detail files (playbook, code-standard, reference-*, project-docs).",
        f"- `~/.stc/core/user/` — personal memory (feedback_*, "
        f"projects/<name>.md). Read by anchor when a rule references "
        f"`[[user-profile]]` or a `[[project-*]]` link. The profile itself is "
        f"inlined above (always-context), not lazy.",
        f"",
    ])

    result.files[bundle_rel] = "\n".join(lines)
    result.manifest.append({"path": bundle_rel, "kind": "always-context",
                            "source": ("h06-pointer+inline-profile" if rules_delivery == "hook"
                                       else "inline-rules+inline-profile")})

    # the single marker block injected into the USER's always-context file.
    result.marker[ac_file] = f"@{_native_root(adapter, bundle_name)}"


def _native_root(adapter, rel):
    """The marker points at the always-context bundle inside the native dir.
    Uses $NATIVE_DIR placeholder, resolved by the orchestrator at write time
    (so render stays disk-agnostic and testable)."""
    return f"$NATIVE_DIR/{rel}"


# MCP capability → how to build its server block. `command` may come from the
# adapter binding directly (npx servers) OR from an env-var-holding-the-binary
# (graphify: command_env: GRAPHIFY_CLI means "the binary path is in $GRAPHIFY_CLI").
_MCP_COMMAND_ENV = {
    # name → (env_var_name, fallback_binary)
    "graphify": ("GRAPHIFY_CLI", "graphify"),
}


def _render_mcp(adapter, stc, result):
    """Generate the .mcp.json patch with stc-* namespaced server names.

    Each server is a valid stdio mcpServer: `command` is the single binary,
    flags live in `args[]`. Claude Code (and the MCP stdio spec) launch the
    binary named by `command` and pass `args` to it — a space-bearing command
    string ("npx -y foo") would be treated as a single filename and fail.
    For binary-backed tools (graphify), the command is the env-var holding the
    binary path, expanded by the harness at launch — we emit the shell-style
    expansion so the harness resolves it. Secrets pass as env-var NAMES only.
    """
    caps = adapter.get("mcp", {}).get("capabilities", {})
    mcp_cfg = stc.get("mcp", {})
    servers = {}
    for name, cap in caps.items():
        if cap.get("supported") is False:
            continue
        enabled = mcp_cfg.get(name, {}).get("enabled", False)
        if not enabled:
            continue
        binding = cap.get("binding", {}) or {}
        srv = {"type": "stdio"}

        # 1. command — mandatory. Split a binding.command string into the
        #    binary + args[] (MCP stdio launches `command` and feeds it `args`).
        #    graphify is the exception: its binary path comes from an env var.
        args = []
        if "command" in binding:
            parts = shlex.split(binding["command"])
            srv["command"] = parts[0]
            args.extend(parts[1:])
        elif name in _MCP_COMMAND_ENV:
            env_var, fallback = _MCP_COMMAND_ENV[name]
            srv["command"] = "${" + env_var + ":-" + fallback + "}"
        else:
            # No command derivable → skip; precheck should have caught this,
            # but never emit a server that can't launch.
            continue

        # 2. secrets/keys by env-var NAME, never inline values.
        cfg = mcp_cfg.get(name, {})
        for k, val in cfg.items():
            if k.endswith("_env") and val:
                srv.setdefault("env", {})[val] = f"${{{val}}}"
            elif name == "playwright" and k == "output_dir" and val:
                # @playwright/mcp takes these as CLI flags, NOT env vars.
                args.extend(["--output-dir", str(val)])
            elif name == "playwright" and k == "cdp_port" and val:
                # playwright connects to an already-launched browser via CDP.
                args.extend(["--cdp-endpoint", f"http://localhost:{val}"])
            # command_env is consumed above (command derivation), not emitted

        if args:
            srv["args"] = args

        servers[f"stc-{name}"] = srv
    if not servers:
        return
    mcp_target = adapter.get("harness_facts", {}).get("mcp_config_file", ".mcp.json")
    delivery = adapter.get("harness_facts", {}).get("capability_delivery", "files")
    if delivery == "plugin":
        # plugin-provided MCP lives INSIDE the plugin root (.mcp.json), namespaced
        # by the harness as plugin:<plugin>:<server>. Template vars (${...}) expand
        # ONLY for plugin-provided servers (config-file servers do not), so plugin
        # delivery is also the only place secrets-via-env-var works at all. Putting
        # this in result.files (not json_patches) keeps it out of the harness-global
        # ~/.<native>/.mcp.json merge path — which is the Claude files-delivery form.
        result.files[os.path.join(PLUGIN_DIR, ".mcp.json")] = \
            _json_dump({"mcpServers": servers})
    elif mcp_target.endswith(".toml"):
        # Codex config.toml: emit STC's [mcp_servers.stc-*] tables as TOML text.
        # add-only merge (tomllib-detect + raw append) happens in deploy.py.
        result.toml_patches[mcp_target] = _render_mcp_toml(servers)
    else:
        result.json_patches[mcp_target] = {"mcpServers": servers}


def _toml_quote(s):
    """Quote a TOML basic string, escaping backslashes and double quotes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_array(items):
    """Render a TOML array of strings (inline, like Codex config.toml uses)."""
    return "[" + ", ".join(_toml_quote(str(i)) for i in items) + "]"


def _render_mcp_toml(servers):
    """Render STC's [mcp_servers.stc-*] tables as TOML text for Codex config.toml.

    Mirrors the JSON shape _render_mcp builds: namespaced stc- names, command +
    args[] split, secrets by env-var NAME. Codex is stdio-only (no `url` key —
    lesson from ECC issue #2224). The output is a sequence of self-contained
    [table] blocks appended at end-of-file by the add-only merge.
    """
    blocks = []
    for name, srv in sorted(servers.items()):
        lines = [f"[mcp_servers.{name}]"]
        lines.append(f"command = {_toml_quote(srv.get('command', ''))}")
        args = srv.get("args") or []
        if args:
            lines.append(f"args = {_toml_array(args)}")
        env = srv.get("env") or {}
        if env:
            # env is a TOML sub-table: header first, then one key = value per line.
            lines.append(f"[mcp_servers.{name}.env]")
            for k, v in sorted(env.items()):
                lines.append(f"{k} = {_toml_quote(str(v))}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _render_permissions(adapter, result):
    """Render the static permissions.deny block into the settings.json patch.

    Defense-in-depth on READ (the secret-scan hook H05 guards on WRITE). Only
    emitted when the adapter declares a non-empty deny list AND has a native
    permissions engine (permissions.native != false). A harness without a
    native deny layer (e.g. ZCode) enforces the SAME rules via a hook
    (H17_secret_read_guard) instead — emitting them here would create a dead
    settings.json that the harness never reads.
    """
    perms = adapter.get("permissions", {}) or {}
    if perms.get("native") is False:
        return  # hook-delivered (H17), not a settings.json block
    deny = perms.get("deny") or []
    if not deny:
        return
    result.json_patches.setdefault("settings.json", {})
    result.json_patches["settings.json"].setdefault("permissions", {})
    # merge under a stable key the harness recognises; tag for idempotent update
    result.json_patches["settings.json"]["permissions"]["_stc_deny"] = deny


def _render_session_defaults(adapter, stc, result):
    """Render deploy.session_defaults into the settings.json patch (FR-28).

    The orchestrator process assumes every session starts in plan mode on the
    expensive model: plan + orchestrate in main, execute in cheap sub-agents.
    Before FR-28 these two keys lived only as hand-edits in settings.json —
    invisible to deploy, silently lost on a reinstall. Gated the same way as
    _render_permissions: a harness without a native permissions engine has no
    settings.json for these keys to live in.
    """
    sd = (stc.get("deploy", {}) or {}).get("session_defaults") or {}
    if not sd:
        return
    perms = adapter.get("permissions", {}) or {}
    if perms.get("native") is False:
        return
    patch = {}
    if sd.get("default_mode"):
        patch["defaultMode"] = sd["default_mode"]
    if sd.get("model"):
        patch["model"] = sd["model"]
    if not patch:
        return
    result.json_patches.setdefault("settings.json", {})
    result.json_patches["settings.json"]["_stc_session_defaults"] = patch


def _render_glue(repo_dir, adapter, result):
    facts = adapter.get("harness_facts", {})
    sl = facts.get("statusline", {})
    if not sl.get("enabled"):
        return
    src = os.path.join(repo_dir, "adapters", adapter.get("harness", ""), "statusline.sh")
    if os.path.exists(src):
        body = _read(src)
        rel = "statusline.stc.sh"
        result.files[rel] = body
        result.manifest.append({"path": rel, "kind": "glue", "source": f"adapters/{adapter.get('harness')}/statusline.sh"})
        # statusLine is a single-key settings entry → note as a collision candidate
        result.json_patches.setdefault("settings.json", {})
        result.json_patches["settings.json"]["_stc_statusline"] = rel


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def render_harness(stc, registry, provider, adapter, core_dir, repo_dir):
    """Render one harness. Returns a populated RenderResult (no disk writes)."""
    harness = adapter.get("harness", "unknown")
    native_dir = adapter.get("native_dir", os.path.join(os.path.expanduser("~"), f".{harness}"))
    facts = adapter.get("harness_facts", {})
    delivery = facts.get("capability_delivery", "files")
    # where rendered artifacts land inside the native dir
    if delivery == "plugin":
        hooks_dir = f"{PLUGIN_DIR}/hooks"
        agents_dir = f"{PLUGIN_DIR}/agents"
        commands_dir = f"{PLUGIN_DIR}/commands"
        skills_dir = f"{PLUGIN_DIR}/skills"
    else:
        hooks_dir = "hooks"
        agents_dir = "agents"
        commands_dir = "commands"
        # skills may live outside native_dir on some harnesses (Codex global
        # skills path = ~/.agents/skills). The adapter's skills.native_path, when
        # absolute (starts with ~ or $HOME), overrides the default native_dir/skills.
        skills_native = (adapter.get("skills", {}) or {}).get("native_path", "")
        if skills_native and (skills_native.startswith("~") or skills_native.startswith("$")):
            skills_dir = os.path.expandvars(os.path.expanduser(skills_native))
        else:
            skills_dir = "skills"

    varmap = resolve_vars(adapter, stc, provider)
    result = RenderResult()

    _render_always_context(core_dir, adapter, result, native_dir, harness)
    _render_hooks(core_dir, adapter, varmap, result, hooks_dir)
    _render_commands(core_dir, adapter, varmap, result, commands_dir)
    _render_subagents(core_dir, registry, provider, adapter, result, agents_dir)
    _render_skills(core_dir, adapter, varmap, result, skills_dir)
    _render_mcp(adapter, stc, result)
    _render_permissions(adapter, result)
    _render_session_defaults(adapter, stc, result)
    _render_glue(repo_dir, adapter, result)

    # plugin-delivery: stamp the content hash into the seed now that all files
    # (hooks/agents/skills/commands/manifest) have been rendered into the tree.
    if delivery == "plugin":
        _finalize_plugin_seed(result)

    return result
