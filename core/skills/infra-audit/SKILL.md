---
name: infra-audit
description: "Audit the global agent infrastructure (rules, memory, skills, commands, hooks, templates, settings). Run roughly once a month when there is token budget to spare, or on demand. Format: 2 runs (sub-agent + self) + verification, done in 2 rounds."
---

# Infra audit
<!-- S17 -->

An audit of the global agent infrastructure. The run is expensive
(2 sub-agents + verification) — run it **when there is token budget to spare**.

## Cadence (like the "review after 3 tasks" idea)

The trigger is NOT a calendar — it is a rule the main agent tracks and
**offers** (like improve-architecture):
- At session start, compare today's date with the "Last run" below. If **≥1
  month** has passed → offer: "it's been a month since the last infra audit —
  run it? (is there token budget?)". Do not run without an explicit "yes".
- Or the user says outright: "run the infra audit".
- After every run — update the "Last run" date.

**Last run:** _(set by the agent after each run)_

## Format: 2 runs + verification, ×2 rounds

1. **Run A — sub-agent** (`general-purpose`, a capable model,
   `run_in_background`, read-only): an independent audit by the checklist,
   report by severity.
2. **Run B — yourself** (in parallel, your own battery of grep/scripts).
3. **Verification:** check every one of the agent's findings on the
   filesystem. Do NOT trust the agent on its word (it has been wrong: a false
   positive on a skill; severity confusion; omissions; over-cautious flags on
   lazy-file explanations).
4. **Merge:** combine A+B, resolve discrepancies, issue a single verdict.
5. **Second round:** after fixes — repeat the whole cycle. Lesson: the second
   round catches both new issues and self-introduced ones from the fixes.

**Why ×2 and both:** separately, neither the agent nor you closed the picture
— only together + verification. Real cases from past audits: a token was
found only by the agent; some secrets were missed by both (surfaced during
verification); a password in a file was missed by everyone in round one.

**Run cost (do not cheapen independence — that IS the quality; do cheapen
each run):** the audit agent → a capable model (a weaker one finds less);
give the agent `/caveman` for its report; **round 2 = delta-scope** (check
only what changed after fixes + new things, not the whole volume again);
during verification, check only what the agent flagged, not everything.

## Scope

The deployed infra in the target harness:
- the instruction file (`CLAUDE.md` / `AGENTS.md`)
- `memory/*.md` (including project notes — for secrets ONLY)
- `commands/*.md`, `agents/*.md` (or skill dispatcher prompts), `hooks/*.sh`
- `templates/*.md`, `settings.json`, the deploy pipeline + doc-backend code

## Checklist

1. **Secrets — EVERYWHERE** (memory + agents + commands + hooks + templates,
   not only memory/!). Tokens/keys/passwords as values: `ntn_`, `sk-`, `re_`,
   `ghp_`, `eyJ`, `*_SECRET=<value>`, `*_TOKEN=<value>`, passwords. Lesson: a
   password once hid in an agent file.
2. **Dangling pointers in always-context:** a pointer-only line `→ [[...]]` /
   `→ playbook §...` with no action next to it = a meta-rule violation (the
   action must live in always-context).
3. **Link integrity:** every `[[wiki]]` resolves to a memory file (by `name:`);
   a `§Section` exists; paths (`templates/`, `scripts/`) exist.
4. **Contradictions** between files.
5. **Duplication** of a rule across >1 always-file.
6. **Orphan/junk code labels** (mis-numbered or stray markers that are not
   real codes).
7. **Hook wiring:** `settings.json` → existing executable files; absolute
   paths consistent; matchers correct.
8. **Leftover `Why:` / `How to apply:` / history in ALWAYS-context** (in lazy
   files it is ALLOWED — do not report).
9. **Dead links** to something deleted.
10. **Label / doc-backend consistency:** run the doc-backend generator
    `--dry-run` → orphaned codes, numbering gaps, duplicates, meta-rule
    violations.
11. **Upstream drift of merged skills:** for every skill in `core/skills/`
    that carries a "Supporting sources" block (Decision 4 / Decision 5 in
    `docs/PROGRESS.md`), check whether each upstream source released
    meaningful updates/fixes since the last audit. If so — port the relevant
    change into the STC skill and note it in the report (skill → source →
    what changed → ported / deliberately skipped). Do not nitpick cosmetic
    diffs; port only changes that improve correctness, coverage, or safety.
    This is how merged-from-external skills stay current without depending
    on the external at runtime.

## Severity

- 🔴 **Must-fix:** a secret in any infra file, a broken link, a contradiction,
  a dangling pointer, a dead link, broken wiring.
- 🟡 **Review:** possible duplication/redundancy, a debatable wording, path
  inconsistency.
- 🟢 **OK:** checked and clean.

## Pitfalls / lessons

- In lazy files, `Why:` / `How to apply:` are ALLOWED — the agent tends to
  false-report them.
- `§Step N` links point at **bold** items (not `##`), but they are readable —
  an acceptable anchor, not a bug.
- When printing grep output, do NOT print full secret values (you would leak
  them into the transcript yourself).
- Public IDs (a market owner id, etc.) are not secrets.
