<!-- README -->

# deploy/

The STC deploy orchestrator. Consumes the Stage-3 contracts
(`adapter.yaml` × `core/models/<provider>.yaml` × `core/agents/registry.yaml`
× `stc.yaml`) and renders the harness form, non-destructively.

## The non-destructive model

STC never overwrites a user's files. Every artifact it creates is uniquely
named so collisions are structurally impossible:

| Layer | How STC lands | User file touched? |
|---|---|---|
| always-context | `CLAUDE.stc.md` / `AGENTS.stc.md` bundle | **one** marker `@import` line, via `# >>> STC BEGIN >>>` … `# <<< STC END <<<` |
| rules | inside the always-context bundle | no |
| hooks | `*.stc.sh` scripts | no |
| agents / commands / skills | `*.stc.md` files | no |
| settings.json | merged under `stc-*` keys | merged (user keys preserved) |
| .mcp.json | `mcpServers["stc-<name>"]` | merged (user keys preserved) |
| statusline | `statusline.stc.sh` | settings.json `statusLine` (collision-flagged) |

Same-name collisions (a user's own `code-reviewer.md`) **cannot happen** — the
STC file is `code-reviewer.stc.md`. The two real collision surfaces are
`settings.json` (a hook on the same matcher) and `.mcp.json` (a server with
the same name): deploy **refuses by default** and prints a precise report;
resolution is only via `--overwrite` or `--skip-collisions`. A backup snapshot
of every touched JSON is taken before any write.

## Commands

```bash
# preview (no live writes) — render into deploy/_rendered/<harness>/
python3 deploy/deploy.py render --target claude --dry-run
python3 deploy/deploy.py render --target zcode --dry-run

# validate stc.yaml + adapters + provider; report collisions
python3 deploy/deploy.py check

# render + write to ~/.stc/ + the native dir
# (refuses on JSON collisions unless a flag is given)
python3 deploy/deploy.py apply --target claude
python3 deploy/deploy.py apply --target claude --overwrite      # backup + STC wins
python3 deploy/deploy.py apply --target claude --skip-collisions # keep user config

# remove STC artifacts (user content preserved; backups retained)
python3 deploy/deploy.py uninstall --target claude

# roll back JSON from a backup snapshot
python3 deploy/deploy.py restore 20260701-120000
```

### Scoped Codex H17 guard update

The versioned `apply-hook` command updates only the H17 guard in the two
managed code locations below. It checks the existing H17 entry in
`~/.codex/hooks.json` but never edits that file. It does not run the general
`apply` flow, copy the full `core/` tree, or need `stc.yaml`, `user/`, or secret
configuration. The expected-before hashes must come from the saved preflight
record for these exact targets; do not guess or reuse hashes from another
machine or checkout.

```bash
python3 deploy/deploy.py apply-hook \
  --target codex --hook H17 --language ru --dry-run \
  --expected-source-sha256 "$SOURCE_BEFORE_SHA256" \
  --expected-native-sha256 "$NATIVE_BEFORE_SHA256"

python3 deploy/deploy.py apply-hook \
  --target codex --hook H17 --language ru \
  --expected-source-sha256 "$SOURCE_BEFORE_SHA256" \
  --expected-native-sha256 "$NATIVE_BEFORE_SHA256"
```

The only target files are `~/.stc/core/hooks/block-secret-read.sh` and
`~/.codex/hooks/block-secret-read.stc.sh`. Before either target is replaced,
the command saves and verifies both original byte streams and modes under
`~/.stc/backups/hook-patch/<backup-id>/`. Keep the printed backup id for a
possible rollback. The backup also records both exact paths and both
before/after hashes and modes. The operation refuses missing or mismatched
binding, unsafe paths, symlinks, unexpected target bytes/modes, or stale
preflight hashes.

Preview and restore the selected backup with the matching scoped command:

```bash
python3 deploy/deploy.py restore-hook "$BACKUP_ID" --dry-run
python3 deploy/deploy.py restore-hook "$BACKUP_ID"
```

Restore verifies the backup files and both current targets before changing
either. A conflict already present in either target makes the entire restore
refuse before changing either target. Before each replacement, the command
checks the full destination bytes and mode again after preparing the temporary
file; a detected late edit is preserved and that replacement is refused. If
an unrelated edit arrives after an earlier restore write, the restore can be
partial and the backup remains available for recovery.

The operation lock serializes only other `apply-hook` and `restore-hook`
operations using this same lock. The final content/mode comparison followed
by rename is not an operating-system compare-and-swap; an unrelated writer can
still race in that very small interval. Keep other writers of these two files
inactive during installation or restore. A successful rerun recognizes the
existing backup and does not create a new before-state snapshot.

## Files

```
deploy/
├── deploy.py        # CLI + orchestration (the entry point)
├── hook_patch.py    # selected, reversible Codex H17 install/restore
├── render.py        # 7-layer renderer (pure: returns artifacts, no disk writes)
├── stc_block.py     # the single marker-block mechanism (one @import line)
├── checks.py        # precheck / collision-detect / backup / postcheck / onboarding
├── _rendered/       # dry-run output (gitignored)
├── _manifest.json   # what deploy created per harness (gitignored; for uninstall)
└── README.md        # this file
```

## Where things land

- `~/.stc/core/` — a mirror of the repo's `core/`, shared by every harness.
  One update here reaches all harnesses.
- `~/.<harness>/` — the native dir (`~/.claude`, `~/.zcode`). STC writes only
  its own `*.stc.*` artifacts + merged JSON keys + one marker line. The user's
  existing files are untouched.
- `~/.stc/backups/<timestamp>/` — JSON snapshots, retained across uninstalls.

## What deploy does NOT do

- It does not run hooks (that's the harness's runtime job).
- It does not write `~/.claude`/`~/.zcode` until you explicitly `apply`
  (and the Stage 5/6 consent gate is the broader switch).
- MCP runtime fallback (server down) is a runtime concern, not a deploy one.
