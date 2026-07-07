<!--
TEMPLATE. The deploy pipeline writes this into the doc backend as
`specs/_specs-index.md` — the feature-spec index, a Dataview view over the
spec files. Replaces a separate AC database: AC live as a checklist inside
each spec, and Dataview/Tasks collect their progress.
-->
---
name: specs-index
description: Feature-spec index (Dataview by frontmatter). Source of truth = the .md spec files.
aliases: [specs]
node_type: memory
type: reference
---

# 📐 Feature specs

Each spec = a `.md` in `specs/` with frontmatter (`project`, `status`,
`created`, `feature`). Created by the `/to-spec` command. Section format →
`[[project-docs]]` + `[[spec-template]]`.

> AC live as a `- [ ]` checklist inside the spec file (replaces a separate AC
> database) — Dataview/Tasks collect them into progress.

## All specs

```dataview
TABLE project AS "Project", status AS "Status", created AS "Created"
FROM "specs"
WHERE node_type = "spec"
SORT created DESC
```

## By project (active)

```dataview
TABLE WITHOUT ID file.link AS "Spec", status AS "Status"
FROM "specs"
WHERE node_type = "spec" AND status != "done"
SORT project ASC, created DESC
GROUP BY project
```

## Open AC (across all specs)

```dataview
TASK
FROM "specs"
WHERE contains(text, "#ac") AND status = " "
GROUP BY file.link
```
