#!/bin/bash
# H05 — hook: secret-scan-memory
# PreToolUse(Write|Edit|MultiEdit): blocks writing a real secret into memory/*.
# Memory is forbidden for secrets (I05) — secrets go to .env. Length-gated
# patterns, so it does NOT fire on documentation that merely mentions the
# prefixes (ntn_ / sk- / *_SECRET=value).
# The secret value is NEVER printed to the log (audit lesson) — only the name
# of the pattern that fired.
#
# Scope: only files inside ${MEMORY_DIR}. Everything else (incl. .env) — not
# our concern.
#
# Render-time vars: ${MEMORY_DIR} — the memory directory.

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

MEMORY_DIR="${MEMORY_DIR}"
case "$FILE" in
  "${MEMORY_DIR}"/*) ;;
  *) exit 0 ;;
esac

CONTENT=$(echo "$INPUT" | jq -r '[.tool_input.content // empty, .tool_input.new_string // empty, (.tool_input.edits[]?.new_string // empty)] | join("\n")')

# label|ERE-pattern (token body required — a bare prefix mention won't fire)
PATTERNS=(
  "Notion token (ntn_)|ntn_[A-Za-z0-9]{30,}"
  "OpenAI/secret key (sk-)|sk-[A-Za-z0-9_-]{20,}"
  "GitHub PAT (ghp_)|ghp_[A-Za-z0-9]{30,}"
  "Resend key (re_)|re_[A-Za-z0-9]{20,}"
  "JWT (eyJ...)|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"
  "SECRET/TOKEN/PASSWORD assignment|(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY)[A-Z_]*['\"]?[[:space:]]*[=:][[:space:]]*['\"][A-Za-z0-9_/+.-]{16,}"
)

for entry in "${PATTERNS[@]}"; do
  label="${entry%%|*}"
  regex="${entry#*|}"
  if echo "$CONTENT" | grep -qE "$regex"; then
    echo "BLOCKED: looks like a secret [$label] in a memory write ($FILE). Memory is forbidden for secrets (I05) — secret → ${SECRETS_ENV}, memory → only a pointer/fact, no value. Value not printed. Remove it and retry." >&2
    exit 2
  fi
done
exit 0
