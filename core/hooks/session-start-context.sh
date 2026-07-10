#!/bin/bash
# H06 — hook: session-start-context
# SessionStart: injects the always-context rule files (the original pre-@import
# mechanism — @import was a later refactor that does not work in harnesses
# without native @-expansion). Also: post-compact loss-check (FR-7) + infra-audit
# cadence nudge.
#
# WHAT H06 OWNS:
#   - cat ~/.stc/core/rules/{behavior,pev,project_docs,session}.md → stdout
#     → the harness feeds hook stdout to the model as additionalContext.
#     This is the ONLY way the always-context rules reliably reach the model
#     across harnesses. The always-context bundle (CLAUDE.stc.md/AGENTS.stc.md)
#     is a fallback pointer, not the loader.
#   - on source=compact → post-compact loss-check directive (FR-7).
#   - on source=startup/clear → infra-audit cadence nudge (≥30 days → remind).
# On source=resume the context is already restored → skip (no re-inject).
#
# FR-7 — post-compact recovery: on source=compact (manual /compact AND auto),
# emit a loss-check directive (reconcile pre-compression state + record
# unsaved facts). A shell hook cannot see the dialogue → can't flush arbitrary
# critique BEFORE compression; instead forces the agent to verify losses.
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${STC_CORE}    — the shared rules/memory root (~/.stc/core), harness-neutral.
#   ${HARNESS_DIR} — the harness home (~/.claude), where skills/ live.
#   ${USER_LANG}   — message language (en|ru). Default en.

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

echo "=== ОБЯЗАТЕЛЬНЫЙ КОНТЕКСТ СТАРТА (инжектнут хуком H06 — НЕ перечитывать вручную, если уже видишь) ==="

# Infra-audit cadence: ≥30 days since the last run → remind.
# Best-effort: the "Last run" timestamp lives in the infra-audit skill.
# Skills render as SKILL.md (plugin) or SKILL.stc.md (files); check both. Absent
# on a harness without the skill → the check silently skips (no nudge).
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

# The always-context rules. ${STC_CORE} resolves to ~/.stc/core (shared, cross-
# harness). 3 firing-rule files (behavior/pev/session) are injected here;
# project_docs.md stays lazy (read by anchor [[project-docs]] when writing
# ADRs/specs) — this keeps the inject within the ZCode 24KB additionalContext
# cap (4 files overflow it by ~160 bytes).
for f in behavior pev session; do
  src="${STC_CORE}/rules/${f}.md"
  if [ -f "$src" ]; then
    echo ""
    echo "----- rules/${f}.md -----"
    cat "$src"
  fi
done
