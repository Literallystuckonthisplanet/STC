#!/usr/bin/env bash
# H21 — hook: exit-plan-grill — sharpen the DoD before leaving plan mode.
# Event: PreToolUse(ExitPlanMode).
#
# Pain: exiting plan → implementation with a fuzzy definition-of-done breeds
# scope decisions mid-build. Those forks get decided in the expensive main
# context (the whole reason this line of work started). An advisory "nail the
# DoD" recidivises (ADR-001). This hook fires a soft nudge, once per session,
# to run grill-me on the DoD for a medium+ task — a precise DoD up front means
# fewer forks later, so less expensive main-context dialogue.
#
# Sub-agent (agent_id present) → pass: sub-agents don't drive the plan gate.
# INJECT (additionalContext, NOT a block), acknowledge-once: marker set BEFORE
#   output so a deliberate re-exit is not nagged again. Never blocks (exit 0) —
#   a small task legitimately skips grill-me.
# Log: /tmp/stc-exitplan-grill-<session> (once-per-session marker).

USER_LANG="${USER_LANG:-ru}"

input=$(cat)
session=$(echo "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
agent_id=$(echo "$input" | jq -r '.agent_id // ""' 2>/dev/null)
[ -n "$agent_id" ] && exit 0   # sub-agents don't drive the plan gate

marker="/tmp/stc-exitplan-grill-${session}"
[ -f "$marker" ] && exit 0
: > "$marker"

case "$USER_LANG" in
  ru) msg="🎯 H21: перед выходом из плана — если задача среднего+ размера, прогони grill-me по DoD (что именно = «готово», критерии приёмки). Точный DoD сейчас = меньше развилок по ходу реализации, а значит меньше дорогого диалога в мейне. Мелкая задача — просто продолжай, это не блок." ;;
  *)  msg="🎯 H21: before leaving plan mode — for a medium+ task, run grill-me on the DoD (what exactly counts as 'done', the acceptance criteria). A sharp DoD now = fewer scope forks mid-build = less expensive main-context dialogue. Small task — just continue, this is not a block." ;;
esac
jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
