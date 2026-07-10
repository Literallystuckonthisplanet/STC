---
name: session-rules
layer: rules            # always-context
scope: global
---

# Session rules

## 1. Always-context — what is loaded and how
<!-- I01 -->

The always-context baseline = the **3 firing rules** (`behavior.md`, `pev.md`,
`session.md` — this file) + your **user profile**. It is delivered once at
session start — do NOT re-read these files manually (double-loading wastes
tokens):

- **Rules** — per harness (`harness_facts.rules_delivery`): where SessionStart
  hooks fire (claude), hook H06 injects them and the bundle
  (`CLAUDE.stc.md`) is a pointer; where plugin hooks don't fire (zcode), the
  rule bodies are inlined into the bundle (`AGENTS.stc.md`) at render-time.
  On resume after compact the delivery repeats automatically (H06 fires on
  compact; the bundle is re-imported).
- **Profile** (`user/profile.md`) — inlined into the bundle by deploy on every
  harness (no hook injects it, so it never duplicates).

Everything else is **lazy**: `core/rules/project_docs.md` (anchor
`[[project-docs]]`), `core/memory/MEMORY.md` (index), `playbook.md`,
`code_standard.md`, and per-project memory (`user/projects/<name>.md`, read
when you name a project).

## 2. Session start
<!-- I02 -->

When the user names a project, read `project_<name>.md` — STATE is the fresh
info from the last session (per `behavior.md` § Memory rotation, I26: STATE
is rotated to archive at session end, so it always reflects the latest
session). No handoff doc is needed. If no `project_<name>.md` exists, start
one from the R08 template.

Infra audit: H06 (`session-start-context.sh`) checks the cadence on session
start — if the "last run" timestamp under the infra-audit skill is ≥ 1 month
old, it nudges you to offer an audit (only when there is token budget to
spare). Never trigger an audit mid-task.

## 3. Session end ("завершаем сессию" / "wrap up the session")
<!-- I03 -->

Mandatory sequence — execute both steps yourself, without asking. The
session-end trigger is detected by hook H03 on the short command; the steps
themselves you execute:

1. Save session memory per `behavior.md` § Memory rotation (I26):
   - Update STATE/CHANGELOG in `project_<name>.md` (R08) with what was done,
     what's in progress, the next step, new facts/decisions.
   - Rotate the prior STATE/CHANGELOG to `archive/project_<name>_archive.md`,
     leaving a `[[project_<name>_archive]]` pointer. STATE = latest session.
   - If infra files (rules/commands/agents/hooks/templates/labels) were edited
     this session → re-apply the deploy so the rendered artifacts and doc
     backend reflect the change: `python3 ${DEPLOY_SCRIPT} apply --target ${HARNESS_LIST}`
     (skip if infra wasn't touched). Then regenerate the infra graph if the
     code-labels changed: `python3 ${STC_CORE}/scripts/infra_graph_render.py`.
2. Stop the project's services: kill dev servers on `${DEV_PORTS}` and run
   `docker compose down` (or the project's documented shutdown command).

Report what was saved and what was stopped.

## 4. Post-compact recovery
<!-- FR-7 -->

After a compact (manual OR auto), H06 emits a loss-check directive. Honor it:
reconcile pre-compression state (changed/uncommitted files, test/verify
commands, open decisions, the active todo-list), record any unsaved important
fact to memory immediately. Auto-compact must not lose anything.
