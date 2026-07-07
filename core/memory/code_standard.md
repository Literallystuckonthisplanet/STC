---
name: code-standard
layer: memory            # lazy reference — read by anchor
scope: global
description: "Code standard — project classifier (complexity + specificity) + annotated rule catalog (core/flags/size) + uncertainty map (when to research) + review process. Read when writing/reviewing code and when starting a new project."
---

<!-- R09 -->

# Code standard — catalog + classifier

A single standard for writing and reviewing code across all projects. Not
flat: **a core for everyone + overlays by complexity and specificity**.
Source of truth = this file (global). Linter configs (the mechanical part)
live in each project's repository (otherwise they won't run). A specific
project's profile is 3 lines in its instruction file.

---

## 0. How to apply (the classifier)

Before working on a project, determine its **profile** on two axes, then
enable the applicable catalog blocks.

**Axis 1 — Complexity (scale → architectural strictness):**
- **S0** — simple site: content, forms, no complex state (landing, card, blog).
- **S1** — application: state, accounts, a DB (shop, SaaS-lite).
- **S2** — complex software: many domains/services, high load, a team. The
  upper tier is sketched — research for a real S2 (see §6).

**Axis 2 — Specificity (what it does → which risks), flags:**
- 💰 MONEY — money/payments
- 👤 ACCT — accounts/authorization
- 📤 FILE — file upload
- 🔐 PII — personal data
- 🌐 API — public API / external integrations
- 📝 UGC — user-generated content
- 📈 LOAD — high load/traffic

**Profile = size + a set of flags.** Core always applies. Flags add their own
blocks. Size sets architectural strictness (§ Size).

**Application tag on every rule:**
- 🤖 enforced by a tool (linter/types/pre-commit) — "basket A", do not spend
  manual review on it
- 👁 checked by a reviewer/agent — "basket B", judgment
- 📐 decided at design time (UI/architecture), before code

---

## 1. Principle: machine vs reviewer

We split all checks into two classes, because they are checked differently:
- **🤖 machine** — deterministic, free, instant, at the pre-commit gate (dirt
  does not get committed). Style, format, dead code, unused, part of types,
  import boundaries.
- **👁 reviewer** — judgment: architecture, fit of errors/edge cases,
  readability of logic, substance of comments, security.

Rule: what a linter catches does NOT go into manual/agent review.

---

## 2. Catalog — CORE (always applies, any project S0+)

### ARCH — architecture and layers
- [ARCH-1] Three layers: Screen (UI) / Actions (validation + rights + call) /
  Data access. Reach the DB only through the data layer. 👁
- [ARCH-2] Page code lives next to the page; cross-page logic is extracted;
  UI atoms are separate. 👁
- [ARCH-3] Cut by responsibility, not by length. 1 file = 1 responsibility.
  God-file and over-fragmentation are equally bad. 👁
- [ARCH-4] Do not abstract before the 3rd repetition (AHA > DRY). Duplication
  is better than the wrong abstraction. 👁
- [ARCH-5] Anything exposed goes through the module's public entry; internals
  stay internal. 👁
