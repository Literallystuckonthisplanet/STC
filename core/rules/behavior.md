---
name: behavior-rules
layer: rules            # always-context
scope: global
---

# Behavioral rules

Firing rules of the form "situation → action". Apply in the moment when the
situation arises. These are imperatives, not suggestions. Where a rule is
**enforced by a hook** (ADR-001), the anchor notes which one — the always-text
here is a pointer; the hook is the guarantee.

## Secrets → .env, facts → memory
<!-- I05 I06 -->

- **Rule 1 — Secrets → .env immediately:** any credential, token, key, or
  password goes into `${SECRETS_ENV}` on first sight. Never echo it back in
  full; reference it by env-var name. Memory is forbidden for secrets.
  **Enforced: H03/I05b** (detects a secret in the prompt → directive) +
  **H05** (blocks a secret write into memory).
- **Rule 2 — Facts → memory immediately:** a fact surfaced in conversation
  (resource ID, a decision, an important result, a config) is saved to memory
  **immediately**, not "at the end of the session". After the task is done and
  the user approves — decide whether to keep it; if not, delete it.
- In code, examples, logs, or handoffs, replace real secrets with a
  placeholder (`<TOKEN>`, `${API_TOKEN}`). Treat the user's real values as
  toxic.
- `.env` files are never committed. `.gitignore` must cover them.

## Worktrees and parallel sessions
<!-- I07 -->

- Choose the concurrency mode by the task:
  - Small task, clearly isolated files → parallel agents + a pre-check for overlap.
  - Medium/large task, fuzzy scope, or shared files (`package.json`, types, configs) → worktree (clean per-branch review, rollback-friendly).
- **Before any new task:** `git worktree list` — what is already in flight.
  A worktree of the same area → merge BEFORE starting.
  **Enforced: H07** (task-start guard — nudges on >1 worktree at the first edit).
- Safe-parallelism criterion: worktree A and B must touch unrelated files. If
  both touch one page/component — that's a conflict.
- Closing a worktree: create → work → checks → merge → delete. Don't leave
  them open. An open worktree is a hanging debt.
- Worktree e2e checks run in main after merge, not inside the worktree. After
  merging all worktrees — a full check cycle over `git diff main...branch
  --name-only`, even if the worktree-agent already verified. Why/detail →
  `[[playbook]]` § Worktree checks.

## Git push and production
<!-- I08 -->

- **Release** → push to `main` only by explicit "releasing" from the user,
  executed by the agent. **Enforced: H01** (git guard blocks push-to-main
  without a one-shot ack marker).
- **Production edits** → only via dev → commit → push + explicit OK. No direct
  SSH edits (env/files/pm2 reload) on the server without the go-ahead — even
  for a config/env change. *(not hook-covered — keep in mind)*
- **Backup** → scheduled (every 3 days) into a `backup` branch of the private
  repo. All repos are private. *(TODO: the launchd job is not yet built —
  carry this forward, do not assume it runs.)*

## Commits
<!-- I09 -->

