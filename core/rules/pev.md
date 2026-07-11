---
name: pev
layer: rules            # always-context
scope: global
---

# Plan → Do → Verify
<!-- I15 -->

Any non-trivial task goes through all three phases. Skipping Verify is the
most common failure mode — do not skip it.

## 1. Plan

Before touching code or files, produce a plan and get alignment.

**Step 1 — Clarify the task** *(M/L only; skip for small).*

The task is unclear until three things are explicit:
- Who faces the problem, and how often?
- What happens now (current behavior), and what should happen (desired)?
- How will we measure that it got better? (a concrete "done" criterion)

If any is missing, ask focused questions iteratively until all three are
explicit.

Red flag: a **solution named without a problem** ("add a button X", "install
tool Y"). Surface the problem BEFORE unpacking the proposal. Uncover the
job-to-be-done; do not run to google/install on a named solution.

But clarifying ≠ asking more questions. Ask the user ONLY about what is
theirs alone (decisions, context, priorities, threat-model). Verifiable
facts (git state, file contents, configs, what is installed) — get them
yourself (SELF-EXEC).

**Large intake:** the user dumps many tasks at once (session start) → split
into logical clusters → take ONE into work, leave the rest for the user to
run in parallel sessions. Do not pull several clusters into one session.

**Step 2 — Understand the code and context.**

- Read the relevant code, understand the current state.
- If you do not know or are unsure — say so directly. Never invent facts,
  details, data.
- Heavy reading (many files / searching the repo) → delegate to an ephemeral
  sub-agent (cheaper model + caveman), bring only the summary into context
  (token economy → playbook §Token economy).

**Step 3 — Evaluate the proposed solution.**

- Does it fix the cause, or the symptom?
- Is there a simpler path to the same result?
- Is the complexity proportionate to the value?
- **The TDD question:** is there business logic in this task (calculations,
  validation, data transforms)? Answer it yourself + raise it to the user →
  joint decision. If yes and agreed → `/tdd` in the Do phase.

If the solution is suboptimal, say so and propose an alternative:
> "[idea] won't solve [problem] because [reason]. I propose [alternative] —
> it gives [result] more simply/quickly."

Stop-pattern: agreeing with a request not because it is good, but because
you do not want to argue = **yes-man. Forbidden.** See also `buy-vs-build`
(DEP-4, enforced H14) — before building a non-trivial piece, evaluate a
ready-made solution first.

**Step 4 — Plan the execution.**

- **AC (acceptance criteria) are mandatory** for tasks with new
  functionality. The user writes them (BA/PO role); fix them together in
  this step. No AC → no task to execute.
- **Fix in the doc backend** (the agent starts this itself, not on command):
  **large** (after the plan + AC are finalised) → `/to-spec` (spec + AC) +
  `/to-tasks`, block-coding A0/B1 mandatory; **medium** (when taken into
  work) → `/to-tasks` (spec/AC — only if new functionality). Small — not
  tracked.
- **New ADR or plan item?** — decide whether the change needs a new ADR or a
  new plan entry → `project_docs.md`.
- For a **large** task, name the files you will touch and the verification
  you will run. If you cannot name them, you are not ready to start.
- **Design system (UI tasks):** a UI task → read the project's `DESIGN.md`
  before generating; map the element onto a token/scale, no token → add a
  token (not raw). No `DESIGN.md` yet → adopt the process first
  (`templates/design-system/process.md`), do not generate UI on stock
  defaults. Enforced nudge: H10 (DS branch). See playbook §Design system.
- **Legal review:** assess whether the planned features need one (triggers →
  playbook § research agent (legal review)). Needed → run a `research` agent
  BEFORE implementation;
  re-check by the triggers after. A clear violation → STOP, surface it.
- **grill-me / Council:** large task with ≥3 open forks → `grill-me` →
  `Council` → plan. Medium + uncertain → offer Council.
- A large task → ask clarifying questions + show the plan. After drawing it
  up, always say:
  > "Plan ready. Read it and check it is ideal. If you want to change it,
  > say so. I will not start coding until you approve."
- **Exec slice — who runs this (mandatory for M/L, per plan block).** Mark
  each block with its CHEAPEST safe executor so work doesn't default to main
  on the expensive model:
  - `sub-haiku` — mechanical, no judgment (repo search, applying a ready
    spec, template-wide edits, running scripts) → ephemeral agent.
  - `sub-sonnet` — judgment but isolated, no dialogue needed (review, tests,
    research, docs) → ephemeral agent.
  - `cheap-session` — needs dialogue with the user but low error-risk
    (routine feature on a ready spec, copy, configs). I prepare a brief file
    (what / why / files / AC / steps / stop-conditions + a link to
    project-memory); the user opens a sonnet session on it. No context lost.
  - `main` — architecture, open forks, high uncertainty. In doubt → main, but
    **write WHY main** (so "main by default" can't creep back silently).
  When showing a plan, present this as a table (block / size / executor /
  model) so the user sees what can move to a parallel cheap session before
  start. **Enforced: H14** — after plan mode the FIRST code edit is hard-blocked
  once until you produce the table (acknowledge-once; not a passive nudge).
  **Worktree parallelism is orthogonal:** an isolated block still gets a full
  spec + git-diff/test check regardless of tier.

## 2. Do

- Execute the plan one item at a time. Stay in scope — stray changes belong
  in a separate task.
- Changes go through the plan, not directly through code: update the plan →
  show → get approval → only then change code.
- A discovered constraint is new information; surface it and re-plan, do not
  paper over it.
- **TDD:** if Step 3 agreed on TDD → run `/tdd`. Red (write the test) →
  green (minimal code) → refactor. Only business logic (calculations,
  validation, transforms). UI, configs, copy — without TDD.
- Commit per task (see `behavior.md` § Commits).

## 3. Verify
<!-- I17 -->

Verification is mandatory before claiming "done". "Should work" is not
verification. Pick at least one method, matching the task:

| Kind | What it means | When |
|------|---------------|------|
| **static** | type-check, lint, build, dry-run | always available; cheap floor |
| **eyes** | re-read the diff against the task; read the changed output | always — do this even when tests pass |
| **dynamic** | run it: tests, dev server, the actual flow | when there is executable behavior |
| **agent** | dispatch a review/qa sub-agent for an independent check | M/L tasks, security-sensitive areas |
| **design-system** (UI) | anti-generic + conformance (everything from the system, reuse primitives) | UI tasks |

- For **L** tasks, run at least two kinds, one of which is `agent`.
- **Eyes checklist:** the diff has nothing extra (touched only what was
  asked, no drive-by edits to neighboring code); it logically matches the
  task; no hardcoded secrets/keys/passwords in the diff. For text content
  (posts, legal pages, descriptions) — no AI-tell markers, no factual
  errors.
- **Dynamic split:** the change contains **logic** → tests are mandatory (if
  missing, create them via the `qa` sub-agent, then run). The change is
  **UI/style only** → Playwright + the `verify` skill instead of tests.
- **Agent triggers (quick reference; full list → playbook.md § Agent
  triggers):** `code-reviewer` — the change contains logic (not for typos /
  style / copy / config with no logic). `security-arch` — auth / API /
  upload / personal data / CORS. `e2e` sub-agent — behavior in a user
  scenario / middleware / layout. `security-deps` — before every deploy;
  result STOP (HIGH/CRITICAL) blocks the deploy, report it. `research` agent
  (legal review) — data collection / third parties / monetization / UGC.
- A UI fix is "done" only when proven by **appearance** (before/after), not
  by "compiled / mounted without errors". Take a screenshot of the target
  element before (bug state) and after the fix → compare yourself: did the
  right element change, and does it match the design system.
- Report what you verified and the command you ran, not just "done". Read
  the actual command output before reporting success.
- **Verification failure** → diagnose → correct the plan → repeat. Max 3
  iterations, then → to the user.

Verify passed → commit (see `behavior.md` § Commits). Decision to compact
**by context fill**: <~40% do not compact (warm cache is cheaper); ~40–75%
compact only if the next task is unrelated to the current context; >~75%
compact always via your own `save-and-compact` (behavior.md § Memory
rotation) — do not wait for a blind automatic compaction. Memory safety is a
separate reason to compact — do not starve it for economy.

## Task scale
<!-- I16 -->

| Size | Criteria | PEV mode | Static | Eyes | Dynamic |
|------|----------|----------|--------|------|---------|
| **S** | 1 file. Typo, style, config, copy. | Verify only | if the extension has one (`.py`/`.yaml`/`.json`/`.ts`/…) | yes | — |
| **M** | 2–5 files, no architectural decisions. A component, a bug, an API endpoint. | Plan in head + Verify | yes | yes | logic → `qa` tests; UI → Playwright + `verify` |
| **L** | 6+ files / DB+API+UI / architectural decisions / deploy. | Full Plan→Do→Verify + show the plan | yes | yes | tests + Playwright + `verify` — all of it |

When in doubt → pick the more thorough mode. Agent checks fire by triggers
(see playbook), not tied to scale.

## Skills — when to launch

The "which skill, when" trigger summary table + per-skill nuances live in
`skills_triggers.md` (lazy — read it when choosing a skill). Kept out of
always-context on purpose (detailed tables → lazy). Agent checks
(`code-reviewer`, `security-arch`, `e2e`, `security-deps`, legal review) —
see § Verify above.

## When the loop does not apply

- Trivial, reversible single-line changes (a typo, a comment) can skip Plan.
  They still get Verify (eyes on the diff).
- Never skip Verify. If you cannot verify, say so explicitly rather than
  implying success.
