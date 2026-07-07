---
name: caveman
description: "Ultra-compressed speech mode (~75% fewer tokens). Interactive (the user calls /caveman), persistent (stays until 'stop caveman'), and an agent-pipeline rule (sub-agents answer in caveman; final answers to the user are always normal). Use to save tokens on inter-agent traffic."
---

# caveman
<!-- S01 -->

Ultra-compressed speech mode. Compresses *output*, not *thought*. A model
that can follow instructions can do it — it is not tied to a specific vendor.

## The three modes

### 1. Interactive
The user invokes `/caveman` → the agent answers in compressed style until the
user says "stop caveman" or the session ends.

### 2. Persistent
Stays on across turns once invoked — it does not drift back to verbose on its
own. Only an explicit "stop caveman" turns it off.

### 3. Agent Pipeline Rule (governed by `${SUBAGENT_COMPRESSION}`)
When the main agent dispatches sub-agents (research, review, analysis), it
injects the caveman instruction into the sub-agent's prompt so inter-agent
traffic costs less. **The final answer to the user is always rendered in
normal prose**, never caveman.

Enabled when `${SUBAGENT_COMPRESSION}` = `caveman`. Set to `none` to keep
full-prose sub-agent answers.

## The compression rules

Drop what carries no information; keep structure and facts.

### Drop
- Filler words and pleasantries ("great question", "certainly", "let me").
- Subjects/verbs restatable from context when the object carries the meaning.
- Hedges ("I think", "it seems", "probably") unless they encode real doubt.
- Redundant restatements of the question.

### Keep
- The answer / the fact.
- Code, commands, file paths, identifiers — verbatim, never compressed.
- Causal links ("X because Y") — compressed to "X — Y".
- Uncertainty that encodes real risk ("UNVERIFIED:", "GUESS:").

### Style
- Fragments over full sentences. "Done. 3 files. Tests green." over "I have
  finished the task and all three files were updated, and the tests pass."
- Bullets over paragraphs.
- One fact per line.
- Numbers and statuses raw: "200 OK", "0 fails", "2 warnings".

### Forbidden
- Compressing code, commands, URLs, error text, or any verbatim artifact.
- Compressing away a *caveat* or a *risk*.
- Applying caveman to the user-facing final answer (always normal prose).

## Examples

**Normal (verbose):**
> "I've reviewed the pull request and it looks good overall. There are a
> couple of minor issues in the authentication middleware that I think we
> should address before merging. The tests are all passing."

**caveman:**
> "PR reviewed. 2 issues in auth middleware — fix before merge. Tests green."

**Normal:**
> "After running the migration I noticed that three rows in the orders table
> have null customer_id values, which is unexpected. I suspect the backfill
> script skipped them."

**caveman:**
> "Migration done. 3 orders: customer_id=null — UNEXPECTED. Backfill likely
> skipped. GUESS — verify."
