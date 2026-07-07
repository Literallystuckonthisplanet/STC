---
name: diagnose
description: "Disciplined root-cause debugging for hard bugs, test failures, build breaks, and performance regressions. The core is a fast, deterministic feedback loop — build that first, everything else is mechanical. Use when the user says 'diagnose/debug this', reports something broken/throwing/failing, or describes a perf regression."
---

# Diagnose
<!-- S02 -->

A discipline for hard bugs. Random fixes waste time and create new bugs;
symptom fixes mask the underlying issue. **Always find the root cause before
attempting any fix.** Skip phases only when explicitly justified.

## The iron law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.
```

If you haven't completed Phase 1, you cannot propose fixes. "Quick fix for
now, investigate later" is the rationalization that turns a 30-minute bug into
a 3-hour thrash. Systematic is faster.

## Phase 1 — Build a feedback loop

**This is the skill.** Everything else is mechanical. If you have a fast,
deterministic, agent-runnable pass/fail signal for the bug, you will find the
cause — bisection, hypothesis-testing, and instrumentation all just consume
that signal. If you don't, no amount of staring at code will save you.

Spend disproportionate effort here. **Be aggressive. Be creative. Refuse to
give up.**

### Ways to construct one — try in roughly this order

1. **Failing test** at whatever seam reaches the bug — unit, integration, e2e.
2. **Curl / HTTP script** against a running dev server.
3. **CLI invocation** with a fixture input, diffing stdout against a known-good snapshot.
4. **Headless browser script** (Playwright / Puppeteer) — drives the UI, asserts on DOM/console/network.
5. **Replay a captured trace.** Save a real network request / payload / event log to disk; replay it through the code path in isolation.
6. **Throwaway harness.** Spin up a minimal subset of the system (one service, mocked deps) that exercises the bug code path with a single function call.
7. **Property / fuzz loop.** If the bug is "sometimes wrong output", run 1000 random inputs and look for the failure mode.
8. **Bisection harness.** If the bug appeared between two known states (commit, dataset, version), automate "boot at state X, check, repeat" so you can `git bisect run` it.
9. **Differential loop.** Run the same input through old-version vs new-version (or two configs) and diff outputs.
10. **HITL bash script.** Last resort. If a human must click, drive _them_ with `scripts/hitl-loop.template.sh` so the loop is still structured. Captured output feeds back to you.

Build the right feedback loop, and the bug is 90% fixed.

### Iterate on the loop itself

Treat the loop as a product. Once you have _a_ loop, ask:

- Can I make it faster? (Cache setup, skip unrelated init, narrow the test scope.)
- Can I make the signal sharper? (Assert on the specific symptom, not "didn't crash".)
- Can I make it more deterministic? (Pin time, seed RNG, isolate filesystem, freeze network.)

A 30-second flaky loop is barely better than no loop. A 2-second deterministic loop is a debugging superpower.

### Non-deterministic bugs

The goal is not a clean repro but a **higher reproduction rate**. Loop the trigger 100×, parallelise, add stress, narrow timing windows, inject sleeps. A 50%-flake bug is debuggable; 1% is not — keep raising the rate until it's debuggable.

### When you genuinely cannot build a loop

Stop and say so explicitly. List what you tried. Ask the user for: (a) access to whatever environment reproduces it, (b) a captured artifact (HAR file, log dump, core dump, screen recording with timestamps), or (c) permission to add temporary production instrumentation. Do **not** proceed to hypothesise without a loop.

Do not proceed to Phase 2 until you have a loop you believe in.

## Phase 2 — Reproduce

Run the loop. Watch the bug appear. Confirm:

- [ ] The loop produces the failure mode the **user** described — not a different failure that happens to be nearby. Wrong bug = wrong fix.
- [ ] The failure is reproducible across multiple runs (or, for non-deterministic bugs, reproducible at a high enough rate to debug against).
- [ ] You have captured the exact symptom (error message, wrong output, slow timing) so later phases can verify the fix actually addresses it.

Do not proceed until you reproduce the bug.

## Phase 3 — Root-cause investigation

**BEFORE forming hypotheses, gather evidence of WHERE it breaks.**

1. **Read error messages carefully.** Don't skip past errors or warnings. They often contain the exact solution. Read stack traces completely — note line numbers, file paths, error codes.
2. **Check recent changes.** What changed that could cause this? `git diff`, recent commits, new dependencies, config changes, environmental differences.
3. **Gather evidence at component boundaries** (multi-component systems: CI → build → signing, API → service → database): for EACH boundary, log what data enters and exits, verify env/config propagation, check state at each layer. One instrumented run reveals which layer fails.
4. **Trace data flow backward** from the bad value: where does it originate? What called this with the bad value? Keep tracing up until you find the source. Fix at the source, not at the symptom.

## Phase 4 — Hypothesise

Generate **3–5 ranked hypotheses** before testing any of them. Single-hypothesis generation anchors on the first plausible idea.

Each hypothesis must be **falsifiable**: state the prediction it makes.

> Format: "If <X> is the cause, then <changing Y> will make the bug disappear / <changing Z> will make it worse."

If you cannot state the prediction, the hypothesis is a vibe — discard or sharpen it.

**Show the ranked list to the user before testing.** They often have domain knowledge that re-ranks instantly ("we just deployed a change to #3"), or know hypotheses they've already ruled out. Cheap checkpoint, big time saver. Don't block on it — proceed with your ranking if the user is AFK.

## Phase 5 — Instrument + test minimally

Each probe must map to a specific prediction from Phase 4. **Change one variable at a time.** Make the SMALLEST possible change to test a hypothesis. Don't fix multiple things at once — you can't isolate what worked.

Tool preference:

1. **Debugger / REPL inspection** if the env supports it. One breakpoint beats ten logs.
2. **Targeted logs** at the boundaries that distinguish hypotheses.
3. Never "log everything and grep".

**Tag every debug log** with a unique prefix, e.g. `[DEBUG-a4f2]`. Cleanup at the end becomes a single grep. Untagged logs survive; tagged logs die.

**Perf branch.** For performance regressions, logs are usually wrong. Instead: establish a baseline measurement (timing harness, `performance.now()`, profiler, query plan), then bisect. Measure first, fix second.

**If the test didn't work:** form a NEW hypothesis. Do NOT add more fixes on top. Return to Phase 3/4 with the new information.

## Phase 6 — Fix + regression test

Write the regression test **before the fix** — but only if there is a **correct seam** for it.

A correct seam is one where the test exercises the **real bug pattern** as it occurs at the call site. If the only available seam is too shallow (single-caller test when the bug needs multiple callers, unit test that can't replicate the chain that triggered the bug), a regression test there gives false confidence.

**If no correct seam exists, that itself is the finding.** Note it. The codebase architecture is preventing the bug from being locked down. Flag it for the architecture review.

If a correct seam exists:

1. Turn the minimised repro into a failing test at that seam. Use the `tdd` skill for the red-green cycle.
2. Watch it fail.
3. Apply the fix — ONE change, no "while I'm here" improvements.
4. Watch it pass. Verify no other tests broke.
5. Re-run the Phase 1 feedback loop against the original (un-minimised) scenario.

### The 3-fail escalation

**If ≥3 fixes have failed:** STOP. Count: each fix revealing a new problem in a different place, or needing "massive refactoring", is the pattern of a **wrong architecture**, not a failed hypothesis. Do NOT attempt fix #4. Question the fundamentals with the user — refactor architecture vs. continue patching symptoms. This is NOT a failed hypothesis; it's a wrong architecture.

## Phase 7 — Cleanup + post-mortem

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop)
- [ ] Regression test passes (or absence of seam is documented)
- [ ] All `[DEBUG-...]` instrumentation removed (`grep` the prefix)
- [ ] Throwaway prototypes deleted (or moved to a clearly-marked debug location)
- [ ] The hypothesis that turned out correct is stated in the commit / PR message — so the next debugger learns

**Then ask: what would have prevented this bug?** If the answer involves architectural change (no good test seam, tangled callers, hidden coupling) hand off to the architecture-review skill with the specifics. Make the recommendation **after** the fix is in, not before — you have more information now than when you started.

## Red flags — STOP and return to Phase 1

If you catch yourself thinking:

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "One more fix attempt" (when already tried 2+)
- Each fix reveals a new problem in a different place

**ALL of these mean: STOP. Return to Phase 1.**

## When the process reveals "no root cause"

If systematic investigation reveals the issue is truly environmental, timing-dependent, or external:

1. You've completed the process.
2. Document what you investigated.
3. Implement appropriate handling (retry, timeout, error message).
4. Add monitoring/logging for future investigation.

**But:** 95% of "no root cause" cases are incomplete investigation.

---

## Supporting sources

Merged from two upstreams (Decision 4, `docs/PROGRESS.md`). Check for drift
during the monthly `infra-audit`:

- User source: `~/.claude/commands/diagnose.md` — contributed the 10-way
  feedback-loop taxonomy, "iterate on the loop as a product",
  non-deterministic → raise reproduction rate, and the loop-first phase
  structure.
- `superpowers/systematic-debugging` (obra/Superpowers, MIT) — contributed
  the iron law, the multi-component evidence-gathering at boundaries, the
  3-fail architecture escalation, and the red-flags/rationalizations tables.
