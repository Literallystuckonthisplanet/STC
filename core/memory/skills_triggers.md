---
name: skills-triggers
layer: memory            # lazy reference — read when choosing a skill
scope: global
description: "Skills — descriptions and nuances. LAZY: read when selecting a skill. The summary 'which skill when' table lives in pev.md § Skills (always-context)."
---

**This file holds skill details (lazy).** The summary table "which skill when"
lives in `pev.md` § Skills (always-context). Here — nuances absent from that
table.

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

**`zoom-out`** — returns a map of modules/calls in the language of the domain
glossary. Uses the project's `CONTEXT.md` / glossary — if absent, it works
more coarsely. Can be self-launched — in the main thread before the Plan step
2, and added to agent/worktree prompts in an unfamiliar area.

**`grill-me`** — ask questions one at a time; the user answers the business
ones, the agent takes the technical ones. Convergent (removes ambiguity).
Relation to Council → see the council skill.

**`improve-architecture`** *(from `improve-codebase-architecture`)* —
strategy (the whole base), unlike a code review (tactics, a diff). Surface
**deepening opportunities** (small interface, large implementation).
Condition: a domain glossary (`CONTEXT.md`) should exist before the first run.
Cue for the user: "it's been a few large tasks — time for an architecture pass?"

**`handoff`** — saves into `${HANDOFFS_DIR}/`, filename `YYYY-MM-DD-topic.md`.

**`save-and-compact`** — steps: 1) session review 2) update the project's
tuning-pending notes 3) save new facts 4) flush infra docs to the doc backend
(incremental; skip if infra wasn't touched) 5) report. After it — the user
runs the harness's compact command. The `stop_services_reminder.sh` hook (H03,
UserPromptSubmit) catches trigger phrases and reminds:
- "compress/compact the session", "compact the context", "save and compact",
  "compacting", "time to compact", etc.
- On the phrase "wrap up the session" it unfolds the session-end protocol
  (save → stop services).
- Also scans the prompt for a secret (I05b) → directive to write it to
  `${SECRETS_ENV}` first.

**`prototype`** — a throwaway artifact for a decision: the user sees something
concrete instead of hearing a description. Two modes: LOGIC (a tiny terminal
app that drives a state machine) / UI (several radical variations on one
route). Suggested pitch: "make a prototype? 30 minutes, you'll see it
concretely".

**`caveman`** — final answers to the user are ALWAYS in normal mode;
compressed style is only for inter-agent traffic in pipelines.

**`to-spec`** — a `.md` spec in `${DOCS_ROOT}/specs/`: use cases + AC + ADR +
buy-vs-build (DEP-4) + abuse-cases + failure-modes + a block-plan. Source of
truth = the file (the doc backend is a view). Launch — after Plan-step 4 of a
large task, before the Do phase.

**`to-tasks`** — task lines in `${DOCS_ROOT}/tasks/<project>-tasks.md` with
inline fields (project/block/exec/priority). In the plan, items are tagged
`[agent]/[main]` → on transfer they become the **exec** field, Name = the
clean title. Launch — after finalizing the plan of a large task (block
encoding mandatory, exec optional); for a medium task — one line when taken
into work.

**`install-mcp`** — how to add an MCP server in the target harness (Claude:
`claude mcp add`; ZCode: edit `.mcp.json`). Includes scope table and the
error table.

**`code-graph`** *(graphify CLI, REQUIRED)* — turn a codebase into a queryable
knowledge graph (build once, query on demand — the graph compounds, grep does
not). graphify `${G} ingest` on first contact with a repo → `query`/`explain`
to orient, `affected "<node>"` for a change's blast radius before a refactor,
`save-result` after a good Q&A for the feedback loop. Part of the STC base
set, like Playwright for e2e. Wraps the graphify CLI (`${GRAPHIFY_CLI}`).

**`llm-wiki`** *(Karpathy pattern, Ingest+Query+Lint)* — compile knowledge
ONCE into a maintained markdown wiki, not re-derive it on every query like
RAG ("no accumulation"). Three operations (Ingest integrates a source into
~10–15 wiki pages + updates `index.md`/`log.md`; Query synthesizes with
citations and files good answers back; Lint health-checks contradictions/
stale/orphans/missing-links). Three layers: raw sources (immutable) / wiki
(LLM-owned) / schema (AGENTS.md). graphify `wiki`/`reflect` is the primary
implementation in STC (over a code graph).

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
to call them, so triggers are lifted into always-context (pev § Skills) or
into event-triggered hooks (ADR-001), and only details stay here.
