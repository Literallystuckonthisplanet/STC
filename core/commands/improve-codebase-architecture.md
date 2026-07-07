---
description: "Find deepening opportunities in a codebase — modules whose interface is small relative to their implementation, where complexity can be pushed behind a clean boundary. Informed by the domain language in the project's CONTEXT.md / glossary and the decisions in its ADRs. Use when the user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, or make a codebase more testable and AI-navigable."
---

# Improve codebase architecture
<!-- S06 -->

Find **deepening opportunities**. A deep module has a small interface relative
to a large implementation — it hides complexity behind a clean boundary
(Ousterhout, *A Philosophy of Software Design*). This command surfaces
candidates, explains the deepening, and proposes the refactor.

## Domain language discipline

Architecture review is only useful if it speaks the project's vocabulary. Read
the project's domain glossary first (`CONTEXT.md`, glossary, or whatever the
project uses — see the user-config `projects.<name>.glossary` if declared).
The terms defined there are **load-bearing**: every architectural suggestion
must use them.

Do not drift into generic synonyms ("component", "service", "API",
"boundary") when the project has a precise term. If the project calls it an
"Order intake", suggestions talk about "the Order intake module", not "the
FooBarHandler" and not "the Order service".

## Step 1 — Load context

Read:
- The project's domain glossary (`CONTEXT.md` / glossary / domain model).
- Existing ADRs in `docs/adr/` (or wherever the project keeps them) — prior
  decisions constrain today's suggestions.
- The instruction file for the project profile (complexity S0/S1/S2 + flags).

## Step 2 — Find candidates

For each module / subsystem, ask these questions. A candidate is something
that scores high on **depth gained** and low on **blast radius**.

### Structural signals
- **Wide and shallow** — module exposes a large surface (many exports, many
  public methods) for a small implementation. Deepening = consolidate the
  surface into fewer, more powerful operations.
- **Tight coupling** — two modules that must change together. Deepening =
  introduce a seam (interface, event, anti-corruption layer) so each can
  change independently.
- **Leaky abstractions** — callers must know internals to use the module
  correctly (e.g. "remember to call `init()` before `use()`, and only on
  Tuesdays"). Deepening = move the contract inside the module.
- **Duplicated deep logic** — the same non-trivial decision made in N places.
  Deepening = one deep module, N thin callers.
- **Untestable in isolation** — a module that can't be tested without booting
  half the system. Deepening = a smaller public surface → narrower deps →
  testable.

### Naming / vocabulary signals
- A module named after an implementation detail (e.g. `RedisCache`,
  `HttpController`) instead of a domain concept → the abstraction is upside
  down. Implementation should be hidden behind a domain name.
- A fuzzy term that everyone uses differently → the boundary is unclear.
  Sharpen it.

## Step 3 — Frame each candidate

For every candidate, present:

```
### [candidate name, using domain vocabulary]

**Why it's shallow:** [the structural signal — what's wide/thin/leaky]

**Deepening proposal:** [the new interface — small surface, stated in domain
terms. This is the load-bearing part. Be concrete: list the operations.]

**What it hides:** [the complexity that moves behind the interface]

**Blast radius:** [files that change, callers that update]

**Testability gain:** [what becomes testable that wasn't]
```

The interface description is the core of the proposal. If you cannot state the
new interface in domain terms in a few lines, the candidate isn't ready —
sharpen it or drop it.

## Step 4 — Vocabulary feedback loop (during the conversation)

These are the moments where the conversation itself should mutate the
project's vocabulary, not just its code:

- **Naming a deepened module after a concept not in the glossary?** Add the
  term to `CONTEXT.md` / the glossary. Create the file lazily if it doesn't
  exist. This is the same discipline as the domain-modeling step of project
  setup.
- **Sharpening a fuzzy term mid-conversation?** Update `CONTEXT.md` right
  there.
- **User rejects the candidate with a load-bearing reason?** Offer an ADR,
  framed as: _"Want me to record this as an ADR so future architecture
  reviews don't re-suggest it?"_ Only offer when the reason would actually be
  needed by a future explorer to avoid re-suggesting the same thing — skip
  ephemeral reasons ("not worth it right now") and self-evident ones. See
  the project's ADR format (`core/rules/project_docs.md` § ADR) for the
  scaffold.

## Step 5 — Reports

Optional but useful for a large review: produce an HTML report of the
candidates with inline diagrams (mermaid renders to an image via
`mermaid.ink`). The report is for the human reviewer, not the agent loop.
Standard scaffold:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Architecture review — [date]</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 880px; margin: 2rem auto; padding: 0 1rem; }
    .candidate { border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.5rem; margin: 1.5rem 0; }
    .interface { background: #f6f8fa; padding: 0.75rem 1rem; border-radius: 6px; font-family: ui-monospace, monospace; }
    img.diagram { max-width: 100%; }
  </style>
</head>
<body>
  <h1>Architecture review — [date]</h1>
  <p>Scope: [what was reviewed]</p>

  <!-- per candidate: -->
  <section class="candidate">
    <h2>[candidate name]</h2>
    <p><strong>Why it's shallow:</strong> …</p>
    <img class="diagram" src="https://mermaid.ink/img/[base64-encoded diagram]" alt="before/after" />
    <p><strong>Deepening proposal:</strong></p>
    <pre class="interface">[the new interface]</pre>
    <p><strong>Blast radius:</strong> …</p>
  </section>
</body>
</html>
```

Mermaid diagrams: before/after of the module boundary, encoded with
`mermaid.ink/img/<base64>` so the HTML is self-contained. Keep diagrams
focused on the boundary change, not the whole system.

## Rules

- **Domain terms only** in suggestions. Drift to generic nouns = the review
  lost touch with the project.
- **Interface-first.** A candidate without a concrete proposed interface is
  not actionable — don't present it.
- **Respect ADRs.** A prior ADR that says "we deliberately chose X over Y" is
  a stop sign, not a challenge.
- **Honest blast radius.** A "deepening" that requires touching 40 files is a
  rewrite, not a refactor — name it as such.

---

## Supporting sources

Migrated from the user's `~/.claude/commands/improve-codebase-architecture.md`
(originally from the Matt Pocock skills set — partially installed, so several
cross-links to sibling skills dangle). Per Decision 1 in `docs/PROGRESS.md`,
the dangling cross-links (`LANGUAGE.md`, `HTML-REPORT.md`,
`INTERFACE-DESIGN.md`, `CONTEXT-FORMAT.md`, `ADR-FORMAT.md`) were resolved by
inlining their content into this file. The ADR format reference now points to
`core/rules/project_docs.md` (STC's ADR scaffold). Check for upstream drift
during the monthly `infra-audit`.
