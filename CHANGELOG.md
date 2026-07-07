# Changelog

All notable changes to STC Core are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0.0. Until then, the `0.x` line carries the deploy pipeline and
breaking changes can happen between minor bumps.

Each release tag (`git tag -a v0.X.0`) points at the section below as its
release notes.

## [Unreleased]

### Added
- Full README — the project guide (purpose, principles, abstraction layers,
  third-party tools, the 17 hooks, the memory structure, the deployer).
- CHANGELOG with a "Hello, World" initial-release entry.

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
