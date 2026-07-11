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
- **e2e — CLI-first: the project's `pnpm test:e2e`** (Playwright CLI, a
  codified suite). Only pass/fail reaches context (reporter `line`/`dot`) —
  ~0 a11y trees. A clean headless bundled `chromium`
  (`npx playwright install chromium`). MCP + real browser, or a sub-agent —
  only for a one-off visual check / exploration (see § e2e sub-agent — three
  channels).

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
- Playwright `toHaveScreenshot()` visual-regression — its own suite
  `pnpm test:visual` (tag `@visual`, excluded from `pnpm test:e2e`). Baseline
  on the first iteration (`pnpm test:visual:update`, in the canonical
  environment: docker up + `.env.local` + dev server), regression afterwards
  runs cheap in the shell; an intentional redesign → re-`--update` + commit
  the new baseline. A one-off visual check by eye → MCP via a sub-agent (see
  § Playwright MCP).

**Need a value outside the scale → decision-tree**
(`design-system/process.md` §7): (1) a token already exists → use it;
(2) reusable → add a token (mini-review, document in DESIGN.md); (3) a one-off
deliberate exception → an arbitrary/inline value **only** with the marker
`// ds-exception: <reason>`. The marker is the escape-hatch for the linter
[STYLE-6] and a visible trace in git. Neither a token nor a justification →
do not hardcode.

