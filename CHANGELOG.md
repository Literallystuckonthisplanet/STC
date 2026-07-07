# Changelog

All notable changes to STC Core are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it
reaches 1.0.0. Until then, the `0.x` line carries the deploy pipeline and
breaking changes can happen between minor bumps.

Releases are tagged from `main` with an annotated tag (`git tag -a v0.X.0`)
and the section below is the release notes a tag points at.

## [Unreleased]

### Fixed — the three render bugs that kept event hooks from ever firing
These three combined to make H06 (`session-start-context`, the hook that
injects always-context) and every other SessionStart/Stop/UserPromptSubmit
hook silently never match. A local hotfix held them in live; this release
fixes the generator so the next deploy does not erase the hotfix.

- **Bug 1 — `$NATIVE_DIR` not resolved in hook commands.** Render emitted
  `"$NATIVE_DIR/hooks/foo.stc.sh"` into `settings.json`, but `$NATIVE_DIR` is
  not a standard Claude Code env var, so the path expanded to empty and the
  hook script was never found. `deploy.py _merge_settings_patch` now
  substitutes the absolute `native_dir` into every hook command before merge
  (render stays disk-agnostic / testable with the `$NATIVE_DIR` placeholder).
- **Bug 2 — rendered hook scripts were not executable.** `_write_tree` created
  files with the default `rw-r--r--` mode; hook scripts carry a shebang and
  are executed directly, so a non-executable file silently failed to run.
  `.sh` / `.stc.sh` files are now written with `+x` (`rwxr-xr-x`).
- **Bug 3 — event-hook matchers used the event name.** Adapters declared
  `matcher: ["SessionStart"]` / `["Stop"]` / `["UserPromptSubmit"]`, but on
  these events Claude Code treats the matcher as a source/content filter, so
  the value never equaled an actual source (`startup`/`resume`/`clear`/
  `compact`) and the hook never fired. Adapters now declare `matcher: ["*"]`
  plus an explicit `event:` field (decoupling the event bucket from the
  matcher string); `render.py` honors `event:` when present. PreToolUse
  matchers (tool-name regexes) are unchanged.

### Added — deploy pipeline
- **Per-harness model providers.** `stc.yaml` now accepts `models.<target>`
  overrides (`models.claude: claude`, `models.zcode: glm`) so each harness
  gets the right model ids. A harness speaks one model family: Claude Code on
  an Anthropic subscription resolves only the short aliases (haiku/sonnet/
  opus), and ZCode maps Anthropic names onto GLM ids. `models.provider`
  remains as the default/fallback for back-compat. **This fixes the silent
  failure where typed sub-agents with `model: glm-5.2` would not dispatch in
  Claude Code.**
- **Session-path drift warnings** in `deploy.py check`/`apply`. Claude Code
  stores a session's working directory in three places (the `.jsonl` `cwd`
  field, the `~/.claude.json` projects map, the desktop app's `local_*.json`);
  a folder migration leaves dead pointers behind and sessions open to
  "Folder not found". `check` now flags any project path that no longer exists
  on disk and warns when `workspace.root` is not registered. This is the
  condition that orphaned sessions and project memory in the Phase D
  migration — now surfaced before deploy, never silently.
- **Extended precheck invariants**: command naming consistency (rejects
  underscore-named commands like `grill_me.md` that leave duplicate files
  after the underscore→hyphen rename), MCP validity (an enabled server with
  no command/env binding is flagged before it renders an empty block), and
  sub-agent body/registry consistency (a capability declared in an adapter
  must have both a `core/agents/<name>.md` body and a `registry.yaml` entry).
- **Event-hook collision refinement**: a user hook with `matcher='*'` on
  SessionStart/UserPromptSubmit/Stop is now treated as coexistence (both
  fire independently), not a collision — e.g. `vscode-todos-bridge` + STC H06.

### Added — testing
- **`deploy/tests/test_render.py`** — a regression test suite (15 tests)
  pinning every deploy bug from the history so it cannot silently return:
  the three render bugs (event-hook matcher, NATIVE_DIR resolution, +x bit),
  the double-wiring merge, idempotent re-deploy, legacy-hook absorption, the
  provider-per-harness contract, naming consistency, and session-path
  warnings. Runs zero-dependency via `python3 deploy/tests/test_render.py`
  and is pytest-compatible.

### Fixed
- **`core/models/claude.yaml`**: tier ids were `claude-haiku` / `claude-sonnet`
  — a form Claude Code's typed sub-agent frontmatter does not accept (only the
  short aliases `haiku`/`sonnet`/`opus`, or `inherit`, or a full versioned id
  like `claude-sonnet-4-6`). Sub-agents silently failed to dispatch. Fixed to
  the short aliases, with a comment block documenting the constraint.
- **`core/rules/session.md`** was stale: it described H06 as injecting
  behavior.md / pev.md / `${USER_PROFILE}` at session start, but H06 was
  re-scoped to post-compact loss-check + infra-audit cadence, and rules now
  load via `@import` in the always-context bundle. Rewritten to match the
  actual architecture.
- **`core/hooks/README.md`** var table referenced `${USER_PROFILE}` (removed
  from RENDER_VARS when H06 was re-scoped) and listed H06 under
  `${MEMORY_DIR}` (H06 now uses `${HARNESS_DIR}`). Table corrected.
- Removed duplicate `import os` in `deploy/checks.py`.

## Release process

1. Update the `## [Unreleased]` section above — move items under a new
   `## [0.X.0] - YYYY-MM-DD` heading.
2. `python3 deploy/tests/test_render.py` — all tests green.
3. `python3 deploy/deploy.py check` — config valid, no unexpected warnings.
4. Commit on `main`, then `git tag -a v0.X.0 -m "release notes summary"`.
5. Push `main` and the tag: `git push origin main --tags`.
6. GitHub Releases: paste the version's section from this file as the notes.
