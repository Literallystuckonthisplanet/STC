# Defect ledger — self-improving review
<!-- R03 -->

A reference catalog. Not loaded into always-context; read when a defect is
caught and during catalog revision.

**The idea.** Any caught error — a failing test, a reviewer finding, a
runtime bug, a wrong primary result — is not just "fix it". It is a trigger
for three questions: **why was it allowed → how to prevent it → how to
improve the rules/checks**. The goal is that the same CLASS of error does
not recur, because it is closed by the cheapest prevention layer.

Connected: `code_standard.md` §7 (review process, where the protocol lives)
· `reference_retired_codes.md` (rule→hook migration — the end of the
escalation).

## The protocol (on EVERY caught defect)

A defect = a failing test, a code-review/security/qa finding, a runtime bug,
a wrong primary result. Run:

1. **Symptom** — what exactly failed/was found (one line, concrete).
2. **Generative cause = a CLASS, not a particular case.** Not "forgot await
   in orders.ts", but "async boundaries are not covered by a type/lint
   rule". Not "didn't sanitize input here", but "no shared boundary-
   validation helper". A class is what will repeat in another file/project.
3. **The cheapest prevention layer** (the ladder left → right — aim for the
   leftmost that actually closes the class):
   - **🤖 machine** — types / lint rule / test / hook / pre-commit gate.
     Deterministic, does not recur. **Priority.**
   - **👁 review checklist** — a point in code_standard §7/§9 or in a
     reviewer agent's profile. Caught by a human/agent, but less reliable
     than always.
   - **📝 always-text** — the last resort. **Recurs** (proven by mining 66
     sessions). Acceptable only as a trigger-anchor pointing to a
     hook/checklist.
4. **Record in the ledger** below, keyed by the CLASS. A repeat of the same
   class (≥2) is a signal to **escalate** one layer left (always→checklist→
   machine), up to rule→hook (see `reference_retired_codes.md`).

**Where in the process:** the Verify phase (PEV) and every reviewer agent
run. Remediation-first: fix the symptom, then the mandatory step
"class + layer" (do not skip under "it works now").

## The class ledger

Format: `| date | cause class | where it surfaced | prevention layer (chosen/done) | status |`

| Date | Cause class | Where it surfaced | Prevention layer | Status |
|---|---|---|---|---|
| YYYY-MM-DD | *(e.g. "code appended to the nearest pattern without checking the global authority for the concern")* | *(project: what happened)* | *(e.g. 👁 [ARCH-6] + 📝 anchor I21 + H10 reuse-inject)* | ✅ closed / ⏳ open |
| 2026-07-06 | **Framework boundary not caught by type/lint, surfaces only at runtime.** E.g. a Next.js `"use server"` file may export only async functions — exporting a const/object passes `tsc`+lint clean but fails at runtime (browser/SSR) on import. | caught on a server-actions file exporting a non-function constant; tsc/lint were green, browser e2e caught it | Symptom fix: move the constant/type out into a non-server module. Class-level: 📝 knowledge (a `"use server"` file exports only async functions — state/constants/types live in a sibling module). Escalates to 🤖 lint rule ("no non-async export in a `use server` file") on repeat. | 🟡 symptom closed, 🤖 gate candidate on repeat |
| 2026-06-29 | **Research/docs done last, at debug time, instead of at design time.** A docs-first hook fired but was ignored — advisory ≠ enforcement; pitfalls get discovered by trial-and-error instead of being known upfront. | an integration misbehaved; a docs-first nudge fired twice and was skipped both times before the doc was actually read | (1) design-time: per-use-case failure-modes + abuse-cases enumerated at spec time for every use case (see `reference_failure_modes.md` / `reference_abuse_cases.md`), not just for integrations. (2) debug-time: contract-first (authoritative source before any edit), always. (3) 🤖 an integration-docs-gate hook (H15) blocks editing a named integration without saved research on file; escape hatch `// docs-checked:`; generalized from a project-specific integration list to a lexicon+domain+generic-verb detector across all projects. (4) preventive shift: the docs-first threshold moved to entry (I25) — an unfamiliar tool gets its docs read before the first edit, not after ≥2 misses; the integration inventory also gets seeded at spec time (`to-spec` §2), so research is saved before Do. | ✅ (3)(4) closed: gate generalized + threshold moved to entry/spec-time; ⏳ (1) full per-use-case failure/abuse coverage remains an ongoing habit |

<!--
Seed with your own caught defects. Each row = a class, not a one-off. The
same class repeating ≥2 times → escalate the layer (move left in the
ladder above).
-->

## Escalation (when a class recurred)

A class repeat → move the layer left. Route:
`📝 always → 👁 checklist/§-rule → 🤖 hook/lint/test`. The "rule→hook" finale
is registered in `reference_retired_codes.md` (the always-code retires, the
body goes into Hxx). This is the same loop as code_standard §6
(research→catalog) and §8 (revision), but the entry is a caught defect, not
a research result.
