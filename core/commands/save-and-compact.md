---
description: "Save the session status to memory files, then prepare for a compact. Run all steps yourself — this is preparation before invoking the compact command."
---
<!-- S09 -->

## 1. Review the conversation and identify

- Tasks: what is complete, what is in progress, the next step.
- Decisions: architectural choices, agreed approaches.
- New facts: resource IDs, configs, important findings, feedback.

## 2. Update the project's pending log

Add an entry:
- What was done in this session (with the date YYYY-MM-DD).
- What is in progress (if anything).
- The next step.

## 3. Save new facts to the right memory files

Only what is not already in memory:
- `project_*.md` — facts about projects/features.
- `feedback_*.md` — behavior rules, learned lessons.
- `reference_*.md` — links to external resources.

Update the memory index if new files were added.

## 4. Flush infra docs to the doc backend (if they changed)

If infra files were edited in this session (rules / commands / agents / hooks
/ templates / labels), run the deploy generators:

```
${DEPLOY_SCRIPT} --apply
${DEPLOY_SCRIPT} --diagram
${DEPLOY_SCRIPT} --content
```

`--content` is incremental — it touches only what changed (if nothing changed
→ 0 requests). If the infra wasn't touched → skip this step.

## 5. Report

Say:
- Which files were updated and what was added to each.
- Whether the infra doc was synced (if applicable).
- "Memory saved. Run `${COMPACT_CMD}`."
