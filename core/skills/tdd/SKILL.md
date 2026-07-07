---
name: tdd
description: "Test-driven development via the red-green-refactor loop. Write the test first, watch it fail, write minimal code to pass, refactor while green. Use for new features, bug fixes, refactors, behavior changes. Exceptions: throwaway prototypes, generated code, config files (ask the user first)."
---

# Test-driven development (TDD)
<!-- S11 -->

## Philosophy

**Core principle:** Tests verify behavior through public interfaces, not
implementation details. Code can change entirely; tests shouldn't.

A **good test** is integration-style: it exercises real code paths through
public APIs. It describes _what_ the system does, not _how_. A good test reads
like a specification — "user can checkout with a valid cart" tells you exactly
what capability exists. These tests survive refactors because they don't care
about internal structure.

A **bad test** is coupled to implementation. It mocks internal collaborators,
tests private methods, or verifies through external means (querying the DB
directly instead of through the interface). Warning sign: the test breaks when
you refactor, but behavior hasn't changed. If renaming an internal function
fails tests, those tests were testing implementation, not behavior.

## The iron law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.
```

Wrote code before the test? Delete it. Start over. No exceptions:
- Don't keep it as "reference".
- Don't "adapt" it while writing tests.
- Don't look at it.
- Delete means delete.

Implement fresh from tests. Period.

**Violating the letter of the rules is violating the spirit of the rules.**
"If I didn't watch the test fail, I don't know if it tests the right thing."

## Anti-pattern: horizontal slices

**DO NOT write all tests first, then all implementation.** This is "horizontal
slicing" — treating RED as "write all tests" and GREEN as "write all code".

It produces **crap tests**:
- Tests written in bulk test _imagined_ behavior, not _actual_ behavior.
- You end up testing the _shape_ of things (data structures, signatures) rather
  than user-facing behavior.
- Tests become insensitive to real changes — they pass when behavior breaks,
  fail when behavior is fine.
- You outrun your headlights, committing to test structure before
  understanding the implementation.

**Correct approach: vertical slices via tracer bullets.** One test → one
implementation → repeat. Each test responds to what you learned from the
previous cycle. Because you just wrote the code, you know exactly what behavior
matters and how to verify it.

```
WRONG (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

RIGHT (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  ...
```

## Planning

Before writing any code (use the project's domain glossary so test names and
interface vocabulary match the project's language; respect ADRs in the area
you're touching):

- [ ] Confirm with the user what interface changes are needed.
- [ ] Confirm with the user which behaviors to test (prioritize).
- [ ] List the behaviors to test (not implementation steps).
- [ ] Identify deep-module opportunities: small interface, deep implementation.
- [ ] Design interfaces for testability.
- [ ] Get the user's approval on the plan.

**You can't test everything.** Confirm with the user exactly which behaviors
matter most. Focus testing effort on critical paths and complex logic, not
every possible edge case.

## RED — write a failing test

Write ONE minimal test showing what should happen. One behavior. Clear name.
Real code (no mocks unless unavoidable).

Verify RED — **mandatory, never skip**:

```bash
[PROJECT TEST COMMAND] path/to/test.test.ts
```

Confirm:
- The test fails (not errors).
- The failure message is expected.
- It fails because the feature is missing (not because of typos).

**Test passes immediately?** You're testing existing behavior. Fix the test.
**Test errors?** Fix the error, re-run until it fails correctly.

## GREEN — minimal code

Write the simplest code to pass the test. Just enough to pass. Don't add
features, refactor other code, or "improve" beyond the test.

Verify GREEN — **mandatory**:

```bash
[PROJECT TEST COMMAND] path/to/test.test.ts
```

Confirm:
- The test passes.
- Other tests still pass.
- Output is pristine (no errors, warnings).

**Test fails?** Fix the code, not the test. **Other tests fail?** Fix now.

## REFACTOR — clean up

After green only — **never refactor while RED**:
- Extract duplication.
- Deepen modules (move complexity behind simple interfaces).
- Apply SOLID where natural.
- Consider what the new code reveals about existing code.
- Run tests after each refactor step. Stay green.

## Per-cycle checklist

```
[ ] Test describes behavior, not implementation
[ ] Test uses the public interface only
[ ] Test would survive an internal refactor
[ ] Code is minimal for this test
[ ] No speculative features added
[ ] Watched the test fail before implementing
[ ] Watched the test pass after
```

## Bug-fix integration

Bug found? Write a failing test reproducing it. Follow the red-green cycle. The
test proves the fix and prevents regression. Never fix bugs without a test.
(See the `diagnose` skill for the full debugging loop — TDD is its Phase 6.)

## Red flags — STOP and start over

- Code before test.
- Test after implementation.
- Test passes immediately.
- Can't explain why the test failed.
- Tests added "later".
- Rationalizing "just this once".
- "I already manually tested it."
- "Tests after achieve the same purpose."
- "It's about spirit not ritual."
- "Keep as reference" or "adapt existing code."
- "Already spent X hours, deleting is wasteful."
- "TDD is dogmatic, I'm being pragmatic."

**All of these mean: delete the code. Start over with TDD.**

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "Tests after achieve the same goals" | Tests-after = "what does this do?" Tests-first = "what should this do?" |
| "Already manually tested" | Ad-hoc ≠ systematic. No record, can't re-run. |
| "Deleting X hours of work is wasteful" | Sunk cost fallacy. Keeping unverified code is technical debt. |
| "Keep as reference, write tests first" | You'll adapt it. That's testing after. Delete means delete. |
| "Need to explore first" | Fine. Throw away exploration, start with TDD. |
| "Test hard = design unclear" | Listen to the test. Hard to test = hard to use. |
| "TDD will slow me down" | TDD is faster than debugging after. Pragmatic = test-first. |
| "Manual test faster" | Manual doesn't prove edge cases. You'll re-test every change. |

## When stuck

| Problem | Solution |
|---------|----------|
| Don't know how to test | Write the wished-for API. Write the assertion first. Ask the user. |
| Test too complicated | The design is too complicated. Simplify the interface. |
| Must mock everything | Code too coupled. Use dependency injection. |
| Test setup huge | Extract helpers. Still complex? Simplify the design. |

---

## Supporting sources

Merged from two upstreams (Decision 4, `docs/PROGRESS.md`). Check for drift
during the monthly `infra-audit`:

- User source: `~/.claude/commands/tdd.md` — contributed the horizontal-slices
  anti-pattern, vertical tracer-bullet workflow, the planning step (confirm
  behaviors to test with the user), and the deep-module/testability framing.
- `superpowers/test-driven-development` (obra/Superpowers, MIT) — contributed
  the iron law (no production code without a failing test first, delete means
  delete), mandatory verify-red / verify-green, and the
  red-flags/rationalizations tables.
