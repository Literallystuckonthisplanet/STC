#!/bin/bash
# H09 — hook: memory-guard (pilot FR-2: rule I04 moved from always → JIT-inject)
# PreToolUse(Write|Edit|MultiEdit): on the FIRST edit of a given memory file
# in a session, injects the I04 checklist via hookSpecificOutput.additionalContext
# (NOT a block, not stdout — bare stdout on PreToolUse does not reach the model;
# additionalContext does).
# Content routing by basename: feedback_ / playbook / council / MEMORY = rules
# (full checklist); project_ / reference_ = facts (R08). Once-per-file-per-session
# via a marker (like dirty-tree-guard).
#
# Render-time vars: ${MEMORY_DIR}, ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION=$(echo "$INPUT" | jq -r '.session_id // "nosession"')
[ -z "$FILE" ] && exit 0

MEMORY_DIR="${MEMORY_DIR}"
case "$FILE" in
  "${MEMORY_DIR}"/*.md) ;;
  *) exit 0 ;;
esac

USER_LANG="${USER_LANG:-en}"

FILEHASH=$(printf '%s' "$FILE" | shasum | cut -c1-12)
MARKER="/tmp/stc-memory-guard-${SESSION}-${FILEHASH}"
[ -f "$MARKER" ] && exit 0
: > "$MARKER"

BASE=$(basename "$FILE")
case "$BASE" in
  feedback_*|playbook.md|council.md|MEMORY.md|behavior.md|pev.md)
    case "$USER_LANG" in
      ru) BODY="ПЕРЕД записью правила: (1) ДЕДУП — grep always+lazy по concern'у; покрыто → дополни существующее, не плоди дубль. (2) МЕСТО — есть файл-владелец concern'а (по description) → туда; сквозной → новый файл + строка в MEMORY.md. (3) ФОРМАТ — сверься с playbook §Стиль memory-инструкций (НЕ по памяти), always-vs-lazy, тест срабатывания." ;;
      *) BODY="BEFORE writing a rule: (1) DEDUP — grep always+lazy by concern; already covered → extend the existing, don't spawn a duplicate. (2) PLACE — is there an owner file for the concern (by description) → there; cross-cutting → new file + a line in MEMORY.md. (3) FORMAT — check playbook § Memory-instruction style (NOT from memory), always-vs-lazy, the firing test." ;;
    esac
    ;;
  project_*|reference_*)
    case "$USER_LANG" in
      ru) BODY="R08 — формат STATE/OPEN/CHANGELOG; НЕ дублируй репо-доки (деталь в репо-док, memory = указатель); закрытое → удаляй, история → git/archive." ;;
      *) BODY="R08 — STATE/OPEN/CHANGELOG format; do NOT duplicate repo docs (detail → repo doc, memory = pointer); closed → delete, history → git/archive." ;;
    esac
    ;;
  *)
    BODY=""
    ;;
esac

[ -z "$BODY" ] && exit 0

case "$USER_LANG" in
  ru) MSG="📝 Правка memory ($BASE) — I04: ${BODY} Правил инфру (правило/команда/агент/хук/метка) → перегенерить doc-backend (playbook §Синхронизация инфра-доки). ПОСЛЕ записи — перечитай файл и примени (сохранил ≠ активировал)." ;;
  *) MSG="📝 Memory edit ($BASE) — I04: ${BODY} Infra-rule (rule/command/agent/hook/label) → regenerate the doc backend (playbook § Infra-doc sync). AFTER writing — re-read the file and apply it (saved ≠ activated)." ;;
esac

jq -cn --arg c "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
