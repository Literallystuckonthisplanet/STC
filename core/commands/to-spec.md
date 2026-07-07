---
name: to-spec
description: "Write the outcome of the Plan conversation as a markdown spec in the doc backend (use cases + AC + ADR + buy-vs-build + abuse-cases + failure-modes + block-plan). Run after Plan-step 4 and AC agreement. Trigger: the agent starts it itself after the plan is finalised, before the Do phase. Argument: project slug."
argument-hint: "<project-slug>"
---
<!-- S12 -->

# to-spec

Freezes a feature spec as a `.md` file in the doc backend based on the current
Plan conversation. Do not ask extra questions — everything is already in the
dialogue. Source of truth = the file (the doc backend is a view).

## Where it writes

Resolved at deploy time from the adapter (the doc backend root) + the project
slug argument:

- **Root:** `${DOCS_ROOT}/specs/`
- **File:** `<project>-<feature-kebab>.md` (e.g. `alpha-checkout.md`).

If no doc backend is configured (`deploy.doc_backend == none`), say so and stop.

## Steps

### 1. Resolve the project

From the argument or context. Map to the project's docs container. If unknown,
list the known project slugs and stop.

### 2. Extract from the conversation

- **Feature name** — the Plan session topic.
- **Use cases** — "As [role], I want [action], so that [goal]".
- **AC** — criteria from Plan-step 4, as a checklist `- [ ] …`.
- **ADR** — Decision → Why → What was rejected (only if there was a non-trivial
  decision with rejected alternatives).
- **buy-vs-build (DEP-4, enforced H14)** — for non-trivial pieces: "Took X /
  by hand, because Y". Trivial → "n/a".
- **Abuse-cases** — for EACH use-case run "how to break it?" against the
  abuse-case catalog (`code_standard.md` §9 + the abuse reference). Loopholes
  → negative AC + NFR. New vectors discovered → append to the catalog.
- **Failure-modes** — for EACH use-case check the failure-modes reference; if no
  entry for a new scenario → docs-research and **save it** (otherwise the
  integration-docs hook will block editing the code).
- **Block-coding** — if the plan contains blocks A/B/C — extract them.

### 3. Write the spec file

Create `${DOCS_ROOT}/specs/<project>-<feature-kebab>.md` with frontmatter:

```yaml
---
node_type: spec
project: <Project Name>
status: draft
created: <YYYY-MM-DD>
feature: <feature name>
---
```

AC as a `- [ ]` checklist.

### 4. Link

Add a link to the spec from the project's project-memory file (the project hub)
and from the memory log (the "facts on the fly" rule).

### 5. Return the path

Return the created file path to the user.
