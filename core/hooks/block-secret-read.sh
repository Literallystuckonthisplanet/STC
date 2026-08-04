#!/bin/bash
# H17 — Codex-native secret-read guard.
#
# Codex has no Claude-style permissions.deny engine. This hook therefore covers
# both structured file tools and shell-shaped command tools. It deliberately
# reports only the protected pattern class; it never echoes a path, command,
# tool output, or possible secret value.
#
# Render-time vars: ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // .tool // empty')
USER_LANG="${USER_LANG:-en}"

case "$TOOL" in
  Read|Glob|Grep|Bash|exec|unified_exec|unifiedExec|LocalShell|shell)
    ;;
  *)
    exit 0
    ;;
esac

# Collect path/pattern/command variants from current Codex payloads. Values are
# used only for matching and are never included in diagnostics.
VALUES=$(echo "$INPUT" | jq -r '
  [
    .tool_input.file_path?,
    .tool_input.path?,
    .tool_input.pattern?,
    (.tool_input.paths[]?),
    .tool_input.command?,
    .tool_input.input?,
    .tool_input.cmd?,
    .tool_input.script?,
    (.tool_input.args[]?),
    .command?,
    .input?
  ] | .[]? | select(type == "string")
' 2>/dev/null)

PATTERN=""
while IFS= read -r value; do
  [ -z "$value" ] && continue
  if printf '%s\n' "$value" | grep -qiE '(^|[^[:alnum:]_])\.env(\.[[:alnum:]_*?-]+)*([^[:alnum:]_-]|$)'; then
    PATTERN=".env"
    break
  fi
  if printf '%s\n' "$value" | grep -qiE '(^|[^[:alnum:]_])[^[:space:]]+\.pem([^[:alnum:]_]|$)'; then
    PATTERN="*.pem"
    break
  fi
  if printf '%s\n' "$value" | grep -qiE '(^|[^[:alnum:]_])id_rsa([^[:alnum:]_]|$)'; then
    PATTERN="id_rsa"
    break
  fi
  if printf '%s\n' "$value" | grep -qiE '(^|[^[:alnum:]_])credentials([._-][[:alnum:]_-]+)*([^[:alnum:]_]|$)'; then
    PATTERN="credentials"
    break
  fi
done <<< "$VALUES"

[ -z "$PATTERN" ] && exit 0

case "$USER_LANG" in
  ru) echo "BLOCKED: H17 запрещает чтение защищённого шаблона ${PATTERN}. Значение, полный путь и команда не выводятся." >&2 ;;
  *)  echo "BLOCKED: H17 denies a protected read pattern ${PATTERN}. The value, full path, and command are not printed." >&2 ;;
esac
exit 2
