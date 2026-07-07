---
name: session-rules
layer: rules            # always-context
scope: global
---

# Session rules

## 1. Always-context is loaded via @import
<!-- I01 -->

The always-context baseline is **loaded once at session start via `@import`
lines** in the harness's always-context bundle (`CLAUDE.stc.md` /
`AGENTS.stc.md`) — do NOT re-read these files manually (double-loading wastes
tokens). On resume after compact, the harness re-imports them automatically.

1. `core/memory/MEMORY.md`         — memory index
2. `core/memory/playbook.md`       — the play loop
3. `core/memory/code_standard.md`  — code standards (judgment rules)
4. `core/rules/behavior.md`        — behavioral rules (SELF-EXEC, secrets, commits, worktrees, agents)
5. `core/rules/pev.md`             — Plan→Do→Verify loop
6. `core/rules/project_docs.md`    — project documentation rules
7. `core/rules/session.md`         — this file

Your personal profile (`user/profile.md`) is read on demand when a rule
references it — not part of the always-context bundle.

## 2. Session start
<!-- I02 -->

When the user names a project or task, check `${HANDOFFS_DIR}/` for fresh
handoff documents (modified within the last 7 days, or matching that
project). If a relevant one exists, offer: "there is a handoff from DATE on
TOPIC — read it?".

Infra audit: H06 (`session-start-context.sh`) checks the cadence on session
start — if the "last run" timestamp under the infra-audit skill is ≥ 1 month
old, it nudges you to offer an audit (only when there is token budget to
spare). Never trigger an audit mid-task.

## 3. Session end ("завершаем сессию" / "wrap up the session")
<!-- I03 -->

Mandatory sequence — execute both steps yourself, without asking. The
session-end trigger is detected by hook H03 on the short command; the steps
themselves you execute:

1. Run the `/save-and-compact` skill — save session memory to the project
   notes, then flush infra docs to the configured doc backend (step 4 of
   the skill).
2. Stop the project's services: kill dev servers on `${DEV_PORTS}` and run
   `docker compose down` (or the project's documented shutdown command).

Report what was saved and what was stopped.

## 4. Post-compact recovery
<!-- FR-7 -->

After a compact (manual OR auto), H06 emits a loss-check directive. Honor it:
reconcile pre-compression state (changed/uncommitted files, test/verify
commands, open decisions, the active todo-list), record any unsaved important
fact to memory immediately. Auto-compact must not lose anything.
