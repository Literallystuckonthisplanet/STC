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

# A simple rg -l invocation has an unambiguous search-pattern/target boundary.
# shlex only tokenizes: it never evaluates shell text. Any unsupported or failed
# parse falls back to matching the complete original command below.
RG_INFO='{"ok":false,"targets":[]}'
case "$TOOL" in
  Bash|exec|unified_exec|unifiedExec|LocalShell|shell)
    RG_INFO=$(printf '%s' "$INPUT" | python3 -I -c '
import json
import shlex
import sys

try:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command or "#" in command or any(char in command for char in "\0\n\r"):
        raise ValueError
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    words = list(lexer)
    operators = "|&;<>()"
    if any(word and all(char in operators for char in word) for word in words):
        raise ValueError
    if any(any(char in word for char in "$`*?[]{}") or word.startswith("~") for word in words):
        raise ValueError
    if len(words) < 4 or words[:2] != ["rg", "-l"]:
        raise ValueError
    has_separator = words[2] == "--"
    pattern_index = 3 if has_separator else 2
    if len(words) <= pattern_index + 1:
        raise ValueError
    targets = words[pattern_index + 1:]
    if words[pattern_index].startswith("-") and not has_separator:
        raise ValueError
    if any(target.startswith("-") for target in targets):
        raise ValueError
    print(json.dumps({"ok": True, "targets": targets}))
except Exception:
    print(json.dumps({"ok": False, "targets": []}))
')
    ;;
esac

RG_OK=$(printf '%s' "$RG_INFO" | jq -r '.ok == true' 2>/dev/null)
case "$RG_OK" in true) ;; *) RG_OK=false ;; esac

# Exclude only a recognized search pattern. Every other structured field and
# every explicit target still reaches the same protected-pattern matcher.
VALUES=$(echo "$INPUT" | jq -r --argjson skip_command "$RG_OK" '
  [
    .tool_input.file_path?,
    .tool_input.path?,
    .tool_input.pattern?,
    (.tool_input.paths[]?),
    (if $skip_command then empty else .tool_input.command? end),
    .tool_input.input?,
    .tool_input.cmd?,
    .tool_input.script?,
    (.tool_input.args[]?),
    .command?,
    .input?
  ] | .[]? | select(type == "string")
' 2>/dev/null)
if [ "$RG_OK" = true ]; then
  RG_TARGETS=$(printf '%s' "$RG_INFO" | jq -r '.targets[]?')
  VALUES=$(printf '%s\n%s\n' "$VALUES" "$RG_TARGETS")
fi

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
