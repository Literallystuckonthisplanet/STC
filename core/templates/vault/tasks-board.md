<!--
TEMPLATE. The deploy pipeline writes this into the doc backend as
`tasks/Board.md` — the task board, a Dataview view over the per-project task
files. Source of truth = the .md task files in this folder; the board is a view.
Requires the Dataview plugin (in Obsidian) — but the raw markdown checkboxes
work in any editor.
-->
---
name: tasks-board
description: Task board (Dataview view by project/status). Source of truth = the .md task files.
aliases: [tasks, board]
node_type: memory
type: reference
---

# 🗂️ Task board

A view over the markdown task files in `tasks/` (one per project). The board
below is a Dataview query (an editor without Dataview shows the raw files).

> Requires the **Dataview** plugin. The **Tasks** plugin (optional) makes the
> `[/]`/`[x]` statuses and dates nicer, but Dataview collects everything on
> its own.

## Task-line convention

One task = one checklist line with Dataview inline fields:

```
- [ ] Task title [project:: <Project>] [block:: A0] [exec:: agent] [priority:: Medium] [adr:: https://...]
```

| Field | Values | Note |
|---|---|---|
| checkbox status | `[ ]` not started · `[/]` in progress · `[x]` done | binary `[ ]/[x]` is plain markdown; `[/]` needs the Tasks plugin |
| `project` | `<Project Name>` | required |
| `block` | A0 / A1 / B0 … (letter+subblock) | a large task from a plan; a medium one may omit it |
| `exec` | agent · main | only with parallel worktrees |
| `priority` | High · Medium · Low | defaults to Medium |
| `adr` | url | optional, a link to the ADR/spec |

Created by the `/to-tasks` command. Small tasks are not tracked (the old rule).

---

## In progress

```dataview
TASK
FROM "tasks"
WHERE status = "/"
GROUP BY project
```

## Not started (by project)

```dataview
TASK
FROM "tasks"
WHERE status = " "
GROUP BY project
```

## Done (recent)

```dataview
TASK
FROM "tasks"
WHERE status = "x"
GROUP BY project
LIMIT 50
```
