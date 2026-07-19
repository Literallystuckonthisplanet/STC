---
name: skills-triggers
layer: memory            # lazy reference — read when choosing a skill
scope: global
description: "Skills — the 'which skill when' trigger summary table + per-skill descriptions and nuances. LAZY: read when selecting a skill. pev.md § Skills carries only a one-line pointer here (keeps always-context lean)."
---

**This file holds the skill trigger summary table + per-skill details (lazy).**
Read it when selecting a skill. `pev.md` § Skills keeps only a one-line pointer
to this file, so the always-context stays lean (detailed tables → lazy, per
playbook § Memory-instruction style).

## Trigger summary — which skill, when

| Skill | Moment / trigger | Who initiates |
|---|---|---|
| `diagnose` | a bug/regression ("it broke", "not working") | I do, after asking "what's the pass/fail loop?" |
| `zoom-out` | starting work in unfamiliar code (before Plan step 2); also folded into agent/worktree prompts (build-agent contract, `reuse-before-reinvent` → playbook § Agent prompt contract) | I do |
| `grill-me` | a large task with ≥3 open forks, before Plan step 4 | I offer it to the user |
| `tdd` | business logic (calculations/validation/transforms), Do phase | joint decision (Plan step 3) |
| `code-review` | reviewing a diff that contains logic (tactics) | I do |
| `verify` | the change is UI/style only | I do |
| design system | a UI task: before generating (Plan) + anti-generic check at Verify | I do |
| `improve-architecture` | roughly every 3 completed large tasks (strategy, whole codebase) | I offer it to the user |
| `prototype` | "show me options", "which is better", "compare approaches" | I offer it to the user |
| `to-spec` + `to-tasks` | large: spec + tasks (after the plan is finalised); medium: tasks only (when taken into work) | I do |
| compact / session-end | "compact/save the context", session end (a hook reminds) | I do |
| `caveman` | "briefly", "fewer tokens"; agent pipelines | the user, or I in sub-agent prompts |

Agent checks (`code-reviewer`, `security-arch`, `e2e`, `security-deps`, legal
review) — see pev § Verify / § Agent triggers below in this file.

Installed commands live in `${COMMANDS_DIR}/`. Built-in harness skills
(verify, code-review, simplify, run, schedule, loop, etc.) are not duplicated
here — their triggers are in the harness's own list.

> Note: STC keeps its own independent skills in `core/` (Decision 4,
> `docs/PROGRESS.md`). Where an external source (e.g. the `superpowers`
> plugin) has an analog, the STC skill is merged from the best of both and is
> self-contained — STC does not depend on the external at runtime. Check
> upstream drift monthly via `infra-audit`.

## Skill nuances
<!-- R04 -->

**`diagnose`** *(STC self-contained, merged: the user's feedback-loop
methodology + `superpowers/systematic-debugging`)* — the first question
BEFORE any action: "what is my pass/fail loop?" (how do I reproduce the bug
fast and deterministically). Only then the diagnostic cycle. The 3-fail
escalation: ≥3 failed fixes → question the architecture, don't attempt fix #4.

**`tdd`** *(STC self-contained, merged: the horizontal/vertical-slice
methodology + `superpowers/test-driven-development`)* — red-green-refactor,
vertical tracer bullets (NOT all-tests-then-all-code). The iron law: no
production code without a failing test first; delete means delete.

**`worktree`** *(STC self-contained, merged: the path-discipline + git-ops +
`superpowers/using-git-worktrees`)* — detect existing isolation first (Step 0),
prefer native harness worktree tools, fall back to git worktree, safety-verify
the dir is gitignored.

**`docs`** *(Context7, vendor-neutral)* — current library/framework docs
through Context7 (a global knowledge base for AI agents, any library). The
docs-first channel — use it BEFORE coding against a library API. Hook H10
(read-first router) nudges it on integration/payment/webhook files.

**`code-review`** — the built-in adversarial review (Boris Cherny: the same
pass Anthropic runs on its own PRs), **free** at effort levels
`low`/`medium`/`high`/`xhigh`: low/medium give fewer high-confidence findings,
high/xhigh broaden coverage. Default for a diff with logic → `/code-review
xhigh`. It **complements** the ×3 agent pipeline (`code-reviewer` +
`security-arch` + `qa`), does not replace it — those read the code fresh with
no context, deliberately. **`ultra` is PAID** (cloud multi-agent) — do **not**
offer it (budget = subscription). Ties to `effortLevel` in settings.

**`zoom-out`** — returns a map of modules/calls in the language of the domain
glossary. Uses the project's `LANGUAGE.md` / `CONTEXT.md` glossary — if
absent, it works more coarsely. Can be self-launched — in the main thread
before the Plan step 2, and added to agent/worktree prompts in an unfamiliar
area.

