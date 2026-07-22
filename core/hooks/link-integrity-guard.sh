#!/bin/bash
# H08 — hook: link-integrity-guard
# Verifies the integrity of [[wiki-links]] in the loaded memory against the
# registry of name: slugs.
# Root cause (audit pt.6): name: ↔ [[link]] drift on renames (convention drift).
# A link resolves if ITS slug = some file's name: (kebab), NOT the filename.
# The registry is built from ALL *.md (incl. archive — a link may point into
# archive); we scan only top-level ${MEMORY_DIR}/*.md (the loaded files;
# archive is not loaded).
# Block once per session (marker) → the agent adjudicates: drift = fix;
# an intentional forward-ref ([[name]] not yet created — allowed by the memory
# rules) = ignore, won't fire again.
#
# EVENT BINDING — harness-specific (set per adapter, NOT here):
#   - Claude: Stop. (Stop fires at session end; exit 2 surfaces broken links.)
#   - Codex:  UserPromptSubmit. Codex `Stop` = end of TURN, not session — binding
#     H08 to Stop there would inject a continuation-prompt mid-task on every turn.
#     So on Codex the hook runs on UserPromptSubmit but ONLY when the prompt text
#     matches the session-end trigger (the same grep H03 uses). This keeps the
#     "check at session end" semantics without the per-turn noise.
#
# Render-time vars: ${MEMORY_DIR}.

INPUT=$(cat)
SESSION=$(echo "$INPUT" | jq -r '.session_id // "nosession"')
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')

# --- event gating -------------------------------------------------------
# Stop (Claude): run, but guard against the stop-hook continuation loop.
if [ "$EVENT" = "Stop" ]; then
  STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
  [ "$STOP_ACTIVE" = "true" ] && exit 0   # already continuing from a stop-hook → no loop
# UserPromptSubmit (Codex): ONLY on the session-end text trigger (same phrases
# H03 uses). A regular prompt never fires the check.
elif [ "$EVENT" = "UserPromptSubmit" ]; then
  PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
  echo "$PROMPT" | grep -iE "ending session|wrap up|that's all for now|завершаем сессию|на сегодня всё|заканчиваем" > /dev/null 2>&1 || exit 0
# legacy: no hook_event_name field (older harness) → behave as before (run).
fi

MEMORY_DIR="${MEMORY_DIR}"
[ -d "$MEMORY_DIR" ] || exit 0

MARKER="/tmp/stc-linkcheck-${SESSION}"
[ -f "$MARKER" ] && exit 0

# Registry of existing slugs (name: from frontmatter of all .md, incl. archive)
REGISTRY=$(find "${MEMORY_DIR}" -name '*.md' -exec grep -hoE '^name:[[:space:]]*"?[A-Za-z0-9._-]+' {} + 2>/dev/null \
  | sed -E 's/^name:[[:space:]]*"?//' | sort -u)

# All [[links]] from the loadable top-level files (no archive/), slug up to | and #.
# Filter to the real-slug form: kebab-latin, ≥2 segments (feedback-pev, project-x-y).
# Cuts meta-placeholders from convention docs ([[...]], [[wiki]], [[link]], [[name]])
# without an ignore-list; no real name: is single-segment, so no false drops.
LINKS=$(grep -rhoE '\[\[[^]]+\]\]' "${MEMORY_DIR}"/*.md 2>/dev/null \
  | sed -E 's/^\[\[//; s/\]\]$//; s/\|.*$//; s/#.*$//' \
  | grep -xE '[a-z][a-z0-9]*(-[a-z0-9]+)+' | sort -u)

BROKEN=""
while IFS= read -r link; do
  [ -z "$link" ] && continue
  if ! printf '%s\n' "$REGISTRY" | grep -qxF "$link"; then
    BROKEN="${BROKEN}  [[${link}]]"$'\n'
  fi
done <<< "$LINKS"

if [ -n "$BROKEN" ]; then
  : > "$MARKER"
  echo "Broken [[wiki-links]] in the loaded memory (no name: matched):" >&2
  printf '%s' "$BROKEN" >&2
  echo "Adjudicate each: convention drift (a rename) → fix the [[link]] or the name:; an intentional forward-ref (file not yet created, allowed by the memory rules) → leave it. Fires once per session." >&2
  exit 2
fi
exit 0
