# STC — Progress Log

Living log of where STC build stands. Read this first when resuming.

## Status: 🟢 Stage 0–2 complete. Sync done. C-sync (2nd pass) done. Stage 3 adapters next.

Last updated: 2026-06-30

---

## What's done

### Stage 0 — Foundation (DONE)
- Fresh repo at `/Users/xtoshin/Work/stuff/VSCode/STC` (git init, no commits yet)
- Directory skeleton: `core/{rules,memory,skills,commands,hooks,templates/design-system}`, `user/projects`, `adapters/{claude,zcode,_template}`, `deploy/doc_backend`, `docs`
- `LICENSE` — MIT, 2026 Literallystuckonthisplanet
- `.gitignore` — protects `user/`, secrets, render output, python/OS
- `README.md` — Warhammer STC framing + what/why/quickstart (English)
- `stc.example.yaml` — compact user config with `${VARS}` + comments

### Audit — reusability of claude-infra assets (DONE)
Full report lives in conversation, key findings:
- Most commands/agents/hooks/templates are reusable after replacing Claude-specifics with `${VARS}`
- Hardcoded things to parameterize: "Антон"×69 → `${USER_NAME}`, "Жан-Клод"×4 → `${AGENT_NAME}`, "Comet"×10 → `${BROWSER_NAME}`, `/Users/xtoshin`×23 → vars, Notion IDs → `${NOTION_*}`
- Notion secrets: CLEAN — never in tracked files nor git history. `gh` not authed.

## Pending decisions (need user input — asked at end of Stage 0)

### Decision 1 — Dangling links in prototype.md / improve-codebase-architecture.md
**Resolved (verified 2026-06-16):** The referenced sub-files (`LOGIC.md`, `UI.md`, `LANGUAGE.md`, `HTML-REPORT.md`, `INTERFACE-DESIGN.md`, `CONTEXT-FORMAT.md`, `ADR-FORMAT.md`) **do not exist anywhere** in `~/.claude` — not in handoffs, not in tuning files. They are ghost links from an unfinished "skills-as-directories" design. → In STC, write their content from scratch as proper skill directories (`core/skills/prototype/{LOGIC.md,UI.md}` etc.).
User hypothesis: prototype.md and improve-codebase-architecture.md may relate to the recently adopted PEV rules. To confirm content direction during Stage 1.

### Decision 2 — e2e.md (mostly Forest Echoes specific)
User clarified: **the idea is for this file to hold the maximal possible test set**, then pick what's needed per project. FE is the first/only project so far, so the overlap is expected. → In STC: keep the methodology skeleton + a generic, framework-agnostic scenario taxonomy in `core/skills/e2e/`. The concrete FE scenarios (40+) go to `user/projects/forest-echoes.md` as the worked example / first instance.