**`grill-me`** — ask questions one at a time; the user answers the business
ones, the agent takes the technical ones. Convergent (removes ambiguity).
Relation to Council → see the council skill.

**`improve-architecture`** *(from `improve-codebase-architecture`)* —
strategy (the whole base), unlike a code review (tactics, a diff). Surface
**deepening opportunities** (small interface, large implementation).
Condition: a domain glossary (`CONTEXT.md`) should exist before the first run.
Cue for the user: "it's been a few large tasks — time for an architecture pass?"

**Compact / session-end** (no separate command — lives in `session.md` §3,
triggered by H03). The `stop_services_reminder.sh` hook (H03, UserPromptSubmit)
catches trigger phrases:
- "compress/compact the session", "compact the context", "save and compact",
  "compacting", "time to compact", etc. → first save memory per behavior.md §
  Memory rotation (I26), then tell the user to run `${COMPACT_CMD}`.
- On the phrase "wrap up the session" it unfolds the session-end protocol
  (rotate memory → stop services).
- Also scans the prompt for a secret (I05b) → directive to write it to
  `${SECRETS_ENV}` first.

**`prototype`** — a throwaway artifact for a decision: the user sees something
concrete instead of hearing a description. Two modes: LOGIC (a tiny terminal
app that drives a state machine) / UI (several radical variations on one
route). Suggested pitch: "make a prototype? 30 minutes, you'll see it
concretely".

**`caveman`** — final answers to the user are ALWAYS in normal mode;
compressed style is only for inter-agent traffic in pipelines.

**`to-spec`** — a `.md` spec in `${DOCS_ROOT}/specs/`: use cases + AC
(checklist tag `#ac`) + ADR + buy-vs-build (DEP-4) + abuse-cases +
failure-modes + a block-plan. Source of truth = the file (the doc backend is
a view). Launch — after Plan-step 4 of a large task, before the Do phase.

**`to-tasks`** — task lines in `${DOCS_ROOT}/tasks/<project>-tasks.md` with
inline fields (project/block/exec/priority). In the plan, items are tagged
`[agent]/[main]` → on transfer they become the **exec** field, Name = the
clean title. Launch — after finalizing the plan of a large task (block
encoding mandatory, exec optional); for a medium task — one line when taken
into work.

**`install-mcp`** — how to add an MCP server in the target harness (Claude:
`claude mcp add`). Includes scope table and the
error table.

**`code-graph`** *(graphify CLI, REQUIRED)* — turn a codebase into a queryable
knowledge graph (build once, query on demand — the graph compounds, grep does
not). graphify `${G} extract .` on first contact with a repo (build; there is
no `ingest` command in 0.9.x) → `query`/`explain` to orient, `affected
"<node>"` for a change's blast radius before a refactor,
`save-result` after a good Q&A for the feedback loop. Part of the STC base
set, like Playwright for e2e. Wraps the graphify CLI (`${GRAPHIFY_CLI}`).

**`llm-wiki`** *(Karpathy pattern, Ingest+Query+Lint)* — compile knowledge
ONCE into a maintained markdown wiki, not re-derive it on every query like
RAG ("no accumulation"). Three operations (Ingest integrates a source into
~10–15 wiki pages + updates `index.md`/`log.md`; Query synthesizes with
citations and files good answers back; Lint health-checks contradictions/
stale/orphans/missing-links). Three layers: raw sources (immutable) / wiki
(LLM-owned) / schema (AGENTS.md). Over a code graph the pattern is realised via
graphify `add`/`query`/`reflect` (no single `wiki` command in 0.9.x).

## git guard (a hook, not a skill)
<!-- H01 -->

Active globally via the `/git-guardrails` command. One script
(`block-dangerous-git.sh`), three responsibilities:
- 🔒 Dangerous patterns: `reset --hard`, `clean -f/fd`, `branch -D`,
  `checkout .`, `restore .` → hard block.
- 🔒 Push to `main`/`master` = release (I08) → blocked without a one-shot ack
  marker (the user says "releasing" → security-deps → `touch ${RELEASE_ACK_FILE}`
  → push passes once).
- 💉 Before every `git commit` → JIT-inject the verify-checklist + commit
  invariants (I17/I09, FR-5); `--no-verify` gets an extra reminder.

File: `${HOOKS_DIR}/block-dangerous-git.sh`. Full hook map + the
`additionalContext` mechanism + the acknowledge-once pattern →
`core/hooks/README.md`.

**Why:** skills without a clear launch moment die — the user does not remember
to call them, so the trigger summary lives here (§ Trigger summary, pointed to
from pev § Skills) or triggers move into event-triggered hooks (ADR-001).
