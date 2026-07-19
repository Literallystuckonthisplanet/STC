<!-- T01 -->

# New project kickoff template

## Principles

1. **One session = one block.** Finish a block → get approval → open a new
   session.
2. **Instruction file** (`${INSTRUCTIONS_FILE}`) — architecture, rules, stack.
   Read every session.
3. **Memory** — facts, credentials, decisions. Saved immediately on receipt.
4. **Sub-agents** — isolated features. Not suited for cross-system tasks.

---

## Phase 0 — Kickoff (before the first line of code)

**Done in one session, together:**
- [ ] Product description: what, for whom, what constraints
- [ ] Stack: language, frameworks, DB, hosting, external services
- [ ] Domain and infrastructure (where it lives, how it deploys)
- [ ] **Deploy script:** the moment the project gets a deployment target, the
      FIRST step is `deploy/deploy.sh` built from the pattern (dry-run, confirm,
      local build, rollback) — deploying without the script does not start (I08)
- [ ] List of external APIs/services to connect
- [ ] Block plan (see below)
- [ ] **Design system:** classify project type → instantiate `DESIGN.md` from
      the template + overlay (see § Design system below)
- [ ] Create the instruction file in the repo

**Result:** instruction file + an agreed plan.

> **Stack is per-project, decided here.** There is no global default stack —
> each project chooses its own at Phase 0.

---

## Block plan (example structure)

```
Block 1: Infrastructure (1 session)
  - repo, Docker/DB, env files, base stack
  - ready when: `pnpm dev` (or equivalent) runs

Block 2: Data and CMS (1–2 sessions)
  - DB schema, collections/models, seed/import data
  - ready when: data is in the DB, admin works

Block 3: Core UI (1–2 sessions)
  - routing, pages, components
  - ready when: the golden path (home → catalog → item) works

Block 4: Business logic (1–2 sessions)
  - cart, orders, payment, email
  - ready when: a test order passes end-to-end

Block 5: Auth (1 session)
  - providers, roles, protected routes
  - ready when: login/logout, account page

Block 6: Integrations (1 session each)
  - third-party services (shipping, analytics, CRM…)
  - ready when: integration tested in isolation

Block 7: SEO + Production (1 session)
  - sitemap, robots, OG, performance
  - deploy to staging → smoke test → deploy to prod
```

Every block has a **readiness criterion**. Don't move on without it.

---

## Design system (project-type-aware)

Before generating UI (Phase 0 / before the UI block):
1. **Classify the project type:** landing / e-commerce / saas-app / admin /
   content-docs → see `core/templates/design-system/process.md` §2.
2. **Instantiate `DESIGN.md`:** copy
   `core/templates/design-system/DESIGN.template.md` to the repo root → fill
   the 9 sections + overlay elements for your type.
3. **Set up tokens** Tier 1+2 in Tailwind `@theme` (palette/fonts/spacing
   scale) — do NOT leave stock shadcn + Inter.

Full taxonomy / token model / tooling → `process.md`. Anti-generic + brief
structure → `DESIGN.template.md`. Plan/Verify flow → `[[playbook]]` § Design
system.

---

## Instruction file — minimal structure

```markdown
# ${HARNESS_NAME} — [Project name]

## Local dev
[commands to run]

## Stack
[stack in one paragraph]

## Project structure
[folder tree]

## Critical rules
[MUST-NOT-DO — the most important constraints]

## Database
[ORM/tables, what not to touch]

## Auth
[providers, strategy, edge/node split]

## External services
[which APIs, where credentials live]

## Design system
[project type: landing/e-commerce/saas-app/admin/content-docs; details in DESIGN.md at root]

## MVP status
[table: Feature | Status]

## Worktree agents
For worktree agents — read before working:
${MEMORY_DIR}/pev.md
${MEMORY_DIR}/behavior.md
```

---

## What to save to memory immediately

| What you got | Where |
|---|---|
| API key / secret | 1) `.env.local` 2) memory credentials |
| Architectural decision ("chose X because Y") | memory project |
| Rule / prohibition ("don't do this, we got burned") | memory feedback |
| External link (dashboard, tracker, doc backend) | memory reference |

Rule: **got it → saved it → continued**. Not "I'll save it at the end."

---

## Slicing into sub-agents (part of planning)

When composing the plan, each task gets a tag:

- `[agent]` — sub-agent in a worktree (isolated branch, separate context)
- `[main]` — main session only

Criteria for `[agent]` vs `[main]` and the `Exec` field in the task tracker →
`[[pev]]` § Step 4. The tagging is only needed for parallel work via worktrees.

**How `[agent]` works with a worktree:**
```
orchestrator → Agent(isolation="worktree", prompt="implement X per the spec in the instruction file")
                       ↓
               sub-agent reads the repo files
               makes changes in a separate git branch
                       ↓
               orchestrator gets: "done, branch feature/X"
               git merge → done
```

Parallel `[agent]` tasks launch simultaneously — saves time and context. See
the `worktree` skill for the full worktree discipline.

---

## Security processes

The canonical triggers live in `[[playbook]]` § Agent triggers (not
duplicated here):
- before merging sensitive areas (auth / API / upload / PII / raw SQL / CORS
  / secrets) → **security-arch**;
- before every deploy → **security-deps** (`pnpm audit` / `pip-audit`),
  HIGH/CRITICAL → stop.

## Session checklist (start of every session)

1. Read the instruction file — refresh context.
2. Ask: "what was done last session?" (or read memory).
3. Agree on the current session's goal (one block, or part of one).
4. Agree on the readiness criterion.

## Session checklist (end of session)

1. Check the readiness criterion.
2. Save everything important to memory.
3. Update the instruction file if the architecture changed.
4. Run `${COMPACT_CMD}` manually.
5. Get approval → open a new session.