### Decision 3 — anthropic-docs + Context7-docs (RESOLVED 2026-06-17)
**Skip both for now.** anthropic-docs is vendor-specific (links to one vendor's docs), which conflicts with `core/` harness-neutrality. Both are added later on request as optional skills (Context7-docs parameterized via adapter tool-names). Not blocking Stage 1.

### Decision 4 — Deduplication policy: own independent skill over any external dependency (RESOLVED 2026-06-18)
**Every capability in STC must be harness-neutral and self-contained.** When a candidate skill (from `~/.claude` or elsewhere) overlaps with an external source — a built-in harness ability, the `superpowers` plugin, any third-party — STC keeps **its own independent skill in `core/`**, merged from the best of both sources. STC does NOT depend on `superpowers` or any single-vendor plugin.

Reasoning: (1) `superpowers` is open-source and multi-harness (Claude Code, ZCode, Codex, etc., via obra/Superpowers), but it is one author's project and is written Claude-first — not a reliable cross-harness foundation. (2) Built-in harness abilities are vendor-specific and change without notice. (3) Open-source skills are usually written for one harness. (4) STC is a multi-harness public framework — the anti-pattern is different behavior for different agents; the only guarantee of identical behavior everywhere is a self-contained skill in `core/`. (5) This mirrors Decision 3's logic: `core/` is harness-neutral; vendor-specifics go to `adapters/` or are skipped.

Applied to Stage 1.4 Group D — three skills are **merged** from the user's `~/.claude/commands/*` source + the `superpowers` equivalent into one canonical STC skill each:
- `core/skills/diagnose/` ← `commands/diagnose.md` + `superpowers/systematic-debugging`
- `core/skills/tdd/` ← `commands/tdd.md` + `superpowers/test-driven-development`
- `core/skills/worktree/` ← `commands/worktree.md` + `superpowers/using-git-worktrees`

Each merged skill links its upstream sources in a "Supporting sources" block for the monthly maintenance check (Decision 5). If an upstream source updates with a meaningful fix, the STC skill is updated to incorporate it.

### Decision 5 — Monthly maintenance check for upstream-tracked skills (RESOLVED 2026-06-18)
Skills merged from external sources (per Decision 4) are tracked for upstream drift. **Automatic, once a month**, via the existing `core/skills/infra-audit/` cadence (already runs ~monthly when token budget allows). A checklist item is added: for each skill with a "Supporting sources" block, check whether the upstream sources released meaningful updates/fixes since the last check; if so, port the relevant change into the STC skill and note it.

This avoids a separate CI/script for now; the infra-audit is the natural home (it already audits the deployed infra monthly).

## Open questions for resuming
1. Stage 1 order — start with `core/rules/` (session/behavior/pev/project_docs) since those are the always-context foundation? Or memory first? **(RESOLVED: rules → memory → skills, all done)**
2. Decision 3 (anthropic-docs) — resolve before or during Stage 1. **(RESOLVED 2026-06-17)**

---

## Next: Stage 1 — core/ migration
Migrate content from `~/.claude` to `STC/core/` with:
- Depersonalization (names/paths/IDs → `${VARS}`)
- Translation to English (public standard)
- Generalization of Claude-specifics (compact command, tool names, install-mcp)
- Show preview of each subdirectory before writing.

Order: `core/rules/` → `core/memory/` → `core/skills/` → `core/commands/` → `core/hooks/` → `core/templates/`

**Progress:**
- ✅ 1.1 `core/rules/` (session, behavior, pev, project_docs)
- ✅ 1.2 `core/memory/` (playbook, code_standard, skills_triggers, MEMORY index)
- ✅ 1.3 `core/skills/` batch 1 — 9 skills: council, caveman, infra-audit, research, qa, security-arch, security-deps, e2e, code-reviewer
- ✅ 1.4 Group D — 3 merged skills: diagnose, tdd, worktree (per Decision 4)
- ✅ 1.4 Group A/B/C — 10 commands in `core/commands/`
- ✅ 1.5 `core/hooks/` — 3 scripts (block-dangerous-git, playwright_reminder, stop_services_reminder); smoke-tested
- ✅ 1.6 `core/templates/` — new-project + design-system/{process, DESIGN.template}

**Stage 1 totals:** 4 rules + 4 memory + 12 skills + 10 commands + 3 hooks + 3 templates = 36 artifacts, all depersonalized and parameterized with `${VARS}`.

## ✅ Stage 2 — user-config layer (DONE 2026-06-19)

The private user layer. All under `user/`, all gitignored (real values never
committed); templates use the `.example.` suffix and ARE committed.

- `user/profile.example.md` — identity, role, language, git identity, how-I-work prefs, voice-input dictionary, project pointers. Renders into `${USER_NAME}`, `${USER_LANG}`, etc.
- `user/secrets.env.example` — env-var definitions for every secret referenced by name from `stc.yaml` (GITHUB_PERSONAL_ACCESS_TOKEN, CONTEXT7_API_KEY, GOOGLE_*; NOTION_API_TOKEN kept optional for the Notion MCP only). No values.
- `user/projects/example.example.md` — per-project memory template: product, stack, data model (ERD sketch), gotchas, MVP status, e2e scenario list (consumed by the e2e skill at run time).
- `core/memory/MEMORY.md` — User-specific section updated to list all three files + their templates.

`user/.state/` is reserved for the deploy pipeline's per-harness state (Stage 4).

### Open item for Stage 4 — doc-backend store decision
The Notion doc-backend was retired in the live infra (Notion→Obsidian migration).
In STC `stc.example.yaml` now models the doc backend as **markdown-local-first**
(`doc_backend: markdown`, root `${workspace.root}/.stc-docs`); the source of
truth is always the `.md` file, the backend is a view. Obsidian reads the same
files in vault mode without extra config. The final store decision
(markdown-only vs an Obsidian-aware backend) is deferred to Stage 4 per the
user's call. Not blocking Stage 3.

## ✅ Synchronization with the live `~/.claude` refactor (DONE 2026-06-28)

The live infra underwent a major refactor in the ~2 weeks since Stage 1 (ADR-001
"rules → event-triggered hooks", ADR-002 "design system = tokens not cases",
FR-1..FR-23). Full re-snapshot + sync performed:

**`core/hooks/` — rewritten 3 → 13 hooks** (929 lines, all smoke-tested).
Added: `session-start-context` (H06, always-context inject + post-compact FR-7),
`secret-scan-memory` (H05) + secret-in-prompt I05b (H03), `dirty-tree-guard`
(H07), `agent-reuse-contract` (H04), `read-first-router` (H10),
`output-hygiene-guard` (H11/FR-15), `acquire-dedup-guard` (H12/FR-17),
`web-route-guard` (H13/FR-17), `link-integrity-guard` (H08),
`memory-guard` (H09). Expanded: `block-dangerous-git` (H01 + push-to-main I08
+ commit-verify FR-5), `playwright_reminder` (H02 channel-router FR-22),
`stop_services_reminder` (H03 + I05b). New **`core/hooks/README.md`** — the
6-event-guard map + the critical `additionalContext` injection mechanism +
the acknowledge-once pattern.

**`core/rules/`** — `session.md`: H06 is now primary (rule = fallback);
post-compact recovery (FR-7). `behavior.md`: extended to I14–I25 (I14 code
conventions, I17 commit-verify, I18 web-via-subagent, I20 baseline, I21 reuse,
I22 codes-with-names, I23 live todo, I24 output hygiene, I25 service-field
language); existing rules annotated "Enforced: H#".

**`core/memory/`** — `playbook.md`: 3 e2e channels (FR-22), agent baseline
(I20), agent prompt contract, functional infra-verify (R07). `code_standard.md`:
LEAN block (LEAN-1..5, the decision ladder), ARCH-6 (one authority per
concern), security baseline on handoff. `skills_triggers.md`: diagnose/tdd/
worktree now STC-self-contained (Decision 4), docs/Context7 added,
git-guard reflects the expanded H01. `MEMORY.md`: hooks section, updated
always-context descriptions, R08 project-memory.

**`core/skills/docs/`** — NEW. Context7 docs-agent (vendor-neutral global
knowledge base, not vendor-specific → no Decision-3 conflict). MCP tool names
parameterized.

**`user/projects/example.example.md`** — rewritten to the R08 format
(STATE/OPEN/CHANGELOG — pointer + status, ~70% smaller than a dump).

**`core/commands/git-guardrails.md`** — updated for the expanded H01
(push-to-main gate + commit-verify inject); functional verify steps.

**Decisions reaffirmed:**
- `docs` (Context7) is vendor-neutral → migrated openly (not a Decision-3 skip).
- I08 auto-backup (launchd) is a **phantom** (script/plist/branch don't exist)
  → carried forward as a TODO, the rule notes "do not assume it runs".
- Obsidian PoC — wait for the verdict before migrating the
  doc-backend; **Notion is now retired** in the live infra. STC's doc backend
  is markdown-local-first; the store decision (markdown-only vs Obsidian-aware)
  is deferred to Stage 4.

**Open items (carry forward):**
- Full human-readable auto-updating **README** for STC — to be written before
  Stage 7 (public release), after the Claude refactor finalizes.

## ✅ C-sync — 2nd-pass synchronization with the live refactor (DONE 2026-06-30)

The live infra kept evolving after the first sync (Notion retired, PEV
I15/I16/I17 + DEP-4, new hooks H14/H15/H16, new reference catalogs, agents).
A full re-snapshot of `~/.claude` (read-only) and a content diff vs `core/`
surfaced gaps. Eight sync blocks applied:

**C1 — Notion retired from `core/`.** Removed `to-notion-spec.md` /
`to-notion-tasks.md`; added neutral `to-spec.md` / `to-tasks.md` (markdown
into `${DOCS_ROOT}/specs|tasks/`, source of truth = the file). `stc.example.yaml`:
the `notion:` block → `doc_backend:` (markdown-local-first, root
`${workspace.root}/.stc-docs`); Notion MCP removed from the `mcp:` block.
Cleaned Notion references from `skills_triggers.md`, `behavior.md`,
`playbook.md`, `secrets.env.example`. Secret-detection of `ntn_` tokens and
the Notion MCP install section kept (universal patterns).

**C2 — PEV (I15/I16/I17) filled into `core/rules/pev.md`.** Added Plan-step 1
(clarify the task; the "solution without a problem" red flag; clarify ≠ ask
more), step 3 (the TDD question; no-yes-man; buy-vs-build), step 4 (AC
mandatory; doc-backend fix via to-spec/to-tasks; design-system; grill-me/
Council; show the plan). Verify kinds (I17) now include the design-system
kind + the UI-fix before/after rule. Task scale table (I16).

**C3 — three new hooks migrated + depersonalized + smoke-tested:**
- `buy-vs-build-reminder.sh` **H14** (FR-24/DEP-4) — JIT-inject on
  `EnterPlanMode` + a Write-backstop for a new module. Marker `/tmp/stc-*`.
- `exec-offload-guard.sh` **H15** — block expensive Bash (noisy data-scripts
  import/seed/scrape/sync → ephemeral agent; audit without `--json`).
  `# in-main` bypass.
- `integration-docs-gate.sh` **H16** — block editing a named integration's
  code without saved research (lifted by research-save or `// docs-checked:`).
  Anton's integrations (cdek/modulbank/…) → one neutral `stripe` example +
  "extend per project"; `${MEMORY_DIR}`/`${DOCS_ROOT}` for paths.
  (Note: in the live source both exec-offload and integration-docs are
  labelled H15 — STC disambiguates to H15/H16.)
  All 3 syntax-clean (`bash -n`), `chmod +x`, 13/13 smoke branches pass.

**C4 — five reference catalogs migrated as neutral templates:**
`reference_retired_codes.md` (the rule→hook retirement registry, read by the
doc-backend generator), `reference_defect_ledger.md` (self-improving review:
symptom → class → cheapest prevention layer → escalation),
`reference_abuse_cases.md` (the attacker perspective by category
AUTH/RATE/AUTHZ/INPUT/BUSINESS-LOGIC/CLIENT-TRUST, with countermeasure + test
hook), `reference_failure_modes.md` (pitfalls per use-case, design-time).
All seeded with the schema + a placeholder example, no personal data.
`reference_infra_audit` stays as the `infra-audit` skill. `MEMORY.md` index
updated; hooks count 13 → 16.

**C5 — `core/hooks/README.md` updated.** The 6-guard map + the "beyond" table
now list H14/H15/H16; the acknowledge-once list adds H14; the render-time
vars table adds `${DOCS_ROOT}`, `${HARNESS_NAME}`, `${SESSION_ID}`; the
wiring example wires the new hooks into the matcher groups.

**C6 — nine agents migrated to `core/agents/` + `registry.yaml` + `README.md`.**
Bodies harness-neutral (research, qa, e2e, security-arch, security-deps,
code-reviewer, docs, cleanup, harness-docs). `registry.yaml` holds the neutral
binding per capability: `model_tier` (fast/mid/heavy), `tools` (capability
set), `affinity` (any / claude-only), `skill_link` (the fallback realisation
for a general-purpose-only harness). The body+binding split keeps the
know-how written once; a harness renders it into its own shape. e2e →
methodology + a pointer to `user/projects/<name>.md` (no FE scenarios);
harness-docs (was anthropic-docs) generalised, affinity=claude-only. All
depersonalized (no Anton/FE/CDEK/personal paths).

**C7 — new codes wired into `behavior.md` / `code_standard.md`.** `code_standard.md`:
[DEP-4] buy-vs-build in the DEP block; §7 review process gained the
self-improving-review protocol; new §9 (abuse-case + failure-mode perspective,
baseline-5, the attacker + the pitfalls reflexes). `behavior.md` I21: added
buy-vs-build (DEP-4/H14) + docs-first (H16); I24: added the expensive-Bash
offload (H15). All 16 H-codes referenced resolve to a hook file.

**C8 — new infra: public vs private.** `core/templates/design-system/`
(process.md + DESIGN.template.md) — neutral methodology, migrated.
`tasks/` (per-session JSON) and `.vscode-todos-bridge/hook.js` (a compiled
VSCode-specific bridge) — **private runtime-state**, not in `core/`
(mechanism noted, not the data). `statusline.sh` — harness-specific, goes to
`adapters/claude/` at Stage 3.

**Decisions reaffirmed (C-sync):**
- **Capability ≠ realisation.** A capability is know-how written once
  (harness-neutral); a harness REALISES it differently. Claude Code → typed
  sub-agents (`~/.claude/agents/`); a general-purpose-only harness (ZCode) →
  the skill + a `general-purpose` dispatch; a vendor-specific capability is
  inert off its harness. The adapter declares `capabilities` per layer;
  `deploy` degrades gracefully.
- **ZCode subagent gap confirmed.** ZCode exposes only `general-purpose` +
  `Explore` — none of the 9 typed agents are dispatchable as a type there.
  Resolution: the methodology lives in `core/skills/` (already migrated,
  Decision 4 — self-contained); ZCode realises it via skill + general-purpose.
- **Claude desktop ≠ a constraint.** The user is moving VS Code → Claude
  Desktop, but it is Claude Code in another GUI — the full infra
  (hooks/agents/commands) survives. The `claude` adapter applies as-is.

**Open items (carry forward, post C-sync):**
- `tasks/` + `.vscode-todos-bridge/` mechanism — decide at Stage 4 whether to
  document a generic "persistent tasks" capability (the live `tasks/` JSON is
  private runtime-state; the bridge is VSCode-specific).
- `statusline.sh` → `adapters/claude/` at Stage 3 (a Claude Code statusLine
  example).
- Full human-readable auto-updating **README** — before Stage 7.

## ✅ C9 — the infra graph + the new memory system (DONE 2026-06-30)

A second look at the tuning history (`project_tuning_pending.md` session
2026-06-22) surfaced two systems the first sync missed: the **infra graph**
(the code-label navigation layer over `core/`; internally nicknamed
"graphify" — **not** the graphify CLI tool, see C10) and the **vault model**
of memory (the Notion→Obsidian migration's actual architecture, not just
"Notion retired").

**C9a — the graph engine.** `core/scripts/infra_graph.py` — the neutral core
extracted from the live `infra-gen.py`: `collect()` + `RELATED` + the md/sh
parsers + FuncRec/ArtifactRec. NO Notion code (the `main()` + the Notion
class are retired). Paths resolve from env (`STC_CORE_DIR`, `STC_MEMORY_DIR`,
`STC_HARNESS_DIR`). Modes: `--summary` (counts), `--check` (orphan/gap/dup
audit, reads `reference_retired_codes.md`), `--json`. Verified: 48 functions
/ 50 artifacts / 28 edges, I04 retired correctly excluded.

**C9b — the graph renderer.** `core/scripts/infra_graph_render.py` — renders
the graph into `${DOCS_ROOT}/infra/` as notes (one per code-label, with
`[[code]]` Related edges + artifact stubs + the `00-infra-index.md` hub).
Tags `infra/<type>` + `load/<loading>` for the Graph view. Idempotent;
`--dry-run` mode. Verified: 92 notes (48 functions + 43 stubs + index).

**C9c — the vault-model templates.** `core/templates/vault/`:
- `Home.md` — the MOC, the vault entry point.
- `tasks-board.md` — the task board (Dataview by project/status) + the
  task-line convention (inline fields project/block/exec/priority).
- `specs-index.md` — the feature-spec index (Dataview) + the open-AC query.
- `spec-template.md` — the `/to-spec` source template (use cases / AC #ac /
  ADR / buy-vs-build / abuse / failure-modes / block plan).

**C9d — playbook § Doc backend** rewritten for the vault model:
markdown-local-first, the MOC, `[[wiki-links]]` + `aliases` (resolve
dash-slugs → underscore files, no phantom nodes), the Dataview boards, the
auto-generated infra graph. The sync step is now `infra_graph.py --check` +
`infra_graph_render.py` (idempotent), not a Notion pipeline.

**C9e — `MEMORY.md`** gained a "Doc backend (vault model)" section; the
playbook description updated.

**Decisions reaffirmed (C9):**
- The doc backend is **markdown-local-first**; Obsidian (or any markdown
  editor) is a *view*, not the store. The source of truth is always the file.
  This keeps STC vendor-neutral (no Obsidian lock-in) while giving the
  graph/Dataview/`[[link]]` UX where an editor supports it.
- The infra graph is the **navigation layer** over the code-labels — it makes
  the whole framework browsable as a graph. The engine is neutral Python; the
  output is plain markdown notes.

**Open items (carry forward, post C9):**
- Code-label coverage: the engine flags `A01-A10` / `S01-S11` / some `R` as
  orphans because the agent/skill/memory files in `core/` were migrated
  without the `<!-- Ann -->` / `<!-- Snn -->` label comments the live files
  carry. Adding the labels (so the graph is complete) is a follow-up (C9f).
- `statusline.sh` → `adapters/claude/` at Stage 3.
- Full human-readable auto-updating **README** — before Stage 7.

## ✅ C10 — graphify (code-graph, REQUIRED) + LLM Wiki pattern (DONE 2026-07-01)

The user pointed out two things the sync had missed: **graphify** (the
safishamsi/graphify CLI tool, installed at `~/.local/bin/graphify`, already
running on FE/Driada) and the **LLM Wiki** recipe by Karpathy (Ingest+Lint,
really Ingest+Query+Lint). Both are about *code/project knowledge*, a
different axis from the agent infra. Per the user's call, graphify is a
**required** core capability, not an optional pilot.

**Name collision resolved:** "graphify" was already used in this repo as the
internal nickname for the infra-graph Python engine (C9). The new skill is
named **`code-graph`** (neutral, no graph-node collision); "graphify" is the
CLI/MCP server name. The C9 changelog was clarified accordingly.

**C10a — `core/skills/code-graph/SKILL.md`** (`S18`) — the required
capability. Wraps the graphify CLI: build (`ingest`/`update`/`watch`),
query (`query`/`affected`/`path`/`explain`), organize (`cluster-only`/
`label`), wiki (`wiki`/`reflect`), cross-repo (`merge-graphs`/`merge-driver`),
feedback (`save-result`). Output `graphify-out/` (gitignored in target
repos). Workflow: ingest on first contact → query during work → save-result
→ update/reflect at milestones.

**C10b — `core/skills/llm-wiki/SKILL.md`** (`S19`) — the Karpathy pattern,
neutral. Compile-once vs RAG ("no accumulation"). Three operations (Ingest
integrates a source into ~10–15 wiki pages + updates `index.md`/`log.md`;
Query synthesizes with citations and files good answers back; Lint health-
checks contradictions/stale/orphans/missing-links). Three layers (raw
sources immutable / wiki LLM-owned / schema AGENTS.md). graphify
`wiki`/`reflect` is the primary implementation in STC.

**C10c — `stc.example.yaml`** — `mcp.graphify` block, `enabled: true`
(REQUIRED, alongside Playwright). `command_env`, `output_dir`,
`api_key_env` (auto-detected). **`user/secrets.env.example`** —
`ANTHROPIC_API_KEY` as a required var (no "if enabled").

**C10d — `core/memory/skills_triggers.md`** — two entries (`code-graph`
required, `llm-wiki` pattern). **`core/commands/install-mcp.md`** — a
graphify section (standalone CLI, `graphify install --platform <harness>`,
not an npx server).

**C10e — `core/scripts/infra_graph.py`** — RELATED edge `S18 → [S19]`
(code-graph → llm-wiki). Both now resolve in the graph (verified: 73
functions, 18 skills, 29 edges).

**Decisions reaffirmed (C10):**
- graphify is a **required** STC base capability (like Playwright for e2e).
- graphify implements the LLM-Wiki pattern over a code graph; the pattern
  itself is documented neutrally (Karpathy's gist is editor/implementation
  agnostic).
- Sources: [safishamsi/graphify](https://github.com/safishamsi/graphify),
  [Karpathy's llm-wiki gist (2026-04-04)](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

**Open items (carry forward, post C10):**
- graphify wiring is the source-of-truth in `stc.example.yaml`; the actual
  render into a harness's MCP config is Stage 4 (deploy.py).
- Code-label coverage (C9f) — the engine still flags a few legacy codes
  (A10, I19, R03/R05/R08, S10/S26) as orphans/gaps from the migration;
  follow-up.

## ✅ C11 — model axis extracted from adapters (DONE 2026-07-01)

User catch: Stage 3 had conflated two orthogonal axes. **ZCode is a harness
(the live form), not a model.** Stage 3's `adapter.yaml` files each carried a
`model_tier_map` (`claude → haiku/sonnet/opus`, `zcode → glm-5.2/glm-5-turbo`),
which wrongly tied a *harness* to one *model family*. That is false: a harness
does not dictate a model. Claude Code can run **GLM** behind the Anthropic-
compatible endpoint (the live infra proves it — `~/.zcode/v2/config.json` shows
GLM on `open.bigmodel.cn/api/anthropic`); ZCode can run Claude models.

**Two orthogonal axes (now explicit):**

| Axis | Controls | Lives in | Examples |
|---|---|---|---|
| **Harness** | live FORM (file layout, dispatch, hook wiring, import syntax) | `adapters/<harness>/adapter.yaml` | claude, zcode |
| **Model** | ENGINE (concrete ids per tier, context windows, transport) | `core/models/<provider>.yaml` | glm, claude |

Composed at deploy: adapter(form) × provider(model) × registry(tier) →
concrete id. The model axis **never degrades form**; only the harness axis
does (claude→zcode loses typed agents because zcode exposes none — a property
of the harness, not the model).

**C11a — `core/models/{glm,claude}.yaml`** — new MODEL axis. Each provider
declares `api` (kind/base_url/auth/key_env), `tiers` (fast/mid/heavy →
concrete id), `context` (per-tier window), `capabilities`. GLM notes heavy→mid
(no opus-class); Claude has opus.

**C11b — `adapter.yaml` × 3** — `model_tier_map` **removed** from claude /
zcode / _template, replaced with a NOTE redirecting to the model axis.

**C11c — `stc.example.yaml`** — new `models.provider` block (`glm | claude | …`),
documented as orthogonal to `deploy.targets`.

**C11d — `adapters/README.md`** — new "Two orthogonal axes" section + the
"GLM in Claude Code" worked example (claude adapter form × glm provider ids,
no form degradation); deploy.py step 1/2 updated to compose provider.

**Verification:** `model_tier_map` purged from all 3 adapters; all 3 still
valid YAML (7 layers); both provider files well-formed (provider/api/tiers/
context); `stc.example.yaml` carries `models.provider: glm`; capability
parity across harnesses unchanged by the edit.

**Decisions reaffirmed (C11):**
- The harness axis and the model axis are independent; `stc.yaml` picks the
  pairing (`deploy.targets` + `models.provider`).
- `affinity: claude-only` on `harness-docs` is a **harness** binding (answers
  from *the harness it runs in*), not a model binding — correct as-is.

## ✅ Stage 3 — adapters (DONE 2026-07-01)

The capability-model adapters: a declarative contract per harness stating
*how this harness realises each STC layer*. `core/` is the know-how (written
once, neutral); the adapter is the binding. This is what resolves the
**"adapters encode the live form of the harness"** concern — the live form
(CLAUDE.md vs AGENTS.md, typed agents vs untyped dispatch, `@import` vs none,
settings.json vs plugin manifest) lives here, never in `core/`.

**The layer model (6 layers + always_context):** each adapter declares, per
layer, a `realization`, a `native_path`, an `import_syntax`, and a
`capabilities` map. Each capability carries:
- `supported: true` — exists natively (`native` describes the rendered artifact)
- `supported: degrade` — weaker native form; `fallback` names the substitute
- `supported: false` — inert on this harness; `fallback` names the substitute
  (or `none`)

Principle: **capability ≠ realisation** — degrade gracefully, never lose the
capability, only its native form.

**Stage 3a — `adapters/README.md`** — the adapter contract: what an adapter
is/is-not, the layer model, canonical paths (`~/.stc/` shared + per-harness
native dir), how `deploy.py` (Stage 4) consumes it, how to add a harness.

**Stage 3b — `adapters/claude/adapter.yaml`** — the REFERENCE realisation,
encoded from the live `~/.claude` form (read-only source): native `@import`
in CLAUDE.md (always_context), 9 typed sub-agent files (subagents — full
type system), 16 hooks wired in `settings.json` matcher groups, statusline
via `settings.json`. All 9 typed agents `supported: true`. `harness_facts`
carries the things deploy needs: `model_tier_map` (fast/mid/heavy → concrete
model id), `hook_event_names`, `mcp_config_file`, `subagent_dispatch_tool`.

**Stage 3c — `adapters/zcode/adapter.yaml`** — the DEGRADE realisation.
ZCode is general-purpose-only (`general-purpose` + `Explore`, no typed
agents). Per the user's resolution, every typed STC agent `supported: degrade`
→ `skill(<name>) loaded as the dispatch instruction` + general-purpose as the
carrier. **No capability is lost** — the methodology travels via the skill;
only the native type is absent. `harness-docs` `supported: false` (vendor-
specific, inert off-claude). always_context uses `AGENTS.md` with `@import`
attempted and H06 JIT-inject as the standing fallback. Capabilities ship as a
plugin (`.zcode-plugin-seed.json` + `skills/` + `hooks/hooks.json`), the
harness's native extension form (observed in `superpowers`/`document-skills`).

**Stage 3d — `adapters/_template/adapter.yaml`** — documented skeleton.
Every `# TODO` marks a decision for a new harness. Mirrors the claude/zcode
shape so `deploy.py --target <new> --dry-run` works the moment it's filled.

**Stage 3e — `adapters/claude/statusline.sh`** — carry-forward from
`~/.claude/statusline.sh` (read-only source). Harness glue deploy can't
derive from yaml (model/dir/ctx-fill statusline, threshold alerts). Syntax
checked + smoke-tested (78% payload → red 🔴 + `/save-and-compact` nudge).

**Verification (Stage 3f):**
- All 3 `adapter.yaml` parse as valid YAML (7 layers each).
- Capability parity: every STC capability present on all 3 harnesses.
  The only intentional count diff: zcode subagents = 11 (9 STC + the 2 native
  types `general-purpose`/`Explore` it *exposes*), claude = 9.
- Contract checks pass: 9/9 typed agents degrade on zcode (skill + dispatch);
  `harness-docs` inert off-claude; 9/9 native on claude; always_context =
  native `@import` primary + H06 fallback on both; playwright + graphify
  REQUIRED on both; 16/16 hooks present (zcode H04 `degrade` — matcher is
  `Agent` not `Task`).

**Decisions reaffirmed (Stage 3):**
- `~/.stc/` is the canonical cross-harness home; `~/.claude`/`~/.zcode` are
  deploy targets (written only by `deploy.py` after the stage-5/6 gate).
- ZCode typed-agent gap resolved via **skill + general-purpose dispatch**
  (user choice) — not "drop the agent layer".
- Always-context divergence resolved via **native `@import` primary, H06
  JIT-inject fallback** (user choice) — H06 already exists for post-compact
  recovery and is the universal safety net.
- Adapter is *declarative* — deploy.py (Stage 4) reads it; it owns no
  deploy-time behaviour itself.

**Open items (carry forward):**
- `deploy.py` (Stage 4) is the consumer of these contracts; the render logic
  (model_tier → concrete id, neutral tools → harness tool ids, skill-loaded-
  dispatch instruction generation) is implemented there.
- ZCode `@import` support is `unverified`; Stage 4/6 will confirm against the
  running harness (H06 fallback covers it either way).
- `_template` is a skeleton — no live harness behind it yet.

## ✅ Stage 4 — deploy/ pipeline (DONE 2026-07-01)

The executable consumer of the Stage-3 contracts. Takes `stc.yaml` × `core/`
× `core/models/<provider>.yaml` × `adapters/<harness>/adapter.yaml` and
renders the harness form. **Non-destructive by construction** — the design
answers the user's central concern: *what happens to a user's existing
environment when STC lands on top of it?*

**The non-destructive model (4 pillars):**
1. **All markdown artifacts carry `.stc.md` suffix** — `code-reviewer.stc.md`,
   `to-spec.stc.md`, `CLAUDE.stc.md`. Same-name collisions are **structurally
   impossible**: a user's `code-reviewer.md` and STC's `code-reviewer.stc.md`
   coexist; the user file is never touched.
2. **The ONE user-owned file touched** is the always-context file
   (`CLAUDE.md`/`AGENTS.md`), via a single `@import` line inside a managed
   marker block (`# >>> STC BEGIN >>>` … `# <<< STC END <<<`). Idempotent;
   uninstall removes only the block, user content byte-identical after
   apply→uninstall (verified).
3. **settings.json / .mcp.json refuse-by-default** on collision (user hook on
   the same matcher, or mcpServer name clash). deploy prints a precise report
   (where/what/whose) and refuses; resolution only via `--overwrite` (backup +
   STC wins) or `--skip-collisions`. A backup snapshot of every touched JSON
   is taken **before** any write.
4. **Re-deploy is idempotent**: `.stc.md` re-overwritten (fully STC-owned),
   marker block replaced between tags, STC JSON entries keyed by `stc-*`
   namespace updated in place (verified: second `apply` = identical output).

**Files (`deploy/`):**
- **`deploy.py`** (~250 lines) — CLI + orchestration. Commands: `render`
  (--dry-run preview), `apply` (--overwrite/--skip-collisions), `uninstall`,
  `check`, `restore <backup-id>`. Defaults to dry-run; never writes
  `~/.claude`/`~/.zcode` until the Stage 5/6 gate.
- **`render.py`** (~300 lines) — the 7-layer renderer, a PURE function
  (returns artifacts, no disk writes — testable in isolation). Renders
  always_context bundle, 16 hooks with **var substitution from each hook's
  own declared `# Render-time vars` block** (13 deploy-owned vars; script
  locals like SESSION/BROKEN left to bash), commands/skills/agents as
  `.stc.md`, `.mcp.json` with `stc-*` namespace. Model composition:
  `registry.tier × provider.tiers = concrete id`.
- **`stc_block.py`** (~110 lines) — the marker-block mechanism (inject /
  remove / has). Idempotent; handles create/insert/replace/noop; survives
  dangling markers.
- **`checks.py`** (~230 lines) — precheck (config validity, required
  capabilities), collision-detect (matcher overlap, mcp-name clash,
  statusline), backup_snapshot/restore, postcheck (`bash -n` on rendered
  hooks), onboarding.
- **`README.md`** — non-destructive model + command reference.

**Verification (all green):**
- `check`: config valid; claude=52 files/2 JSON patches/**19 collisions**
  (the live `~/.claude` already has STC's hooks — detection is correct);
  zcode=52/2/**0 collisions**.
- `render --target claude --dry-run`: 9 agents (frontmatter+model composed:
  code-reviewer→glm-5.2, harness-docs→glm-5-turbo), 10 commands, 15 skills,
  16 hooks, CLAUDE.stc.md, statusline.stc.sh, settings.json+.mcp.json patches.
- `render --target zcode --dry-run`: 11 agent dispatch-instructions (9
  degrade + general-purpose + Explore), **0 typed agent files**, harness-docs
  correctly absent (supported:false), AGENTS.stc.md, plugin-delivery layout
  (`cli/plugins/cache/stc/current/...`).
- **bash -n** on all 16 rendered hooks: 0 syntax errors.
- **Non-destructive round-trip** (isolated sandbox): apply→uninstall leaves
  user CLAUDE.md **byte-identical**; user `code-reviewer.md` coexists with
  STC's `.stc.md`; re-inject idempotent (`noop`).
- **settings.json cycle**: collision detected (4) → backup → merge (user
  hook `~/my.sh` preserved + 7 STC hooks added, user `model`/`permissions`
  untouched) → re-deploy idempotent (8==8) → uninstall strips only STC
  entries, user hook survives.
- **var substitution**: MEMORY_DIR fully resolved in H06 body; USER_LANG
  bash-default (`${USER_LANG:-en}`) correctly left intact.

**Decisions reaffirmed (Stage 4):**
- `.stc.md` / `.stc.sh` suffix everywhere → same-name collisions excluded by
  construction (user's call, refined from the marker-block-in-every-file idea).
- settings.json/.mcp.json refuse-by-default + show-conflict (user's call) —
  never silently overwrite JSON.
- Backup snapshot always-before-write; `restore <id>` for rollback.
- `~/.stc/core/` mirrors the repo `core/` so one update reaches all harnesses.

**Open items (carry forward):**
- Native-dir writes (`~/.claude`/`~/.zcode`) gated to Stage 5/6.
- Live `apply` against the real `~/.claude` will surface the 19 real
  collisions (expected — STC grew out of that infra); `--overwrite` resolves.
- Doc backend: markdown-local-first, Obsidian as an optional view (resolved in
  C9, not frozen). No Obsidian-aware flag — the .md file is always the source
  of truth; a vault-mode editor over `doc_backend.root` is a view, no lock-in.
- MCP runtime-fallback (server down) is runtime, not deploy.

## ✅ FR-28 — orchestrator mode (DONE 2026-07-14)

The process shift on top of the exec-slice line (FR-27): plan on the
expensive model, execute on cheap tiers, main = orchestration only.

- **deploy `session_defaults`** — deploy owns `permissions.defaultMode: plan`
  + `model: opus` in settings.json (manifest-tracked, uninstall strips only
  unchanged values). The plan-mode-default H14/H21 always assumed is now
  STC-owned, not a hand-edit.
- **H21 → exit-plan-gate (hard):** ExitPlanMode blocks once unless the plan
  carries AC/DoD + block→executor decomposition + a forks-resolved line; M/L
  need `/to-spec` + `/to-tasks` artifacts written (the decomposition is a doc,
  not chat).
- **H14 → orchestrator gate (session-long):** after plan mode, main editing a
  project file blocks once PER FILE (retry passes — the WHY lands in the
  transcript); sub-agents pass; memory/docs/*.md/.env/STC-infra excluded.
- **`builder` agent (sonnet)** — executes ONE plan block per spec/brief;
  DECIDED/FORK protocol; H04 requires `fork-protocol` + `reuse-before-reinvent`
  in build-agent prompts.
- **Fork routing:** local trivia → executor (DECIDED); architectural → main
  decides + ADR line in the spec; business → the user; plan-breaking
  constraint → re-plan the affected blocks, independent blocks keep running.
- Rules: pev.md Step 4 + Do (orchestration loop); playbook (prompt contract,
  token economy); to-tasks (builder default; `main` needs an inline WHY).

## Stages still ahead
- Stage 5: stc.yaml + end-to-end (real `apply` against `~/.claude`/`~/.zcode`,
  resolving the live 19 collisions; the consent gate opens here)
- Stage 6: verification + switch (claude-infra stays untouched until STC proven)
- Stage 7: public release (after beta)

---

## Hard constraints (carry forward)
- `~/.claude` and claude-infra: read-only, never modified
- `~/.zcode`: only after approval at Stage 5
- Files created only inside STC repo (local until push)
- Each stage → preview → user "ok" → apply
- No commit/push without explicit "push"
