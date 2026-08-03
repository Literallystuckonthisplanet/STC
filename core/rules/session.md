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
  hooks fire; H06 injects them on the initial start and the bundle is a
  pointer/fallback according to the adapter contract.
- **Profile** (`user/profile.md`) — inlined into the bundle by deploy on every
  harness (no hook injects it, so it never duplicates).

Everything else is **lazy**: `core/rules/project_docs.md` (anchor
`[[project-docs]]`), `core/memory/MEMORY.md` (index), `playbook.md`,
`code_standard.md`, and per-project memory (`user/projects/<name>.md`, read
when you name a project). Anything about the infra itself (what codes/hooks/
skills exist, where something lives) → `core/memory/SNAPSHOT.md`, per I27
(behavior.md § Question about the infra) — never a scan of the `core/` tree.

## 2. Session start
<!-- I02 -->

When the user names a project, read the project documentation needed for the
task. Project memory remains available as a reference, but the active session
is not required to maintain STATE/CHANGELOG manually. If a project memory file
is needed and does not exist, create it only as part of an explicit project
documentation task.

Infra audit: H06 (`session-start-context.sh`) checks the cadence on session
start — if the "last run" timestamp under the infra-audit skill is ≥ 1 month
old, it nudges you to offer an audit (only when there is token budget to
spare). Never trigger an audit mid-task.

## 3. Session end

Session end has no memory-rotation protocol. The offline ingest job owns
transcript import and monthly memory reports independently of harness
lifecycle. Stopping project services remains a project-specific operational
action, not a memory requirement or a universal hook contract.