**Verify (UI) — conformance (is everything from the system), mid tier:**
- Linter (from project config, see the code standard [STYLE-6]): no hardcoded
  colors (`#hex`, `rgb()`, `oklch()` in components), no arbitrary Tailwind
  values (`p-[13px]`, `text-[#...]`), no inline `style` for visuals, no
  `font-family` bypassing tokens. Exception — only a line with
  `// ds-exception: <reason>` (§ decision-tree above).
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
   snapshot/navigate/click drags the full a11y tree into context (measured on
   one project's history: ~714k tokens total, ~4.9k/snapshot, max 43k).
3. **e2e sub-agent** (isolation) — pure exploratory e2e; the sub-agent
   isolates the expensive output from the main context. CLI-first inside the
   sub-agent too.

MCP is not for regression. A MCP scenario that passed and is worth keeping →
codify it into the CLI suite (channel 1), do not re-run it via MCP.

**Hook:** H02 (playwright-mcp-guard) injects the channel choice once per
session + a preflight nudge to start the real browser if it's down.

### cleanup agent (mechanical edits)
Run when the edit is **uniform, bulk, spec-in-hand** and low-judgment:
- codemod / rename a symbol across the repo
- clean existing code to the standard (violations already surfaced by the
  linter / `code-reviewer` — the agent only applies the list)
- a batch of one-class lint fixes across many files
- the execution half of a lean-review: the edit list exists → hand it here.

Flow: **what to change** is decided by the parent / linter / reviewer
(judgment) → **applying it** is the cleanup agent (mechanics, `haiku`). The
prompt MUST carry the literal `reuse-before-reinvent` (build-agent, enforced
H04) + an enumerable edit spec.
NOT a trigger: the edit touches business logic / architecture / behavior, or
the scope is fuzzy → do it in main or via a worktree agent on `sonnet`. This
is the `sub-haiku` tier of the exec-slice (pev Step 4, FR-27).

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
<!-- FR-16 -->

A research task finishes (the `research` agent, or any investigation with a
result) → save it **local-first** in `memory/notes/research/` (not the doc
backend):
1. Copy `notes/research/_TEMPLATE.md` → `YYYY-MM-DD-<kebab-topic>.md`.
2. **The brief is a delta:** the file holds only the delta vs. the baseline
   (what's new / adopted / rejected + why). Do not copy the agent's or pages'
   raw material into it — that was transient, it lived in context only. Mark
   trust per claim: ✅ verified / ⚠ unverified.
3. Add a row to the TOP of the table in `notes/research/00-index.md` (the
   registry: date · topic · project · delta · trust · cost · file). FR-21:
   cost = `python3 core/scripts/agent_cost.py --latest` right after the
   research agent finishes (not a manual cost check — that is cumulative for
   the whole session, not the agent run).

Registry + rules → `notes/research/00-index.md`.

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
| **cleanup** | Executor of mechanical edits against a READY spec: codemod, rename across the repo, cleanup to standard, a batch of lint fixes + static verification | Does NOT decide what to change (that's the parent/linter/reviewer), does not touch business logic, does not change behavior |

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

**Starting the real browser (CDP):** an IDE-extension integration does not
auto-launch the browser with CDP enabled — start it manually before the
first MCP call of the session:
```bash
<browser-binary> --remote-debugging-port=${CDP_PORT} --no-first-run --user-data-dir=/tmp/cdp-profile &
# verify:
curl -s http://localhost:${CDP_PORT}/json/version | python3 -c "import json,sys; print(json.load(sys.stdin).get('Browser'))"
# after the task:
kill $(lsof -ti:${CDP_PORT})
```
A desktop-app integration (not an IDE extension) may open CDP automatically —
check first before running the manual bootstrap.

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
  in main — only the summary. **Return contract:** the finding + `file:line`,
  NOT file contents and NOT raw search results.
  - **Enforcement (hook H15, exec-offload-guard):** hard-blocks expensive
    Bash in main — (a) a noisy data-script (import/seed/publish/scrape/
    sync/backfill) and (b) an `audit` run without `--json` → offload it to an
    ephemeral cheap-model agent (runs it, returns the result/errors/counters,
    not the raw stdout). A deliberate run in main → the marker `# in-main` on
    the command. Most output-triage into the window is already held by the
    output-hygiene hook (H11 — collapses raw output yourself or via an
    agent); H15 closes the residual case of "the command itself prints a
    wall of text."
- **Cheap session:** a task cannot go to an agent (needs dialogue) but a
  cheaper model can handle it → write the brief (what/why/files/AC/steps)
  into the project's `project_<name>.md` OPEN section (I26 — the next
  session reads STATE/OPEN on start) + a prompt; the user opens a session
  on the cheaper model. Pays off for medium+ tasks with low judgment risk.
- **Compact by context fill, NOT at every task boundary** (see pev §3).
  Mechanics: every turn resends the whole context; the stable prefix is
  cached (~10% of the price, TTL ~5 min while you keep working). Compacting
  BREAKS the cache + re-reads everything for the summary + reloads all rules
  uncached (~8.7k tokens) — there is a prepayment cost. A new session = a
  cold cache + the same reload. Hence the thresholds (`/context`):
  - **<~40% (≈<80k):** don't compact. Small tasks accumulate in the cached
    prefix at ~10% — cheap; compacting here loses money.
  - **~40–75%:** compact only if the next task is UNrelated to the current
    context (drop the ballast); related → keep going.
  - **>~75% (≈>150k):** always compact, via your own compact-and-save
    (memory saves correctly) — don't wait for a blind auto-compact to catch
    you.
  A new session instead of compacting — only when the work is fully
  independent AND otherwise you'd drag along a large irrelevant context.

**Self-enforcing (no need to remember — built in):**
- **Model tier** — in the agent's frontmatter (docs/security-deps = haiku;
  reviewers = sonnet). When spawning, do not pass `model` → the frontmatter
  applies.
- **caveman** — in agents whose output is facts (research/docs/security-deps).
  Reviewers (code-reviewer/security-arch/qa) — WITHOUT caveman (need
  reasoning). caveman compresses output, not thought.
- **Snapshot over screenshot** — §Playwright MCP.

**Habits (best-effort, discipline, not hard rules):**
- Do not edit always-files mid-session (kills prompt-cache) → batch, sync once.
- Read in ranges (`Read offset/limit`), refer as `path:line`, do not paste walls.
- Do not dump bash output >~50 lines into the window without a filter: `wc -l`
  first, then `tail`/`grep`/`grep -A/-B`; 50 lines isn't enough → grep ~50 more
  with context, don't dump everything.
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

**Dedup + placement — run before a NEW rule:**
- **Dedup:** grep always+lazy by the concern's keywords. A match → extend or
  refine the existing rule, do not duplicate it (reuse-before-reinvent for
  rules — the parallel of [ARCH-6] in the code standard, but for rules). The
  same rule duplicated across more than one always-file is a violation the
  infra audit catches.
- **New file vs. extend:** a file = one concern. The concern matches an
  existing file's `description` → extend that file. A standalone concern, or
  one that cuts across several areas → a new file + an index-pointer line in
  MEMORY.md. Do not dump unrelated content into one file, and do not split
  one concern across several files.
- **Always vs. lazy:** an executable action (`situation → action`) → always;
  explanation/history/examples/detail → lazy (or delete, if the lesson is
  already baked into the wording).

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

**Hook header format — the same logic as for rules (self-documenting +
predictable).** Every hook script opens with a 4-part `#`-comment block:
1. **Identification (the format `infra_graph.py`'s `RE_SH_LABEL` parses):**
   `# Hxx — hook: <kebab-name> — <what it enforces> (FR-NN).` The `— hook:`
   token right after the code is mandatory — without it the generator can't
   see the label and the code becomes an orphan (this exact mistake has
   orphaned hook codes before). Next line: `# Event:
   <PreToolUse(matcher)|Stop|SessionStart|UserPromptSubmit>`.
2. **Pain/why:** 1-2 lines — why a hook and not always-text (what kept
   recidivising). Explanation is fine here — a hook file is not
   always-context, it doesn't cost session tokens.
3. **What it does:** list the BLOCK (`exit 2`) or INJECT
   (`hookSpecificOutput.additionalContext`) conditions concretely.
4. **Marker/bypass:** the once-per-X marker path (if any) + the escape
   condition (an override flag, an ack-marker) — OR explicitly "no bypass".

**Delivery mechanics to the model** (matters for part 3): on PreToolUse, bare
stdout does NOT reach the model — only the user sees it — so inject via
`hookSpecificOutput.additionalContext` (not a block) or `exit 2` on stderr (a
block); bare stdout only reaches the model on SessionStart/UserPromptSubmit.
Format examples: `output-hygiene-guard.sh` (H11, block),
`playwright_reminder.sh` (H02, inject). Full mechanics + the event-guard map
→ `core/hooks/README.md`.

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
2. **reuse-before-reinvent** — grep/`Explore` the repo for existing patterns
   (auth / data access / error handling / utilities / API response format /
   money & dates / id-SKU formats) → found it, reuse it; a second way to do
   the same thing = only with an explicit recorded justification.
3. **return contract** — what comes back: a `file:line` summary, not raw
   output; an answer ≤ 1500 tokens (tight; this is inter-agent traffic).
   Caveman-compressed if `${SUBAGENT_COMPRESSION}` is on.

**Read-only agents are exempt:** `Explore`/`research`/`code-reviewer`/
`security-*`/`docs`/`qa`/`e2e` don't write code, so they don't need the
preamble — the hook (H04) passes them through without checking.

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

Functional check, by artifact type:
- **A hook** — a live trigger (a real tool call, not just piping JSON into the
  script) + test cases from the real distribution (actual compound commands,
  `2>` redirects, pipes — not toy `cmd file` inputs). NB: a hook only becomes
  active from the NEXT session — until restart, say honestly "activates next
  session, not verified live" instead of claiming it works.
- **A rule (always/lazy)** — the firing-test above: does it actually fire at
  the real decision point?
- **An agent/skill** — a run on a real task, not a synthetic one.
- **A script** — on real data + edge cases (e.g. the doc-backend generator on
  the full label set, not on one label).

Principle: **verify infra as strictly as you verify code** (PEV applies to
rules/hooks/scripts, not just to projects); a false green is debt — don't
push defect discovery onto the user.

The `infra-audit` skill runs both layers on its monthly cadence. Don't claim
"fixed" or "works" from the structural layer alone.
