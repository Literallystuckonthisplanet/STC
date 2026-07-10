<!--
PER-PROJECT MEMORY TEMPLATE (R08 format: STATE / OPEN / CHANGELOG).
Copy to user/projects/<slug>.md (gitignored) and fill in. The <slug> matches
what you pass to commands like /to-spec <slug> and /to-tasks <slug>; specs and
tasks land under ${DOCS_ROOT}/specs/ and ${DOCS_ROOT}/tasks/.

PRINCIPLE (R08): memory = pointer + STATUS, NOT detail. Detail lives in the
repo docs (DECISIONS.md / DATAMODEL.md / PLAN.md / the instruction file) —
memory only points at them. History → git (it's backed up), not into this file.
Closed items are deleted from OPEN; the changelog is thin — read only the last
entry. This keeps active project memory small (~70% smaller than a dump).

The project's instruction file (CLAUDE.md / AGENTS.md) lives IN THE REPO and
holds: stack, commands+ports, technical constraints, links back to memory for
worktree agents. Don't duplicate that here.
-->

---
name: project-<slug>
description: "<one-line: project + current status>"
---

# Project — <name>

- **Slug:** `<slug>`                <!-- key used in /to-spec, /to-tasks -->
- **Path:** `${workspace.root}/<dir>`
- **Doc-backend project:** `${DOCS_ROOT}/specs/<slug>-*.md`, `${DOCS_ROOT}/tasks/<slug>-tasks.md`

## STATE  <!-- the current truth, overwritten in place; pointers to repo docs -->

<!-- One paragraph: what it is right now. Point at the repo docs for detail. -->
<!-- e.g. "E-commerce storefront, in production. Stack/commands/constraints →
     CLAUDE.md in the repo. Schema → DATAMODEL.md. Decisions → DECISIONS.md." -->

- **Instruction file:** `<repo>/CLAUDE.md` (or `AGENTS.md`)
- **Repo docs:** DECISIONS.md · DATAMODEL.md · PLAN.md (whichever exist)

## OPEN  <!-- blockers / questions / what's next; done items get deleted -->

- <what's blocking, what's undecided, what's next>

## CHANGELOG  <!-- append-only, THIN — read only the last entry -->
<!-- Rotation (I26): at session end, prior STATE/CHANGELOG entries move to
     archive/project_<name>_archive.md; leave a [[project_<name>_archive]]
     pointer here. STATE always = the latest session only. -->

- **YYYY-MM-DD** — <one-line pointer; detail in repo docs / a commit>.
- **YYYY-MM-DD** — <one-line>.

## E2E scenarios  <!-- used by the e2e skill; concrete IDs + test data -->

<!--
The core/skills/e2e/ taxonomy is generic. A real test run needs a concrete
scenario list for THIS project — that list lives here. The e2e dispatcher
reads this file at run time; without it, only the generic taxonomy is tested.

| ID | Scenario | Notes |
|----|----------|-------|
| CAT-01 | Home → listing shows items | |
| CHK-01 | Checkout redirects to the PSP | don't complete the payment |
-->

## Gotchas  <!-- only the things that burned you; delete resolved ones -->

- <e.g. "Drizzle migrations run from the repo root, not the app dir.">

<!--
INVARIANT: a decision / a schema change → update the repo doc IN THE SAME TASK
(Verify + commit); in this file's CHANGELOG — ONE line, a pointer. A pointer
must never dangle (if the repo doc doesn't exist yet, leave the detail here +
mark "needs a repo doc").
-->