Commit-invariants (one task = one commit; don't commit unfinished/broken even
"temporarily"; no check = no commit) + the verify-checklist + the `--no-verify`
reminder — **delivered JIT by H01/B2** before every `git commit`. A dirty tree
before the first edit of a session (may be a parallel session's WIP) → **H07**.
Task-start = the first Edit / "going to do", not only the session start
(discussion → doing = also task-start).

Adjudicating a dirty tree (own WIP → Verify→commit / someone else's WIP →
lock it down with the user) + committing inside a worktree after checks before
merge → `[[playbook]]`.

## Self-execution (SELF-EXEC)
<!-- I10 -->

Run everything you can yourself: docker, npm/pip, the `.env` setup, launching
the browser, starting/stopping services. Ask the user only for a **value** (a
token, a choice between options) or a **decision** (which approach). Never ask
permission to do the obvious next mechanical step. If a command fails, read
the error, fix it, retry — don't surface a failed command to the user as their
problem. **Reinforced: H03** (prints SELF-EXEC every prompt).

**Only two exceptions:** (1) an external service without API/tool access
(GitHub OAuth, Vercel, DNS) → explain where and what, prepare the rest
yourself; (2) irreversible/destructive (drop table, force push) → confirm
before. Concrete patterns → `[[playbook]]` § SELF-EXEC.

## Background services
<!-- I11 -->

- **Auto-start before an operation:** if the work needs a service, verify it's
  running, start it yourself if not. Take the port and start command from the
  project's instruction file or `package.json`.
- **Cascade restarts after a config change:** restart the dependent service
  yourself, don't tell the user "restart it".
- **Stop:** only on "wrap up the session" (protocol → session rules §3). In
  the middle of a session and on compact — don't touch services. Do it
  yourself.

## Long ASCII strings (base64 / tokens / hashes) — don't type by hand
<!-- I12 -->

Never reproduce a long ASCII string (base64, JWT, hash, key, URL with encoded
content) by hand in a tool-call or file. Homoglyph substitution (latin↔cyrillic)
silently breaks the whole string. Generate/transform programmatically
(python/bash), read from a file — don't transcribe in the answer. If an edit
is unavoidable — change a short unique anchor pointwise, don't rewrite the
whole string. **After any insert/edit — verify:** grep for non-ASCII
(`[^\x00-\x7F]`) + by meaning (base64 → decode without errors; an image URL →
`curl` to `HTTP 200`). The homoglyph pair list → `[[playbook]]` § Homoglyphs.

## Project start
<!-- I13 -->

A new project begins from `${TEMPLATES_DIR}/new-project.md` (Phase 0 Kickoff).
Don't improvise the structure on the fly. The kickoff determines the stack for
*this* project — it is not inherited from a global default. The project-memory
file uses the STATE/OPEN/CHANGELOG format (R08) — don't duplicate repo docs →
`[[project_docs]]` § R08.

## Code conventions
<!-- I14 -->

- Always use **python3** (not python).
- Always install dependencies via **pip**.
- Downloads go to `~/Downloads/`.

## Agent baseline (accepted/out-of-scope problems)
<!-- I20 -->

A reviewer agent (security-deps / qa / code-reviewer / e2e / security-arch)
reports a deliberately-accepted or out-of-scope problem → record it in the
repo's baseline file (with a "why accepted" note) → on the next run, pass the
baseline in the prompt so it doesn't re-report. Security HIGH/CRITICAL never
go under baseline — always a block. **Enforced: H04** (agent guard — nudges
passing the baseline when launching a reviewer). Detail/example → `[[playbook]]`
§ Agent baseline.

## Find the existing way before making a new one
<!-- I21 -->

**Trigger:** about to implement something that may already exist (auth / data
access / errors / logs / cache; an operation on an entity; an API-response
format; money/dates; id/sku/slug) → FIRST find (grep/`Explore`) how it's done
in the repo → reuse. A second way = only an explicit recorded decision (the
instruction file / an ADR); a divergence = stop for review.
**Enforce-nudge: H10** (read-first router, the reuse branch). Broader → pev
Step 3. The class of error/example → `[[code-standard]]` [ARCH-6].

**Buy-vs-build (DEP-4):** before writing a non-trivial piece by hand — a new
domain capability >~50 lines OR the territory of typical libraries (parsing/
validation/dates/rate-limit/retries/files/crypto/state-machines/HTTP-clients)
→ evaluate a READY solution first (`docs` agent / Context7, or `research`
agent), fix the decision as an ADR line. **Enforced: H14** (JIT-inject on
entering plan mode + a new-module backstop). Detail → `[[code-standard]]`
[DEP-4].

**Docs-first on integrations:** editing the code of a named integration
without saved research (the failure-modes catalog or notes/research) is
blocked — read the contract FIRST, then edit. **Enforced: H16** (a block,
lifted by saving the research or a `// docs-checked:` marker). The catalogs
→ `[[reference-failure-modes]]` / `[[reference-abuse-cases]]`.

**Delegating to a build-agent** (`general-purpose` / `claude`) → the prompt
opens with a contract (zoom-out + `reuse-before-reinvent` + a return
contract); the `reuse-before-reinvent` marker is mandatory, otherwise H04
blocks the launch. Template/who it concerns → `[[playbook]]` § Agent prompt
contract.

## Code-label reference — always with the name
<!-- I22 -->

Mentioning a code-label (I/S/A/H/R/T/N + number) in an answer to the user →
write it with a short name in parens: `I08 (git push/prod)`, `R09 (code
standard)`, `H04 (agent contract)` — not a bare code. The name = the §-heading
at the label (source of truth = the files). The user doesn't memorize codes.

## Saving research
<!-- I18 -->

Produced a research result (market/technologies/strategy, legal, an
approach comparison) — via the `research` agent OR in main → save it **locally**
(`memory/notes/research/`, brief = delta not raw) + a line in the research
index; the run cost → FR-21 (`agent-cost.py --latest`). How → `[[playbook]]`
§ Saving research.

## Progress tracking — live todo-list
<!-- I23 -->

A task with >1 step or a sequence of edits/plan-items → keep a live
`TodoWrite` list (one `in_progress` item, mark `completed` as you go). The
user wants to see progress constantly — don't let the list slide into history.
A tiny single-action task — no list.

## Command output hygiene — don't flood the window
<!-- I24 -->

Don't show raw command output in the window by default (the user: "remove
command output forever and everywhere"). Build commands to emit only a short
summary line: redirect noisy output (`>/dev/null 2>&1`), capture into a
variable → print only the point ("built ✓", "3/3 tests", a specific
number/path). One-liners without a useful result (`chmod`/`mkdir`/`mv`) —
quietly, no echo and no comment. Long output → filter (`grep`/`tail`/counter)
to the fact, don't dump it whole. Show raw output ONLY when (a) the user
explicitly asks, or (b) error diagnosis needs a specific fact. In the answer —
conclusions, not raw output. **Enforced: H11** (output-hygiene guard, FR-15).

**Expensive-Bash offload:** a noisy data-script (import/seed/publish/scrape/
sync) or a wall-of-text audit is not run silently in the main context —
offload it to an ephemeral agent (run → return the summary/counters, not the
whole stdout). **Enforced: H15** (exec-offload guard — blocks unless stdout
is redirected, carries `--json`, or is marked `# in-main`). The lever → pev
Step 2 / `[[playbook]]` § Token economy.

## Service-field language
<!-- I25 -->

Service fields visible to the user — in the user's language, like the text
answers. Covers: tool-call `description`, `TodoWrite` items
(`content`/`activeForm`), `AskUserQuestion` headers/previews. (Internal
reasoning runs in EN → it used to leak into the wrapper.) **Exception:** code
artifacts of the repo's ambient language — code comments and git commits stay
in that language; if the user asks for their language there too — extend the
rule.

## Tokens economy on inter-agent traffic
<!-- I13b -->

- When dispatching sub-agents (research, review, analysis), instruct them to
  answer in caveman style if `${SUBAGENT_COMPRESSION}` is enabled. The final
  answer to the user is always rendered in normal prose.
- See the caveman skill for the exact compression rules.
