---
name: worktree
description: "Create and manage git worktrees for isolated, parallel work in one project. Use when the user wants parallel work ('do X and Y separately'), isolated changes, or a reversible experiment. Detects existing isolation first, prefers native harness worktree tools, falls back to git worktree."
---

# Worktree
<!-- S14 -->

Isolated workspaces via git worktrees — let multiple agent sessions work in
parallel in one project without stepping on each other.

**Core principle:** detect existing isolation first. Then prefer native
worktree tools. Then fall back to git. Never fight the harness.

## Step 0 — Detect existing isolation

**Before creating anything, check if you are already in an isolated workspace.**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

**Submodule guard:** `GIT_DIR != GIT_COMMON` is also true inside git submodules.
Before concluding "already in a worktree", verify you are not in a submodule:

```bash
# If this returns a path, you're in a submodule, not a worktree — treat as normal repo
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**If `GIT_DIR != GIT_COMMON` (and not a submodule):** you are already in a
linked worktree. Skip to "Working in the worktree". Do NOT create another
worktree.

Report:
- On a branch: "Already in isolated workspace at `<path>` on branch `<name>`."
- Detached HEAD: "Already in isolated workspace at `<path>` (detached HEAD,
  externally managed). Branch creation needed at finish time."

**If `GIT_DIR == GIT_COMMON` (or in a submodule):** you are in a normal repo
checkout. Has the user already indicated a worktree preference? If not, ask
consent:

> "Would you like me to set up an isolated worktree? It protects your current
> branch from changes."

Honor any declared preference without asking. If the user declines, work in
place and skip to "Working in the worktree".

## Step 1 — Create the workspace

Try mechanisms in this order.

### 1a. Native worktree tools (preferred)

The user wants isolation (Step 0 consent). Do you already have a way to create
a worktree built into your harness? It might be a tool named `EnterWorktree`,
`WorktreeCreate`, a `/worktree` command, or a `--worktree` flag. If you do,
use it and skip to "Working in the worktree".

Native tools handle directory placement, branch creation, and cleanup
automatically. Using `git worktree add` when you have a native tool creates
phantom state your harness can't see or manage.

Only proceed to 1b if you have no native worktree tool.

### 1b. Git worktree fallback

**Only if 1a does not apply** — no native tool available.

#### Directory selection

Priority order (explicit user preference beats observed filesystem state):

1. **Check instructions for a declared worktree directory preference.** If the
   user already specified one, use it without asking.
2. **Check for an existing project-local worktree directory:**
   ```bash
   ls -d .worktrees 2>/dev/null     # Preferred (hidden)
   ls -d worktrees 2>/dev/null      # Alternative
   ```
   If found, use it. If both exist, `.worktrees` wins.
3. **If there is no other guidance**, default to `.worktrees/` at the project
   root.

#### Safety verification (project-local directories only) — MUST verify before creating

```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

**If NOT ignored:** add to `.gitignore`, commit the change, then proceed. This
prevents accidentally committing worktree contents to the repository.

#### Create

```bash
NAME="$ARGUMENTS"   # worktree name, e.g. research, content, experiment
git worktree add ".worktrees/$NAME" -b "worktree-$NAME"
```

**Sandbox fallback:** if `git worktree add` fails with a permission error
(sandbox denial), tell the user the sandbox blocked worktree creation and
you're working in the current directory instead.

## Step 2 — Project setup

Auto-detect and run the appropriate setup inside the worktree:

```bash
# Node.js
if [ -f package.json ]; then npm install; fi      # or pnpm install / yarn
# Rust
if [ -f Cargo.toml ]; then cargo build; fi
# Python
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then poetry install; fi
# Go
if [ -f go.mod ]; then go mod download; fi
```

## Step 3 — Verify clean baseline

Run the project's tests to ensure the workspace starts clean:

```bash
[PROJECT TEST COMMAND]   # npm test / cargo test / pytest / go test ./...
```

**If tests fail:** report failures, ask whether to proceed or investigate.
**If tests pass:** report ready:

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Working in the worktree

Once created — **switch all your work to the worktree path:**

1. **All file paths** go through `.worktrees/<name>/`, NEVER the project root.
2. **Read files:** `.worktrees/<name>/path/to/file`
3. **Write files:** `.worktrees/<name>/path/to/file`
4. **Run scripts:** `cd .worktrees/<name> && <command>`
5. **Results** land in `.worktrees/<name>/tmp/...`
6. **Commit often** — small commits = clean merge.
7. **Don't touch the root** — only your worktree.
8. **Shared infra** (the instruction file, skills) is read from the project
   root — common to all worktrees.

## Operations

### List all worktrees

```bash
git worktree list
```

### Merge a worktree back

```bash
# 1. Commit any uncommitted changes inside the worktree
cd .worktrees/$NAME && git add -A && git status
#   if there's something to commit:
cd .worktrees/$NAME && git commit -m "worktree $NAME: <description>"

# 2. Return to the root and merge
cd <project-root> && git merge "worktree-$NAME" --no-edit
```

If a merge conflict — show the conflicting files, help resolve, then
`git add` + `git commit`. After a successful merge ask: "Delete worktree
`$NAME`? Its changes are in the main branch now."

### Delete a worktree

```bash
git worktree remove ".worktrees/$NAME"
git branch -d "worktree-$NAME"
```

## Quick reference

| Situation | Action |
|-----------|--------|
| Already in linked worktree | Skip creation (Step 0) |
| In a submodule | Treat as normal repo (Step 0 guard) |
| Native worktree tool available | Use it (Step 1a) |
| No native tool | Git worktree fallback (Step 1b) |
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Both exist | Use `.worktrees/` |
| Neither exists | Default `.worktrees/` at project root |
| Directory not ignored | Add to `.gitignore` + commit |
| Permission error on create | Sandbox fallback, work in place |
| Tests fail during baseline | Report failures + ask |
| No package manifest | Skip dependency install |

## Error handling

| Error | Fix |
|--------|------|
| `fatal: is not a git repository` | Not a git repo. Run `git init` first. |
| `fatal: '$NAME' is already checked out` | Worktree with that name exists. Show `git worktree list`. |
| `error: branch 'worktree-X' not found` | Branch already deleted. Just remove the dir: `rm -rf .worktrees/X`. |
| Merge conflict | Show conflicting files, help resolve, then `git add` + `git commit`. |

## Common mistakes

- **Fighting the harness** — using `git worktree add` when the platform already
  provides isolation. Fix: Step 0 detects; Step 1a defers to native tools.
- **Skipping detection** — creating a nested worktree inside an existing one.
  Fix: always run Step 0 first.
- **Skipping ignore verification** — worktree contents get tracked, pollute
  git status. Fix: always `git check-ignore` before creating project-local.
- **Proceeding with failing baseline tests** — can't tell new bugs from
  pre-existing. Fix: report failures, get explicit permission to proceed.

---

## Supporting sources

Merged from two upstreams (Decision 4, `docs/PROGRESS.md`). Check for drift
during the monthly `infra-audit`:

- User source: `~/.claude/commands/worktree.md` — contributed the
  "all paths through the worktree, never the root" working discipline,
  the merge/delete/error-handling operations, and the commit-often-clean-merge
  rule.
- `superpowers/using-git-worktrees` (obra/Superpowers, MIT) — contributed
  Step 0 (detect existing isolation + submodule guard), Step 1a (prefer native
  tools), the safety-verification-before-create step, the directory-selection
  priority, the project-setup auto-detect, and the baseline-test check.
