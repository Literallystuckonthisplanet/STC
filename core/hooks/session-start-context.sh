#!/bin/bash
# H06 — hook: session-start-context
# SessionStart: post-compact loss-check (FR-7) + infra-audit cadence reminder.
#
# This hook does NOT inject always-context rules — those load via @import in
# the always-context file (CLAUDE.md → CLAUDE.stc.md → @~/.stc/core/rules/*,
# @~/.stc/core/memory/*). Injecting them here would duplicate @import and
# require the hook to second-guess paths that @import already resolves.
# H06 owns only what @import CANNOT provide:
#   - on source=compact → force a loss-check (the summary may be incomplete)
#   - on source=startup/clear → infra-audit cadence nudge (≥30 days → remind)
# On source=resume the context is already restored → skip.
#
# FR-7 — post-compact recovery: on source=compact (manual /compact AND auto),
# emit a loss-check directive (reconcile pre-compression state + record
# unsaved facts). A shell hook cannot see the dialogue → can't flush arbitrary
# critique BEFORE compression; instead forces the agent to verify losses.
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${HARNESS_DIR}  — the harness home (~/.claude), where skills/ live.
#   ${USER_LANG}    — message language (en|ru). Default en.

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.source // empty')
case "$SOURCE" in
  resume) exit 0 ;;
esac

USER_LANG="${USER_LANG:-en}"

if [ "$SOURCE" = "compact" ]; then
  case "$USER_LANG" in
    ru)
      echo "=== 🔁 ПОСТ-КОМПАКТ — ПРОВЕРКА ПОТЕРЬ ПЕРЕД ПРОДОЛЖЕНИЕМ (H06/FR-7) ==="
      echo "Только что произошло СЖАТИЕ контекста (ручное ИЛИ авто). Саммари может быть неполным — НЕ считай его полным по умолчанию."
      echo "ДО следующего действия:"
      echo "1. Сверь критику ИЗ ДО-сжатия: изменённые/незакоммиченные файлы, тест/verify-команды, открытые решения, активный todo-лист (I23)."
      echo "2. ЛЮБОЙ важный факт (ID/конфиг/решение/результат), которого ещё НЕТ в memory-файле → записать НЕМЕДЛЕННО (I05 r2). Авто-компакт не должен ничего терять."
      echo "3. Что-то урезано саммари → восстанови из memory/ или транскрипта ПЕРЕД работой."
      echo "4. Был живой todo (I23) → восстанови его и продолжай с того же in_progress-пункта."
      ;;
    *)
      echo "=== 🔁 POST-COMPACT — LOSS CHECK BEFORE CONTINUING (H06/FR-7) ==="
      echo "Context was just COMPRESSED (manual OR auto). The summary may be incomplete — do NOT assume it is complete by default."
      echo "BEFORE the next action:"
      echo "1. Reconcile the critique FROM PRE-compression: changed/uncommitted files, test/verify commands, open decisions, the active todo-list (I23)."
      echo "2. ANY important fact (ID/config/decision/result) NOT already in a memory file → record IMMEDIATELY (I05 r2). Auto-compact must not lose anything."
      echo "3. Something trimmed by the summary → recover from memory/ or the transcript BEFORE working."
      echo "4. There was a live todo (I23) → restore it and continue from the same in_progress item."
      ;;
  esac
  echo ""
fi

# Infra-audit cadence: ≥30 days since the last run → remind.
# Best-effort: the "Last run" timestamp lives in the infra-audit skill.
# Skills render as SKILL.stc.md (collision-proof suffix); check both the STC
# name and a plain SKILL.md so this works pre/post-deploy. Absent on a harness
# without the skill → the check silently skips (no nudge, which is correct).
AUDIT_FILE=""
for cand in "${HARNESS_DIR}/skills/infra-audit/SKILL.stc.md" "${HARNESS_DIR}/skills/infra-audit/SKILL.md"; do
  [ -f "$cand" ] && AUDIT_FILE="$cand" && break
done
if [ -f "$AUDIT_FILE" ]; then
  AUDIT_DATE=$(grep -oE 'Last run:.*[0-9]{4}-[0-9]{2}-[0-9]{2}' "$AUDIT_FILE" 2>/dev/null | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
  if [ -n "$AUDIT_DATE" ]; then
    AUDIT_TS=$(date -j -f "%Y-%m-%d" "$AUDIT_DATE" +%s 2>/dev/null || date -d "$AUDIT_DATE" +%s 2>/dev/null)
    if [ -n "$AUDIT_TS" ]; then
      DAYS=$(( ( $(date +%s) - AUDIT_TS ) / 86400 ))
      if [ "$DAYS" -ge 30 ]; then
        case "$USER_LANG" in
          ru) echo ">>> АУДИТ ИНФРЫ: с последнего прогона ($AUDIT_DATE) прошло $DAYS дн (≥30). Предложи прогнать аудит (когда есть запас токенов)." ;;
          *) echo ">>> INFRA AUDIT: $DAYS days (≥30) since the last run ($AUDIT_DATE). Offer to run the audit (when there is token budget to spare)." ;;
        esac
      fi
    fi
  fi
fi
