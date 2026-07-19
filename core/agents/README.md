# Agents

A **capability** (research, qa, code-review, security-arch, …) is know-how that
lives ONCE, harness-neutral. How a harness REALISES it varies:

- **Claude Code** (and any harness with typed sub-agents) → renders each
  `<name>.md` + its `registry.yaml` binding into an agent file the main agent
  dispatches by name.
- **A general-purpose-only harness** (no typed sub-agents) → the capability is
  realised by the matching **skill** (`core/skills/<name>/SKILL.md`) loaded into
  a `general-purpose` dispatch.
- **A vendor-specific capability** (`affinity: claude-only`, e.g.
  harness-docs) is inert on other harnesses — replaced by the harness's own
  equivalent.

## Layout

- `<name>.md` — the prompt body (harness-neutral know-how). `${VARS}` for
  harness-specific values.
- `registry.yaml` — the neutral binding per capability:
  `model_tier` (fast/mid/heavy), `tools` (capability set),
  `affinity` (any / claude-only), `skill_link` (the fallback realisation).

## Why body + binding split

The body is the **know-how** (write once, reuse everywhere); the binding is
**per-harness plumbing** (concrete model id, concrete tool ids). Mixing them
couples know-how to one harness. The registry lets a harness render the same
capability into its own shape without touching the body.

## How a harness maps a tier

`model_tier` → a concrete model id at deploy time, per the adapter. Examples
(not prescriptive — the adapter decides):

- `fast` → haiku-class (cheap, high-volume)
- `mid` → sonnet-class (the workhorse)
- `heavy` → opus-class (reserved for hard judgment)

## The ×3 review pipeline

For changes with logic, three independent reviewer agents run, results merged:
`code-reviewer` (quality/architecture) + `security-arch` (security) + `qa`
(tests). They are deliberately context-free — they judge on the code's own
merits. `security-deps` is a separate pre-deploy gate. See `playbook.md`
§ Agent triggers and § Agent-driven verification outcomes.

## Verifying agents

- **Structural** — frontmatter/binding resolves, `${VARS}` resolve, tools map
  to the target harness's tool ids.
- **Functional** — the agent's return contract holds under a realistic
  dispatch (the `infra-audit` skill covers this on its cadence).
