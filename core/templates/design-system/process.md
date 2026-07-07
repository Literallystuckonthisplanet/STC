<!-- T02 -->
# Design system process (project-type-aware)

A portable process: gives the agent a machine-readable design system BEFORE
UI generation. The model is layered: a shared **core** + a per-type
**overlay** (Variant B — explicit classification). The main consumer of the
design system is the agent generating UI, so everything is machine-readable
(tokens in code + a `DESIGN.md`).

**When to apply:** at the start of a new project (via
`core/templates/new-project.md`) OR when introducing a design system to an
existing project. The per-project artifact is a `DESIGN.md` at the repo root
(instantiated from `DESIGN.template.md`).

---

## 1. Layered token model

Three token tiers (consensus: Brad Frost / Design Tokens spec):

| Tier | What | Example | Layer |
|---|---|---|---|
| **Tier 1 — Global** | raw values | color-raw, font-family, spacing-scale, radius, shadow, motion-duration | **shared core** |
| **Tier 2 — Semantic** | roles | `color-primary`, `color-surface`, `color-danger`, `color-success`, `color-info` | **shared core** |
| **Tier 3 — Component** | component binding | `btn-padding`, `card-radius`, `input-border` | **type-specific overlay** |

**Core (Tier 1+2)** is the same for every project: semantic colors,
spacing/font-size scales, radius, shadow, the base atoms (Button, Input,
Badge, Link, Card).
**Overlay (Tier 3 + patterns)** is added per project type.
Technically core+overlay live in one `@theme` (Tailwind v4) block, and
`DESIGN.md` describes their semantics.

---

## 2. Type taxonomy → required elements

Core (see §1) is mandatory everywhere. Below is what each archetype adds.

| Project type | Type-specific elements (overlay) |
|---|---|
| **Landing / Marketing** | Hero sections, Pricing block, Testimonial, media-rich imagery, motion/reveal animations, **strong typography as the primary carrier** |
| **E-commerce storefront** | Product card, Gallery, Badge (Sale/New), Review stars, PDP layout, Checkout flow, Cart widget, **mobile-first tappable targets** |
| **SaaS / Web app** | Data table, Chart wrapper, Dashboard layout (sidebar+topbar), Empty/loading states, Alerts/toasts, role-specific UI, onboarding tooltips |
| **Admin / Internal tool** | Dense data tables, Filters panel, Bulk actions, Status badges, CRUD forms, permission-aware components |
| **Content / Blog / Docs** | Prose styles (MDX/typography), Code blocks, TOC, **readability-first**, minimal interactivity |

**Reuse insight (research judgment):** e-commerce and SaaS share ~60% of
tokens and ~40% of primitives; landing and storefront share all tokens, but
the component layer diverges strongly. → core is stable, divergence is in the
overlay.

---

## 3. Adoption process (Variant B)

1. **Classify the project type** — pick an archetype from §2 (or the nearest;
   for a hybrid, name the dominant + the additions). Record it in the
   `DESIGN.md` header: `## Project Type: <archetype>`.
2. **Instantiate `DESIGN.md`** from
   `core/templates/design-system/DESIGN.template.md` → fill the 9 sections;
   pull in the overlay elements for your type from §2.
3. **Set up tokens in `@theme`** (Tailwind v4, in `globals.css`): Tier 1+2
   from DESIGN.md (palette, fonts, spacing/type scale, radius, shadow). Do
   NOT leave stock shadcn (gray palette + Inter).
4. **Verify** — anti-generic checklist + screenshots
   (`[[playbook]]` § Design system).

**Variant A vs B (B chosen, 2026-06-14):**
- A — shared core, type patterns pulled on demand: less startup overhead, but
  a generic-output risk (the agent doesn't know the context patterns).
- B — an explicit classification step → the relevant overlay is loaded
  immediately: a little overhead, but the agent gets the patterns it needs.
  **With 2+ project types, B wins.** (No industry consensus on this practice
  — judgment based on the DESIGN.md + Brad Frost overlay model.)

---

## 4. Tooling — verdicts (for solo + AI, free)

| Tool | Verdict | Why |
|---|---|---|
| **Tailwind v4 `@theme`** | **USE** (the single source of truth for tokens) | CSS-first, no config.js, generates utilities + CSS vars |
| **`DESIGN.md`** | **USE** | machine-readable brief, read by the agent automatically |
| **frontend-design SKILL** | **USE** | anti-generic philosophy on top of DESIGN.md |
| **shadcn/ui** | **USE** | primitive code lives in the project, the agent edits JSX directly, no lock-in |
| **CVA** | **USE with >5 components** | typed variants, explicit API instead of prop sprawl (~2KB) |
| **Playwright `toHaveScreenshot()`** | **USE for Verify** | free visual regression, no Storybook needed |
| **Storybook** | **SKIP** | overkill for solo (no team/designer/review); replaced by a dev page + screenshots |
| **Style Dictionary** | **SKIP** | unnecessary with a single Tailwind target; duplicates `@theme` |
| **Chromatic** | **SKIP** | paid, requires Storybook |

---

## 5. Three instruction layers (how they coexist)

- **Instruction file / memory** — agent behavior, workflow, guardrails (what
  to do).
- **`frontend-design` SKILL** — universal design philosophy and anti-generic
  thinking (how to think about UI). On-demand.
- **`DESIGN.md`** — project-specific visual constraints and tokens (our
  concrete values). Read automatically.

On a UI task: the SKILL gives "how to think", `DESIGN.md` gives "our tokens".
Run both (see `[[playbook]]` § Design system).

---

## 6. Component reuse

- **Atoms — one component + variants, not copy-pasted styles.** Button /
  Input / Card are defined once (shadcn primitive + CVA variants
  `primary/secondary/ghost/destructive`). A specific use is a variant, not a
  new component: "Save" = `<Button variant="primary">Save</Button>`, NOT
  `<SaveButton>`. UI is never styled inline bypassing the primitive.
- **Compositions — rule of three.** A repeating *bundle* (a "Cancel + Save"
  row, a product card) is extracted into a component when it appears for the
  3rd time. Earlier than that — don't proliferate.
- **Semantic actions** (Save/Cancel/Delete) are consistent by convention: one
  variant + an icon + an action label (recorded in DESIGN.md §4), not
  separate components.
- Conformance (is everything really from the system?) is checked at Verify →
  `[[playbook]]` § Design system.

---

## Sources

- Anthropic Claude Code Best Practices — **Anthropic official** — https://code.claude.com/docs/en/best-practices
- Anthropic frontend-design SKILL.md (GitHub) — **Anthropic official** — https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md
- Anthropic Blog: Improving Frontend Design Through Skills — **Anthropic official** — https://claude.com/blog/improving-frontend-design-through-skills
- DESIGN.md standard — https://betterstack.com/community/guides/ai/design-md-ai/ , https://emelia.io/hub/design-md-ai-agents-standard
- Three layers (AGENTS/SKILL/DESIGN) — https://dev.to/aws-builders/agentsmd-skillmd-designmd-how-ai-instructions-split-into-three-layers-d0g
- Brad Frost — Themeable Design Systems — https://bradfrost.com/blog/post/the-many-faces-of-themeable-design-systems/
- Tailwind `@theme` — https://tailwindcss.com/docs/theme
- Anti-generic AI UI — https://alexlavaee.me/blog/lessons-learned-designing-with-ai/
