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

- **STATE** — the current truth, overwritten in place; config/stack, key
  decisions in brief, credentials via `.env` — pointers to repo docs, not
  copies.
- **OPEN** — blockers / questions / what's next, marked 🔴 blocker / ⏳
  waiting / 🔵 tracking; closed items are **deleted**.
- **CHANGELOG** — append-only, **thin**: `### YYYY-MM-DD — 1-2 lines`. Read
  only the last entry.

**Don't duplicate repo docs.** Detail lives in a repo doc (`CLAUDE.md` /
`DECISIONS.md` / `DATAMODEL.md` / `PLAN.md` / `DEPLOY.md`); memory = a
pointer + the doc list.

**Maintenance invariant:** a decision or a schema change → update the repo
doc in the same task (Verify + commit). The CHANGELOG one-line pointer must
not dangle.

**Guardrail:** move detail out of memory into a repo doc only if that doc
already exists. No doc yet → the detail stays in STATE, flagged "needs doc".

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

## Security-baseline in AC spec

When handing a feature/project off to development (`to-spec`) — include the
applicable security-baseline items in the AC, per the project's profile:
rate-limit (auth / public mutations / paid proxies), input validation on both
boundaries, email-ownership verification, zero admin keys client-side,
server-side access control. Full checklist and wiring (handoff + verify) →
`[[code-standard]]` § Security baseline. Without this the spec is incomplete:
the rules exist in the catalog but silently drop if they aren't fixed as AC.

## Data models (ERD)

Document the data model as an ERD on the project's doc-backend page.

**Renderer:** mermaid.ink — `https://mermaid.ink/img/<base64 of the mermaid
source>`. GET-by-content, no browser; the doc backend embeds it directly as
an image. **`layout: elk` is mandatory** — orthogonal routing produces far
fewer crossings than the default dagre for hub-heavy schemas
(Order/Customer). Set via init-syntax in the source itself:
`%%{init: {'layout': 'elk', 'theme': 'base', 'themeVariables': {...}}}%%`.
Colors (`themeVariables`) — per project branding. Default layout (no init
block) is `TB`.

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
