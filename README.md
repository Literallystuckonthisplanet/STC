# STC Core — Standard Template Construct

[![release](https://img.shields.io/github/v/tag/Literallystuckonthisplanet/STC?label=release&sort=semver&color=blue)](https://github.com/Literallystuckonthisplanet/STC/tags)
[![last commit](https://img.shields.io/github/last-commit/Literallystuckonthisplanet/STC)](https://github.com/Literallystuckonthisplanet/STC/commits/main)
[![license](https://img.shields.io/badge/license-AGPL--3.0%20%2B%20commercial-blue)](LICENSING.md)
![stack](https://img.shields.io/badge/stack-Python%20%C2%B7%20Bash-informational)
![harness](https://img.shields.io/badge/harness-Claude%20Code%20%C2%B7%20Codex-8A2BE2)

> _A Standard Template Construct stores the blueprints. The deploy pipeline reproduces them._
>
> In Warhammer 40k lore, an STC is a relic from the Dark Age of Technology — a terminal that holds complete, reproducible construction blueprints. You feed it a request, it emits a buildable design adapted to the materials at hand.
>
> This project borrows that idea. An AI coding agent (Claude Code, Codex, or any harness) works well when its instructions, memory, skills, hooks, and tools are consistent across sessions. STC holds the blueprints of that configuration. A deploy command reproduces them into the concrete harness you use, adapted to its format.

## Table of contents

- [What it is](#what-it-is)
- [Why: the three problems STC solves](#why-the-three-problems-stc-solves)
  - [1. Token economy](#1-token-economy)
  - [2. Knowledge across sessions and providers](#2-knowledge-across-sessions-and-providers)
  - [3. SDLC via SDD → TDD](#3-sdlc-via-sdd--tdd)
- [Guiding principles](#guiding-principles)
- [Abstraction layers](#abstraction-layers)
  - [The four directories](#the-four-directories)
  - [The two axes: Harness × Provider](#the-two-axes-harness--provider)
  - [Capability ≠ realisation](#capability--realisation)
  - [Always-context vs on-demand](#always-context-vs-on-demand)
- [Third-party tools and credits](#third-party-tools-and-credits)
- [The 21 hooks](#the-21-hooks)
- [The rules (always-context)](#the-rules-always-context)
- [Memory structure](#memory-structure)
- [Offline transcript memory pipeline](#offline-transcript-memory-pipeline)
- [Skills, agents, commands](#skills-agents-commands)
- [The deployer and the renderer](#the-deployer-and-the-renderer)
  - [CLI commands](#cli-commands)
  - [Scenarios the deployer handles](#scenarios-the-deployer-handles)
  - [The renderer pipeline](#the-renderer-pipeline)
- [Quickstart](#quickstart)
- [Testing](#testing)
- [Repository layout](#repository-layout)
- [Status](#status)
- [License](#license)

## What it is

STC is a **template-construct pipeline for AI agent infrastructure**. It is not a single harness's config — it is the source of truth that generates one or many harness configs.

You write your agent's behavioral rules, memory, skills, hooks, commands, and tool bindings **once**, in a harness-neutral form, in `core/`. You declare how each target harness realises them in `adapters/`. A Python deploy command renders `core/` + your private `user/` config into the concrete harness directory (`~/.claude`, `~/.zcode`, ...), adapted to that harness's format.

The same blueprints deploy to many harnesses. The same harness can host many providers. Drift is impossible by construction: edit once in `core/`, deploy to any target.

## Why: the three problems STC solves

### 1. Token economy

Every token that goes into the model's context window costs money and attention budget. An agent that re-reads the same long rule file every turn, that dumps raw command output to the terminal, or that runs an expensive job in the main thread burns tokens for no value.

STC attacks this on several fronts:

- **Always-context is loaded once per session.** The three firing rules (`behavior.md`, `pev.md`, `session.md`) plus the user profile enter context a single time and are never re-read; delivery is per-harness (on Claude the **H06** hook injects them, the bundle `@import` staying a pointer so nothing is delivered twice; a harness whose plugin hooks don't fire gets them inlined into the bundle). Everything else — the memory index, playbook, code standard, reference catalogs, `project_docs.md` — is **on-demand**, read only when a rule or hook references it.
- **Caveman compression** only where context loss is cheap. The `research`, `docs`, and `harness-docs` read-only agents return terse evidence-preserving results. Builders, reviewers, QA, security, and e2e keep full context; the final answer to the user is always normal prose.
- **Output hygiene hook (H11)** blocks raw-output dumps (`cat`/`sed`/`head`/`tail`/`git diff`/`find`/`grep -r` without redirection). Output goes to a file; only the summary reaches the model.
- **Exec-offload hook (H15)** blocks expensive data scripts (import/seed/publish/scrape/sync, audits without `--json`) in the main thread and routes them to an ephemeral sub-agent, so the main context stays lean.
- **The web-route hook (H13)** blocks web calls from the main agent once per session and routes them through the single research sub-agent that has web access, so the main context never fills with search results.
- **Acquire-dedup hook (H12)** keeps a session log of normalized read/grep/glob targets and nudges on exact repeats, so the agent does not re-acquire what it already has.
- **Explicit model routing.** Codex uses Luna Max for the main task and every ordinary sub-agent by default. The running model must surface a need to escalate; Terra/Sol are reserved for explicitly identified high-risk or high-uncertainty forks, not selected merely because a task touches production.

### 2. Knowledge across sessions and providers

A coding agent starts every session with amnesia. Without a deliberate structure, hard-won knowledge — the stack constraints, the schema gotchas, the legal decision and why it was made, the defect you already caught and its cheapest prevention layer — evaporates when the session ends, and has to be re-derived the next time, possibly under a different model from a different vendor.

STC makes knowledge durable and portable:

- **Transcripts are the durable source.** Every harness contributes to one cross-harness transcript corpus. The independent offline ingest turns new transcripts into a monthly review for canonical memory.
- **Obsidian is the review surface.** The offline ingest process writes staging candidates and monthly reports into the configured memory vault. Canonical Wiki/rules changes happen only during an explicit review; a model never mutates them directly.
- **`[[wiki-links]]` connect facts.** Anywhere a rule or a memory file needs another, it writes `[[reference-failure-modes]]`; the agent reads that file on demand, by anchor, not the whole catalog. Link integrity is checked where the harness has a reliable lifecycle event, or by offline lint otherwise.
- **The reference catalogs are seed templates you fill per project.** `reference_defect_ledger.md` (the self-improving review loop: each caught defect → a row → a design-time prevention), `reference_abuse_cases.md` (how they will break it, per category), `reference_failure_modes.md` (where it will stall, per use-case: symptom → cause → solution → verify).
- **ADRs record the why.** `project_docs.md` defines the ADR format (Decision → Why → Rejected alternatives, `ADR-NNN`); the trigger is "would a new session need the WHY?". A decision without the why is a future bug.
- **Provider-orthogonal.** The two-axis model (see below) means the same knowledge and the same rules deploy behind a Claude model today and a GLM model tomorrow, with no rewrite. The model is an engine you swap; the know-how is the same.

### 3. SDLC via SDD → TDD

STC encodes a software development lifecycle that goes from **Spec-Driven Development** to **Test-Driven Development**, not the other way around:

- **PEV (Plan → Do → Verify)** is the always-on task loop in `pev.md`. Plan clarifies the task, understands the code, evaluates solutions (asking the buy-vs-build question and the TDD question), and plans execution with mandatory acceptance criteria. Do works one item at a time, in scope. Verify is mandatory and never skipped — even for a single-line change. The task-scale table (S/M/L) decides how heavy each phase is and whether `/to-spec` and `/to-tasks` are required.
- **`/to-spec`** writes the Plan outcome as a markdown spec file (use cases + AC + ADR + buy-vs-build + abuse-cases + failure-modes + block-plan) into the doc-backend vault. This is SDD: the spec exists as a reviewable artifact before code is written.
- **`/to-tasks`** slices a finalised spec into task lines in the project's task file. Large tasks require a finalised spec (block-coding mandatory).
- **The `tdd` skill** is red-green-refactor via vertical tracer bullets (not all-tests-then-all-code). The iron law: no production code without a failing test first. The skill was merged from the user's own `tdd` command and the `superpowers/test-driven-development` methodology.
- **The ×3 review pipeline** (`code-reviewer` + `security-arch` + `qa`, plus `security-deps` before deploy) runs fresh sub-agents with no prior context, deliberately, so the review is unbiased. Each returns a verdict (PASS / NEEDS FIXES / CRITICAL STOP). A caught defect becomes a row in the defect ledger, which becomes a design-time prevention for next time — a self-improving review loop.
- **Offline ingest** closes the loop: raw transcripts are imported independently, explicit `📌 MEMORY` / `📌 запомнил` markers are high-confidence candidates, and a bounded local semantic pass searches for additional candidates. Monthly review decides whether a candidate becomes a Wiki fact, preference, Instinct candidate, or rule/process proposal.

## Guiding principles

1. **Minimal third-party tools. Maximal use of the harness's own capabilities.** STC uses the harness's native hook system, native `@import`, native typed sub-agents (where they exist), native MCP config. It does not ship a runtime daemon, a database, or a framework. The only language besides the harness's native format is Python — and only for the deploy pipeline itself, which runs outside the agent loop.
2. **One source of truth, many realisations.** A capability (a rule, a hook, a skill, an agent) is written **once**, in a harness-neutral form, in `core/`. Each adapter declares how a harness realises it. You never edit `~/.claude` or `~/.zcode` directly — you edit `core/` and deploy.
3. **Non-destructive by construction.** Every artifact carries a `.stc.md` / `.stc.sh` suffix (collision-proof). JSON merges happen under a namespace (`_stc_managed` / `stc-`) and refuse by default on genuine conflicts. A backup snapshot is taken before any JSON write. The only user-owned file ever touched is the always-context file, and only via one managed marker `@import` line.
4. **Degrade gracefully, never lose the capability.** A harness that lacks typed sub-agents (ZCode) does not lose the review pipeline — the methodology travels via the skill, and the agent dispatches as `general-purpose` carrying that skill. Only the native *form* is absent; the *capability* is intact.
5. **Edit once, deploy to any target.** Drift is impossible by construction: `core/` is the source, the live harness directory is a render. Re-deploy is idempotent.

## Abstraction layers

### The four directories

```
STC/
├── core/        # universal blueprints (public) — rules, memory, skills, hooks, commands, agents, models, templates
├── user/        # your private config (gitignored) — profile, project notes, secrets
├── adapters/    # per-harness descriptors — how core/ maps onto ~/.claude, ~/.zcode, ...
└── deploy/      # the pipeline — render + apply + check + uninstall + restore + tests
```

- **`core/`** is harness-agnostic and public. This is what you publish and contribute to. The capability bodies (the prompt text, the hook script, the rule text) live here, once.
- **`user/`** is private (gitignored). Templates use the `.example.` suffix and ARE committed (`profile.example.md`, `secrets.env.example`, `projects/example.example.md`); the real files they spawn are ignored.
- **`adapters/`** is declarative. Each `adapter.yaml` states, per layer, how a harness realises the capability, with no deploy-time behaviour of its own.
- **`deploy/`** is the pipeline. `render.py` is a pure function (no disk writes); `deploy.py` owns the write step; `checks.py` validates and backs up.

### The two axes: Harness × Provider

This is the load-bearing abstraction. Two axes are **orthogonal**:

| Axis | Controls | Lives in | Examples |
|---|---|---|---|
| **Harness** (FORM) | file layout, dispatch mechanism, hook wiring, import syntax | `adapters/<harness>/adapter.yaml` | `claude`, `codex`, `zcode` |
| **Model** (ENGINE) | concrete model ids per tier, context windows, transport | `core/models/<provider>.yaml` | `claude`, `codex`, `glm` |

At deploy time, the composition is:

```
adapter (form)  ×  provider (engine)  ×  registry (tier)  →  concrete model id
```

The model axis **never degrades form**. Only the harness axis degrades form (claude → zcode loses typed agents because zcode exposes none — a property of the harness, not the model). Concrete example: "GLM behind Claude Code" = claude adapter (full native form) × glm provider (glm model ids), with no form degradation. This is why a harness can host any provider, and a provider can mount into any harness.

Each harness speaks **one** model family at a time, so `stc.yaml` lets you pin a provider per target:

```yaml
models:
  provider: claude            # default provider (the reference harness's own)
  claude:  claude             # Claude Code on Anthropic sub → sonnet/haiku/opus
  codex:   codex              # Codex (ChatGPT on macOS) → agents inherit parent model
  zcode:   glm                # ZCode → glm-5.2/glm-5-turbo (adapter currently frozen)
```

### Capability ≠ realisation

Every adapter declares per layer a `realization`, a `native_path`, an `import_syntax`, and a `capabilities` map. Each capability carries a `supported` value:

- `true` — exists natively; the adapter describes the rendered artifact.
- `degrade` — a weaker native form exists; `fallback` names the substitute (e.g. a typed agent degrades to "general-purpose dispatch carrying the methodology skill").
- `false` — inert on this harness; `fallback` names the substitute (or none).

The principle: a capability is know-how written once (neutral); a harness realises it differently. Degrade gracefully — never lose the capability, only its native form.

### Always-context vs on-demand

- **Always-context** (Layer 1) is loaded every session: the three firing rules (`behavior.md`, `pev.md`, `session.md`) + the user profile. Delivery is per-harness — on Claude Code the **H06** session-start hook injects the rules (the bundle `@import` stays a pointer, so rules are not delivered twice); a harness whose plugin hooks don't fire (ZCode) gets them inlined into the bundle. The profile is inlined everywhere. H06 owns initial delivery and the infra-audit cadence nudge.
- **On-demand** is everything else: the memory index (`MEMORY.md`), `playbook.md`, `code_standard.md`, `project_docs.md`, the reference catalogs, and every skill/command/agent — read by anchor (`[[link]]`) or on invocation, only when needed.

## Third-party tools and credits

STC is deliberately light on dependencies, but a few external tools are load-bearing. Each is credited where it is used.

| Tool / pattern | Author | Link | Role in STC |
|---|---|---|---|
| **graphify** | safishamsi (YC S26) | [github.com/safishamsi/graphify](https://github.com/safishamsi/graphify) | **Required** core capability. Turns a codebase into a queryable knowledge graph (tree-sitter AST + LLM entity clustering). Powers the `code-graph` skill (S18) — `extract .` once (build), then `query`/`explain`/`affected` for blast-radius before a refactor (no `ingest` command in 0.9.x). Standalone CLI, not an MCP server. Install: `uv tool install "graphify[mcp]"`. |
| **LLM-Wiki pattern** | Andrej Karpathy | [gist.github.com/karpathy/442a6bf555914893e9891c11519de94f](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | The pattern behind the `llm-wiki` skill (S19): treat the LLM as a knowledge compiler (compile-once, not RAG). Three operations (Ingest/Query/Lint), three layers (raw / wiki / schema). Over a code graph it is realised via graphify `add`/`query`/`reflect` (no single `wiki` command in 0.9.x). |
| **Superpowers** | Jesse Vincent (obra) | [github.com/obra/superpowers](https://github.com/obra/superpowers) (MIT) | Methodology source. STC does **not** depend on it — every capability is self-contained in `core/` (Decision 4). Three skills were **merged** from the user's own commands + the superpowers equivalent: `diagnose` (← systematic-debugging), `tdd` (← test-driven-development), `worktree` (← using-git-worktrees). Each carries a "Supporting sources" block for the monthly upstream-drift check. |
| **Context7** | Upstash | [npmjs.com/package/@upstash/context7-mcp](https://www.npmjs.com/package/@upstash/context7-mcp) | The `docs` agent + docs-first contract. Vendor-neutral docs knowledge base. Powers H16 (integration-docs-gate) and the read-first-router buy-vs-build reminders. Secret via `CONTEXT7_API_KEY`. |
| **Ollama** | Ollama | [ollama.com](https://ollama.com) | Optional local runtime for the offline semantic memory pass. The scheduled path uses a small Qwen3 model and structured JSON output; if the runtime is unavailable, deterministic marker ingest still completes. |
| **AgentShield** | affaan-m | [github.com/affaan-m/agentshield](https://github.com/affaan-m/agentshield) | Weekly deterministic scan of deployed Claude/Codex configuration. STC never runs its model analysis or `--fix` automatically; findings are triaged in Obsidian and only explicitly approved fingerprints may enter a baseline. |
| **Playwright MCP** | Microsoft | [npmjs.com/package/@playwright/mcp](https://www.npmjs.com/package/@playwright/mcp) | **Required** core capability for browser-driven e2e. Powers the `e2e` agent and the H02 playwright router. Connects to a browser on `--remote-debugging-port=9222`. |
| **mcp-gsheets** | community | [npmjs.com/package/mcp-gsheets](https://www.npmjs.com/package/mcp-gsheets) | User-specific MCP server (optional). Google Sheets access. |
| **Matt Pocock skills set** | Matt Pocock ([total-typescript.com](https://www.total-typescript.com)) | — | Origin of the `prototype` and `improve-codebase-architecture` command methodologies. Ghost links to a sibling skills set were resolved by inlining the content directly (Decision 1). |
| **GLM** | Zhipu / BigModel | [open.bigmodel.cn](https://open.bigmodel.cn/api/anthropic) | Model provider (`core/models/glm.yaml`). Anthropic-compatible Messages endpoint, mounts into any harness speaking the Anthropic protocol. |
| **Claude** | Anthropic | [anthropic.com](https://api.anthropic.com) | Model provider (`core/models/claude.yaml`). The natural pairing with the claude harness but not bound to it. |

## The 20 hooks

Hooks are the **enforcement layer** (ADR-001: a rule in always-text recidivs; a rule in a hook does not). A hook reads tool-call JSON from stdin and either **hard-blocks** (`exit 2`), **JIT-injects** context (`hookSpecificOutput.additionalContext`), or **passes** (`exit 0`). They are the guarantee behind the rules — the rule states the intent, the hook enforces it.

The active source catalog contains H01–H18, H21 and H22. H19 is historical
and appears only in the retired-code register; H20 was never assigned.

| ID | Event | What it does | Type |
|---|---|---|---|
| **H01** block-dangerous-git | PreToolUse(Bash) | Blocks dangerous git (`reset --hard`, `clean -f`, `branch -D`, `checkout .`); blocks push-to-main without a one-shot ack; injects the verify-checklist + commit invariants before every commit. | guard |
| **H02** playwright-reminder | PreToolUse(playwright) | Injects once/session the 3-channel router (CLI / real-browser-in-main / e2e-subagent) + the preflight to start the browser on CDP_PORT. | inject |
| **H03** prompt-safety-reminder | UserPromptSubmit | Prints the SELF-EXEC scope and scans the prompt for secrets → directive to write to `.env`. | inject |
| **H04** agent-reuse-contract | PreToolUse(Task) | Blocks a build-capable sub-agent launch if the reuse-before-reinvent marker is absent; injects the reviewer-agent baseline. | guard |
| **H05** secret-scan-memory | PreToolUse(Write\|Edit\|MultiEdit) | Blocks writing a real secret into `memory/*`. Length-gated so it does not fire on docs. Never prints the secret value. | guard |
| **H06** session-start-context | SessionStart | Injects the firing rules (`behavior`/`pev`/`session`) on initial session start (`rules_delivery: hook`; the bundle `@import` stays a pointer) and owns the infra-audit cadence nudge (≥1 month). | inject |
| **H07** dirty-tree-guard | PreToolUse(Write\|Edit\|MultiEdit) | On first edit in a repo: blocks if the tree is dirty (uncommitted WIP, possibly a parallel session); injects a worktree nudge if more than one worktree exists. | guard |
| **H08** link-integrity-guard | Stop | Verifies `[[wiki-links]]` integrity against the `name:` frontmatter registry (catches rename drift). Blocks once/session. | guard |
| **H09** memory-guard | PreToolUse(Write\|Edit\|MultiEdit) | Injects the I04 checklist on first edit of a memory file (once-per-file-per-session). Routes by basename (rules vs facts). | inject |
| **H10** read-first-router | PreToolUse(Write\|Edit\|MultiEdit) | Injects domain reminders by path (design-system / security / docs-integrations / data / tdd / legal / reuse). Once-per-domain-per-session. | inject |
| **H11** output-hygiene-guard | PreToolUse(Bash) | Blocks raw-output dumps to terminal (cat/sed/head/tail/git diff/find/grep -r un-redirected). Enforces output-to-file-then-summary. | guard |
| **H12** acquire-dedup-guard | PreToolUse(Read\|Grep\|Glob\|Bash) | Injects an anti-duplicate nudge: keeps a session log of normalized targets, nudges on exact-repeat reads. | inject |
| **H13** web-route-guard | PreToolUse(WebSearch\|WebFetch) | Blocks web calls from the main agent once/session — forces routing through the research sub-agent. Passes inside a sub-agent. | guard |
| **H14** buy-vs-build-reminder | PreToolUse(EnterPlanMode\|Write\|Edit\|MultiEdit) | On plan entry: the "evaluate a ready solution before building" reminder. After plan mode: hard-blocks the first code edit once until the FR-27 exec-slice table (which model runs each block) is produced — acknowledge-once. | guard |
| **H15** exec-offload-guard | PreToolUse(Bash) | Blocks expensive data-scripts (import/seed/publish/scrape/sync; audits without `--json`) → must offload to an ephemeral agent. | guard |
| **H16** integration-docs-gate | PreToolUse(Write\|Edit\|MultiEdit) | Blocks editing a named integration's code without saved research (failure-modes catalog or notes/research). Lifted by a research save or a `// docs-checked:` marker. | guard |
| **H17** secret-read-guard | PreToolUse(Read\|Glob\|Grep) | Blocks reading secret files (`.env`/`.pem`/`id_rsa`). Harness-neutral equivalent of Claude's `permissions.deny` (ZCode has no perms engine). Override via `// secret-exception:`. | guard |
| **H18** graphify-first | PreToolUse(Grep\|Bash) | In a repo with a built code-graph (`graphify-out/graph.json`), blocks the first grep-style search once → nudges `graphify query`/`affected`/`explain` for how/why/connect questions (acknowledge-once; exact-string lookups pass). Repos without a graph are never gated. | guard |
| **H21** exit-plan-grill | PreToolUse(ExitPlanMode) | Leaving plan mode blocks once unless the plan carries AC/DoD, a block→executor decomposition and an explicit forks-resolved line — the plan is the dispatch artifact for the cheap executor tier, so it has to be executable by someone other than the expensive model. | guard |
| **H22** prompt-lens | UserPromptSubmit | Appends a short hint to the message — **it never rewrites it**, the user's text reaches the model intact. Flags a degree word with no measure, a dangling reference, an open verb with neither a done-criterion nor an object, ≥3 tasks in one message, and project nicks from the private dictionary. Deterministic (no model in the path, so errors cannot multiply). Rules live in ONE module shared by the hook, the monthly audit and the guard test; every rule and every alias must clear a hit threshold against your own transcript corpus, or the guard test fails. | inject |

On ZCode, where there is no `permissions.deny` engine, **H17 is the only read-guard** for secrets. On Claude Code, both run (deny is faster when it short-circuits; the hook covers any harness gap).

## The rules (always-context)

Four rule files. The three firing rules — `behavior.md`, `pev.md`, `session.md` — are always-context (delivered per-harness: Claude → H06 injection with the bundle as a pointer; ZCode → inlined into the bundle). `project_docs.md` is on-demand, read by anchor when recording decisions:

| File | About |
|---|---|
| **`behavior.md`** | The firing-rule catalog — "situation → action" imperatives. Secrets → `.env`; durable facts → transcript/Wiki pipeline; worktrees + parallel sessions; git push = release; commit invariants; SELF-EXEC scope; background services; reuse-before-reinvent + buy-vs-build; docs-first on integrations; output hygiene; token economy on sub-agent traffic. Each anchor notes which hook enforces it. |
| **`pev.md`** | The Plan → Do → Verify loop. Plan (clarify, understand, evaluate incl. the TDD + buy-vs-build questions, plan execution with mandatory AC); Do (one item at a time, in scope, TDD if agreed); Verify (mandatory, pick ≥1 of static/eyes/dynamic/agent/design-system; L tasks need ≥2 incl. agent). Task-scale S/M/L table decides PEV mode. |
| **`project_docs.md`** | How to record decisions. ADR format (Decision → Why → Rejected, `ADR-NNN`, trigger: "would a new session need the WHY?"); task encoding (Blocks A/B/C, sub-blocks B0→B1→B2); ERD data models via mermaid.ink (`layout: elk` mandatory). |
| **`session.md`** | Session lifecycle. Always-context = 3 firing rules + user profile; rule delivery is per-harness (`rules_delivery`: claude → H06 hook injection, bundle stays a pointer; zcode → rules inlined into the bundle), profile is inlined everywhere. Session start reads the project documentation needed for the task; transcript ingest and monthly review maintain the memory pipeline. |

## Memory structure

Memory is **lazy reference**, read by anchor. A `[[link]]` anywhere means "read that file now". Files here are reference, not process (processes live in `skills/`).

```
core/memory/
├── MEMORY.md                      # the index — table of all lazy + always-context files + conventions
├── playbook.md                    # operational instructions: stack constraints, check commands,
│                                  #   design-system verify, agent triggers, Playwright MCP, stop commands,
│                                  #   token-economy levers, SELF-EXEC patterns, worktree checks
├── code_standard.md               # the single code standard: complexity classifier (S0/S1/S2 + flags),
│                                  #   CORE catalog (ARCH/VALID/ERR/.../DEP/TEST/...), review process (×3 pipeline)
├── reference_defect_ledger.md     # seed: self-improving review (defect → class → prevention layer → hook)
├── reference_abuse_cases.md       # seed: abuse/bypass base by category (AUTH/RATE/AUTHZ/INPUT/...)
├── reference_failure_modes.md     # seed: per-use-case pitfalls (symptom → cause → solution → verify)
├── reference_retired_codes.md     # code-labels retired when a rule migrated to a hook (ADR-001)
└── skills_triggers.md             # the "which skill when" summary table + per-skill nuances
```

The `reference_*.md` files are **empty seed templates** in the public repo. You fill them per project, in your private `user/projects/<name>.md` or in the harness's project memory, as you spec and debug. They are not loaded into always-context — a rule or hook reads them by anchor when it needs them.

Your **personal profile** (`user/profile.md`, gitignored) is inlined into the generated always-context bundle; the private source remains outside the public repository.

## Offline transcript memory pipeline

The memory pipeline is deliberately outside every harness session:

```
Claude / Codex / other harnesses
            ↓ raw transcripts
shared transcript corpus
            ↓ deterministic marker scan + bounded local semantic pass
staging candidates (JSONL)
            ↓ monthly review session
Obsidian report → accepted Wiki fact / preference / Instinct candidate / proposal
```

The scheduled job does not edit canonical memory, rules, hooks, always-context,
or project files. It writes only:

- `memory/candidates/YYYY-MM.jsonl` — append-only staging records with source references;
- `memory/reports/stc/YYYY-MM/memory-review.md` — grouped monthly review note.
- `memory/reports/stc/review-decisions.json` — durable explicit human decisions;
- `memory/reports/stc/YYYY-MM/review-decisions.json` — optional month-local audit
  decisions; accepted/obsolete claims are removed from the active section on the next render.

On macOS, `launchd` runs the technical import at load/wake and once per day. The
semantic pass is optional, bounded, local-only, and fails open: a missing or
malformed model response cannot prevent transcript import or report generation.
The monthly review is the point at which a candidate is accepted, rejected,
deferred, or turned into a separately approved rule/process proposal.
Review decisions are durable metadata for the report only: they do not rewrite
the raw transcript or staging JSONL, and they never auto-edit canonical memory.

The canonical cross-harness memory root is `~/Work/memory`. Legacy Claude and
Codex roots can be migrated with `core/scripts/memory_root_migrate.py`; the
migrator plans and hashes every operation first, preserves conflicts in a
quarantine archive, and never silently overwrites canonical files.

## Project status and code navigation

The first stop for a project-status question is the generated central index:
`~/Work/memory/projects/SNAPSHOT.md`. Each registered project also receives a
root `SNAPSHOT.md` with the current git/freshness state and pointers to project
memory, repo documents, and Graphify. The snapshots are deterministic,
generated outside harness sessions at load/wake and once per day, and excluded
from each repository's local git exclude file. They are navigation artifacts,
not canonical memory and not a replacement for the Wiki.

Graphify is the code-only layer: use its map for relationships, callers, and
blast radius. Its deterministic structural maintenance runs independently in
the background at load/wake and once per day; it refreshes every registered
project so uncommitted source changes are represented, and does not start
semantic extraction automatically. It does not
contain project memory. Read the memory pointer from the Snapshot for status,
decisions, and open questions.

The same independent scheduler also runs a weekly behavioral audit, a weekly
AgentShield scan, and a monthly live Codex canary. Deterministic collectors own
PASS/FAIL; optional loopback Qwen only edits the weekly narrative. Reports are
written to `~/Work/memory/reports/stc/YYYY-MM/` for review in Obsidian. The
matching Calendar schedule can be generated with
`core/scripts/schedule_calendar.py`, so wake/login jobs are visible without a
terminal UI.

## Skills, agents, commands

**16 active skills** (each is a self-contained `SKILL.md`):

- **Methodology** (12): `caveman` (compressed speech), `code-reviewer`, `council` (5-critic review), `diagnose` (root-cause debugging), `e2e` (Playwright), `infra-audit` (~monthly self-audit), `qa`, `research` (the only web-enabled agent), `security-arch`, `security-deps`, `tdd`, `worktree`.
- **Utility** (4): `code-graph` (graphify), `docs` (Context7), `llm-wiki` (Karpathy pattern), `transcript-history` (shared cross-harness corpus).

**10 agents** in `registry.yaml`, each with model routing, tools, affinity, and a `dispatches` description: `builder`, `code-reviewer`, `security-arch`, `qa`, `security-deps`, `e2e`, `cleanup`, `research`, `docs`, and `harness-docs`. The registry is neutral bindings; the prompt body lives in `core/agents/<name>.md`. A harness with typed sub-agents renders both; one without routes through `skill_link` + a general-purpose dispatch.

**8 slash commands**: `git-guardrails`, `grill-me`, `improve-codebase-architecture`, `install-mcp`, `prototype`, `to-spec`, `to-tasks`, `zoom-out`.

## The deployer and the renderer

### CLI commands

```bash
python3 deploy/deploy.py check                    # validate config (no writes)
python3 deploy/deploy.py render --target claude --dry-run   # preview into deploy/_rendered/
python3 deploy/deploy.py apply --target claude    # render + write to ~/.stc/ + ~/.claude (backs up first)
python3 core/scripts/harness_applicability.py --target claude,codex  # static applicability bundle
python3 core/scripts/harness_applicability.py --target codex --live   # + real Codex canary
python3 core/scripts/memory_ingest.py run --config stc.yaml  # offline transcript ingest + monthly report
python3 deploy/launchd_install.py --apply          # install/update independent macOS jobs
python3 core/scripts/schedule_calendar.py --output ~/Work/memory/stc-scheduled-tasks.ics
python3 deploy/deploy.py restore <backup-id>      # roll back JSON from a backup snapshot
python3 deploy/deploy.py uninstall --target claude
```

`apply` is the only command that mutates live config. Defaults are dry-run/preview everywhere.

### Scenarios the deployer handles

The deployer is built to be safe to re-run on a live harness. Every scenario below is covered:

- **Markdown file collisions — cannot happen.** Every artifact carries a `.stc.md` / `.stc.sh` suffix (unique). The only user-owned file touched is the always-context file, and only via the managed marker block.
- **JSON collisions (settings.json / .mcp.json).** `detect_collisions` compares rendered patches vs live JSON. STC's own `stc-*` keys and legacy STC-hook-basename entries are NOT collisions (update-in-place / absorbed). A genuine conflict (same event+matcher on PreToolUse, same mcpServer name, or statusLine) → deploy REFUSES by default; resolution only via `--overwrite` (backup + STC wins) or `--skip-collisions` (keep user config).
- **Event-hook `'*'` coexistence.** On SessionStart/SessionEnd/Stop/UserPromptSubmit, a user hook with `matcher='*'` is coexistence, not conflict (both fire independently) — e.g. `vscode-todos-bridge` + STC H06 both on SessionStart.
- **Duplicate names.** `_naming_consistency` rejects underscore command names at precheck (`grill_me.md` vs `grill-me.md` would leave duplicate files). Sub-agent and MCP names are namespace-prefixed (`stc-`).
- **Idempotent re-deploy.** Every JSON entry is tagged `_stc_managed` + `_stc_cap`; re-apply drops the prior entry and appends the new one (no duplicates). `stc-` MCP names update in place. The marker block is idempotent. `_register_plugin` is a no-op if already registered.
- **Orphan prune.** When a capability is retired (a command removed, a skill dropped), `apply` deletes the stale artifact by diffing the previous manifest against the current render — no more files lingering in the harness after they leave `core/`. Scoped to STC-owned shapes (`.stc.md` / `.stc.sh` / `SKILL.md`); a user file is never removed.
- **Legacy hook absorption.** Pre-namespace (untagged) hooks pointing at an STC script basename are recognised as STC-owned via scoped per-entry basename matching and absorbed during merge, so they do not fire twice.
- **The double-wiring fix.** Basename matching is scoped per-entry (not global), so Bash-matcher capabilities sharing `matcher: "Bash"` (H01/H11/H15) stay distinct. A global matcher would collapse them into one.
- **`$NATIVE_DIR` resolution.** Render emits the placeholder (disk-agnostic, testable); the orchestrator substitutes the absolute `native_dir` during merge so the harness finds the hook script.
- **Per-harness model provider.** `provider_for` follows the harness so Claude Code gets Anthropic aliases and ZCode gets GLM ids (prevents silently-failing typed sub-agents).
- **Plugin visibility.** For plugin-delivery harnesses, `_register_plugin` enables the plugin in `cli/config.json` and adds the filesystem marketplace to `known_marketplaces.json` (the cache dir alone is not discovered).
- **Rollback.** Before any JSON write, `backup_snapshot` copies each existing JSON to `~/.stc/backups/<timestamp>/`; `_record_backup` ties the id to target + native_dir in `_ledger.json`. `restore <id>` looks up the native_dir and copies files back. User content and backup snapshots are retained on uninstall.
- **Partial uninstall.** `~/.stc/core/` is shared across harnesses; removed only when the last harness is uninstalled.

### The renderer pipeline

`render.py` is a **pure function**: `render_harness(stc, registry, provider, adapter, core_dir, repo_dir) -> RenderResult`. It NEVER writes to disk — the orchestrator owns the write step, so render is testable and safe to dry-run. It runs 8 layer renderers in order, each populating the same `RenderResult`:

1. **`_render_always_context`** — the bundle (the `.stc.md` file with the `@import` lines into `~/.stc/core/...`) + the single marker `@import` line that goes into the user's always-context file.
2. **`_render_hooks`** — the adapter-supported hook scripts (with `${VAR}` substitution) + matcher wiring. Retired capabilities are pruned from STC-owned live artifacts.
3. **`_render_commands`** — the slash command markdown.
4. **`_render_subagents`** — typed agent files (native) or degraded dispatch instructions.
5. **`_render_skills`** — the skill directories.
6. **`_render_mcp`** — the MCP server blocks (command split via `shlex`, secrets by env-var name, `stc-` namespaced).
7. **`_render_permissions`** — the static deny block (`.env`/`.pem`/`id_rsa` read-guards).
8. **`_render_glue`** — the statusline, if enabled.

For plugin delivery, `_finalize_plugin_seed` stamps a SHA-256 digest over the plugin's file tree into the seed, last (so it depends on every file being present).

## Quickstart

```bash
git clone https://github.com/Literallystuckonthisplanet/STC.git
cd STC

# 1. Fill your private config from the examples
cp stc.example.yaml stc.yaml                # edit: your name, role, workspace, MCP ports,
                                            #        models.<harness> per-target overrides
cp user/profile.example.md user/profile.md  # edit: your style, stack, voice dictionary
cp user/secrets.env.example user/secrets.env  # add tokens (CONTEXT7_API_KEY, GRAPHIFY_CLI, ...)

# 2. Preview what deploy would write (no live writes)
python3 deploy/deploy.py check
python3 deploy/deploy.py render --target claude --dry-run
python3 deploy/deploy.py render --target claude,zcode --dry-run   # both at once

# 3. Deploy into one or many harnesses (writes ~/.stc/ + the native dir; backs up first)
python3 deploy/deploy.py apply --target claude          # → ~/.claude
python3 deploy/deploy.py apply --target codex           # → ~/.codex (hooks.json + config.toml + agents/*.stc.toml)
python3 deploy/deploy.py apply --target zcode           # → ~/.zcode (as a plugin)
python3 deploy/deploy.py apply --target claude,codex    # both
python3 deploy/deploy.py apply                          # all targets from stc.yaml

# Roll back a deploy if it went wrong:
python3 deploy/deploy.py restore <backup-id>      # id printed by apply
python3 deploy/deploy.py uninstall --target claude
```

`--target` accepts one harness id or a comma-separated list. Unknown names fail
fast with the list of available adapters — a typo never silently deploys. When
`--target` is absent, all targets from `stc.yaml deploy.targets` are used.

## Testing

```bash
python3 deploy/tests/test_render.py    # zero-dependency stdlib runner
# or, if pytest is installed:
python3 -m pytest deploy/tests/        # the suite is pytest-compatible
```

### Harness applicability bundle

`core/scripts/harness_applicability.py` is the single read-only entrypoint for
checking whether STC can be applied to a target harness. It runs `deploy.py
check`, target-specific dry-run renders, the full `deploy/tests/` suite, and a
source Snapshot check. It never runs `apply` or `uninstall`.

```bash
# Claude + Codex: source/render/test contract only, no model call
python3 core/scripts/harness_applicability.py --target claude,codex

# Codex: add the real startup-context canary (one bounded Luna Max call)
python3 core/scripts/harness_applicability.py --target codex --live

# Make an UNVERIFIED live layer fail the shell command as well
python3 core/scripts/harness_applicability.py --target claude,codex --live --fail-on-warn
```

The report is written under `memory/reports/stc/YYYY-MM/`. `contract=PASS`
means the adapter renders and the repository behavior suite passes. `live=PASS`
requires a real canary; `live=UNVERIFIED` means that no live canary exists for
the selected harness yet. Codex has a live canary. Claude and frozen ZCode are
currently verified only through source/render/hook contracts.

### Snapshot routing

Snapshot is a navigation artifact, not part of the H06 startup payload. H06
loads the always-context rules and user profile. The session routing rule tells
the model when to open Snapshot with a read operation:

- STC/infra question → `core/memory/SNAPSHOT.md`;
- project status question → `~/Work/memory/projects/SNAPSHOT.md`, then that
  project's generated `SNAPSHOT.md`;
- code relationships → follow the project's Graphify pointer from Snapshot.

Therefore the default is **model-driven read-on-demand**, not automatic
injection. The background Snapshot job refreshes the files independently at
load/wake and once per day. The applicability bundle additionally compares the
source Snapshot with `~/.stc/core/memory/SNAPSHOT.md` when `--live` is used and
reports a stale deployment as `WARN`.

The suite covers renderer/deployer regressions, adapter contracts, collision handling, idempotent re-deploy, orphan pruning, provider selection, native hook behavior, always-context size and content, transcript corpus import, Graphify/Snapshot ordering, weekly audits, AgentShield orchestration, launchd/calendar generation, the Codex live canary, and the offline memory pipeline.

## Repository layout

```
STC/
├── core/
│   ├── rules/          # 3 always-context firing rules + lazy project-doc rules
│   ├── memory/         # MEMORY.md + playbook + code_standard + 4 reference catalogs + skills_triggers
│   ├── hooks/          # H01–H18, H21, H22 source hooks + README
│   ├── skills/         # methodology/utility skills
│   ├── agents/         # registry.yaml + 10 agent prompt bodies
│   ├── commands/       # 8 slash commands
│   ├── models/         # claude.yaml, codex.yaml, glm.yaml (the MODEL axis providers)
│   ├── templates/      # design-system, new-project, vault
│   └── scripts/        # corpus/memory, Graphify/Snapshot, audits, canary, calendar
├── deploy/launchd/      # macOS background jobs for memory, maps, snapshots, audits, canary
├── adapters/
│   ├── claude/         # the REFERENCE realisation (files-delivery)
│   ├── codex/          # native Codex (ChatGPT) — hooks.json + config.toml + *.stc.toml agents
│   ├── zcode/          # the DEGRADE realisation (plugin-delivery) — currently frozen
│   └── _template/      # documented skeleton for new harnesses
├── deploy/
│   ├── deploy.py       # CLI orchestrator (render/apply/check/uninstall/restore)
│   ├── render.py       # pure 8-layer renderer
│   ├── checks.py       # precheck, collision detection, backup/restore
│   ├── stc_block.py    # STC_BEGIN/STC_END marker mechanism
│   └── tests/          # regression test suite
├── docs/               # PROGRESS.md — the build log + design decisions
├── stc.example.yaml    # the public config template
├── user/               # private (gitignored) — profile, secrets, projects
├── README.md
├── CHANGELOG.md
└── LICENSE
```

See [`docs/PROGRESS.md`](docs/PROGRESS.md) for the full build log and design decisions, and [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## Status

Early beta — the `0.1.x` line (current release in the badge above) carries the deploy pipeline and 21 hooks; breaking changes can happen between minor bumps until `1.0.0`. Contributions and ideas welcome.

Development currently focuses on **`claude`** and **`codex`**. Claude remains the reference files-delivery realisation; Codex is a native peer with typed sub-agents (`*.stc.toml`), native hook envelopes, sandbox declarations, and Luna Max as the default main/agent route. A monthly read-only live canary verifies the deployed Codex behavior rather than only checking file syntax. The **`zcode`** adapter is **frozen** — it stays in-tree as the reference degrade realisation, but default deploys skip it; deploy it explicitly with `--target zcode` if needed.

## License

STC Core is **dual-licensed**: [**AGPL-3.0**](LICENSE) (free, OSI-approved open
source) for the community, and a **commercial license** for closed-source or
proprietary use. Most users — individuals, researchers, open-source projects,
companies self-hosting and willing to share modifications — use it free under the
AGPL-3.0. Embedding it in a closed product or running it as a hosted service
without sharing changes needs the commercial license.

See [`LICENSING.md`](LICENSING.md) for which applies to you, and
[`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md) for the commercial terms.
Commercial inquiries: Anton Gavryushin — <gavryushin@gmail.com>.
