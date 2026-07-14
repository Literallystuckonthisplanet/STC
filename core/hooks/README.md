# Hooks

The enforcement layer. A rule in always-context **recidivs** (empirically
proven by mining 66 sessions); the same rule in a hook **does not**. This is
ADR-001: rules migrate from always-text to event-triggered hooks at the exact
flow point where they apply.

The hook model (Claude Code / ZCode / any harness supporting PreToolUse +
related events):

- **PreToolUse / PostToolUse / UserPromptSubmit / Stop / SessionStart / SessionEnd** — the event types.
- A hook script reads the tool-call JSON from stdin, decides, and either:
  - **Hard-block** — `exit 2` with a stderr message; the tool call is rejected.
  - **JIT-inject** — emit a `hookSpecificOutput.additionalContext` JSON object
    (see below); the message reaches the model.
  - **Pass** — `exit 0`, optionally with bare stdout (reaches the **user**, not
    the model — useful only for SessionStart/UserPromptSubmit).

## Critical mechanism: how to reach the model

On **PreToolUse**, bare `stdout` does **NOT** reach the model — it is shown
only to the user. To inject context that the model sees, use:

```bash
jq -cn --arg c "$MESSAGE" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
```

This is the only channel for JIT context-injection on PreToolUse. The
JIT-injecting hooks (H01, H02, H04, H06, H07, H09, H10, H12, H14, H16) all use
it — some inject unconditionally, others alongside a block/nudge.

On **SessionStart / UserPromptSubmit**, bare stdout DOES reach the model —
plain `echo` works (used by H03, H06).

## Acknowledge-once pattern

Several hooks block or nudge **once per session**, then let a repeat pass
deliberately (a deliberate override is not locked out forever). The pattern:

```bash
MARKER="/tmp/stc-<hookname>-${SESSION}"
[ -f "$MARKER" ] && exit 0   # already fired → pass
: > "$MARKER"                # set BEFORE a possible exit 2 → retry passes
# ... block or nudge ...
```

Used by: H01 (push-to-main), H04 (build-agent-contract), H07 (dirty-tree),
H08 (link-integrity), H13 (web-route), H14 (buy-vs-build), H18 (graphify-first).

## The 6 event-guards (flow-point → file)

The 18 hooks are routed by the harness `settings.json` matcher groups into
~6 flow points. One file = one guard (single-responsibility, auditable).

| Flow point | Hook(s) | What it enforces |
|---|---|---|
| **task-start** (first edit in a repo) | `dirty-tree-guard.sh` H07 | 🔒 I09 dirty-tree block + 💉 I07 worktree nudge |
| **memory-write** (edit under memory/) | `secret-scan-memory.sh` H05 🔒 + `memory-guard.sh` H09 💉 | H05: block a secret write. H09: inject I04 checklist (dedup/place/format). Two files deliberately — single-responsibility. |
| **read-first router** (edit project code) | `read-first-router.sh` H10 | 💉 domain reminders (DS / security / docs / data / tdd / legal / reuse) |
| **git guard** (Bash) | `block-dangerous-git.sh` H01 | 🔒 dangerous patterns + 🔒 I08 push-to-main + 💉 I17 commit-verify |
| **agent guard** (Task) | `agent-reuse-contract.sh` H04 | 🔒 I21 build-agent reuse-contract + 🔒 FR-28 fork-protocol marker (executors must stop on architectural/business forks, DECIDED lines for trivia) + 💉 I20 reviewer baseline |
| **session guards** (UserPromptSubmit / SessionStart / Stop) | `stop_services_reminder.sh` H03 + `session-start-context.sh` H06 + `link-integrity-guard.sh` H08 | H03: SELF-EXEC + I05b secret-in-prompt + compact/session-end. H06: always-context inject + post-compact recovery. H08: link integrity. |

Beyond the 6-guard map (legitimate extras):