- [ARCH-6] **One authority per cross-cutting concern** — auth / data access /
  errors / logs / cache / money / dates / id-sku: ONE canonical way in the
  repo. Before adding a path for such a concern → grep/`Explore` how it's done
  → reuse; a second way = only an explicit recorded decision (instruction
  file / ADR); a divergence = stop for review. (Origin: a "two admin
  authorizations" bug — a second ad-hoc auth path silently diverged.) 👁

### VALID — input validation at boundaries
- [VALID-1] Anything coming from outside (forms, URL params, external API
  responses) is validated by a schema on entry. 👁
- [VALID-2] Parse once at the boundary; inside the layer data is trusted, do
  not re-parse. 👁
- [VALID-3] Derive types from the schema (`z.infer`), do not duplicate by
  hand. 👁
- [VALID-4] Frontend validation (masks/highlights/hints) is a UX convenience,
  NOT a replacement for server-side. Do both. 📐👁

### ERR — error handling and error UX
- [ERR-1] Distinguish expected errors (show to the user) from unexpected
  (crash loudly + Sentry). 👁
- [ERR-2] Do not swallow errors silently (empty catch / catch-log-continue is
  forbidden). 👁
- [ERR-3] Actions return a result (ok/err), they do not drop the form with an
  exception. 👁
- [ERR-4] Sentry — only on the unexpected, not on validation (do not
  overload). 👁
- [ERR-5] Fail-fast in the data layer: an unexpected null where a record must
  exist = a bug, let it surface. 👁
- [ERR-6] 404 and 500 pages are mandatory. 📐
- [ERR-7] Every screen is designed with states: loading / empty / error. 📐
- [ERR-8] Sensible messages on failures/timeouts ("Server error, try again
  later"), not a white screen. 📐

### READ — readability ("every if is understandable on its own")
- [READ-1] Early return (guard clauses) instead of nested ifs (3+ conditions
  on entry → mandatory). 👁
- [READ-2] A complex boolean condition → a named variable, reads like a
  phrase. 👁
- [READ-3] Magic numbers → named constants. 🤖(partial)👁
- [READ-4] Names for intent: functions = verb+object; booleans = is/has/can/
  should; domain language, not `data`/`val`. 👁
- [READ-5] No "clever"/implicit code for brevity's sake. 👁

### CMT — comments
- [CMT-1] "Why, not what". A comment explaining WHAT obvious code does is a
  signal to rewrite, not to comment. 👁
- [CMT-2] Forbidden: commented-out code, "recommendations into the void",
  TODO without context (ticket/date). 👁🤖
- [CMT-3] JSDoc/docstring — only on public API with non-trivial params. 👁

### STYLE — style, naming, dead code (mechanics, config in repo)
- [STYLE-1] Formatting — Prettier/a formatter automatically. 🤖
- [STYLE-2] Naming by the project's convention table (components PascalCase,
  files kebab-case, constants UPPER_SNAKE, functions = verb). 🤖(where a
  linter catches it)👁
- [STYLE-3] Dead code / unused imports/exports/files/deps — forbidden (ESLint
  + knip). 🤖
- [STYLE-4] A single import order. 🤖
- [STYLE-5] Import boundaries: forbid reaching into the DB bypassing the data
  layer; forbid dangerous raw calls. 🤖
- [STYLE-6] With a design system — forbid visuals bypassing tokens: hardcoded
  colors (`#hex`/`rgb()`/`oklch()` in components), arbitrary Tailwind values
  (`p-[13px]`, `text-[#...]`), inline `style` for visuals, `font-family`
  bypassing tokens. Config — in the project repo; on existing code "only
  choke the new". See `templates/design-system/process.md` §6 and playbook §
  Design system. 🤖

### TYPE — type safety
- [TYPE-1] Strict compiler mode (strict + noUncheckedIndexedAccess). 🤖
- [TYPE-2] `any` forbidden (only `unknown` + narrowing). 🤖
- [TYPE-3] `as T` without preceding validation forbidden; double assertion
  forbidden. 🤖(partial)👁
- [TYPE-4] Boundary types (in/out) explicit; derive from schemas/ORM, do not
  duplicate. 👁

### SEC — baseline security (typical for any web)
- [SEC-1] Injections: parameterized queries (SQL/NoSQL); output escaping
  (XSS). 👁🤖
- [SEC-2] Secrets — only in env; never in code/bundle/logs. 👁
- [SEC-3] Transport: HTTPS everywhere; security headers (CSP, HSTS). 👁
- [SEC-4] Access control to functions — on the server, not "hid the button in
  the UI". 👁
- [SEC-5] Open redirects / SSRF — only by allowlist. 👁

### DEP — dependency hygiene
- [DEP-1] Before adding a library — checklist: alive (commits <12 mo), size,
  downloads, transitive, install-scripts. 👁
- [DEP-2] ≤50 lines and no live analog → write it yourself. Crypto/auth/
  parsing — never write from scratch. 👁
- [DEP-3] Lockfile is committed and reviewed like code; `--frozen-lockfile`
  in CI; `audit` on high/critical. 🤖👁
- [DEP-4] **buy-vs-build (a ready solution before self-writing).** A
  non-trivial piece — >~50 lines OR the territory of typical libraries
  (parsing, validation, dates, rate-limit, retries, files, crypto,
  state-machines, HTTP-clients) — BEFORE writing by hand, actively evaluate
  a ready solution: the `docs` agent (Context7, a known-library API) or the
  `research` agent (find+compare maturity/support/size/transitive), then
  run [DEP-1]. Fix the decision as an ADR line in the spec (`to-spec`):
  "Took X / by hand, because Y". The mirror threshold from below is
  [DEP-2]/[LEAN-5] (≤50 lines, no live analog, trivial → write it yourself,
  do not pull a library for a trifle). Enforced: **H14** (JIT-inject on
  `EnterPlanMode`). 👁📐

### LEAN — write less code (the decision ladder)
A numbered procedure: stop at the first "yes".
- [LEAN-1] **Decision ladder** — before writing code for a need, check in
  order: (1) is it needed at all? (2) stdlib? (3) the platform (Next/Payload/
  Prisma/your stack)? (4) a dependency already installed? (5) a one-liner?
  (6) only then — your own implementation. Stop at the first "yes". 👁
- [LEAN-2] **What NOT to cut** — validation, error handling, security,
  state handling, a11y. Less code, not fewer features. 👁
- [LEAN-3] **`lean:` label** — where you stop on the ladder + an upgrade path
  (when a need grows). Stays at the code site. Intersects with the review
  baseline. 👁
- [LEAN-4] **Less CODE, not fewer symbols.** [READ-5] (readable) outranks
  brevity — don't golf. 👁
- [LEAN-5] **Stitching** — aligns with [ARCH-4] (one concern, one place) and
  [DEP-2] (write small things yourself). 👁

### TEST — testability
- [TEST-1] Separate business logic (calculations, discounts, validation,
  transforms) into pure functions, do not mix with IO. 👁
- [TEST-2] Cover pure functions + business-logic edge cases with unit tests.
  👁
- [TEST-3] Do not test trivia, framework glue, generated code. Coverage as an
  end in itself is harmful. 👁

### ENV — configuration
- [ENV-1] Validate env vars on startup (a bad config crashes the app at once,
  not in prod piece by piece). 👁

### DBM — DB migrations
- [DBM-1] Do not edit already-applied migrations; backup before rolling to
  prod. 👁

---

## 3. Catalog — blocks by specificity flag (enable by profile)

### 💰 MONEY — money/payments
- [MONEY-1] Store and count money as integers (cents), not floats. 👁
- [MONEY-2] Prices are server-authoritative: do not trust the client price,
  recalculate on the server. 👁
- [MONEY-3] Payment idempotency: a unique key + a UNIQUE lock in the DB
  (protection against double charge). 👁
- [MONEY-4] Verify payment-webhook signatures (HMAC, timing-safe compare);
  the webhook is outside the auth middleware. 👁
- [MONEY-5] Structured logging of every payment operation (userId, orderId,
  amount, key) — for dispute analysis. 👁

### 👤 ACCT — accounts/authorization
- [ACCT-1] Check authorization close to the data (in the data layer), not
  only in Actions — so it cannot be forgotten. 👁
- [ACCT-2] IDOR protection: select with a filter by owner (`where id AND
  userId`), not by id alone. 👁
- [ACCT-3] Login protection: rate-limit / lock after N attempts; safe
  sessions. 👁
- [ACCT-4] Check the session before business logic; a single entry point to
  the session. 👁

### 📤 FILE — file upload
- [FILE-1] Check type and size; do not trust the filename. 👁
- [FILE-2] Storage isolation; do not execute the uploaded; serve via a safe
  path. 👁

### 🔐 PII — personal data
- [PII-1] Minimization: collect only what is necessary. 👁
- [PII-2] Mask PII in logs/Sentry (email/phone/name/address). 👁
- [PII-3] Retention period and deletion; the join with legal-review (triggers
  → playbook § Agent triggers). 👁
- [PII-4] Encrypt the sensitive. 👁

### 🌐 API — public API / external integrations
- [API-1] A single API error contract: a consistent response shape, correct
  codes, clear text. 👁
- [API-2] Validate external API responses by schema before use (the contract
  can change). 👁
- [API-3] Rate-limit public endpoints. 👁
- [API-4] External URLs — from constants/allowlist, not from the request
  (SSRF). 👁

### 📝 UGC — user-generated content
- [UGC-1] Sanitize content on output (XSS); do not trust user markup. 👁
- [UGC-2] Moderation / a publish flow if the content is public. 👁📐
- [UGC-3] Anti-spam / rate-limit on content creation. 👁

### 📈 LOAD — high load
- [LOAD-1] Caching (explicit; know the framework's cache defaults). 👁
- [LOAD-2] N+1 queries — eliminate (eager-load related in one query). 👁
- [LOAD-3] Only the needed fields (select), pagination, indexes under common
  filters/sorts. 👁
- [LOAD-4] Bundle size: heavy stuff → server; pinpoint imports; image
  optimization. 👁🤖

---

## 4. Catalog — by the complexity axis

- **SIZE-S0** — core only; layers not formalized (one or two folders is
  enough).
- **SIZE-S1** — core + an explicit data layer (DAL) + layer separation +
  state discipline (client state = UI only, not a cache of server data).
  Baseline performance ([LOAD-2/3]) is already here.
- **SIZE-S2** — core + hard architectural boundaries (plugin-enforced),
  decomposition into modules/services, heavy test infra. Details parked →
  research for a concrete S2 project (§6).

---

## 5. Project profile (template)

A project profile is 3 lines in the project's instruction file. Example
shape:

```
Project: <name>
Complexity: S1
Flags: 💰 MONEY · 👤 ACCT · 🔐 PII · 🌐 API · 📝 UGC
Apply: CORE + SIZE-S1 + [MONEY] + [ACCT] + [PII] + [API] + [UGC]
Do NOT apply: [FILE] (no uploads), [LOAD] (S2 infra — not yet needed)
```

The profile is verified against the real code, not on someone's word (e.g.
UGC is on because there is a reviews feature). When uploads/load appear — add
the flag.

---

## 6. When a focused research is needed (the uncertainty map)

The catalog covers the known (a Node/TypeScript/React/Prisma-ish stack +
typical web flags). Research kicks in when the profile steps outside that:
1. **A new stack/platform** not in the catalog (Python/Django, Go, mobile,
   serverless-edge, GraphQL-federation).
2. **A new specificity without a block** (marketplace/multi-party
   settlement, ML/AI, realtime, geo, crypto).
3. **An S2 level** — the upper architectural tier for the concrete case.
4. **A regulation-sensitive domain** (medicine/finance/children/special PII
   categories) → join with legal-review.
5. **Honest uncertainty** when profiling (does a rule apply / how does it
   map) — the council skill's "unfamiliar domain" criterion.
6. **The catalog is stale** (a major framework version broke an approach) →
   revise the block.

**Loop:** a focused research result → write it back into the catalog (grow the
asset, not a one-off). Launch via the research agent (playbook § Agent
triggers), with Council-framing.

---

## 7. Review process

A check pipeline for a code change:
1. **🤖 Auto:** linters + types + pre-commit as an iron gate (strict: did not
   pass → no commit is created).
2. **👁 Code review ×3, isolated, by free agents:** `code-reviewer` (quality/
   architecture) + `security-arch` (security) + `qa` (tests) → the Council
   merges the results.
3. **Tests:** unit on business logic (qa agent).
4. **e2e:** Playwright through the user's browser (e2e sub-agent) — user
   scenarios.

### Security baseline on handoff and verify

Security rules live in the catalog (SEC + the flag blocks MONEY/ACCT/FILE/
PII/API/UGC), but they used to **silently drop** — not fixed as acceptance
criteria on handoff. Wire them into the process:

- On handoff / spec → the security baseline (rate-limit / dual validation /
  resource-ownership verification / zero admin keys in the bundle /
  access-control) goes into the spec's acceptance criteria.
- At Verify → the `security-arch` agent checks the baseline as a gate.
- A deliberately-accepted or out-of-scope finding → the repo baseline (see
  playbook § Agent baseline); security HIGH/CRITICAL never go under it.

**Agent wiring (make-or-break):** review agents read the project profile from
its instruction file → pick the applicable catalog blocks (core + flags +
size) → check only those. Without auto-selection by profile the standard
drifts.

**Review output format:** `Scope / Changes / Risks / Tests / Manual`.
**Review defaults:** remediation-first (fix first, report after); secrets in
output → placeholder + rotation; repo-boundary (do not leave the repository).

**Self-improving review (a mandatory step on EVERY caught defect).** Any
caught error — a failing test, an agent finding, a bug, a wrong primary
result — after fixing the symptom, is run through the protocol: *symptom →
the generative cause (a CLASS, not a particular case) → the cheapest
prevention layer (🤖 machine > 👁 checklist > 📝 always) → a record by class
→ escalation leftward on a repeat (up to rule→hook)*. Do not skip under "it
works now". The full protocol and the registry →
`reference_defect_ledger.md`.

---

## 9. Abuse-case and failure-mode perspective (the attacker + the pitfalls)

**Why.** The rules above are ALREADY in the catalog, but they silently drop
if not fixed as AC on handoff: they are forgotten at the spec stage →
retrofitted after an incident. An AI/developer builds exactly what was
asked; security lives in the unasked questions ("what if an endpoint is hit
10k times?", "who can read this data?").

**Two reflexes on EVERY use-case of a spec:**
1. **The attacker reflex — "how to break it?"** Run it against the
   abuse-case catalog (`reference_abuse_cases.md`) by the profile flags
   (ACCT/API/UGC/PII/MONEY). Loopholes → negative AC + NFR. New vectors
   discovered → append to the catalog.
2. **The failure-mode reflex — "where will it stall/break?"** Check the
   failure-modes catalog (`reference_failure_modes.md`) for the use-case; no
   entry for a new scenario → docs-research and **save it** (otherwise the
   integration-docs hook H16 will block editing the code).

**Baseline-5 (minimum for any S1+ with ACCT/API/UGC/PII)** — the security
hygiene floor, each point an AC at handoff (📐, before code) AND a gate at
verify (👁, after):

1. **Rate-limit on sensitive endpoints** [ACCT-3][API-3][UGC-3]: auth
   (brute-force + magic-link/OTP bombing → provider cost), public mutations
   (orders/reviews/forms), proxies to a paid token. Two layers: app-level
   (per-endpoint) + edge (Nginx `limit_req`/`limit_conn` — anti-DDoS before
   the runtime). Single-instance → an in-memory limiter, Redis not needed.
2. **Input validation on BOTH boundaries** [VALID-1][VALID-4]: email/phone/
   any input — a mask on the frontend (UX) + a schema on the server (zod),
   a shared helper-regex so they do not drift. The frontend is never a
   substitute for the server.
3. **Ownership verification** where an account is created by email/password:
   email confirmation (or a provider/magic-link that verifies itself). "Enter
   any email and you are in" is a hole. If there is no registration (OAuth/
   magic-link only) — record that as a deliberate fact, do not skip.
4. **Zero secrets/admin-keys in the client bundle** [SEC-2]: check
   `grep NEXT_PUBLIC_` (or the harness equivalent) — only public ids/keys
   there; DB/admin — server-side only. Confirm explicitly at review.
5. **Access control on the server** [SEC-4][ACCT-1/2]: an IDOR filter by
   owner, the rights check close to the data, not "hid the button".

**Wider than the baseline — the attacker perspective.** These 5 are the
hygiene minimum. The full base of forbidden scenarios and bypass methods (by
the AUTH/RATE/AUTHZ/INPUT/BUSINESS-LOGIC/CLIENT-TRUST categories, with a
countermeasure and a test hook, cross-project) →
`reference_abuse_cases.md`. Spec reflex: for each AC ask "how to break it?"
→ a loophole into a negative AC/NFR + a test. A new vector → append to the
base (the loop, same as §6/§8).

---

## 8. Maintenance (against staleness and misclassification)
- **Catalog revision** roughly every 3–6 months (like the infra-audit skill):
  best-practice freshness, dead rules, new typical situations.
- **Verify the profile against the real code**, not declaratively (a
  forgotten flag = a silently dropped check block).
- **Focused research → into the catalog** (the §6 loop).
- **Adoption on existing code** as a separate task/session; new projects —
  with a profile from the start. On existing code, linters in "only choke the
  new" mode; mass cleanup is separate.
