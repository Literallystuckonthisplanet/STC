# Changelog

All notable changes to STC Core are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0.0. Until then, the `0.x` line carries the deploy pipeline and
breaking changes can happen between minor bumps.

Each release tag (`git tag -a v0.X.0`) points at the section below as its
release notes.

## [Unreleased]

### Added — H19 precompact-memory-guard (rotate memory before compaction)
- New hook `precompact-memory-guard.sh` on the `PreCompact` event (fires before a
  manual `/compact` AND before auto-compaction): injects the I26 memory-rotation
  directive so facts are saved before the summary replaces context. Restores the
  proactive pre-compaction reminder that was dropped on the STC migration under the
  (now outdated) assumption that the harness has no PreCompact hook. `PreCompact`
  added to the claude adapter's `hook_event_names`; `behavior.md` rule 2 now cites
  H19 + H06 (post-compact recovery) as the compaction-boundary safety net. Core
  hook count 18 → 19.

### Changed — H11 output-hygiene disabled on the claude harness
- `adapters/claude/adapter.yaml`: `H11_output_hygiene` set `supported: false`. The
  claude harness already collapses/persists large tool output, so the guard is
  redundant here and over-fires on grouped commands (`find`/`grep -r` inside a
  `{ … } > file` block, where the redirect is on the group not the segment). Kept
  in `core/` for clutter-prone harnesses (VS Code/zcode). Claude now deploys 18
  active hooks (H11 inert).

### Added — commit-checklist memory anchor (H01/I26)
- The JIT commit checklist (`block-dangerous-git.sh`, I17/I09) gains a MEMORY line
  (ru+en): a commit is the completion point of a code task, so if it changes project
  state/decisions, update `project_<name>.md` (STATE/CHANGELOG) before committing.
  Makes the deterministic commit event a memory-write trigger instead of relying on
  a fuzzy "task done" notion.

### Removed — leftover GitHub MCP references
- Dropped the GitHub MCP row from README and the `GITHUB_PERSONAL_ACCESS_TOKEN`
  block from `user/secrets.env.example` (the server was already removed from the
  `mcp:` block on 2026-07-11; it survived as a manual entry in the user's private
  `~/.claude.json` with a plaintext PAT, since removed and the token revoked). STC
  does all GitHub work through the git CLI over SSH.

### Fixed — deploy now prunes removed MCP servers
- `_merge_mcp_patch` upserted servers but never removed one dropped from the
  `mcp:` block — a retired server (with its secret) lingered in `.mcp.json`
  forever (the same gap the hooks-sweep fixed). Now prunes `stc-*` servers the
  render no longer emits (guarded on a non-empty patch; user servers untouched).
  Regression test added. Applied: removed the unused `github` MCP (all GitHub
  work goes through the git CLI) and `gsheets` from the private config.

