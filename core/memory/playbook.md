---
name: playbook
layer: memory            # lazy reference — read by anchor
scope: global
description: "Operational instructions — when/how to run agents, verification, restarts, stop commands, stack constraints, Playwright MCP, token economy, memory-style."
---

Read at the moment of action: before the Verify step, when launching agents,
when managing services, when creating a new project's instruction file, before
using Playwright MCP.

> **Note:** concrete commands below (`pnpm`, `docker`, `prisma`) are **examples**
> for a Node/TypeScript project. The actual commands come from the project's
> own instruction file or `package.json`. Replace per project stack.

## Known stack constraints
<!-- R02 -->

When creating a new project's instruction file, copy the relevant constraints
into its "Technical constraints" section. These are **examples** — record the
ones you actually hit in each project.

| Stack | Constraint |
|-------|-----------|
| **Zustand** | Do not subscribe to methods (`s.has`, `s.contains`) — stable reference, no re-render. Use a computed value: `s.ids.includes(id)` |
| **VK OAuth + Auth.js v5** | VK does not support PKCE → add `checks: ['state']` to the provider, or you get "Code challenge method is unsupported" |

## Static checks

- `.py` → `python3 -m py_compile file.py`
- `.yaml` → `python3 -c "import yaml; yaml.safe_load(open('file'))"`
- `.json` → `python3 -c "import json; json.load(open('file'))"`
- TypeScript → `pnpm tsc --noEmit` (or the project's type-check command)
- Lint → `pnpm lint` (or the project's lint command)

## Dynamic checks (tests)

Commands come from the project's instruction file or `package.json`. Typical:
- `pnpm test` / `pnpm vitest` — unit/integration tests
- e2e — only through the e2e sub-agent (do **not** run `pnpm playwright test`
  directly — headless Chromium is not installed on this machine; the e2e
  agent drives the user's real browser via Playwright MCP)

### After unit/integration tests (even if all passed)

Scan the output for:
- `console.error` / `console.warn` calls inside tests
- framework deprecation warnings
- unexpected messages that are not test failures

### After e2e scenarios (each scenario)

After a scenario passes, call `browser_console_messages` and check the output
for:
- `error` — any JS errors, failed fetches, hydration errors
- `warn` — React/Next.js warnings, deprecations

These do not block a passing test, but record them as flags for review.

## Design system

Process/templates → `${TEMPLATES_DIR}/design-system/` (`process.md` — taxonomy
+ layered token model + tooling verdicts; `DESIGN.template.md` — brief +
anti-generic rules).

**Plan (UI task):** read `DESIGN.md` in the project root + invoke the
design-system skill. No `DESIGN.md` → first adopt the process (`process.md`),
do not generate UI on stock shadcn/Inter.

**Verify (UI) — anti-generic checklist:**
- [ ] no Inter / Roboto / system-ui (fonts from DESIGN.md §3)
- [ ] background is not solid white/gray
- [ ] one color dominance + accent (not equal-weight pastels)
- [ ] spacing on a custom scale (DESIGN.md §5)
- [ ] 1–2 staggered reveals, not scatter animations
- [ ] cross-check against Do's & Don'ts (DESIGN.md §7)
- optional: Playwright `toHaveScreenshot()` — baseline on first iteration,
  regression afterwards. Take the screenshot via Playwright MCP (not
  `pnpm playwright test` — Chromium not installed, see §e2e).

**Verify (UI) — conformance (is everything from the system), mid tier:**
- Linter (from project config): no hardcoded colors (`#hex`, `rgb()`, `oklch()`
  in components), no arbitrary Tailwind values (`p-[13px]`, `text-[#...]`), no
  inline `style` for visuals, no `font-family` bypassing tokens.
- Diff each UI task: reused an existing primitive (did not reinvent), all
  visual values from `@theme` tokens, a new component only by the rule of
  three (`design-system/process.md` §6).
- Sub-agent screenshot against DESIGN.md (do's/don'ts + reuse) — for LARGE UI
  (page/layout), not for pinpoint edits.

## Agent triggers

### security-arch
Run when touched:
- auth/middleware files (Next.js: `auth.ts`, `auth.config.ts`, `middleware.ts`
  — names differ in other stacks)
- OAuth provider, JWT config, password logic
- a new/changed route or endpoint (Next.js: `app/api/`)
- removing/changing auth guards on existing endpoints
- webhook handlers
- raw SQL or dynamic queries with user input
- new collections/tables holding personal data
- file upload endpoints
- third-party libraries with access to user data
- CORS, CSP headers, new secrets in env

NOT a trigger: UI, SEO, styles, copy, data-import scripts.

### e2e sub-agent
Run when:
- a change touches behavior in any user scenario
- middleware / layout / root routing → e2e always

NOT a trigger: purely visual (styles, colors, spacing) → Playwright + the
verify skill is enough.

**Three e2e channels (FR-22) — pick by the task:**
1. **CLI** (default, cheap): the project's CLI command (e.g. `pnpm test:e2e`).
   Use for regression / repeat runs. The system Google Chrome
   (`channel:'chrome'`) is the target if the bundled Chromium is unavailable.
2. **MCP + real browser in main** — only when you need the user's real session
   / saved credentials (the browser on `${CDP_PORT}`). Heavy: every
   snapshot/navigate/click drags the full a11y tree into context.
3. **e2e sub-agent** (isolation) — pure exploratory e2e; the sub-agent
   isolates the expensive output from the main context. CLI-first inside the
   sub-agent too.

**Hook:** H02 (playwright-mcp-guard) injects the channel choice once per
session + a preflight nudge to start the real browser if it's down.

### research agent (open questions)
Run when broad investigation is needed: strategy, technologies, market,
architecture options.
Add Council-framing to the agent prompt automatically → see the council skill.

### research agent (legal review)
Run when:
- collecting new personal data
- new third parties with access to user data
- new cookies or tracking
- new monetization or payment flows
- features where the user creates, publishes, or uploads content

The agent reads the project's instruction file (jurisdiction, business type,
list of legal documents), researches the law → reports what must be updated.
If there are no legal documents, tell the user explicitly — do not stay silent.

## Saving research

When a research task is done (the research agent, or any investigation with a
result), save the output as a **separate sub-page** in the doc backend:
- With a project → into that project's "Research" container.
- Without a project → into the "Research (no project)" branch.

Page: title = topic + date; body = research summary (markdown).

## Agent-driven verification outcomes

- Explicit violation → **STOP**, do not continue, report to the user.
- Gray area → flag to the user, decide together.
- All clean → continue.

## Agent descriptions

| Agent | What it does | What it does NOT do |
|-------|-------------|---------------------|
| **research** | Broad investigation: strategy, tech, market, legal | Does not write code. Open questions → Council-framing → council skill |
| **code-reviewer** | Architecture + code quality: patterns, coupling, correctness, readability | Does not hunt CVEs, not deep security audit |
| **security-arch** | Security audit of code: OWASP, logic flaws, auth patterns, injection | Does not check dependencies/packages |
| **security-deps** | CVEs in dependencies: npm/pnpm audit + WebSearch for HIGH/CRITICAL | Does not read code |

## Cascading restarts

| Change | Action |
|---|---|
| `.env` / `.env.local` | restart dev server |
| `package.json` (new dependency) | `pnpm install` → restart dev server |
| Prisma schema | `prisma migrate dev` (creates + applies migration + regenerates client) → restart dev server |
| `docker-compose.yml` | `docker compose up -d` (recreate containers) |

## Playwright MCP

Playwright MCP connects to the user's **real browser** via CDP — not headless.
**Pick the channel by the task** (see § e2e sub-agent for the three channels):

- CLI (`pnpm test:e2e`) — the cheap default for regression/repeat.
- MCP + real browser in main — only for credentials / saved session
  (`${CDP_PORT}`).
- e2e sub-agent — for pure exploratory e2e (isolation).

**When you do use MCP:**
- Warn the user before launching: the browser theme may reset for the session.
- Right after the task, close it: `browser_close` — close **even on error or
  interruption**, do not leave the CDP session open.
- reCAPTCHA is not solved automatically → hand to the user (exception to
  SELF-EXEC).
- Do not use Playwright if the task can be solved without a browser.
- **Economy:** prefer `browser_snapshot` (text/a11y tree — cheap, usually
  enough for clicks/checks). `browser_take_screenshot` — only when you
  actually need the visual (layout, visual bug).

## Stop commands

| Service | Command |
|---|---|
| Dev server / `pnpm dev` | `kill $(lsof -ti:PORT)` |
| Docker Compose | `docker compose stop` (not kill!) |

## Doc backend — vault model (local-first)

The doc backend is **markdown-local-first**: the `.md` files are the single
source of truth; an editor (e.g. Obsidian in vault mode over the backend
root) is a **view**. No external sync layer (the Notion pipeline is retired).

**Structure** (`${DOCS_ROOT}`):
- `Home.md` — the MOC, the vault entry point (from `templates/vault/Home.md`).
- `memory/` — the global memory files (rules/playbook/catalogs) with
  `[[wiki-links]]` and frontmatter `aliases` (resolve dash-slugs → underscore
  files, so the graph has no phantoms).
- `specs/` — feature specs (`_specs-index.md` Dataview view + `_spec-template.md`).
  AC live as a `- [ ] #ac` checklist inside each spec.
- `tasks/` — task files per project (`Board.md` Dataview view). A task = a
  `- [ ]` line with inline Dataview fields (project/block/exec/priority).
- `infra/` — the **infra graph**, auto-generated (see below).

**Navigation.** Open the Graph view (Ctrl/Cmd+G): the `[[...]]` links + the
`aliases` + the `infra/` tags cluster by type/loading. A code-label (I/S/A/H/
R/T/N) is a node, with edges to its Related functions.

**When to sync (infra docs):** the infra graph regenerates from the code-labels
in the files — so after any global-infra change (a rule, a command, an agent,
a hook, a template, a code label, an MCP server) → regenerate `infra/`:
1. `python3 core/scripts/infra_graph.py --check` — review orphan codes,
   numbering gaps, duplicates; resolve.
2. `python3 core/scripts/infra_graph_render.py` — rewrite `infra/` (idempotent
   — the folder is rewritten on each run).
3. The `infra/00-infra-index.md` hub re-lists everything by type.
**Project tasks (`to-tasks`) and specs (`to-spec`) are NOT this** — they are
timely, per-task: write them when taken into work / after planning. Do not
defer them to a "resync".

**Guarantees:**
- Source of truth = the code-labels in the core files. `infra/` is a reflection.
- A **new function** = put a label (`<!-- Xnn -->` in md / `# Xnn — hook: …`
  in sh) → add an edge to `RELATED` in `infra_graph.py` (what it connects to)
  → re-render. A non-standard name → add it to `NAME_OVERRIDE`.
- Deleted a function → remove the label → re-render (its note disappears).
- A retired rule (ADR-001, migrated to a hook) → register in
  `reference_retired_codes.md` so it is not an orphan / does not gap the
  numbering.
- Checks (orphan / gap / dup) are run by `infra_graph.py --check`; the
  `infra-audit` skill runs the full pass on its monthly cadence.

## Token economy

The main loop = the main model + persistent context (every file is paid for
every turn + recompressed on compact). Levers are placed where they fire:

**Fire by anchors in always-context (PEV):**
- **Offload reading (lever #1):** heavy reading/search/analysis → an
  ephemeral agent (mechanics: cheaper model + caveman, judgment: main model),
  in main — only the summary.
- **Cheap session:** a task cannot go to an agent (needs dialogue) but a
  cheaper model can handle it → write the brief (what/why/files/AC/steps)
  into the project's `project_<name>.md` OPEN section (I26 — the next
  session reads STATE/OPEN on start) + a prompt; the user opens a session
  on the cheaper model. Pays off for medium+ tasks with low judgment risk.
- **Compression at the task boundary** (see pev §3).

**Self-enforcing (no need to remember — built in):**
- **Model tier** — in the agent's frontmatter. When spawning, do not pass
  `model` → the frontmatter applies.
- **caveman** — in agents whose output is facts (research/docs/security-deps).
  Reviewers (code-reviewer/security-arch/qa) — WITHOUT caveman (need
  reasoning). caveman compresses output, not thought.
- **Snapshot over screenshot** — §Playwright MCP.

**Habits (best-effort, discipline, not hard rules):**
- Do not edit always-files mid-session (kills prompt-cache) → batch, sync once.
- Read in ranges (`Read offset/limit`), refer as `path:line`, do not paste walls.
- Do not re-read unchanged files (the harness tracks state); do not verify an
  `Edit` with a `Read`.
- Background = fire-and-forget + one check.
- Use `SendMessage` for follow-ups/deltas to a live agent (warm context;
  works for worktree agents too) — do not respawn; a new spawn only for
  independence or a different type.

## Memory-instruction style

When writing/editing rules in always-context files:
- Format: `situation → action`, imperative, brief. One thought per line.
- Do NOT put in always-context: `Why:`, history ("we got burned twice"),
  worked examples, `How to apply:`.
- Need justification/history → move to a lazy file or delete (if the lesson is
  already baked into the wording).
- Always-context = instructions, not explanations. Explanations are expensive
  — read every session.
- **When moving to lazy, move ONLY the explanation/examples/details. The action
  itself (`situation → action`) stays in always** — otherwise the rule stops
  firing (lazy is not always read). Do not move the executable instruction
  wholesale into lazy; only its detail.

**Firing test — run before saving ANY rule (mandatory):**
1. **Trigger:** what situation fires the rule?
2. **Location:** where will I be at that moment — is the trigger in an
   always-file or at the decision point (a PEV step, an agent frontmatter, a
   hook, a §-section I will definitely read by anchor)? If the action is only
   buried in lazy without an anchor at the decision point → it will NOT fire.
   Lift the trigger into always / to the decision point.
3. **Type — mark honestly:** firing-rule (needs an anchor) / self-enforcing
   (built into config: frontmatter, settings, hook) / habit (best-effort, on
   discipline). "Wrote it down" ≠ "it fires".

## SELF-EXEC patterns

Extracted from always-context (I10). Concrete "instruction to user → correct
(do it yourself)" patterns; violations are recorded:

| Situation | Forbidden | Correct |
|---|---|---|
| Need Docker | "run `docker compose up`" | Run it yourself via Bash |
| A value for .env obtained | "insert into .env.local" | Write it to the file yourself |
| Need dependencies | "run `npm install`" / "run `pip install`" | Run it yourself via Bash |
| Config changed | "restart the service" | Restart it yourself |
| Need a UI action | "place a test order" | Do it via Playwright MCP |

## Worktree checks

Extracted from always-context (I07).
- **Inside a worktree agent (before close):** the agent reads the project's
  instruction file automatically — it has links to memory with check rules.
  Do not run e2e inside the worktree — only in main after merge.
- **In main after merge:** run the full check cycle on
  `git diff main...branch --name-only`. Repeat even if the worktree agent
  already checked — a combination of several changesets creates problems none
  had alone.

## Homoglyphs

Extracted from always-context (I12). Latin ↔ Cyrillic pairs that systematically
corrupt long ASCII strings: `B`↔`Б`, `a`↔`а`, `e`↔`е`, `o`↔`о`, `p`↔`р`,
`c`↔`с`, `x`↔`х`, `y`↔`у`, `H`↔`Н`, `K`↔`К`, `M`↔`М`, `T`↔`Т`. One
substitution silently breaks the whole string.

## Agent baseline (accepted/out-of-scope problems)
<!-- I20 -->

A reviewer agent (security-deps / qa / code-reviewer / e2e / security-arch)
will re-report problems you already deliberately accepted. Prevent that with a
**baseline** kept in the repo:

- The agent reports a deliberately-accepted or out-of-scope problem → record
  it in the repo's baseline file (with a "why accepted" note).
- On the next agent launch → pass the baseline in the prompt (so it skips
  them). **Hook H04** nudges this if "baseline" is not in the prompt.
- A newly accepted problem from the report → append to the baseline.
- **Security HIGH/CRITICAL never go under baseline** — always a block.

The baseline lives where the project keeps it (a `BASELINE.md`, an ADR, a
section of the instruction file). Format: `code/file:line — issue — accepted
because <reason>`.

## Agent prompt contract
<!-- I21 -->

When delegating to a **build-capable** sub-agent (`general-purpose` / `claude`),
open the prompt with a contract — otherwise the agent starts cold and
reinvents what the repo already has. **Hook H04 blocks the launch** if the
`reuse-before-reinvent` marker is absent.

Contract preamble:
1. **zoom-out** — the agent reads the relevant area to get the lay of the land.
2. **reuse-before-reinvent** — grep/`Explore` how the concern is already done
   in the repo → reuse; a second way = only an explicit recorded decision.
3. **return contract** — what comes back: a `file:line` summary, not raw
   output; an answer ≤ 1500 tokens (tight; this is inter-agent traffic).
   Caveman-compressed if `${SUBAGENT_COMPRESSION}` is on.

For **reviewer** agents (security-deps/qa/code-reviewer/e2e/security-arch):
add the **baseline** (see § Agent baseline) and any "accepted/out-of-scope"
context, so they don't re-report. They answer in normal prose (not caveman) —
the review needs precision.

## Verifying infra — structural ≠ functional
<!-- R07 -->

A structurally-clean hook/script/skill (syntax ok, dry-run paths exist, link
graph resolves) is **not** the same as a working one. Audit lesson (H11):
19/19 unit cases passed, but the hook failed live until a human found the bug
— the test inputs didn't match real tool-call shapes.

Two layers for any infra artifact:
1. **Structural** — `bash -n`, dry-run of the doc-backend generator, link
   integrity, matcher/path wiring, `${VARS}` resolve. Cheap, catches
   formatting drift.
2. **Functional** — run the artifact under a realistic stdin (the smoke tests
   in `core/hooks/` cover the block/pass/inject branches of H01 and H05);
   confirm the `additionalContext` JSON actually shapes the model's behavior.

The `infra-audit` skill runs both on its monthly cadence. Don't claim "fixed"
or "works" from the structural layer alone.
