---
description: "Compact the current conversation into a handoff document for another agent to pick up."
argument-hint: "What will the next session be used for?"
---
<!-- S05 -->

Write a handoff document summarising the current conversation so a fresh agent
can continue the work. Save to `${HANDOFFS_DIR}/`. Create the directory if it
doesn't exist. Name the file with today's date and a short topic slug, e.g.
`2026-06-10-reviews-feature.md`.

Include a "Suggested skills" section in the document, listing skills the next
agent should invoke.

Do not duplicate content already captured in other artifacts (PRDs, plans,
ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally
identifiable information.

If the user passed arguments, treat them as a description of what the next
session will focus on and tailor the doc accordingly.
