<!--
TEMPLATE. The deploy pipeline writes this into the doc backend root as
`Home.md` (or `00-Home.md`) — the Map of Content, the vault's entry point.
The body below uses [[wiki-links]] that resolve once the backend is populated.
Open the Graph view (Ctrl/Cmd+G): the aliases resolve dash-slugs to the
underscore files, and the infra graph (auto-generated) clusters by type.
-->
---
name: home
description: Vault entry point — the memory map (MOC).
aliases: [home, Home, MOC]
node_type: memory
type: reference
---

# 🏠 Home — the memory map

The entry point. Open **Graph view** (Ctrl/Cmd+G) — the `[[...]]` links are
laid out, aliases resolve dash-slugs to the underscore files.

## Behavior and process
- `[[behavior]]` — memory, secrets, worktrees, commits, self-exec
- `[[pev]]` — Plan→Do→Verify
- `[[project-docs]]` — ADR, block encoding, the project-memory format
- `[[skills-triggers]]` — skills and triggers
- `[[playbook]]` — agents, checks, restarts, stop commands

## Boards (the doc-backend views)
- `[[tasks-board]]` — the task board (Dataview), by project/status
- `[[specs-index]]` — feature specs + AC (Dataview)

## Profile and standards
- `[[user-profile]]` — who the user is (private, not in the public repo)
- `[[code-standard]]` — the code standard and review
- `[[reference-defect-ledger]]` · `[[reference-abuse-cases]]` ·
  `[[reference-failure-modes]]` — the self-improving review catalogs
- `[[reference-retired-codes]]` — the retired-code registry

## Projects
<!--
Per-project memory hubs live here, one note per project, each linking its
sub-notes (design / deploy / legal / reviews / ...). Seed your own:
- [[project-<name>]] — the project hub
-->

## Infra graph (auto-generated)
- `[[infra-index]]` — the infra graph hub (one note per code-label, generated
  by `infra_graph_render.py`).

---
*A generated MOC. The links resolve once the doc backend is populated by
deploy. Keep this as the single entry point; per-section detail lives in the
linked notes, not here.*
