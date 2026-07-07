---
name: research
description: "Dispatch a research sub-agent for broad investigation — strategy, technologies, market, architecture options, legal questions. The sub-agent is the ONLY one with web access; all other agents route web work through it. Answer comes back caveman-compressed if SUBAGENT_COMPRESSION is on."
---

# research — dispatcher

Broad investigation: strategy, technologies, market, architecture options,
legal questions. This agent is the **single point of web access** — other
agents that need the web route through it (see playbook § Token economy).

## When to dispatch

- A broad topic needs depth beyond what's in memory.
- An open question surfaced during planning (add Council-framing → council
  skill).
- A legal-review trigger fired (playbook § Agent triggers): collecting new
  personal data, new third parties with data access, new cookies/tracking,
  new monetization/payment, features where the user creates/publishes/uploads
  content.

## What the sub-agent does NOT do
- It does not write code.
- It does not make product decisions — it surfaces options with tradeoffs.

## How to dispatch

Call the Agent/Task tool with the prompt below, filling in `[TOPIC]` and the
optional `[COUNCIL-FRAMING]` block. Use a capable model. If the agent returns
an open question, re-dispatch with the narrowed scope (do not have it flail).

```
description: "Research: [TOPIC]"
prompt: |
  You are a research agent. Investigate [TOPIC].

  Tools available: WebSearch, WebFetch, Read, Glob, Grep.

  Method:
  - Do NOT answer from memory. Every non-trivial claim cites a source.
  - Up to 3 retrieval attempts per sub-question; if you cannot source it,
    say "UNSOURCED" and move on.
  - Surface 2-3 viable options with concrete tradeoffs, not a single
    recommendation, unless one is clearly dominant (then say why).

  Output (caveman-compressed if instructed):
  - TL;DR (1-2 lines)
  - Findings — one per line, each with a source link
  - Options + tradeoffs (if applicable)
  - Open questions for the user
  - Sources (deduped)

  [COUNCIL-FRAMING] (optional):
  Analyze the topic through five roles:
  1. Contrarian: attacks weak assumptions
  2. First-principles thinker: finds the real problem
  3. Expansionist: looks for hidden x10 potential
  4. Outsider: a fresh view with no project context
  5. Executor: concrete steps for the next 24 hours
  Then Chairman: VERDICT / BLIND SPOT / CONFIDENCE.
```

## After the sub-agent returns

- Save the result to the doc backend as a research sub-page (playbook §
  Saving research): with a project → that project's "Research" container;
  without → "Research (no project)".
- If open questions remain → grill-me or another research round, not a guess.
