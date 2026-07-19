#!/usr/bin/env python3
"""checks.py — compat, collision-detection, backup, and onboarding for deploy.py.

Non-destructive policy:
  - MD collisions cannot happen (all STC markdown is *.stc.md — unique suffix).
  - settings.json / .mcp.json CAN collide (user already has hooks on the same
    matcher, or an mcpServer with the same name). deploy REFUSES by default and
    prints a precise report; resolution only via --overwrite / --skip-collisions.
  - A backup snapshot of every JSON touched is taken BEFORE any write, so
    `deploy.py restore <id>` rolls back exactly.

Hooks for the STC namespace prefix `stc-`: re-deploy is idempotent because we
key our own JSON entries by that prefix and update-in-place.
"""

import json
import os
import re
import shutil
import subprocess
import time


class Collision:
    def __init__(self, kind, file, detail):
        self.kind = kind        # "matcher" | "mcp-name" | "statusline"
        self.file = file
        self.detail = detail

    def __str__(self):
        return f"[{self.kind}] {self.file}: {self.detail}"


# ---------------------------------------------------------------------------
# precheck — does the configuration even make sense?
# ---------------------------------------------------------------------------

def precheck(stc, registry, provider, adapters, core_dir):
    """Return a list of error strings (empty = ok)."""
    errs = []
    if not stc:
        errs.append("stc.yaml is empty or missing.")
        return errs

    # Model providers are per-target now (a harness speaks one model family).
    # Validate the default AND each target's override. The default
    # (models.provider) is back-compat and the fallback when a target has none.
    models = stc.get("models", {}) or {}
    default_provider = models.get("provider")
    if not default_provider:
        errs.append("stc.yaml: models.provider (default) is required.")
    else:
        pfile = os.path.join(os.path.dirname(core_dir), "core", "models", f"{default_provider}.yaml")
        if not os.path.exists(pfile):
            errs.append(f"models.provider '{default_provider}': no core/models/{default_provider}.yaml.")

    targets = stc.get("deploy", {}).get("targets", [])
    if not targets:
        errs.append("stc.yaml: deploy.targets is empty.")
    for t in targets:
        if t not in adapters:
            errs.append(f"deploy.targets '{t}': no adapters/{t}/adapter.yaml.")
            continue
        # a per-target provider override (models.<target>) must resolve to a real file
        override = models.get(t)
        if override:
            pfile = os.path.join(os.path.dirname(core_dir), "core", "models", f"{override}.yaml")
            if not os.path.exists(pfile):
                errs.append(f"models.{t} '{override}': no core/models/{override}.yaml.")
        # a Claude Code target must NOT resolve to the glm provider: glm-* model
        # ids make claude typed sub-agents silently fail to dispatch (the danger
        # behind the glm-authoring default-provider leak, 2026-07-11). Resolved
        # provider = models.<target> override, else the models.provider default.
        resolved = override or default_provider
        harness = (adapters[t].get("harness") or t)
        if harness == "claude" and resolved == "glm":
            errs.append(
                f"target '{t}' (claude harness) resolves to the glm provider "
                f"(models.{t if override else 'provider'}='glm') — glm-* ids make "
                f"claude typed sub-agents silently fail; use provider 'claude'.")

    # REQUIRED capabilities must be available. playwright is an MCP server by
    # nature (browser automation over stdio) → must be mcp.playwright.enabled.
    # graphify is a SKILL + standalone CLI by design (safishamsi/graphify docs:
    # installed as a skill, runs headless via its own backend; MCP is an optional
    # extra). STC wraps it in core/skills/code-graph/, so graphify is satisfied
    # EITHER by an enabled mcp.graphify entry OR by the CLI being on PATH /
    # named in the GRAPHIFY_CLI env var. Do not force the MCP form.
    mcp = stc.get("mcp", {})
    if not mcp.get("playwright", {}).get("enabled"):
        errs.append("mcp.playwright: REQUIRED capability is not enabled:true.")
    if not mcp.get("graphify", {}).get("enabled"):
        import shutil
        cli = os.environ.get("GRAPHIFY_CLI", "")
        if not (cli or shutil.which("graphify")):
            errs.append(
                "graphify: REQUIRED capability not satisfied — neither "
                "mcp.graphify.enabled:true nor a graphify CLI on PATH/GRAPHIFY_CLI."
            )

    # required skill must exist in core
    code_graph = os.path.join(core_dir, "skills", "code-graph", "SKILL.md")
    if not os.path.exists(code_graph):
        errs.append("required skill core/skills/code-graph/SKILL.md missing.")

    # every provider that will actually be rendered (default + per-target overrides)
    # must declare a tiers map. provider passed in is the legacy single-provider
    # value (may be None now); the per-target YAMLs are loaded by render.py.
    import yaml as _yaml
    models = stc.get("models", {}) or {}
    providers_to_check = {}
    if models.get("provider"):
        providers_to_check["default"] = models["provider"]
    for t in targets:
        if models.get(t):
            providers_to_check[t] = models[t]
    for label, pname in providers_to_check.items():
        pfile = os.path.join(os.path.dirname(core_dir), "core", "models", f"{pname}.yaml")
        if os.path.exists(pfile):
            try:
                pdata = _yaml.safe_load(open(pfile, encoding="utf-8")) or {}
                if not pdata.get("tiers"):
                    errs.append(f"models provider '{pname}' ({label}): no tiers map.")
            except Exception:
                errs.append(f"models provider '{pname}' ({label}): unreadable YAML.")

    errs += _naming_consistency(core_dir, adapters)
    errs += _mcp_validity(stc, adapters)
    errs += _subagent_consistency(core_dir, registry, adapters)
    errs += _reference_integrity(core_dir)
    errs += _no_personal_data_in_core(core_dir)
    return errs


