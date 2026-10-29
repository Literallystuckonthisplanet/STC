#!/bin/bash
# H17 — Codex wrapper for the shared read policy.
#
# Covers Codex structured read tools and shell-shaped command tools. The shared
# policy is installed under ~/.stc/core by the STC core sync.
#
# Render-time vars: ${STC_CORE}, ${HARNESS_NAME}, ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
USER_LANG="${USER_LANG:-en}"
HARNESS_NAME="${HARNESS_NAME:-codex}"
RESULT=$(printf '%s' "$INPUT" | python3 -I \
  "${STC_CORE}/hooks/secret_read_policy.py" --harness "$HARNESS_NAME") || RESULT=unparsed

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
