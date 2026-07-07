# Abuse-case catalog (forbidden scenarios / bypass vectors)

A reference catalog. Not loaded into always-context; read when writing a
spec/AC/test-cases for any S1+ project, and during a security pass.

**The idea.** Edge cases and security cannot be "remembered" fresh each
time. When writing AC/test-cases (better already in NFRs), pose the question
**from an attacker's perspective: how to bypass this scenario / access
restriction / limit?** Each such scenario is dissected, the loophole is
closed — and **saved here**, to reuse across projects, not reinvent.

**How to use:**
- **Spec/AC (`to-spec`):** for each significant AC, run the reflex "how to
  break it?" against the applicable categories below → turn loopholes into
  negative AC and NFR points. Pairs with `code_standard.md` §9 (the
  security baseline in AC).
- **Test-cases:** each dissected vector → a negative test-case (the hook in
  the "Test" column).
- **Security pass:** the `security-arch` agent runs this list against the
  project profile (flags ACCT/API/UGC/PII/MONEY) as a checklist.
- **Loop:** found a new vector in a project → append here (grow the asset).
  A defect-class repeat → `reference_defect_ledger.md`.

## Categories (profile flag → applicability)

Format: **bypass scenario → countermeasure → test-case hook.**

### 🔐 AUTH — authentication (flag ACCT)
- **Reset/magic-link/OTP flooding** (mail-bombing the victim + provider
  cost) → rate-limit per-email + per-IP, cooldown, daily cap; token
  one-time-use + TTL → *test: 10× reset requests on one email in a minute =
  block after N.*
- **Account enumeration** (different answer/timing on "user exists") → a
  uniform answer and timing for existing/non-existing; do not reveal in
  reset/login/register → *test: the answer and latency on a known vs
  unknown email are identical.*
- **Credential stuffing / brute force** → rate-limit + exponential
  backoff + captcha after a threshold; prefer a provider/magic-link →
  *test: a series of wrong passwords → block/challenge.*
- **Session fixation / token theft** → session rotation on login;
  httpOnly+Secure+SameSite cookies; PKCE on OAuth → *test: a pre-login
  token is invalid after login.*

### 🚦 RATE / SPAM — spam and limit abuse (flags ACCT/API/UGC/MONEY)
- **Spam order/resource creation** (a bot floods fakes → trash in DB/
  notifications, oversell) → rate-limit per-IP+per-session on the create
  endpoint; idempotency (request key); honeypot field; captcha on anomaly
  → *test: 50× create in a minute from one IP = throttle.*
- **Paid proxy-token drain** (a third-party token proxied through your
  backend) → a limit on the proxy endpoint; a click-gate (load on action);
  origin check → *test: a direct hammer on the proxy route = throttle.*
- **Two limiter layers:** app-level (per-endpoint, in-memory on
  single-instance) + edge (Nginx `limit_req`/`limit_conn` — anti-DDoS
  before the runtime, especially on a weak VPS).

### 🔓 AUTHZ — authorization and access (flags ACCT/PII)
- **IDOR** (changed id in URL/body → someone else's resource) → an
  owner-filter close to the data, not "hid the button"; check on the
  server always → *test: user A requests `/orders/{B_id}` = 403/404.*
- **Privilege escalation** (a customer session hits an admin endpoint) →
  one authority per role ([ARCH-6]); do not gate the admin via an email
  allowlist → *test: a customer session on `/api/admin/*` = deny.*
- **Mass-assignment** (extra fields in the body → `isAdmin:true`,
  `price:0`) → an explicit field whitelist (zod schema), do not trust the
  whole body → *test: a POST with `role`/`price` in the body is ignored.*

### 💉 INPUT — injections and input (any web, flag API/UGC)
- **SQL/NoSQL/command injection** → parameterized queries (ORM), no
  concatenation; type validation → *test: `'; DROP`/`$ne` in fields does
  not break.*
- **XSS** (UGC/reviews/name in an email) → escape on output, CSP, no
  `dangerouslySetInnerHTML` on user content → *test: `<script>` in a
  review renders as text.*
- **SSRF** (user/agent passes a URL → the backend fetches it internally →
  access to localhost, the private network, **cloud-metadata
  `169.254.169.254`** = IAM-cred theft) → **resolve-then-check**: resolve
  DNS and check the FINAL IP (not the string — otherwise a DNS-rebinding
  bypass); block-lists: `127.0.0.0/8`+`localhost`, RFC1918, link-local
  `169.254.0.0/16` (incl. metadata), `0.0.0.0`, IPv6 `::1`/`fc00::/7`/
  `fe80::/10`; allowlist schemes (`http(s)` only); **block redirects into
  private networks** (check every hop, not only the first); catch
  octal/hex/decimal IP bypasses; block `file://`/`gopher://`/`dict://`.
  **Do not write a filter by hand — take a ready library** (Node
  `ssrf-req-filter`, Python `ssrfcheck`). → *tests: a URL on
  `169.254.169.254`, `localhost`, `10.x`, and a public→private redirect —
  all rejected.*
- **File-upload abuse** (flag FILE: type/size/polyglot/path-traversal) →
  MIME + magic-byte check, size limit, random name outside webroot →
  *test: a .php disguised as .jpg is rejected.*

### 💰 BUSINESS-LOGIC — logic and money (flag MONEY)
- **Price/amount manipulation** (price from the client, negative quantity,
  discount >100%) → the price/total is computed ONLY on the server from
  the DB; qty≥1; the coupon is validated server-side → *test: an order
  with `price` in the body ignores it; qty=-1 is rejected.*
- **Oversell / a stock race** (parallel orders on the last item) → an
  atomic decrement/reserve in a transaction, a stock check on payment →
  *test: 2 parallel orders on 1 item → one is rejected.*
- **Double payment / webhook replay** → idempotency by a custom key; webhook
  signature verification; an order state-machine → *test: a repeated PAID
  webhook does not duplicate.*
- **Refund/cancel abuse** → cancel rights to the owner only; a window/
  status-gate; logging → *test: canceling someone else's / a paid order =
  deny.*

### 🖥 CLIENT-TRUST — trusting the client (flag SEC, any S1+)
- **Secrets/admin-keys in the bundle** → `grep NEXT_PUBLIC_` = only public
  ids; DB/admin server-only → *test: the bundle contains no secrets.*
- **Client-only validation** → a server schema is mandatory, the frontend
  is UX → *test: a request bypassing the UI with broken data is rejected
  by the server.*
- **"Hid the button" = access control** → access is decided on the server,
  not by visibility in the UI → *see AUTHZ/IDOR.*

## Profile → starter category set

| Flag | Categories |
|---|---|
| ACCT (accounts) | AUTH, RATE, AUTHZ, CLIENT-TRUST |
| API (integrations/public) | RATE, INPUT, CLIENT-TRUST |
| UGC (content) | RATE, INPUT(XSS), AUTHZ |
| PII (personal data) | AUTHZ, CLIENT-TRUST + code_standard §9 baseline |
| MONEY (payments) | BUSINESS-LOGIC, AUTHZ, RATE |

<!--
Extend per project. New vectors discovered during a security pass or a
caught defect → append to the relevant category (the loop, same as
code_standard §6/§8).
-->
