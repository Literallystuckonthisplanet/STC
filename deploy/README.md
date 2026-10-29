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

### Scoped H17 guard update

The versioned `apply-hook` command can update H17 across an explicit adapter
set without running the general `apply` flow. It checks each existing H17
binding and leaves the settings files unchanged. It does not copy the full
`core/` tree or need `stc.yaml`, `user/`, or secret configuration. Start with
the read-only dry-run and pass its aggregate state hash to the installation
command; do not guess or reuse that hash from another machine or checkout.

```bash
python3 deploy/deploy.py apply-hook \
  --target claude,codex,zcode --hook H17 --language ru --dry-run

python3 deploy/deploy.py apply-hook \
  --target claude,codex,zcode --hook H17 --language ru \
  --expected-before-state-sha256 "$EXPECTED_BEFORE_STATE_SHA256"
```

The fixed targets are the shared H17 policy and source wrappers under
`~/.stc/core/hooks/`, plus the rendered wrapper under each selected native
adapter. ZCode's wrapper is scoped to the renderer's existing versioned plugin
cache path; the adapter remains frozen and this operation does not change its
plugin identity or activate the platform. The command reads only the matching
H17 routing entry from Claude settings, Codex hooks, and the ZCode plugin hooks
file. It records a digest of that entry and the canonical target paths in the
aggregate precondition, without printing the surrounding config.

Before writing, the command snapshots and verifies every fixed target's
existence, bytes, and mode. One verified backup directory records the complete
before/after state. If the shared policy did not exist before installation,
the backup records that absence; restore removes it only while its installed
bytes and mode still match. The operation refuses missing or mismatched H17
bindings, unsafe paths, symlinks, unexpected target modes, or a stale aggregate
precondition. Keep the printed backup id for rollback.

The legacy Codex-only command using `--expected-source-sha256` and
`--expected-native-sha256` remains supported. Its version-1 backup format is
still restored by the same command; explicit adapter-set installs use the
version-2 manifest. Because the current Codex launcher calls the shared H17
policy, the legacy path now requires that policy to already exist in
`~/.stc/core/hooks/secret_read_policy.py` with the exact source bytes and mode.
If it is missing or stale, use the explicit aggregate adapter-set path; the
legacy command will not silently add a third file outside its two-file backup.

Preview and restore the selected backup with the matching scoped command:

```bash
python3 deploy/deploy.py restore-hook "$BACKUP_ID" --dry-run
python3 deploy/deploy.py restore-hook "$BACKUP_ID"
```

Restore verifies the backup files, binding metadata, and every current target
before changing any target. A conflict in any target makes the entire restore
refuse before changing the rest. Native wrappers restore first; the shared
policy is removed last when it was absent before installation. Before each
replacement, the command rechecks destination bytes and mode after preparing
the temporary file. If an unrelated edit arrives after an earlier restore
write, restore can be partial and the backup remains available for recovery.

The operation lock serializes only other `apply-hook` and `restore-hook`
operations using this same lock. The final content/mode comparison followed
by rename is not an operating-system compare-and-swap; an unrelated writer can
still race in that very small interval. Keep other writers of the selected
files inactive during installation or restore. A successful rerun recognizes
the matching backup and does not create a second before-state snapshot.

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
