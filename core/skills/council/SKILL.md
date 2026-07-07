---
name: council
description: "Use for a large task (before Plan step 4, automatically), or a medium task with uncertainty (offer to run), or to frame a research agent. Runs the question through five critic roles, then a Chairman summary."
---

# Council
<!-- S16 -->

A multi-role deliberation: run a question or task through five critic roles
sequentially, then the Chairman sums up. The result becomes the basis for a
plan or an agent prompt.

## When to apply

| Situation | Action |
|---|---|
| **Large task** | Run before Plan step 4, automatically, without asking |
| **Medium task + uncertainty** (criteria below) / "let's ask the council" | Offer to the user ("run it through the Council?"), run if they agree |
| **Research agent (open question)** | Add Council-framing to the agent prompt |

**What counts as "uncertainty" (≥1 point → offer Council):**
1. You see ≥2 viable approaches with no clear winner.
2. The decision is hard to reverse: a DB schema, an external contract/API,
   money, a data migration.
3. An unfamiliar domain/stack where your confidence is low.

(Lack of facts does not belong here — close that with research/grill-me, not
the Council. Inventing facts is always forbidden → `pev.md` § Step 2.)

## Council ↔ grill-me — order on a large task

These are different tools, not interchangeable:
- **grill-me** — an interview of the user: extracts decisions down a tree,
  removes ambiguity (convergent, needs dialogue). Useful when there are ≥3
  open branches only the user can answer.
- **Council** — your own run through five critic roles: generates perspectives
  and blind spots (divergent, the user not needed).

**Pipeline:** `grill-me` (extract decisions from the user) → `Council`
(critique the worked-out direction) → plan. Council on a large task is
automatic; grill-me is offered if there are open product branches.

## How to apply

Run the question/task through the five roles in sequence, then the Chairman
sums up.

## Roles

**1. Contrarian** — attacks the weakest part of the assumption or problem
statement.

**2. First-principles thinker** — ignores the framing, digs down to the real
problem.

**3. Expansionist** — looks for hidden ×10 potential: what if the scale is
bigger than it seems?

**4. Outsider** — a fresh view: what does someone with no context of this
project see?

**5. Executor** — concrete steps for the next 24 hours, no abstractions.

## Chairman (summary)

After the five voices:
- **VERDICT** — the final verdict
- **BLIND SPOT** — a blind spot none of the five noticed
- **CONFIDENCE** — confidence level (0–100%)

## Council-framing for a research agent

Add this block to the agent prompt:

```
Analyze the topic through five roles:
1. Contrarian: attacks weak assumptions
2. First-principles thinker: finds the real problem
3. Expansionist: looks for hidden x10 potential
4. Outsider: a fresh view with no project context
5. Executor: concrete steps for the next 24 hours

Then Chairman: VERDICT / BLIND SPOT / CONFIDENCE.
```
