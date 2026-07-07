---
name: e2e
description: "Dispatch an end-to-end test sub-agent that drives a live app through a browser (Playwright MCP). Run after meaningful changes or before a deploy. Requires a running dev server. The methodology + scenario taxonomy lives here; CONCRETE SCENARIOS PER PROJECT live in user/projects/<name>.md. Returns a PASS/FAIL table."
---

# e2e — dispatcher

End-to-end testing of a live app through a real browser. This file holds the
**methodology and the scenario taxonomy**. The **concrete scenario list for a
given project** lives in `user/projects/<name>.md` — without it the sub-agent
tests only the generic taxonomy below.

## When to dispatch

- After meaningful UI/flow changes.
- Before a deploy (pairs with security-deps as the pre-deploy gate).
- The user asks "run e2e" / "test the app".

## Prerequisites

- A running dev server at `${DEV_URL}` (default `http://localhost:${DEV_PORT}`).
  The sub-agent checks first with a curl; if not 200, it stops and says so.
- The Playwright MCP browser tools available to the sub-agent.
- A scenario list. If `user/projects/<name>.md` defines one → use it. If not →
  the sub-agent builds one from the generic taxonomy below + a quick recon of
  the actual routes, and confirms it with the user before running.

## Scenario taxonomy (generic)

Every project's scenario list is an instance of this taxonomy. Not every
category applies to every project — drop what doesn't.

- **Catalog & navigation** — home loads, primary listing shows items,
  search/filter works, detail view opens, key elements present on the detail
  view, secondary pages (wishlist, favorites) open, add-to-favorites works.
- **Cart** — add to cart (with variant selection if applicable), header
  counter updates, cart page opens, quantity change, remove item, cart
  persists across reload (localStorage or equivalent).
- **Checkout** — enter checkout with items, form renders, validation on empty
  submit, third-party widgets load (shipping, payment), fill with test data,
  submit button enables, redirect to payment provider or success page (don't
  complete the real payment).
- **Authentication** — login page opens, form renders, invalid credentials
  show an error, third-party login buttons present and clickable (don't follow
  the redirect), magic-link / alternative flows present.
- **Account (auth required)** — protected route redirects to login when
  unauthenticated, credentials login succeeds, account page renders user
  info, history/orders section renders (or empty-state), logout works and
  clears the session.
- **Static pages** — about, privacy, terms, refund policy, etc. open without
  errors.
- **Third-party widgets** — community/social widgets present, don't block
  primary content.
- **Technical checks** — no critical console errors on key pages, 404 page
  renders for unknown URLs.
- **Corner cases** — cart cleared on storage wipe, protected/empty-state
  fallbacks (no crash), unknown slugs → 404 or not-found, very long inputs
  don't crash, double-click on primary actions handled.

## What the sub-agent does

- Verifies the dev server is up; if not, stops and says "start the server".
- Loads the scenario list (from `user/projects/<name>.md` or builds one).
- Walks every scenario end to end through the browser, recording PASS/FAIL
  with a short reason on FAIL.
- Cleans up state after auth scenarios (logout so no session lingers).
- Flags any test orders / created data with an ID so they can be removed.
- Saves FAIL screenshots to `${TMP_DIR}/e2e-screenshots/`.

## What the sub-agent does NOT do

- It does not modify source code.
- It does not complete real payments — only checks the redirect.
- It does not dump every step's HTML into chat — only the table and FAIL
  details.

## How to dispatch

Call the Agent/Task tool with the prompt below. Fill in `[PROJECT NAME]`,
`[DEV URL]`, and `[SCENARIO FILE]` (or `none`). Use a capable model — browser
driving is fiddly.

```
description: "E2E: [PROJECT NAME]"
prompt: |
  You are a QA agent with NO project context. You test a live app through a
  browser at [DEV URL].

  Tools available: Bash, Read, Glob, and the Playwright MCP browser tools
  (navigate, snapshot, click, fill_form, type, wait_for, take_screenshot,
  evaluate, press_key, select_option, navigate_back, tabs).

  ## Step 0 — Server check
  curl -s -o /dev/null -w "%{http_code}" [DEV URL]  → must be 200.
  If not → say "start the dev server" and stop.

  ## Step 1 — Load scenarios
  If [SCENARIO FILE] is not "none" → read it, use its scenario list verbatim.
  If "none" → do a quick recon (visit [DEV URL], snapshot, list routes you can
  see), build a scenario list from the e2e taxonomy, and CONFIRM it with the
  user before running.

  ## Step 2 — Run every scenario end to end
  Walk each scenario fully through the browser. Record PASS/FAIL + a short
  reason on FAIL. Take a screenshot on FAIL.

  ## Step 3 — Cleanup
  - After any auth scenario that logged in → log out, so no session lingers.
  - If a test order / data was created → note its ID in the report so it can
    be removed manually.

  ## Output (chat)
  ```
  ## E2E Report — [date]

  ### Verdict: X/Y PASS (Z FAIL)

  | ID | Scenario | Status |
  |---|---|---|
  | CAT-01 | Home → listing | PASS |
  | CHK-07 | Redirect to payment | FAIL — no redirect, page hung |
  ...

  ### FAIL details
  **CHK-07**: [what happened, URL at the point of failure]

  ### Test data created
  - Order #12345 (delete manually)

  ### Screenshots
  Saved to ${TMP_DIR}/e2e-screenshots/ (on FAIL)
  ```

  Do NOT dump per-step HTML / intermediate states into chat. Table + FAIL
  details only.
```

## Per-project scenarios

The taxonomy above is the skeleton. A real project needs a concrete list —
that lives in `user/projects/<name>.md` (e.g. `user/projects/forest-echoes.md`)
with literal IDs (CAT-01, CHK-07, …), literal test data, and literal routes.
The dispatcher reads that file at run time; without it, only the generic
taxonomy is tested.
