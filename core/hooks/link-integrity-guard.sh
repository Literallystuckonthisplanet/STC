#!/bin/bash
# H08 — hook: link-integrity-guard
# Stop: verifies the integrity of [[wiki-links]] in the loaded memory against
# the registry of name: slugs.
# Root cause (audit pt.6): name: ↔ [[link]] drift on renames (convention drift).
# A link resolves if ITS slug = some file's name: (kebab), NOT the filename.
# The registry is built from ALL *.md (incl. archive — a link may point into
# archive); we scan only top-level ${MEMORY_DIR}/*.md (the loaded files;
# archive is not loaded).
# Block once per session (marker) → the agent adjudicates: drift = fix;
# an intentional forward-ref ([[name]] not yet created — allowed by the memory
# rules) = ignore, won't fire again.
#
# Render-time vars: ${MEMORY_DIR}.

INPUT=$(cat)
SESSION=$(echo "$INPUT" | jq -r '.session_id // "nosession"')
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
[ "$STOP_ACTIVE" = "true" ] && exit 0   # already continuing from a stop-hook → no loop

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
