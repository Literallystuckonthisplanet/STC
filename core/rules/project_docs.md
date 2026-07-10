---
name: project-docs
layer: rules            # always-context
scope: global
---

# Project documentation rules

How to record decisions and encode work inside a project.

## Project memory format (R08)
<!-- R08 -->

A project's memory file (`user/projects/<name>.md` / `project_<name>.md`)
follows a compact three-section format — saves tokens (loaded when you work
on a project), detail lives in repo docs:

- **STATE** — the current truth, overwritten in place; pointers to repo docs.
- **OPEN** — blockers / questions / what's next; closed items are **deleted**.
- **CHANGELOG** — append-only, **thin** — read only the last entry.

**Principle:** memory = pointer + STATUS, not detail. History → git (it's
backed up), not into this file. Rotation: see `behavior.md` § Memory rotation
(I26) — at session end, prior STATE/CHANGELOG moves to
`archive/project_<name>_archive.md`.

## Architecture Decision Records (ADR)
<!-- R05 -->

Capture any principled architectural or functional decision in ADR format.

**Format:** Decision → Why → What was rejected.

**Trigger:** "Would a new session need to understand WHY this was done this
way?" → if yes, write an ADR.

**Where:** `DECISIONS.md` in the project, or the project's page in the
configured doc backend. Number records as `ADR-NNN`.

## Task encoding

A three-level system used in `PLAN.md` / the doc backend's task list:

- **Blocks (letter):** `A` / `B` / `C` — phases and their start order. The
  letter says when a block may start: `A` before `B`, `B` before `C`.
- **Sub-blocks (letter+digit):** `B0` → `B1` → `B2` — steps inside a phase,
  ordered by dependency. Parallelize only sub-blocks with no dependency on
  each other.
- **Artifacts:**
  - `ADR-NNN` — a decision (permanent).
  - `T-NN` — a thesis for discussion (temporary: after discussion it becomes
    an ADR or is closed).

**How to apply:** when planning any project or large feature, introduce the
system from the start. `T-NN` is ephemeral by design — do not let it linger.

## Data models (ERD)

Document the data model as an ERD on the project's doc-backend page.

**Renderer:** mermaid.ink — `https://mermaid.ink/img/<base64 of the mermaid
source>`. GET-by-content, no browser; the doc backend embeds it directly as
an image. **`layout: elk` is mandatory** — orthogonal routing produces far
fewer crossings than the default dagre for hub-heavy schemas
(Order/Customer).

**Workflow:** the agent edits the mermaid source, encodes to base64
**programmatically** (python), assembles the URL, and swaps the image via
the doc backend's update API. The image is static: regenerate when the
schema changes.

**Patch trick (for editing a URL without homoglyph pain):** do not rewrite
the whole URL (thousands of chars). Patch only the changed fragment. If the
source insertion lands on a 3-byte boundary and is itself a multiple of 3
bytes, the base64 tail stays identical and only a short prefix changes.
Compute old/new prefixes programmatically via common-suffix.

**Verification is mandatory** (see `behavior.md` § Long ASCII): decode the
base64 without errors AND `curl` the URL → `HTTP 200` valid PNG before
committing it.

**Fallback:** PlantUML (stable, uglier). **Do not try Kroki** — it chokes on
`erDiagram`.
