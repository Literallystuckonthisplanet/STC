#!/bin/bash
# H06 — hook: session-start-context
# SessionStart: injects the always-context rule files (the original pre-@import
# mechanism — @import was a later refactor that does not work in harnesses
# without native @-expansion). Also: infra-audit cadence nudge.
#
# WHAT H06 OWNS:
#   - cat ~/.stc/core/rules/{behavior,pev,session}.md → stdout
#     → the harness feeds hook stdout to the model as additionalContext.
#     This is the ONLY way the always-context rules reliably reach the model
#     across harnesses. The always-context bundle (CLAUDE.stc.md/AGENTS.stc.md)
#     is a fallback pointer, not the loader.
#   - on source=startup/clear → infra-audit cadence nudge (≥30 days → remind).
# Resume/compact are not memory lifecycle events; H06 only owns initial
# always-context delivery.
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${STC_CORE}    — the shared rules/memory root (~/.stc/core), harness-neutral.
#   ${HARNESS_DIR} — the harness home (~/.claude), where skills/ live.
#   ${USER_LANG}   — message language (en|ru). Default en.

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.source // empty')
case "$SOURCE" in
  resume|compact) exit 0 ;;
esac

USER_LANG="${USER_LANG:-en}"

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
