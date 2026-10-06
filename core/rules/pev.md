---
name: pev-loop
layer: rules
scope: global
---

# Plan → Execute → Verify

PEV mode is selected by the task-scale table below.

## Task scale
<!-- I16 -->
| Size | Trigger | Required loop |
|---|---|---|
| **S** | 1 file; local reversible typo/style/copy/config change; no behavior or infra effect | Execute → eyes/static Verify |
| **M** | 2–5 files or 2+ dependent implementation steps; no override below | short Plan → Execute → Verify |
| **L** | 6+ files or an override below | full shown Plan → Execute → Verify |

Override to L: architecture/API/data schema/lifecycle, security boundary,
irreversible/non-recoverable action, 2+ executors, or one unresolved implementation fork.
Routine
production/deploy is not an override when runbook,
backup/rollback, and smoke checks are proven. Three or more open forks → grill-me/Council.

## Plan
For M/L, state:

1. outcome, scope, and what is not changing;
2. affected files/systems and current evidence;
3. acceptance criteria and verification;
4. implementation blocks and dependencies;
5. delegation/model/isolation for each independent block;
6. unresolved user decisions.

Do not start unresolved branches. Technical trivia → `DECIDED`; architecture/
API/schema/dependency deviations → `FORK`; business/user-visible/money/data/
legal choices go to the user.

New behavior/bugs: TDD when applicable (failing test → minimal pass → refactor);
config/generated/throwaway work follows its own contract.

## Delegation, routing, & Escalation
<!-- FR-27 FR-28 -->

<!-- codex-direct-reminder:start -->
- Across projects and continuation/fix turns, main's model does not replace the
  cheapest capable executor. Builders own source/tests/tools/fixes;
  main owns diagnosis, brief, integration, and reporting.
- After two failures, diagnose, correct brief, return cheap. Expensive
  implementation needs concrete insufficiency and bounded scope. `# in-main`
  or a passing guard grants only the annotated integration step, never ownership.
<!-- codex-direct-reminder:end -->

- Main default = **Luna Max**; decompose M/L work and delegate streams
  with clear input, output, write scope, and acceptance check.
- Luna handles planning, implementation, deploys, exploration, and
  verification; escalate one specialist stream, not the whole session.
- Terra handles broad bounded integration on contradictory/incomplete evidence.
- Sol handles architecture/high-risk decisions when uncertainty cannot be
  isolated; main changes model only when the conversation needs that depth.
- Astra handles complex end-to-end investigation, consequential architecture
  forks, or high-impact review beyond Sol; it is explicit, not routine.
- Escalate after two bounded failed Luna attempts, a `FORK/BLOCKED/UNVERIFIED`
  result, contradictory evidence, an unbounded blast radius, missing recovery,
  or a security/irreversibility decision. File count and routine production
  alone are not escalation triggers.
- Before escalation, report trigger, insufficiency, recommended scope, and what
  can continue on Luna.
- Read-only roles get read-only isolation; parallel writers get
  disjoint worktrees/write scopes. Caveman is read-only; builders, reviewers,
  QA, security, E2E, architects, and final answers use structured prose.

Agent role triggers and prompt contracts → `skills_triggers.md` and playbook
§ Agent prompt contract. H04 validates dispatch metadata.

## Execute
- Work one accepted block at a time. The executor changes only its declared
  write scope and returns status, files, checks, AC, `DECIDED`, and `FORK`.
- Main owns decomposition, decisions, diagnosis, integration, acceptance,
  commits, and reporting; update the plan on a plan-breaking constraint.
- Acceptance briefly records the implementation/fix owner; executor launch alone
  is not proof of compliance.
- Keep unrelated findings out of the patch; report them separately.

## Verify
<!-- I17 -->

Never claim done without evidence:

- **static:** parse/type/lint/build/dry-run as applicable;
- **eyes:** inspect diff/output against scope and secrets;
- **dynamic:** run behavior/tests; UI uses Playwright and appearance evidence;
- **independent:** M/L logic → QA/review; auth/API/data/security → security review;
  deploy → dependency/security check; user flow → E2E.

L requires two kinds including an independent check. Failure → diagnose, correct,
rerun; after three failed repairs, surface the blocker. Report scenarios.

## No full Plan
S tasks may skip Plan, never Verify. Read-only work uses evidence and an
explicit confidence boundary.