### Added — llm-wiki feedback loop wired into the session lifecycle
- The Karpathy llm-wiki pattern now runs itself instead of being a manual ritual:
  H18 nudges `graphify query` in a graphed repo → a useful answer is
  `save-result`'d during work → `session.md` §3 (session end) runs `graphify
  reflect` to fold saved outcomes into `LESSONS.md`. Ingest/Query/Lint mapped
  onto add/query/reflect; the lessons compound across sessions. (graphify 0.9.x
  has no single `wiki` command, so the loop is the reflect/feedback path.)

### Added — H18 graphify-first (enforce code-graph over grep-chains)
- New hook `graphify-first.sh`: in a repo that already has a built code-graph
  (`graphify-out/graph.json`), the first grep-style search (Grep tool, or a Bash
  `grep`/`rg`/`ag`/`git grep`) is hard-blocked once with a nudge to use
  `graphify query`/`affected`/`explain` for how/why/connect/blast-radius
  questions — a built graph nobody queries is wasted. Acknowledge-once: the
  marker is set before `exit 2`, so a repeat passes (grep is still right for an
  exact-string lookup). Repos without a graph are never gated. Wired on
  `Grep|Bash`; hook count 17 → 18.

### Fixed — H16 integration-docs-gate false-positive on bare service names
- The tier-1 LEXICON keyed an integration off ANY occurrence of a service name,
  so a generic-English name (openai/stripe/aws/sheets/…) in a comment, a string,
  a regex, or a **secret-pattern definition** produced a false docs-first block
  (hit while adding token regexes to the leak-guard). Generic-English names now
  require a **USAGE** signal (import / API host / `*_api_key` / SDK client /
  network call); niche/regional names (cdek/modulbank/vk/…) still match on a
  bare mention. Same class as the earlier H15/H16 language-keyword fixes.
  Functional test covers the pass/block cases; logged in the defect ledger.

### Fixed — first ×3 review pass (code-reviewer + security-arch + qa) on STC itself
The review pipeline was run against its own codebase for the first time. Real
findings fixed (each with a regression test; suite 34 → 42):
- **infra-graph skill-artifact slug collision** (`infra_graph_render.py`) —
  every skill's source file is literally `SKILL.md`, so `art_slug` collapsed all
  15 skills into one `art-skill-md` stub (last wins; 14 skill notes pointed at
  the wrong artifact). Now disambiguates on the parent dir → `art-<name>-skill`.
- **stale hook wiring after a retired capability** (`deploy.py`) — a hook
  capability fully removed from a render left its `settings.json` entry behind
  forever (pointing at a script `_prune_orphans` had just deleted). `apply` now
  sweeps STC-managed entries whose cap is no longer emitted (guarded on a
  non-empty patch), mirroring uninstall.
- **corrupt `hooks` key silently dropped config** (`deploy.py`) — a non-dict
  `hooks` value made `_merge_settings_patch` return early, discarding the
  statusLine/permissions writes too, under a "✓ applied" report. Now resets it
  with a loud warning and still applies the rest.
- **destructive-git block was trivially bypassable** (`block-dangerous-git.sh`,
  H01) — the match was literal / case-sensitive / single-space, so
  `GIT RESET --HARD`, `git  reset  --hard`, or a tab slipped past. Now
  whitespace-normalized + case-insensitive (`-i`); verified functionally.
- **public-leak guard was incomplete + not wired to git** (`checks.py`) — it
  scanned only emails/IPs/private-keys, not API tokens; added the token-format
  set (ghp_/ntn_/sk-ant/AKIA/xox/…, min-length so placeholders don't trip), and
  a versioned `deploy/git-hooks/pre-commit` that runs it on every commit
  (activate: `git config core.hooksPath deploy/git-hooks`).
- **`stc_block` dangling-marker data loss** — a BEGIN with a hand-deleted END
  swallowed the user's trailing content on the next `inject_block`; now treated
  as "no block" (append fresh, tail preserved).
- **infra-graph external-code ignore was a blanket subtraction** — `A10`/`S26`
  were removed unconditionally, which would also hide a *genuine* orphan; now
  context-scoped (only next to OWASP/YC markers). `RE_RETIRED` arrow class
  tightened to `→|->`.

### Fixed — H01 release-ack marker was global, not per-session
- `block-dangerous-git.sh` built its push-to-main ack path from `${SESSION_ID}`,
  which a hook never receives in its environment — it arrives in the stdin JSON.
  The marker therefore collapsed to a single global `/tmp/stc-release-`, so one
  session's "releasing" acknowledgement leaked into every other session. The hook
  now parses `.session_id` from stdin so the marker is genuinely per-session.

### Added — deploy prunes orphaned artifacts on apply
- `apply` now removes files a prior deploy wrote that the current render no longer
  emits (e.g. a retired command like `handoff.stc.md`), by diffing the previous
  manifest against the render. Scoped hard to STC-owned shapes (`.stc.md` /
  `.stc.sh` / `SKILL.md`) so a user file can never be removed even on a manifest
  glitch. Previously a dropped artifact lingered in the harness forever (removed
  by hand). Regression test covers prune + the user-file-safety invariant.

### Fixed — infra graph: full code-label coverage, no false orphans
- The graph engine dropped R-codes defined in `project_docs.md` (it was scanned
  under a single "I" type letter) — the scan now accepts multiple letters ("IR"),
  so `R05`/`R08` resolve. Added the missing `<!-- Rnn -->` labels to the three
  reference catalogs (`R01` failure-modes, `R03` defect-ledger, `R06` abuse-cases)
  and `<!-- I19 -->` to the design-system rule. External-taxonomy collisions
  (`A10` = OWASP Top-10 SSRF, `S26` = a YC batch tag) are excluded from the
  mention scan so they no longer read as orphans. The retired registry
  (I04/S05/S09) resolves from `core/memory`. Result: **0 orphans, 0 duplicates**
  (was 6 orphans + numbering gaps R/I/S); only the historical `S10` gap remains
  (a code that never materialized in the canon). The `infra_graph_render.py` map
  renders cleanly into the doc backend.

### Added — FR-27 exec-slice planning (which model runs each block)
- New planning lever in `pev.md` § Plan step 4: every M/L task block is tagged
  with its cheapest safe executor — `sub-haiku` / `sub-sonnet` / `cheap-session`
  / `main` (a written reason required for `main`) — presented to the user as a
  table before work starts, so mechanical work stops defaulting to the expensive
  main thread. **Enforced by H14**: after plan mode the first code edit is
  hard-blocked once until the exec-slice table is produced (acknowledge-once).

### Added — three deploy prechecks
- **Reference integrity** — every `Hxx` / `[[wiki-link]]` / skill-dir a rule
  names must resolve (hyphen/underscore normalized; templates and piped aliases
  handled); a dangling reference fails the precheck.
- **Personal-data leak-guard** — `core/**` is public, so the precheck scans for
  real e-mails, public IPv4 (loopback/private/link-local excluded), and
  private-key headers, and refuses the deploy if any are found.
- **glm-on-claude guard** — a `glm-*` model id resolved onto a `claude` target
  is rejected (typed sub-agents would otherwise silently fail to dispatch).

### Changed — zcode adapter frozen
- Development now focuses on the `claude` harness. The `zcode` adapter stays
  in-tree as the reference degrade realisation but is marked `frozen: true`:
  `apply`/`render` with no `--target` skip it; an explicit `--target zcode`
  still works, with a warning. The adapter principle is unchanged.

### Changed — skills trigger table moved to lazy memory
- The "which skill, when" summary table moved out of `pev.md` (always-context)
  into `skills_triggers.md` (lazy); `pev.md` keeps a one-line pointer. Keeps the
  always-context bundle lean (detailed tables → lazy).

### Fixed — skills invisible on the claude target too (`SKILL.stc.md`)
- `_render_skills` emitted `SKILL.stc.md` for files delivery, but the Claude
  loose-file skill loader requires exactly `SKILL.md` (same as the plugin
  loader) — so every skill was invisible on `claude` as well, not only zcode.
  Now `SKILL.md` for both deliveries. Completes the 0.1.2 plugin-only fix.

### Fixed — generic content dropped during the pre-STC → core/ migration
- A migration audit found generic rule/reference content lost when the pre-STC
  memory was migrated into `core/`. Restored: the docs-first behaviour rule, the
  legal-review checkpoint, the integration registry, playbook operational
  content, and the `code_standard` / `abuse_cases` / `defect_ledger` /
  `failure_modes` / `retired_codes` / `skills_triggers` catalog bodies.

### Fixed — GLM default-provider leak
- `stc.yaml` and `stc.example.yaml` defaulted `models.provider` to `glm`;
  corrected to `claude` (the default should be the reference harness's own
  provider). The glm-on-claude precheck backstops any recurrence.

### Fixed — H15/H16 hook false-positives on language keywords
- **H15** (exec-offload) no longer blocks inline-eval runners: `python -c
  "import …"` / `node -e` / `ruby -e` — `import` there is a language keyword,
  not a data-import script.
- **H16** (integration-docs-gate) narrowed the `anthropic` key to real SDK/API
  signals (`api.anthropic` / `@anthropic-ai` / `import anthropic` /
  `anthropic.Anthropic` / `*_api_key`), so an `@anthropic.com` e-mail literal in
  code no longer reads as an Anthropic-API integration.

### Testing
- Suite grew 15 → 42 tests (frozen-adapter skip, reference-integrity,
  personal-data leak-guard + token patterns, glm-on-claude, `SKILL.md` for both
  deliveries, orphan-prune + user-file safety, and the ×3-review regression
  shields: art_slug, retired-cap sweep, corrupt-hooks, dangling marker,
  multi-letter/context-scoped graph scan).

### Changed — session-end flow: memory rotation replaces handoff/save-and-compact
- **New rule I26 (`behavior.md` § Memory rotation).** Project facts are saved
  to `project_<name>.md` (R08 STATE/CHANGELOG) live as they arise; at task
  completion and session end the prior STATE/CHANGELOG rotates to
  `archive/project_<name>_archive.md`, so STATE always reflects the latest
  session. Session start = read STATE; no handoff doc needed.
- **Removed commands `/handoff` (S05) and `/save-and-compact` (S09)** from
  core and all adapters; both registered in `reference_retired_codes.md`
  (→ I26). `COMPACT_CMD` now defaults to the harness-native `/compact`;
  hook H03 texts point at I26 instead of the removed command. The dead
  `workspace.handoffs_dir` config knob is gone; the playbook "cheap session"
  lever writes its brief into the project's OPEN section instead of
  `${HANDOFFS_DIR}`.
- **R08 format documented in `project_docs.md`** (STATE/OPEN/CHANGELOG,
  pointer + status, rotation reference).

### Fixed — per-harness rule delivery (the double-delivery bug)
- `_render_always_context` now branches on `harness_facts.rules_delivery`:
  **claude = `"hook"`** — H06 injects the 3 firing rules on SessionStart
  (verified live), the bundle stays a pointer (inlining would have delivered
  every rule twice, ~20KB duplicate per session, after the 0.1.2-era inline
  workaround); **zcode = `"inline"`** — plugin hooks register but do not
  fire in the current build, so rule bodies land in the bundle. The user
  profile is inlined for both (no hook injects it — never duplicates).
  Regression tests split accordingly (`test_claude_bundle_is_pointer_not_inline`,
  `test_zcode_bundle_inlines_rules`, profile-inline test).
- `session.md` §1 rewritten to describe the real loading mechanism (3 rules +
  profile always; MEMORY.md/playbook/code_standard lazy) instead of the stale
  7-file `@import` list.
- New render vars `DEPLOY_SCRIPT` (absolute path to deploy.py, was a phantom
  token) and `HARNESS_LIST` for the session-end infra re-apply step.

## [0.1.2] — 2026-07-08

### Fixed — zcode plugin delivery
Three bugs that made the STC plugin, its MCP servers, and its skills invisible
on the zcode target (capability_delivery == "plugin"). All three stemmed from
the zcode adapter being written by the Claude files-delivery model.

- **Plugin not discovered.** ZCode enumerates plugin candidates from
  `cache/zcode-plugins-official/` (hardcoded) and `cli/plugins/installed_plugins
  .json` — not from `known_marketplaces.json` or any `marketplace.json` (the
  diagnosing-plugins skill's claim did not match the runtime code). STC was
  enabled in `config.json` but had no `installed_plugins.json` record, so
  discovery never reached it. `_register_plugin` / `_unregister_plugin` now
  write/remove that record; the non-functional `marketplace.json` generation is
  removed, and the `known_marketplaces.json` entry now carries `pluginCount`
  (without it the record was dropped by the validity filter).
- **MCP servers not discovered.** `_render_mcp` unconditionally wrote servers
  to a harness-global `~/.zcode/.mcp.json` patch (the Claude form). Plugin
  delivery requires them inside the plugin root (`<pluginRoot>/.mcp.json`,
  namespaced `plugin:<plugin>:<server>`) — the only location where `${...}`
  secrets expand. `_render_mcp` now branches on `capability_delivery`: plugin →
  `result.files[<plugin_root>/.mcp.json]`; files → the existing json_patches
  path. Claude (files delivery) is unchanged.
- **Skills not discovered.** Skills rendered as `SKILL.stc.md` (the collision-
  proof suffix used for Claude loose files). The plugin loader expects
  `SKILL.md` (the convention every working plugin follows); inside a plugin the
  skill is already namespaced by `skills/<name>/`, so the `.stc.md` suffix made
  every skill invisible. `_render_skills` now emits `SKILL.md` for plugin
  delivery and keeps `SKILL.stc.md` for files delivery.
- Bumped `PLUGIN_VERSION` 0.1.0 → 0.1.2 (the plugin version had lagged behind
  the CHANGELOG). Added regression tests covering all three fixes.

## [0.1.1] — 2026-07-07

### Added
- **README** as a comprehensive guide: the three problems STC solves (token
  economy, cross-session/cross-provider knowledge, SDLC via SDD→TDD); the
  guiding principles (minimal third-party tools, maximal use of the harness's
  own capabilities); the abstraction layers; third-party tool credits with
  links; a detailed walkthrough of every hook, rule, and injected context;
  the memory file structure; and a full deployer/renderer scenario reference.
  Hyperlinked table of contents.

## [0.1.0] — 2026-07-07 — "Hello, World"

The first release. The codebase lands in the repository.

> _Hello, World. The Construct is online._

This is the initial import of the STC Core pipeline. Everything below was
built and battle-tested against a live `~/.claude` and `~/.zcode` before the
first commit landed here.

### Added — the pipeline
- **`deploy/`** — the deploy orchestrator: `deploy.py` (CLI: `render`,
  `apply`, `uninstall`, `check`, `restore`), `render.py` (pure 8-layer
  renderer, no disk writes), `checks.py` (precheck, collision detection,
  backup/restore), `stc_block.py` (the `STC_BEGIN`/`STC_END` marker block).
  Non-destructive by construction: every artifact carries a `.stc.md` /
  `.stc.sh` suffix; `settings.json` and `.mcp.json` are merged under the
  `_stc_managed` / `stc-` namespace; the only user-owned file touched is the
  always-context file, via one managed marker `@import` line. Re-deploy is
  idempotent. Backup snapshot before any JSON write; `restore <id>` rolls back.
- **`deploy/tests/test_render.py`** — a regression test suite pinning every
  deploy bug from the history so it cannot silently return (double-wiring
  merge, idempotent re-deploy, legacy-hook absorption, per-harness provider,
  naming consistency, session-path warnings, the three render bugs). Runs
  zero-dependency via `python3 deploy/tests/test_render.py` and is
  pytest-compatible.
- **Per-harness model providers.** `stc.yaml` accepts `models.<target>`
  overrides so each harness gets the right model ids (Claude Code resolves
  only the short aliases haiku/sonnet/opus; ZCode maps Anthropic names onto
  GLM ids). Fixes the silent failure where typed sub-agents with
  `model: glm-5.2` would not dispatch in Claude Code.
- **Session-path drift warnings** in `deploy.py check`/`apply`. Claude Code
  stores a session's cwd in three places; a folder migration leaves dead
  pointers and sessions open to "Folder not found". `check` flags any project
  path that no longer exists and warns when `workspace.root` is not
  registered.
- **Extended precheck**: command naming consistency (rejects underscore names
  like `grill_me.md`), MCP validity (an enabled server with no command/env
  binding), sub-agent body/registry consistency.

### Fixed — the three render bugs that kept event hooks from ever firing
These combined to make H06 (`session-start-context`) and every other
SessionStart/Stop/UserPromptSubmit hook silently never match.

- **Bug 1 — `$NATIVE_DIR` not resolved.** Render emitted the placeholder into
  `settings.json`; Claude Code does not expand it, so the hook script was
  never found. `_merge_settings_patch` now substitutes the absolute
  `native_dir` before merge.
- **Bug 2 — rendered hook scripts were not executable.** `_write_tree` now
  sets `+x` on `.sh` / `.stc.sh` files (hook scripts carry a shebang and are
  executed directly).
- **Bug 3 — event-hook matchers used the event name.** Adapters now declare
  `matcher: ["*"]` plus an explicit `event:` field (decoupling the event
  bucket from the matcher string); `render.py` honors `event:` when present.

### Added — core/
- **`core/rules/`** — 4 always-context rule files: `behavior.md` (the
  situation→action imperative catalog, anchors I01–I25), `pev.md` (the
  Plan→Do→Verify loop), `project_docs.md` (ADR + task encoding + ERD),
  `session.md` (session lifecycle, always-context loaded via `@import`).
- **`core/memory/`** — `MEMORY.md` (index), `playbook.md` (operational
  instructions), `code_standard.md` (the single code standard), 4 reference
  catalogs (`defect_ledger`, `abuse_cases`, `failure_modes`, `retired_codes`)
  as seed templates, `skills_triggers.md`.
- **`core/hooks/`** — 17 hook scripts (H01–H17): git guardrails, playwright
  router, SELF-EXEC/services reminder, agent-reuse contract, secret-scan,
  session-start context, dirty-tree guard, link integrity, memory guard,
  read-first router, output hygiene, acquire-dedup, web-route, buy-vs-build,
  exec-offload, integration-docs-gate, secret-read guard.
- **`core/skills/`** — 15 skills: caveman, code-reviewer, council, diagnose,
  e2e, infra-audit, qa, research, security-arch, security-deps, tdd, worktree
  (methodology); code-graph, docs, llm-wiki (utility).
- **`core/agents/`** — `registry.yaml` + 9 agent prompt bodies (code-reviewer,
  security-arch, qa, security-deps, e2e, cleanup, research, docs, harness-docs).
- **`core/commands/`** — 10 slash commands (git-guardrails, grill-me, handoff,
  improve-codebase-architecture, install-mcp, prototype, save-and-compact,
  to-spec, to-tasks, zoom-out).
- **`core/templates/`** — design-system, new-project, vault (Home, spec-template,
  specs-index, tasks-board).
- **`core/models/`** — `claude.yaml` and `glm.yaml` (the two-axis MODEL
  providers; tier→id maps + context windows).

### Added — adapters/
- **`adapters/claude/`** — the REFERENCE realisation (files-delivery, native
  typed sub-agents, native `@import`, settings.json hooks, permissions.deny).
- **`adapters/zcode/`** — the DEGRADE realisation (plugin-delivery, untyped
  dispatch, H17 hook as the only read-guard, AGENTS.md).
- **`adapters/_template/`** — a documented skeleton for new harnesses.

### Added — docs/
- **`docs/PROGRESS.md`** — the build log: stages 0–4, design decisions
  (ADR-001 rules→hooks, ADR-002 design=tokens, capability≠realisation,
  non-destructive deploy, the two-axis model).

## Release process

1. Update the `## [Unreleased]` section above — move items under a new
   `## [0.X.0] - YYYY-MM-DD` heading.
2. `python3 deploy/tests/test_render.py` — all tests green.
3. `python3 deploy/deploy.py check` — config valid, no unexpected warnings.
4. Commit on `main`, then `git tag -a v0.X.0 -m "release notes summary"`.
5. Push `main` and the tag: `git push origin main --tags`.
6. GitHub Releases: paste the version's section from this file as the notes.
