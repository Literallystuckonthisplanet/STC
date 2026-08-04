---
name: behavior-rules
layer: rules
scope: global
---

# Behavioral rules

Only firing rules live here: situation → required action. Procedures and
examples are lazy in `playbook.md`, `code_standard.md`, project docs, and
skills.

## Secrets and durable facts
<!-- I05 I06 I26 -->

- Secret/token/password appears → put it in `${SECRETS_ENV}`, never print it
  in full, never write it to memory or git. Suspected leak → revoke/rotate.
  Guards: H03 (prompt), H05 (memory write), H01 (commit).
- Durable decision/preference appears → mark it `📌 MEMORY` when useful. Raw
  transcripts feed the independent ingest and Obsidian review pipeline.

## Worktrees and parallel work
<!-- I07 -->

- Before work → inspect existing worktrees and dirty state.
- Independent files → parallel work is allowed. Shared files, fuzzy scope, or
  overlapping concerns → isolate in a worktree.
- Parallel writers must have disjoint write scopes. Overlap or an unexpected
  shared-file change → stop that stream and return a fork to main.
- Merge one branch at a time and verify after each merge. Detail → playbook
  § Worktree checks. Guard: H07 (dirty/worktree warning).

## Git push and deployment
<!-- I08 I09 -->

- Commit only a verified logical change. H01 supplies the commit checklist and
  blocks dangerous git, secrets, and unapproved push to main.
- Push/release only on the user's explicit release instruction.
- Deploy through the project's versioned deploy/rollback script. A broken
  script → fix the script; never replace it with improvised production edits.
- Routine production with a tested rollback/runbook stays on Luna. Unknown
  state, missing rollback, destructive migration, money/personal-data risk, or
  broad blast radius → escalation.

## SELF-EXEC
<!-- I10 -->

Run safe mechanical steps yourself: installs, tests, services, browser,
Docker, and retries. Ask only for a missing value or a decision. External
access and irreversible/destructive actions are the exceptions. H03 reinforces
the reminder; examples → playbook § SELF-EXEC.

## Services and long strings
<!-- I11 I12 -->

- Operation needs a service → check/start it; config changed → restart the
  dependent service; failure → diagnose. Stop services only for explicit
  cleanup or a project requirement.
- Never hand-transcribe tokens, hashes, encoded URLs, JWT/base64, or other long
  ASCII strings. Transform programmatically and verify the result.

## Existing way, docs, and dependencies
<!-- I21 -->

- Before implementing a concern → find and reuse the existing project pattern.
  A second implementation requires an explicit recorded decision. H10 gives
  the read-first nudge.
- Named integration/API/SDK → read current primary docs before code and record
  reusable failure modes. H16 enforces the docs-first gate.
- New non-trivial capability or common-library territory → evaluate a ready
  dependency first and record buy-vs-build. H14 is the backstop.

## Snapshot and project routing
<!-- I13 I27 -->

- New project → use `${TEMPLATES_DIR}/new-project.md`; project documentation
  follows `project_docs.md`.
- Project status → central project index, then that project's `SNAPSHOT.md`.
- STC/infra status → `core/memory/SNAPSHOT.md` first.
- Code relationships/impact → Graphify after the snapshot. Graphify covers
  code, not project memory or the Wiki.

## Research, output, and code names
<!-- I14 I22 I28 I29 -->

- Reusable research → save under `${DOCS_ROOT}/notes/research/` and update its
  index; one-off lookup stays in the transcript.
- Tool output → request the smallest useful slice; preserve exact errors,
  paths, commands, security findings, and caveats.
- Mention an internal code to the user → add its human name, for example
  `H01 (git safety)`, never a bare code.
- Use `python3`; downloads go to `~/Downloads/`.

## Token economy
<!-- I13b -->

Delegate bounded independent work to the cheapest capable model. Caveman is
allowed only for read-only exploration, research, docs, and status collection;
never for builders, review, QA, security, E2E, architecture, or user-facing
answers.
