#!/bin/bash
# H17 — hook: secret-read-guard (defense-in-depth on READ)
# PreToolUse(Read|Glob|Grep): blocks reading secret files (.env / .pem / id_rsa).
#
# Why: Layer-8 permissions.deny does this on Claude Code natively, but ZCode
# has no permissions engine. This hook is the harness-neutral equivalent — the
# SAME 5 rules rendered into settings.json on claude, and the ONLY read-guard
# on zcode. On claude it runs alongside permissions.deny (belt + suspenders);
# a native deny that never reaches the tool is faster, but this hook covers the
# path where a harness ignores/has no permissions layer.
#
# Scope: only the secret-file patterns below. A deliberate override (you are
# legitimately inspecting .env during infra work) is `// secret-exception:` in
# the prompt, or just edit this file locally. Mirrors integration-docs-gate's
# escape hatch convention.
#
# The secret VALUE is never printed — only the file pattern that fired.
#
# Render-time vars: ${USER_LANG} (message language: en|ru).

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
[ -z "$TOOL" ] && exit 0

# gather the paths/patterns this tool call targets
HAY=$(echo "$INPUT" | jq -r '
  [.tool_input.file_path // empty,
   .tool_input.path // empty,
   .tool_input.pattern // empty,
   (.tool_input.paths[]? // empty)
  ] | join(" ")
' 2>/dev/null)

[ -z "$HAY" ] && exit 0

# the 5 secret-file patterns (mirror adapters/*/permissions.deny)
SECRET_HIT=""
case "$HAY" in
  *".env.local"*)    SECRET_HIT=".env.local" ;;
  *".env.*.local"*)  SECRET_HIT=".env.*.local" ;;
  *".env"*)          SECRET_HIT=".env" ;;
  *".pem"*)          SECRET_HIT="*.pem" ;;
  *"id_rsa"*)        SECRET_HIT="id_rsa" ;;
esac
[ -z "$SECRET_HIT" ] && exit 0

LANG_CODE="${USER_LANG:-en}"
case "$LANG_CODE" in
  ru)
    echo "🔒 secret-read-guard БЛОК — попытка чтения секрета ($SECRET_HIT). Секреты (env-файлы, PEM-ключи, id_rsa) нельзя читать напрямую — это утечка в контекст/логи. Если нужно значение — возьми его из \${VAR} в коде или .env через source, а не Read файла целиком. Легитимный разбор инфры — пометь // secret-exception: в промте." >&2
    ;;
  *)
    echo "🔒 secret-read-guard BLOCK — attempt to read a secret ($SECRET_HIT). Secrets (env files, PEM keys, id_rsa) must not be read directly — that leaks them into context/logs. If you need a value, reference \${VAR} from code or source the .env, do not Read the whole file. Legitimate infra inspection — mark // secret-exception: in the prompt." >&2
    ;;
esac
exit 2