| Hook | Event | What |
|---|---|---|
| `playwright_reminder.sh` H02 | PreToolUse(mcp__playwright__*) | 💉 FR-22 channel router (CLI / real-browser / e2e-subagent) + FR-18 preflight |
| `output-hygiene-guard.sh` H11 | PreToolUse(Bash) | 🔒 I24/FR-15 block raw output dumps (cat/sed/head/tail/git diff/find/grep -r) |
| `acquire-dedup-guard.sh` H12 | PreToolUse(Read\|Grep\|Glob\|Bash) | 💉 FR-17 soft anti-duplicate (already-gathered nudge) |
| `web-route-guard.sh` H13 | PreToolUse(WebSearch\|WebFetch) | 🔒 FR-17 web-via-subagent (block main, pass sub-agent) |
| `buy-vs-build-reminder.sh` H14 | PreToolUse(EnterPlanMode) + PreToolUse(Write\|Edit\|MultiEdit) | 💉 FR-24/DEP-4 buy-vs-build inject on plan entry **+ 🔒 FR-28 ORCHESTRATOR GATE**: after plan mode, EVERY main edit of a project file blocks once per file (retry passes — the stated WHY is the audit trail); sub-agents (the executor tier) pass; memory/docs/*.md/.env/STC-infra excluded; no-plan sessions ungated |
| `exec-offload-guard.sh` H15 | PreToolUse(Bash) | 🔒 expensive-Bash-offload block (noisy data-scripts import/seed/scrape/sync → ephemeral agent; audit without --json) |
| `integration-docs-gate.sh` H16 | PreToolUse(Write\|Edit\|MultiEdit) | 🔒 FR-26 docs-first block: editing a named integration's code without saved research → block (lifted by research-save or `// docs-checked:`). Generic-English service names (openai/stripe/aws/…) require a USAGE signal (import/API-host/`_api_key`/netcall) so a bare mention in a comment/regex doesn't false-block; niche/regional names match bare. |
| `secret-read-guard.sh` H17 | PreToolUse(Read\|Glob\|Grep) | 🔒 block reading a secret file (`.env` / `.pem` / `id_rsa`) → keeps secrets out of context/logs (defense-in-depth: mirrors `permissions.deny` on claude, the ONLY read-guard on a harness without a permissions engine). Escape: `// secret-exception:` |
| `graphify-first.sh` H18 | PreToolUse(Grep\|Bash) | 🔒 in a repo with a built code-graph (`graphify-out/graph.json`), the first grep-style search is blocked once → nudge `graphify query`/`affected`/`explain` for how/why/connect questions (acknowledge-once; repeat passes for an exact-string lookup). Repos without a graph are never gated. |
| `exit-plan-grill.sh` H21 | PreToolUse(ExitPlanMode) | 🔒 FR-28 exit-plan-gate: leaving plan mode blocks once unless the plan carries AC/DoD + a block→executor decomposition + an explicit forks-resolved line (plan text from tool_input.plan or the freshest `$NATIVE_DIR/plans/*.md`). Acknowledge-once — the deliberate re-exit passes; sub-agents pass. Pairs with plan-mode-default (every session starts in plan) + H14 (orchestrator gate). |

## Settings wiring

The harness `settings.json` (global, per-user) wires hooks by matcher. The
adapter (`adapters/<harness>/`) produces the rendered `settings.json` from the
STC source. Example matcher routing (Claude Code shape — ZCode uses the same
hook-event names):

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{"type":"command","command":".../block-dangerous-git.sh"}, {"type":"command","command":".../output-hygiene-guard.sh"}, {"type":"command","command":".../exec-offload-guard.sh"}] },
      { "matcher": "mcp__playwright__browser", "hooks": [{"type":"command","command":".../playwright_reminder.sh"}] },
      { "matcher": "Task", "hooks": [{"type":"command","command":".../agent-reuse-contract.sh"}] },
      { "matcher": "Write|Edit|MultiEdit", "hooks": [{"type":"command","command":".../secret-scan-memory.sh"}, {"type":"command","command":".../dirty-tree-guard.sh"}, {"type":"command","command":".../memory-guard.sh"}, {"type":"command","command":".../read-first-router.sh"}, {"type":"command","command":".../integration-docs-gate.sh"}, {"type":"command","command":".../buy-vs-build-reminder.sh"}] },
      { "matcher": "EnterPlanMode", "hooks": [{"type":"command","command":".../buy-vs-build-reminder.sh"}] },
      { "matcher": "Read|Grep|Glob|Bash", "hooks": [{"type":"command","command":".../acquire-dedup-guard.sh"}] },
      { "matcher": "Read|Glob|Grep", "hooks": [{"type":"command","command":".../secret-read-guard.sh"}] },
      { "matcher": "Grep|Bash", "hooks": [{"type":"command","command":".../graphify-first.sh"}] },
      { "matcher": "WebSearch|WebFetch", "hooks": [{"type":"command","command":".../web-route-guard.sh"}] }
    ],
    "UserPromptSubmit": [{ "hooks": [{"type":"command","command":".../stop_services_reminder.sh"}] }],
    "SessionStart": [{ "hooks": [{"type":"command","command":".../session-start-context.sh"}] }],
    "Stop": [{ "hooks": [{"type":"command","command":".../link-integrity-guard.sh"}] }]
  }
}
```

## Render-time variables

Each hook references `${VARS}` resolved by `deploy.py` from `stc.yaml`:

| Var | Source | Used by |
|---|---|---|
| `${MEMORY_DIR}` | adapter (memory location per harness) | H05, H08, H09, H10, H16 |
| `${DOCS_ROOT}` | `doc_backend.root` | H16 (notes/research) |
| `${HARNESS_DIR}` | adapter (`~/.claude` / `~/.zcode`) | H06, H07, H10 |
| `${HARNESS_NAME}` | adapter (`claude` / `zcode`) | H16 (infra-scope skip) |
| `${USER_LANG}` | `user.language` | all (message language) |
| `${USER_NAME}` | `user.name` | H03 |
| `${DEV_PORTS}` | `workspace.dev_ports` | H03 |
| `${COMPACT_CMD}` | adapter (harness-native compact) | H03 |
| `${SECRETS_ENV}` | adapter (the .env file) | H03, H05 |
| `${RELEASE_ACK_FILE}` | adapter (per-session marker path) | H01 |
| `${CDP_PORT}` | `mcp.playwright.cdp_port` | H02 |
| `${E2E_CLI_CMD}` | project (the CLI e2e command) | H02 |
| `${SESSION_ID}` | harness (injected per tool-call) | H14 (once-marker) |

## Verifying hooks

A structurally-clean hook (syntax ok, dry-run paths exist) ≠ a working hook
(audit lesson: H11 passed 19/19 unit cases but failed live until a human found
the bug). Two layers:

1. **Structural** — `bash -n` syntax, path/matcher wiring, `${VARS}` resolve.
2. **Functional** — run the script under a realistic stdin (the smoke tests
   in this repo cover the block/pass/inject branches of H01 and H05).

The `infra-audit` skill runs both layers on its monthly cadence.
