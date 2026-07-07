---
name: qa
description: "Dispatch a QA sub-agent to generate and run tests for a code fragment. Covers business logic and edge cases (not trivia). Does NOT modify the source. Used in the Verify step and in the ×3 review pipeline (code-reviewer + security-arch + qa)."
---

# qa — dispatcher

Generate and run tests for a code fragment. Used in the PEV Verify step and in
the ×3 review pipeline (code-reviewer + security-arch + qa).

## What the sub-agent does
- Generates tests targeting **business logic and its edge cases** (the
  code-standard § TEST block), not trivia/framework glue/generated code.
- Runs the tests and reports PASS/FAIL with the failure output.
- Cleans up any temp scaffolding it created.

## What the sub-agent does NOT do
- It does NOT modify the source under test.
- It does NOT chase coverage as an end in itself.

## When to dispatch

- The Verify step of a task touching business logic (calculations,
  validation, transforms, state transitions).
- The ×3 review pipeline (playbook § Review process): qa is the test arm.
- The user asks for tests on a fragment.

## How to dispatch

Call the Agent/Task tool with the prompt below, filling in `[FRAGMENT]`,
`[ENTRY POINT / PUBLIC API]`, and `[PROJECT TEST COMMAND]`.

```
description: "QA tests: [FRAGMENT]"
prompt: |
  You are a QA agent. Generate and run tests for [FRAGMENT].

  Tools available: Read, Write, Bash, Glob, Grep.

  Rules:
  - Test through the PUBLIC API of the fragment, not its internals.
  - Target business logic + edge cases. Do NOT test trivia, framework glue,
    or generated code.
  - Do NOT modify the source under test. If you cannot test it without a
    source change, STOP and report why.
  - Run the project's test command: [PROJECT TEST COMMAND].
  - Clean up any temp files you created.

  Output (caveman-compressed if instructed):
  - Tests written: <paths>
  - Run command + result (PASS/FAIL, counts)
  - For each failure: the assertion, the expected vs actual, the file:line
  - Coverage note (only if meaningful — e.g. "edge case X now covered")
  - Cleanup: what was removed
```

## Review-pipeline note

In the ×3 review (code-reviewer + security-arch + qa), the three run isolated
and the Council merges their results. Do not let qa's findings drift into
security or architecture territory — that's the other two agents' job.
