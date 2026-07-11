---
name: to-tasks
description: "Slice a finalised plan into task lines in the doc backend. Large task — from a finalised plan (block-coding mandatory), together with /to-spec. Medium — one line when taken into work (no spec). Small tasks are not tracked. Trigger: the agent starts it itself. Argument: project slug."
argument-hint: "<project-slug>"
---
<!-- S13 -->

# to-tasks

Slices a finalised plan into task lines in the doc backend. Do not ask extra
questions — it executes against a finished plan. Source of truth = the file.

## Where it writes

Resolved at deploy time from the adapter (the doc backend root) + the project
slug:

- **Root:** `${DOCS_ROOT}/tasks/`
- **File per project:** `<project>-tasks.md` → section `## Open`.

If no doc backend is configured (`deploy.doc_backend == none`), say so and stop.

## Task line format

```
- [ ] <task title> [project:: <Project>] [block:: A0] [exec:: sub-haiku] [priority:: Medium] [adr:: <url>]
```

Field conventions and statuses (`[ ]` open / `[/]` in progress / `[x]` done)
live in the doc backend's tasks index.

## Steps

### 1. Resolve the project

From the argument or context.

### 2. Extract tasks from the plan

From Plan-step 4 collect the marked items. For each:

- Title (without the markup suffixes).
- Exec slice → inline `exec` field (NOT in the title): `sub-haiku`
  (mechanical) / `sub-sonnet` (isolated judgment) / `cheap-session` (dialogue,
  low risk) / `main` (architecture/uncertainty). See pev Step 4.
- Block-coding (A0, A1, B0…) → inline `block` field.
- Priority if stated → inline `priority` (else Medium).

No block-coding → `block:: A0`, then in order.

### 3. Append lines

Add `- [ ]` lines under the `## Open` section of the project's file. Do not
duplicate existing ones.

### 4. Return the summary

How many lines added + a link to the tasks index.
