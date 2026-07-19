#!/usr/bin/env bash
# H21 — hook: exit-plan-gate — the plan may not leave plan mode half-baked (FR-28).
# Event: PreToolUse(ExitPlanMode).
#
# Pain: exiting plan → implementation with a fuzzy definition-of-done breeds
# scope decisions mid-build. Those forks get decided in the expensive main
# context. Under FR-28 (orchestrator mode) the plan is also the DISPATCH
# artifact — cheap sub-agents execute it — so a plan without AC/DoD, without
# a block→executor decomposition, and without its forks resolved cannot be
# executed by anyone but expensive main. An advisory nudge recidivises
# (ADR-001) → this is now a HARD GATE.
#
# Checks the plan text for four marker groups (presence, not quality):
#   1. AC/DoD          — acceptance criteria / definition-of-done section
#   2. decomposition   — blocks routed to executors (builder/cleanup/worktree/
#                        cheap-session/exec-tier vocabulary)
#   3. forks           — an explicit line about forks: resolved or "none open"
#   4. task→model→mode — the user-facing «Правила проекта: задача → модель →
#                        режим» table + a copy-paste new-session prompt (FR-29)
# Plan text source: tool_input.plan when the harness passes it; otherwise the
# freshest *.md under $NATIVE_DIR/plans/ (the plan-file workflow).
#
# Missing marker(s) → exit 2 ONCE with the checklist (acknowledge-once: the
# ACK marker is set BEFORE exit 2, so a deliberate re-exit passes — the gate
# forces one deliberate pause, it does not evaluate the plan's quality).
# Sub-agent (agent_id present) → pass: sub-agents don't drive the plan gate.
# All markers present → pass silently (the grill-me nudge is folded into the
# block message; a passing plan needs no nag).
# Log: /tmp/stc-exitplan-gate-<session> (ack marker).
#
# Render-time vars: ${USER_LANG}. $NATIVE_DIR is substituted at deploy time.

USER_LANG="${USER_LANG:-ru}"

input=$(cat)
session=$(echo "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
agent_id=$(echo "$input" | jq -r '.agent_id // ""' 2>/dev/null)
[ -n "$agent_id" ] && exit 0   # sub-agents don't drive the plan gate

ack="/tmp/stc-exitplan-gate-${session}"
[ -f "$ack" ] && exit 0

# --- plan text: tool_input.plan, else the freshest plan file -----------------
plan=$(echo "$input" | jq -r '.tool_input.plan // ""' 2>/dev/null)
if [ -z "$plan" ]; then
  plans_dir="$NATIVE_DIR/plans"
  [ -d "$plans_dir" ] || plans_dir="$HOME/.claude/plans"
  newest=$(ls -t "$plans_dir"/*.md 2>/dev/null | head -1)
  [ -n "$newest" ] && plan=$(cat "$newest" 2>/dev/null)
fi
# No plan text found at all → nothing to check; don't false-block a harness
# that exposes neither the parameter nor a plans dir.
[ -z "$plan" ] && exit 0

# --- marker groups (case-insensitive, RU+EN vocabulary) ----------------------
missing=""
if ! echo "$plan" | grep -qiE '(^|[^a-zA-Z])AC([^a-zA-Z]|$)|acceptance|DoD|definition of done|критери'; then
  missing="${missing}AC/DoD; "
fi
if ! echo "$plan" | grep -qiE 'sub-haiku|sub-sonnet|builder|cleanup|worktree|cheap-session|exec::|ворктри|исполнител'; then
  missing="${missing}decomposition→executors; "
fi
if ! echo "$plan" | grep -qiE 'развил|fork'; then   # stem: развилка/развилки/развилок
  missing="${missing}forks-resolved line; "
fi
# FR-29: the user-facing «задача → модель → режим» table must be present.
if ! echo "$plan" | grep -qiE 'Правила проекта|задача → модель|task → model'; then
  missing="${missing}«задача→модель→режим» table + new-session prompt; "
fi

[ -z "$missing" ] && exit 0

: > "$ack"   # acknowledge-once: the deliberate re-exit passes
case "$USER_LANG" in
  ru) echo "⛔ H21 exit-plan-gate (FR-28): в плане не хватает — ${missing}План = артефакт диспатча: без этого его некому исполнять, кроме дорогого main. Чек-лист перед выходом: (1) AC/DoD — что именно значит «готово» (мутный DoD → прогони grill-me); (2) декомпозиция: каждый блок → исполнитель (builder-агент / cleanup / worktree / cheap-session; main — только исключение с WHY); (3) развилки: явная строка — «открытых развилок нет» или список решённых; (4) раздел «Правила проекта: задача → модель → режим» (таблица task→model→main/субагент) + в конце плана блок «Промпт для новой сессии»; (5) M/L: спека+таски записаны (/to-spec + /to-tasks) — декомпозиция живёт в Obsidian-хранилище, не в переписке. Дополни план и повтори выход — второй раз гейт пропустит." >&2 ;;
  *)  echo "⛔ H21 exit-plan-gate (FR-28): the plan is missing — ${missing}The plan IS the dispatch artifact: without these nobody but expensive main can execute it. Checklist before exiting: (1) AC/DoD — what exactly counts as done (fuzzy DoD → run grill-me); (2) decomposition: every block → an executor (builder agent / cleanup / worktree / cheap-session; main only as a justified exception); (3) forks: an explicit line — 'no open forks' or the resolved list; (4) a «задача → модель → режим» table (task→model→main/subagent) + a copy-paste 'new-session prompt' at the end of the plan; (5) M/L: spec+tasks written (/to-spec + /to-tasks) — the decomposition lives in the doc backend, not in chat. Amend the plan and re-exit — the gate passes the second time." >&2 ;;
esac
exit 2
