---
name: pev-loop
layer: rules
scope: global
---

# Plan → Execute → Verify

PEV mode is selected by the task-scale table below. Procedures, role prompts,
spec formats, and verification matrices are lazy in playbook/skills.

## Task scale
<!-- I16 -->

| Size | Trigger | Required loop |
|---|---|---|
| **S** | 1 file; local reversible typo/style/copy/config change; no behavior or infra effect | Execute → eyes/static Verify |
| **M** | 2–5 files or 2+ dependent implementation steps; no override below | short Plan → Execute → Verify |
| **L** | 6+ files or an override below | full shown Plan → Execute → Verify |

Override to L: architecture/API/data schema/lifecycle change; a security
boundary; an irreversible or non-recoverable action; 2+ executors; or one unresolved implementation fork that can change the solution. Routine
production/deploy is not an override when runbook, backup/rollback, and smoke
checks are proven. Three or more open forks → grill-me/Council.

## Plan

For M/L, state:

1. outcome, scope, and what is not changing;
2. affected files/systems and current evidence;
3. acceptance criteria and verification;
4. implementation blocks and dependencies;
5. delegation/model/isolation for each independent block;
6. unresolved user decisions.

Do not start an unresolved branch. Technical trivia may be recorded as
`DECIDED`; architecture/API/schema/dependency deviations return `FORK`;
business/user-visible/money/personal-data/legal choices go to the user.

For new behavior or a bug, use TDD when applicable: one failing behavior test
→ minimal pass → refactor while green. Config/generated/throwaway work follows
its own verification contract.

## Delegation, model routing, and Escalation
<!-- FR-27 FR-28 -->

- Main default = **Luna Max**. Decompose M/L work before execution and delegate
  every bounded independent stream that has a clear input, output, write scope,
  and acceptance check.
- Luna handles normal planning, implementation, routine deploys, exploration,
  and verification. Prefer escalating one specialist stream instead of the
  whole main session.
- Terra handles broad but bounded integration/synthesis when Luna returns
  contradictory or incomplete evidence.
- Sol handles architecture or high-risk decisions when the uncertainty cannot
  be isolated. Main changes model only when the continuing user conversation
  itself requires that depth.
- Escalate after two bounded failed Luna attempts, a `FORK/BLOCKED/UNVERIFIED`
  result, contradictory evidence, an unbounded blast radius, missing recovery,
  or a security/irreversibility decision. File count and routine production
  alone are not escalation triggers.
- Before escalation, report: trigger, why Luna is insufficient, recommended
  Terra/Sol scope, and what can safely continue on Luna.
- Read-only roles get technical read-only isolation. Parallel writers get
  disjoint worktrees/write scopes.
- Caveman only for read-only exploration/research/docs/status. All builders,
  reviewers, QA, security, E2E, architects, and final answers use normal
  structured prose.

Agent role triggers and prompt contracts → `skills_triggers.md` and playbook
§ Agent prompt contract. H04 validates dispatch metadata.

## Execute

- Work one accepted block at a time. The executor changes only its declared
  write scope and returns status, files, checks, AC, `DECIDED`, and `FORK`.
- Main owns user decisions, cross-block integration, acceptance, commits, and
  final reporting. A discovered plan-breaking constraint → update the affected
  plan before continuing.
- Keep unrelated findings out of the patch; report them separately.

## Verify
<!-- I17 -->

Never claim done without evidence:

- **static:** parse/type/lint/build/dry-run as applicable;
- **eyes:** inspect the actual diff/output against scope and secrets;
- **dynamic:** run behavior/tests; UI uses Playwright and appearance evidence;
- **independent:** M/L logic → QA/review; auth/API/data/security → security
  review; deploy → dependency/security check; user flow → E2E.

L requires at least two kinds, including an independent check. A verification
failure → diagnose, correct, rerun; after three failed repair iterations,
surface the blocker. Report commands and observed results.

## No full Plan

S tasks may skip Plan, never Verify. Read-only explanation/status work uses
evidence collection and an explicit confidence boundary.
