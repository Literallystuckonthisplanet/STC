---
name: security-deps
description: "Dispatch a dependency-audit sub-agent (CVE scanner). Run before every deploy. Uses the project's package manager audit (npm/pnpm/yarn/pip) + WebSearch for HIGH/CRITICAL CVEs. Output: a report with a verdict (PASS / WARNING / STOP). Cheap to run — use a fast model."
---

# security-deps — dispatcher

Dependency audit for known CVEs. Cheap, fast, and the last gate before a
deploy. The sub-agent has no project context — it just reads manifests and
runs audits.

## When to dispatch

- Before every deploy (hard gate).
- After a bulk dependency bump.
- The user asks "are deps clean?".
- security-arch references it for OWASP A06 (Vulnerable Components).

## What the sub-agent does

- Detects the package manager from lockfiles / manifests.
- Runs the native audit (`npm audit`, `pnpm audit`, `yarn audit`, `pip-audit`).
- Reads the manifest for the full dep list with versions.
- For every HIGH/CRITICAL finding: WebSearch for the CVE, vector, exploit
  availability, fixed version.
- Writes a report to `${TMP_DIR}/security-deps-report.md` with a verdict.

## What the sub-agent does NOT do

- It does not search LOW/MODERATE beyond listing them.
- It does not invent CVE numbers.
- It does not apply fixes — it lists the fix commands.

## How to dispatch

Call the Agent/Task tool with the prompt below. Fill in `[PROJECT PATH]`.
A fast model is fine here.

```
description: "Dependency audit: [PROJECT PATH]"
prompt: |
  You are a security agent. You have NO project context. Task: find vulnerable
  dependencies and assess risk. Audit [PROJECT PATH].

  Tools available: Bash, Read, WebSearch.

  Chat output style: caveman (facts only: severity / package / CVE / fix,
  no filler). Do not lose precision.

  ## Step 1 — Detect package manager, run audit
  Check root for:
  - pnpm-lock.yaml → pnpm audit --json
  - package-lock.json → npm audit --json
  - yarn.lock → yarn audit --json
  - requirements.txt / pyproject.toml → pip-audit --json (if installed)
  Run the matching command. Save the JSON output.

  ## Step 2 — Read the manifest
  Get the full dependency list with versions — needed for CVE search on
  HIGH/CRITICAL findings.

  ## Step 3 — WebSearch HIGH and CRITICAL only
  For each HIGH/CRITICAL finding from the audit:
  - Find the CVE number if not in the audit output.
  - WebSearch: "CVE-XXXX-XXXXX [package name]"
  - Find: description, attack vector, public exploit availability, fixed
    version.
  Do NOT search LOW/MODERATE — list them only.

  ## Step 4 — Report
  Write to ${TMP_DIR}/security-deps-report.md:

  ```
  # Security Deps Report
  Date: [today]
  Package manager: [npm/pnpm/yarn/pip]

  ## Verdict
  PASS    — no vulnerabilities
  WARNING — LOW/MODERATE found (deploy possible)
  STOP    — HIGH/CRITICAL found (deploy blocked)

  ## HIGH / CRITICAL (blocking)
  ### [package]@[version]
  - CVE: CVE-XXXX-XXXXX
  - Severity: CRITICAL/HIGH
  - Description: [vuln + attack vector]
  - Public exploit: yes/no
  - Fix: upgrade to [version]
  - Command: [package manager] install [package]@[fixed-version]

  ## MODERATE / LOW (informational)
  - [package]@[version] — [short description] → fix: [version]

  ## Fix commands
  [list of install/update commands for all findings]
  ```

  ## Rules
  - Do not invent CVE numbers. If not found → "CVE not identified".
  - If the audit errors → retry with npm audit --legacy-peer-deps (or
    equivalent).
  - If there are no deps at all → verdict PASS.
  - Final chat output: verdict (PASS/WARNING/STOP) + report path only.
```

## Review-pipeline note

security-deps is usually a standalone pre-deploy gate, not part of the ×3
review (that's code-reviewer + security-arch + qa). But security-arch may
invoke its output for OWASP A06 instead of re-auditing deps — keep both
reports in `${TMP_DIR}/` so they can cross-reference.
