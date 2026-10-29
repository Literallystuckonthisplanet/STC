# Security Architecture Review

Date: 2026-10-29
Scope: Delta acceptance only for the two prior A findings in the false-positive
guard change (`core/hooks/block-secret-read.sh`). B grants/source and unrelated
security scenarios were not reviewed.

Stack: Bash hook with an embedded Python 3 stdlib parser, rendered into a
Codex `PreToolUse` hook. No package manifest/version change was in scope.

## Verdict

PASS / CLOSED — both previous blockers are closed in the current frozen source.
No new direct bypass of the same `rg` path/payload boundary was found in the
requested sibling check.

## Historical findings — closed

### 1. Shell `~` expansion bypass

- Previous location: `core/hooks/block-secret-read.sh:66`, `:74-76`,
  `:81-82`, `:144-162`.
- Closure: `parse_rg()` now rejects `~`-prefixed option values and targets
  before path/directory approval (`:123-128`, `:148-151`), then falls back to
  the generic `unparsed` denial for the protected query hint.
- Delta reproduction: with a helper copy, synthetic `$HOME=<fixture>`, and
  `tool_name=exec`, `command="rg -n credentials ~/scan"` returned `2` with
  the generic denial. The actual shell-expanded read was not executed after
  the denial (`actual_read=not-executed`).
- Direct positive neighbor: `command="rg -n credentials src/app.py"` against
  an ordinary file returned `0`.

### 2. `tool_input.cmd` safe-form false denial

- Previous location: `core/hooks/block-secret-read.sh:176-195`, with the
  Codex binding at `adapters/codex/adapter.yaml:157`.
- Closure: `command` and `cmd` are unified before `parse_rg()` (`:180-186`),
  while conflicting values fail closed (`:183-184`).
- Delta reproduction: synthetic `tool_name=exec`,
  `tool_input.cmd="rg -n credentials src/app.py"` returned `0`.
- Direct positive neighbor: the equivalent `tool_input.command` form also
  returned `0`.

## Sibling-field safety check

- A safe `cmd` field paired with a dangerous sibling `input="cat
  credentials.json"` returned `2` and the protected-pattern denial. The
  fallback scan still examines non-selected `command`/`cmd`/`input`/`script`
  values; the dangerous sibling is not hidden by the `cmd` normalization.
- No path, command, query value, or synthetic file contents were echoed by
  the denial.

## Validation boundary

- This was a targeted delta acceptance using helper copies and a temporary
  synthetic fixture tree only. No installed hooks, real secrets, paid models,
  network calls, or live bridge were used.
- No source or test file was changed by this review; only this report was
  updated.
