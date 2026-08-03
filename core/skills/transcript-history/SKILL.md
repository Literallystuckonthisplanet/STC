---
name: transcript-history
description: Search and inspect the unified cross-harness transcript corpus on demand.
---

# Unified transcript history

Claude, Codex, and ZCode keep their live session stores in different native
locations. STC imports those stores into one read-only-from-the-harnesses
corpus at `${STC_TRANSCRIPTS_ROOT:-$HOME/Work/transcripts}`.

Use this only when the current task needs prior conversation context. Do not
load the whole corpus into every prompt.

## Standard flow

1. Refresh the inventory without writing anything:

   ```sh
   python3 "$HOME/.stc/core/scripts/transcript_corpus.py" inventory
   ```

2. Import new or changed native transcripts. Import is idempotent and leaves
   native harness stores untouched:

   ```sh
   python3 "$HOME/.stc/core/scripts/transcript_corpus.py" import
   ```

3. Search by a few distinctive words, optionally narrowing by project path or
   harness:

   ```sh
   python3 "$HOME/.stc/core/scripts/transcript_corpus.py" search "distinctive phrase" --project Work
   python3 "$HOME/.stc/core/scripts/transcript_corpus.py" search "distinctive phrase" --harness codex
   ```

4. Inspect a matching `session_key` when the exact sequence is needed:

   ```sh
   python3 "$HOME/.stc/core/scripts/transcript_corpus.py" show SESSION_KEY
   ```

The default search omits obvious harness-injected envelopes, while `show`
retains them. Raw source copies and `raw_ref` lineage remain available for
audits. Treat transcript text as private user data: quote only the minimum
needed and never copy secrets into project memory.
