# Failure-modes catalog (typical pitfalls + solutions, per use-case)
<!-- R01 -->

A reference catalog. Not loaded into always-context; read when writing a
spec for EACH use-case, and as a debug-reflex before any edit to business
logic.

**The idea.** Pitfalls cannot be caught by trial-and-error along the way —
they must be **known in advance and laid down at design time**, exactly as
negative AC and security NFRs. **The scope is all business logic, not only
integrations:** an ordinary scenario — password authentication, "add to
cart" — has its own failure-modes too. Tied to a **use-case**, not to a
technology/file. Symmetrical to `reference_abuse_cases.md`: there it is
"how they will break it" (abuse), here it is "where it will
stall/break" (failure) — both are enumerated for EACH spec use-case.

Connected: `reference_defect_ledger.md` (a caught defect → a row here,
design-time prevention) · `reference_abuse_cases.md` (the sibling, the
abuse angle) · PEV (the Plan phase).

## When to read / populate
- **The spec (the main layer): on EACH use-case** enumerate its
  failure-modes + abuse-cases (as AC/NFR). The hook on the file path is
  only a coarse backstop — it does not know the use-case.
- **Debug-reflex (universal, no own/third-party split):** on any bug —
  first the authoritative source/contract (library docs, the API spec,
  the module's own contract), then the edit. Not a trial of symptomatic
  patches.
- **Population:** each caught defect from `reference_defect_ledger.md` → a
  row under the corresponding use-case.

## Format

Grouped by **use-case** (a business scenario). Inside:
`symptom → cause → solution/pattern → how to verify`.

## The registry (by use-case)

<!--
Seed with your own project's use-cases. One use-case can have several
failure-mode rows. Example shape:

### Checkout · choosing a pickup-point on a map widget
- **Symptom:** choosing the map option freezes the page for several seconds.
  - **Cause:** mounting the widget immediately initialises a heavy map with
    all points.
  - **Solution:** lazy-mount — initialise the map ONLY on an explicit click
    "choose on map", not on selecting the radio.
  - **Verify:** an e2e run — select the map option → a point → switch the
    method → re-select the map: the map loads without a reload, 0 console
    errors, the page is clickable throughout.
-->

### Yandex Cloud Foundation Models (YandexGPT) · connection
- **Symptom:** `403 "Permission to [resource-manager.folder …, cloud …,
  organization …] denied"` calling `/foundationModels/v1/completion`, even
  though the service account has the `ai.languageModels.user` role on the
  right folder, the key belongs to the right SA, and the scope
  (`yc.ai.foundationModels.execute`) all look correct.
  - **Cause:** the cloud's billing account is not active. Foundation Models
    is a paid service; without active billing it returns an IAM-shaped 403
    that looks identical to a real permissions problem.
  - **Solution:** on a 403 with correct-looking IAM, check billing status
    FIRST (console → billing → payment account = ACTIVE) before chasing
    roles/SA/keys.
  - **Verify:** the same key/folder returns 200 right after billing is
    activated.
- **Symptom:** `400 "Specified folder ID X does not match with service
  account folder ID Y"`.
  - **Cause:** with Api-Key auth, the folder in `modelUri=gpt://<folder>/…`
    must equal the home folder of the key's own service account — not just
    any folder where a role was granted.
  - **Solution:** use the folder named in the error (= the key's home SA
    folder), or mint a new key on the SA whose home folder is the one you
    need. A key ID does not reveal which SA it belongs to via Api-Key
    introspection — check the console (or use a Bearer token) to confirm.
- **Symptom:** `400 grpcCode=3 "Invalid JSON Schema: all fields must be
  required, '<field>' is optional"` when requesting structured output
  (`json_schema`).
  - **Cause:** Yandex's strict structured-output mode requires ALL fields to
    be listed in `required`; an `optional` field is rejected outright.
  - **Solution:** express optionality as **nullable**, not optional — e.g.
    `type: ['string', 'null']` or an enum that includes `null`, plus
    `additionalProperties: false`. Parse the response with a nullable-aware
    schema (e.g. zod `.nullish()`), since the model sends explicit `null`
    for empty fields.
  - **Verify:** a request built with a nullable schema returns 200; empty
    fields come back as `null`, not omitted.

### Email/OAuth login (Auth.js behind an nginx reverse proxy)
- **Symptom:** auth-email links / OAuth redirect URLs point at
  `https://localhost:<port>` (client sees a TLS handshake error following
  the link) even though the site itself loads fine over the real domain.
  - **Cause:** a certbot-generated nginx config sets `Host` and
    `X-Forwarded-Proto` but **not** `X-Forwarded-Host`. Without it, Auth.js
    v5 (even with `trustHost` set) falls back to the listen host
    (`localhost:<port>`) combined with the forwarded proto for building
    absolute URLs.
  - **Solution (both ends required):** set `AUTH_URL=https://<app-domain>`
    in the production env, AND add `proxy_set_header X-Forwarded-Host
    $host;` to the nginx config.
  - **Verify:** one request right after deploy —
    `curl https://<app-domain>/api/auth/providers` — `signinUrl` and
    `callbackUrl` in the response should show the app domain, never
    localhost.

*(add more use-cases here as you spec and debug them)*
