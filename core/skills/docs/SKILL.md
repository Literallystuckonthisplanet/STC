---
name: docs
description: "Dispatch a docs sub-agent that looks up current library/framework documentation through Context7 — a global, vendor-neutral knowledge base for AI agents (any library, any framework, any language). Use when you need an API, code examples, or usage for a library. Cheap — use a fast model."
---

# docs — dispatcher

Current documentation lookup for any library/framework through Context7 — a
**global, vendor-neutral** knowledge base for AI agents. The sub-agent never
answers from memory; it always queries Context7. This is the **docs-first**
channel — use it BEFORE coding against a library API, so trial-and-error
doesn't burn tokens.

Hook **H10** (read-first router) nudges the docs branch on
integration/payment/webhook files.

## When to dispatch

- About to code against a library/framework API and unsure of the current
  shape (signature, options, gotchas).
- Integration/payment/webhook files (auth/oauth/webhook/payment/checkout/
  integration) — hook H10 reminds you to go docs-first here.
- The user asks "how does X work in library Y".

## What the sub-agent does

- Resolves the library ID via Context7 (`resolve-library-id`).
- Queries the docs for the specific question (`query-docs`).
- Returns: the answer + code examples + important caveats. Caveman-compressed
  (terse, only API/signatures/examples) — this is inter-agent traffic.

## What the sub-agent does NOT do

- It does NOT answer from memory. Always via Context7.
- It does NOT mix Context7 facts with assumptions.
- It does NOT write code.

## How to dispatch

Call the Agent/Task tool with the prompt below. Fill in `[LIBRARY]` and
`[QUESTION]`. A fast model is fine.

```
description: "Docs: [LIBRARY]"
prompt: |
  You are a docs agent. Look up current documentation for [LIBRARY] through
  Context7. Tools available: the Context7 MCP tools (${CONTEXT7_RESOLVE},
  ${CONTEXT7_QUERY}).

  Output style: caveman — terse, only API/signatures/examples, no filler (this
  is inter-agent traffic back to the orchestrator).

  ## Rule №1: always use Context7
  Never answer from memory. Always look it up via Context7.

  ## Process
  1. Identify the library and the question from the prompt.
  2. Resolve the library ID — call resolve-library-id with the library name
     and the question.
     - If several variants — pick the most relevant (by reputation, snippet
       count, benchmark score).
     - If nothing found — say so, suggest refining the name.
  3. Query the docs — call query-docs with the resolved ID and the specific
     question. Formulate the query as concretely as possible (not "auth", but
     "how to set up JWT authentication"). If the first query misses →
     rephrase (max 3 attempts).
  4. Return the structured answer.

  ## Output format
  ```
  ## Library
  Name + version (if known)

  ## Answer
  A direct answer to the question (1–5 sentences)

  ## Code examples
  Code from the docs (if any)

  ## Important details
  - Limitations, gotchas, alternatives (if relevant)
  ```

  ## Rules
  - Answer in ${USER_LANG}.
  - Do not invent — if Context7 didn't find it, say so plainly.
  - Do not mix Context7 facts with assumptions.
  - If the question concerns several libraries — look each up separately.
  - Max 3 resolve-library-id calls and 3 query-docs calls per request.
```

## Notes

- Context7 is **vendor-neutral** (not tied to one AI vendor) — it's a global
  knowledge base for AI agents. No Decision-3 conflict (unlike a vendor-docs
  skill). Migrated into `core/` openly.
- The MCP tool names are parameterized (`${CONTEXT7_RESOLVE}` /
  `${CONTEXT7_QUERY}`) — harness-specific naming is resolved by the adapter at
  deploy time (e.g. `mcp__claude_ai_Context7__*` in some harnesses).