def _no_personal_data_in_core(core_dir):
    """Public-leak guard (2026-07-11): core/ is PUBLISHED (the public half of
    STC). Personal/project memory belongs in user/ (gitignored), never here.
    This fails fast if a high-signal personal marker reaches core/ — the merge
    of migration-debris memory into STC is the moment this can slip. Scans
    core/**/*.{md,sh,yaml,yml} for real email addresses, public IPv4s, and
    private-key headers. Deliberately narrow (near-zero false positives on
    generic rule prose); it is a tripwire, not a full DLP scan.

    NOTE: git history is hard to scrub — this runs BEFORE commit/push. Do not
    weaken it to silence a hit; move the offending content to user/ instead."""
    import glob
    import re
    errs = []
    email_re = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.I)
    ipv4_re = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
    key_re = re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")
    # API-key / token formats (minimum lengths so placeholders like `sk-...`,
    # `ghp_...`, `${TOKEN}` do not trip it — only a real key's length matches).
    # Mirrors the proven patterns in core/hooks/secret-scan-memory.sh; core/ is
    # public so a real key pasted into a doc example must fail the deploy.
    token_res = [
        (re.compile(r"\bghp_[A-Za-z0-9]{36}\b"), "GitHub PAT"),
        (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"), "GitHub fine-grained PAT"),
        (re.compile(r"\bntn_[A-Za-z0-9]{40,}\b"), "Notion token"),
        (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}\b"), "Anthropic API key"),
        (re.compile(r"\bsk-[A-Za-z0-9]{40,}\b"), "sk-prefixed vendor key"),
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
        (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"), "Slack token"),
        (re.compile(r"\bre_[A-Za-z0-9]{30,}\b"), "Resend API key"),
    ]
    # placeholder / doc emails that are fine to appear in generic prose
    email_allow = ("example.com", "example.org", "you@", "user@", "name@")

    def _public_ip(m):
        a, b = int(m.group(1)), int(m.group(2))
        if not (0 <= a <= 255 and 0 <= b <= 255):
            return False
        if a in (0, 10, 127):
            return False
        if a == 192 and b == 168:
            return False
        if a == 172 and 16 <= b <= 31:
            return False
        if a == 169 and b == 254:
            return False
        if a == 255 or a >= 224:              # broadcast / multicast / reserved
            return False
        return True

    for pat in ("**/*.md", "**/*.sh", "**/*.yaml", "**/*.yml"):
        for f in glob.glob(os.path.join(core_dir, pat), recursive=True):
            rel = os.path.relpath(f, os.path.dirname(core_dir))
            text = open(f, encoding="utf-8").read()
            for em in set(email_re.findall(text)):
                if not any(a in em.lower() for a in email_allow):
                    errs.append(f"{rel}: real email '{em}' in public core/ — move to user/.")
            for m in ipv4_re.finditer(text):
                if _public_ip(m):
                    errs.append(f"{rel}: public IP '{m.group(0)}' in public core/ — move to user/.")
            if key_re.search(text):
                errs.append(f"{rel}: private-key material in public core/ — move to user/.")
            for tok_re, label in token_res:
                if tok_re.search(text):
                    errs.append(f"{rel}: {label} in public core/ — move to user/ and rotate it.")
    return errs


def _reference_integrity(core_dir):
    """Dangling-reference guard (migration-loss class, 2026-07-11).

    The STC migration lost rules whose anchors then pointed at nothing — a
    silent failure: the reference just does nothing, no error surfaces. This
    check fails fast on the three shapes that broke:
      1. every skill dir carries an exactly-named SKILL.md (the loader ignores
         any other name — the bug that hid all 15 skills);
      2. every H<NN> hook code cited in core/rules/*.md is declared by some
         core/hooks/*.sh header;
      3. every [[wikilink]] in core/rules/*.md resolves to a core memory/rules
         file (hyphen/underscore-insensitive). Piped display aliases
         ([[target|shown]]) and template placeholders ([[project_<name>]]) are
         handled — the latter never matches (it contains '<').
    Returns a list of error strings (empty = ok)."""
    import glob
    import re
    errs = []

    # 1. skill dir → SKILL.md present
    for sd in sorted(glob.glob(os.path.join(core_dir, "skills", "*"))):
        if os.path.isdir(sd) and not os.path.exists(os.path.join(sd, "SKILL.md")):
            errs.append(
                f"skills/{os.path.basename(sd)}: missing SKILL.md "
                f"(the loader requires exactly SKILL.md).")

    # 2. hook codes declared by some hook header ("# H<NN> — hook: ...")
    declared = set()
    for h in glob.glob(os.path.join(core_dir, "hooks", "*.sh")):
        with open(h, encoding="utf-8") as f:
            for m in re.findall(r"#\s*(H\d{2})\b", f.read(2000)):
                declared.add(m)

    # 3. resolvable wikilink targets = memory + rules file stems, normalized
    def _norm(s):
        return s.replace("-", "_").lower()

    resolvable = set()
    for d in ("memory", "rules"):
        for f in glob.glob(os.path.join(core_dir, d, "*.md")):
            resolvable.add(_norm(os.path.splitext(os.path.basename(f))[0]))

    for rf in sorted(glob.glob(os.path.join(core_dir, "rules", "*.md"))):
        name = os.path.basename(rf)
        text = open(rf, encoding="utf-8").read()
        for code in sorted(set(re.findall(r"\b(H\d{2})\b", text))):
            if code not in declared:
                errs.append(
                    f"rules/{name}: cites hook {code} but no core/hooks/*.sh "
                    f"declares it.")
        for tgt in sorted(set(re.findall(r"\[\[([a-z0-9_-]+)(?:\||\]\])", text))):
            if _norm(tgt) not in resolvable:
                errs.append(
                    f"rules/{name}: wikilink [[{tgt}]] resolves to no core "
                    f"memory/rules file.")
    return errs


def _naming_consistency(core_dir, adapters):
    """Commands must be hyphen-named (the deploy bug that left both grill-me
    and grill_me coexisting after the underscore→hyphen rename). Catch it at
    the source so the duplicate-file condition can't recur on next deploy.
    """
    errs = []
    cmds_dir = os.path.join(core_dir, "commands")
    if not os.path.isdir(cmds_dir):
        return errs
    for f in os.listdir(cmds_dir):
        if f.endswith(".md") and "_" in f[:-3]:
            errs.append(
                f"core/commands/{f}: underscore in name — use hyphens "
                f"(e.g. grill-me.md, not grill_me.md). The deploy renders "
                f"<name>.stc.md and does NOT clean up the old underscore file."
            )
    return errs


def _mcp_validity(stc, adapters):
    """Every enabled MCP server must declare what to run it. npx-style servers
    carry a command/token_env in the adapter binding; standalone tools like
    graphify resolve via CLI env. A server that is enabled but has neither is
    a config gap that renders as an empty server block (silently broken MCP).
    """
    errs = []
    mcp = stc.get("mcp", {}) or {}
    # servers whose command is built by _render_mcp (npx + fixed package) — they
    # don't carry a `command` key in stc.yaml, only tunables (cdp_port, env).
    # Listing them here means "command is known, don't flag as missing".
    BUILTIN_COMMAND = {"playwright", "github", "gsheets", "context7"}
    standalone_ok = bool(os.environ.get("GRAPHIFY_CLI") or shutil.which("graphify"))
    for name, cfg in mcp.items():
        if not cfg or not cfg.get("enabled"):
            continue
        has_cmd = bool(cfg.get("command"))
        has_env = bool(cfg.get("token_env") or cfg.get("api_key_env")
                       or cfg.get("credentials_path_env") or cfg.get("project_id_env"))
        if name == "graphify":
            if not standalone_ok and not has_cmd:
                errs.append(f"mcp.{name}: enabled but no GRAPHIFY_CLI on PATH.")
            continue
        if name in BUILTIN_COMMAND:
            continue  # command is fixed in render.py; tunables are optional
        if not has_cmd and not has_env:
            errs.append(
                f"mcp.{name}: enabled but has no command/token_env/api_key_env "
                f"— the server block will be empty (broken MCP)."
            )
    return errs


# sub-agents that are harness-NATIVE (general-purpose, Explore on zcode): they
# reference the harness's built-in dispatcher, not an STC prompt body, so the
# body+registry consistency check must skip them.
_HARNESS_NATIVE_AGENTS = {"general-purpose", "Explore"}


def _subagent_consistency(core_dir, registry, adapters):
    """Each typed-subagent capability must have BOTH a prompt body in
    core/agents/<name>.md AND a registry entry (binding: model_tier, tools,
    dispatch text). A capability missing either renders an empty stub or
    crashes render — catch it here with a precise pointer.
    """
    errs = []
    agent_bodies = set()
    agents_dir = os.path.join(core_dir, "agents")
    if os.path.isdir(agents_dir):
        agent_bodies = {f[:-3] for f in os.listdir(agents_dir)
                        if f.endswith(".md") and f != "README.md"}
    reg_agents = set((registry.get("agents") or {}).keys())
    for h, adapter in adapters.items():
        caps = (adapter.get("subagents", {}) or {}).get("capabilities", {}) or {}
        for name, cap in caps.items():
            if cap.get("supported") is False:
                continue  # inert on this harness (e.g. harness-docs on zcode)
            if name in _HARNESS_NATIVE_AGENTS:
                continue  # harness built-in, no STC body expected
            if name not in agent_bodies:
                errs.append(
                    f"adapters/{h}: subagent '{name}' has no body in "
                    f"core/agents/{name}.md."
                )
            if name not in reg_agents:
                errs.append(
                    f"adapters/{h}: subagent '{name}' has no entry in "
                    f"core/agents/registry.yaml (no binding/dispatch text)."
                )
        errs += _tool_binding_validity(h, adapter)
    return errs


# Tool names that ARE native on every supported harness — a binding may use
# them without a tool_map entry.
_NATIVE_TOOL_NAMES = {
    "Read", "Write", "Edit", "MultiEdit", "Bash", "Glob", "Grep",
    "WebSearch", "WebFetch", "Task", "NotebookEdit", "TodoWrite",
}


def _tool_binding_validity(harness, adapter):
    """A neutral tool name that is neither native nor in the adapter's
    tool_map renders verbatim into the agent file, where the harness does not
    recognise it and silently DROPS it. An agent that loses every tool this way
    refuses to spawn ("would be spawned with zero tools"). Catch it at deploy.
    """
    errs = []
    subs = adapter.get("subagents", {}) or {}
    tool_map = subs.get("tool_map", {}) or {}
    for name, cap in (subs.get("capabilities", {}) or {}).items():
        if cap.get("supported") is False:
            continue
        tools = (cap.get("binding", {}) or {}).get("tools")
        if not isinstance(tools, list):
            continue
        for t in tools:
            if t in _NATIVE_TOOL_NAMES or t in tool_map or t.startswith("mcp__"):
                continue
            errs.append(
                f"adapters/{harness}: subagent '{name}' binds tool '{t}', which is "
                f"neither a native tool nor mapped in subagents.tool_map — it would "
                f"be dropped at spawn. Add it to tool_map (use \"*\" if the MCP "
                f"server id is only known at connect time)."
            )
    return errs


def session_path_warnings(stc, native_dir=None):
    """Warn (don't block) when Claude Code's project/session paths disagree
    with stc.yaml's workspace.root — the condition behind the 'Folder not
    found' session loss after a folder migration.

    Claude Code stores a session's working directory in THREE places:
      1. the top-level `cwd` field inside each .jsonl session file,
      2. the projects map in ~/.claude.json (keyed by absolute path),
      3. the desktop app's local_*.json (cwd / originCwd).
    If a project folder is renamed/moved, the old paths persist as dead
    pointers: sessions open to 'Folder not found' and project memory under
    ~/.claude/projects/<encoded-old-path>/ is orphaned. This deploy does NOT
    migrate paths, but a deploy is often paired with one — so warn loudly.
    """
    warns = []
    home = os.path.expanduser("~")
    ws_root = stc.get("workspace", {}).get("root", "")
    ws_root = ws_root.replace("${HOME}", home)

    ccjson = os.path.join(home, ".claude.json")
    projects = {}
    if os.path.exists(ccjson):
        try:
            projects = (json.load(open(ccjson, encoding="utf-8")) or {}).get("projects", {}) or {}
        except (json.JSONDecodeError, OSError):
            projects = {}

    # 1. dead project pointers — paths in the map that no longer exist on disk.
    #    These are the direct cause of 'Folder not found' on session restore.
    dead = [p for p in projects if not os.path.isdir(p)]
    if dead:
        warns.append(
            f"~/.claude.json has {len(dead)} project path(s) pointing at "
            f"non-existent folders (the 'Folder not found' condition): "
            + ", ".join(sorted(dead))
        )

    # 2. workspace.root itself — if the agent's project root is not known to
    #    Claude Code, project memory (~/.claude/projects/<encoded>/) won't be
    #    found after deploy and the agent starts context-blind.
    if ws_root and projects and ws_root not in projects:
        # a parent of ws_root being known is acceptable (projects often nest)
        if not any(ws_root.startswith(p.rstrip("/") + "/") for p in projects):
            warns.append(
                f"workspace.root '{ws_root}' is not in Claude Code's projects "
                f"map — project memory under ~/.claude/projects/ may not be "
                f"discovered. Open a session in that folder once to register it."
            )
    return warns


# ---------------------------------------------------------------------------
# collision detection (settings.json + .mcp.json)
# ---------------------------------------------------------------------------

def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def detect_collisions(render_result, native_dir, harness):
    """Compare the rendered JSON patches against the live native JSON files.

    STC's own prior installs (stc-* keys) are NOT collisions — they are
    update-in-place. Only genuine user conflicts are reported.
    """
    collisions = []
    for fname, patch in render_result.json_patches.items():
        live = _load_json(os.path.join(native_dir, fname))
        if live is None:
            continue  # no existing file → no collision

        if fname == "settings.json":
            collisions += _settings_collisions(patch, live)
        elif fname == ".mcp.json":
            collisions += _mcp_collisions(patch, live)
    return collisions


def _settings_collisions(patch, live):
    """A matcher collision = user has a hook on the same event+matcher as STC.
    statusLine collision = user already points statusLine somewhere.

    A live entry that points at a known STC hook script (by basename, with or
    without the .stc.sh suffix) is NOT a real collision — it is a legacy STC
    entry that merge() will absorb. Reporting it as a collision would force the
    operator to pass --overwrite just to update STC's own prior output.

    Handles user matchers as either a string ("Bash|Write") OR a list
    (["Bash","Write"]) — both are legal Claude Code settings shapes.
    """
    # Known STC hook basenames from the patch (the .stc.sh scripts being added).
    stc_basenames = set()
    for entries in patch.get("hooks", {}).values():
        for e in entries:
            if not isinstance(e, dict):
                continue
            for h in e.get("hooks", []):
                cmd = h.get("command", "") if isinstance(h, dict) else ""
                b = os.path.basename(cmd)
                if b:
                    stc_basenames.add(b)
                    stc_basenames.add(re.sub(r"\.stc\.sh$", ".sh", b))

    out = []
    live_hooks = live.get("hooks", {}) if isinstance(live.get("hooks"), dict) else {}
    stc_hooks = patch.get("hooks", {})
    # event hooks where '*' is the ONLY valid matcher (Claude Code treats the
    # matcher on these as a source/content filter, never a tool-name). A user
    # hook with matcher='*' on the same event is coexistence, not a conflict —
    # e.g. vscode-todos-bridge + STC H06 both on SessionStart.
    EVENT_HOOKS = {"SessionStart", "SessionEnd", "Stop", "UserPromptSubmit"}
    for event, entries in stc_hooks.items():
        for e in entries:
            matcher = e.get("matcher") or e.get("_stc_matcher") or ""
            for u_ev, u_entries in live_hooks.items():
                if u_ev != event:
                    continue
                for u in u_entries:
                    if not isinstance(u, dict):
                        continue
                    # skip STC's own legacy entries — merge() absorbs them.
                    if _is_stc_legacy_entry(u, stc_basenames):
                        continue
                    u_match = _user_matcher(u)
                    if not (u_match and _matchers_overlap(matcher, u_match)):
                        continue
                    # on event hooks, '*' vs '*' is expected coexistence, not a
                    # collision — both fire, independently. Only PreToolUse
                    # matcher overlaps (same tool, two owners) need a decision.
                    if event in EVENT_HOOKS and matcher == "*" and u_match == "*":
                        continue
                    out.append(Collision(
                        "matcher",
                        f"settings.json [{event}]",
                        f"STC matcher '{matcher}' overlaps user matcher '{u_match}' "
                        f"(user command: {_user_cmd(u)})."))
    live_statusline = live.get("statusLine")
    # a live statusLine that's already STC's own (idempotent re-deploy, or the
    # non-collision path _merge_settings_patch just wrote it through) is NOT a
    # collision — only a genuinely different USER command is. Without this
    # check every re-apply after the first would falsely refuse, forcing
    # --overwrite forever just to keep STC's own statusLine in place.
    stc_statusline_basename = os.path.basename(patch.get("_stc_statusline", ""))
    live_is_stc_own = (isinstance(live_statusline, dict) and stc_statusline_basename
                       and os.path.basename(live_statusline.get("command", ""))
                           == stc_statusline_basename)
    if "_stc_statusline" in patch and live_statusline and not live_is_stc_own:
        out.append(Collision(
            "statusline",
            "settings.json",
            f"user already has a statusLine config pointing at "
            f"{live_statusline.get('command', '?')}; STC wants its own."))
    return out


def _is_stc_legacy_entry(entry, stc_basenames):
    """A live hook entry that points at a known STC script basename is a legacy
    STC entry (pre-namespace), not a genuine user hook."""
    if not isinstance(entry, dict) or not stc_basenames:
        return False
    for h in entry.get("hooks", []):
        cmd = h.get("command", "") if isinstance(h, dict) else ""
        if os.path.basename(cmd) in stc_basenames:
            return True
    return False


def _user_matcher(entry):
    """Normalize a user matcher to a string. Claude Code accepts a string OR
    a list of strings; both must not crash the collision check."""
    m = entry.get("matcher")
    if isinstance(m, list):
        return "|".join(str(x) for x in m)
    return m or ""


def _user_cmd(entry):
    hooks = entry.get("hooks") or []
    if hooks and isinstance(hooks[0], dict):
        return hooks[0].get("command", "?")
    return "?"


def _matchers_overlap(a, b):
    """Two matcher strings overlap if any tool token is shared."""
    ta = set(_re_split(a))
    tb = set(_re_split(b))
    return bool(ta & tb)


def _re_split(matcher):
    """Split a matcher into tool tokens. Accepts str or list (defensive)."""
    if isinstance(matcher, list):
        matcher = "|".join(str(x) for x in matcher)
    if not isinstance(matcher, str):
        return []
    import re
    return [t for t in re.split(r"[|]", matcher) if t]


def _mcp_collisions(patch, live):
    out = []
    live_servers = live.get("mcpServers", {})
    for name in (patch.get("mcpServers") or {}):
        if name in live_servers:
            # stc-* re-deploy is fine (update in place); anything else = conflict
            if name.startswith("stc-"):
                continue
            out.append(Collision(
                "mcp-name",
                ".mcp.json",
                f"mcpServer '{name}' already exists (user-defined). STC would "
                f"shadow it; refusing."))
    return out


def report_collisions(collisions):
    if not collisions:
        return
    print("✗ collisions detected — deploy refuses by default:")
    for c in collisions:
        print(f"   {c}")
    print("\nResolve with:")
    print("   --overwrite       back up the conflicting JSON, then let STC take precedence")
    print("   --skip-collisions keep the user config; the STC capability will be absent")


# ---------------------------------------------------------------------------
# backup + restore
# ---------------------------------------------------------------------------

def backup_snapshot(native_dir, files_to_touch, backups_root):
    """Copy each existing JSON in files_to_touch into backups_root/<ts>/."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(backups_root, ts)
    os.makedirs(dest, exist_ok=True)
    saved = []
    for fname in files_to_touch:
        src = os.path.join(native_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dest, fname))
            saved.append(fname)
    return ts, dest, saved


def restore(backup_id, native_dir, backups_root):
    dest = os.path.join(backups_root, backup_id)
    if not os.path.isdir(dest):
        raise FileNotFoundError(f"no backup: {dest}")
    for fname in os.listdir(dest):
        shutil.copy2(os.path.join(dest, fname), os.path.join(native_dir, fname))
        print(f"   restored {fname}")


# ---------------------------------------------------------------------------
# postcheck — sanity on the rendered output
# ---------------------------------------------------------------------------

def postcheck(render_result):
    """bash -n on every rendered .sh; report unresolved ${VAR} without default."""
    warnings = []
    for rel, text in render_result.files.items():
        if rel.endswith(".sh"):
            r = subprocess.run(["bash", "-n", "-"], input=text, capture_output=True, text=True)
            if r.returncode != 0:
                warnings.append(f"{rel}: bash syntax error: {r.stderr.strip()}")
    return warnings


# ---------------------------------------------------------------------------
# onboarding
# ---------------------------------------------------------------------------

ONBOARDING = """\
No stc.yaml found. To set up STC:

  1. cp stc.example.yaml stc.yaml
  2. edit stc.yaml:
       user.name, user.language, user.git.*
       models.provider        (glm | claude | …)  → must match core/models/<x>.yaml
       deploy.targets         ([claude, zcode] or a subset)
       mcp.* enabled flags    (playwright + graphify are REQUIRED)
  3. cp user/secrets.env.example user/secrets.env  → fill real values
  4. deploy.py render --target claude --dry-run     → preview
  5. deploy.py check                                → validate config
"""


def onboarding(stc_exists):
    if not stc_exists:
        print(ONBOARDING)
        return False
    return True
