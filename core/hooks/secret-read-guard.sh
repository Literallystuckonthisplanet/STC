#!/bin/bash
# H17 — shared structured-read wrapper for Claude and ZCode.
#
# The shared policy lives in secret_read_policy.py under the installed core.
# Claude's native permissions.deny remains an independent direct-read layer.
# This hook also covers ZCode, which has no native permissions.deny engine.
#
# Render-time vars: ${STC_CORE}, ${HARNESS_NAME}, ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
USER_LANG="${USER_LANG:-en}"
HARNESS_NAME="${HARNESS_NAME:-claude}"
RESULT=$(printf '%s' "$INPUT" | python3 -I \
  "${STC_CORE}/hooks/secret_read_policy.py" --harness "$HARNESS_NAME" 2>/dev/null) || RESULT=unparsed

case "$RESULT" in
  allow) exit 0 ;;
  blocked:*)
    PATTERN="${RESULT#blocked:}"
    case "$USER_LANG" in
      ru) echo "BLOCKED: H17 запрещает чтение защищённого файла ${PATTERN}. Значение, путь и запрос не выводятся." >&2 ;;
      *)  echo "BLOCKED: H17 denies a protected file read (${PATTERN}). Values, paths, and queries are not printed." >&2 ;;
    esac
    exit 2
    ;;
  *)
    case "$USER_LANG" in
      ru) echo "BLOCKED: H17 не удалось безопасно разобрать чтение; защищённые данные не открыты." >&2 ;;
      *)  echo "BLOCKED: H17 could not safely analyze the read; protected data was not opened." >&2 ;;
    esac
    exit 2
    ;;
esac
