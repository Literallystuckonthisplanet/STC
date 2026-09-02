#!/usr/bin/env bash
# H19 — hook: plan-recall — что по этой теме уже решали, подаётся при выходе из плана.
# Event: PreToolUse(ExitPlanMode).
#
# Боль, померенная по корпусу: поиск по прошлым разговорам вызывался 15 раз за
# всё время против 121 чтения снапшотов. Правила «проверь, разбиралось ли»
# в rules нет вообще — то есть здесь не забывание решений, а отсутствие шага.
# Симптом со стороны Антона: «приходится тыкать, чтобы проверил что-то из этой
# или предыдущей сессии, тк предлагаются уже разобранные ранее моменты».
#
# Разобранный случай: заметка о пяти кругах ревью Roundtable (11–12.08) с
# выводом «11 из 11 находок поздних кругов — регрессии автора» пролежала
# сиротой месяц, и тот же вопрос разбирался заново.
#
# Поэтому хук не напоминает искать, а САМ ищет и подаёт найденное: напоминание
# «не забудь посмотреть» — это ровно тот advisory, который по defect_ledger
# рецидивирует. Один вызов memory_graph.py, ~0.5 c на 75 узлах.
#
# НЕ блокирует: план мог и не иметь прошлого, а пустой результат — законный
# ответ («решение принимается впервые»). Гейт качества плана — отдельно, H21.
#
# Один раз на план: маркер по сессии и хешу текста, поэтому повторный выход
# после блокировки H21 не дублирует подсказку, а новый план — подаёт свою.
#
# Render-time vars: ${STC_CORE}, ${USER_LANG}, ${HARNESS_NAME}. $NATIVE_DIR
# подставляется при деплое.

USER_LANG="${USER_LANG:-ru}"
STC_CORE="${STC_CORE:-$HOME/.stc/core}"

input=$(cat)
agent_id=$(echo "$input" | jq -r '.agent_id // ""' 2>/dev/null)
[ -n "$agent_id" ] && exit 0   # субагенты не предъявляют план

session=$(echo "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)

plan=$(echo "$input" | jq -r '.tool_input.plan // ""' 2>/dev/null)
if [ -z "$plan" ]; then
  plans_dir="$NATIVE_DIR/plans"
  [ -d "$plans_dir" ] || plans_dir="$HOME/.claude/plans"
  newest=$(ls -t "$plans_dir"/*.md 2>/dev/null | head -1)
  [ -n "$newest" ] && plan=$(cat "$newest" 2>/dev/null)
fi
[ -z "$plan" ] && exit 0

SCRIPT="$STC_CORE/scripts/memory_graph.py"
[ -f "$SCRIPT" ] || exit 0

# Маркер по содержимому: другой план в той же сессии получит свою подсказку.
plan_hash=$(printf '%s' "$plan" | cksum | tr -d ' \t')
marker="/tmp/stc-plan-recall-${session}-${plan_hash}"
[ -f "$marker" ] && exit 0
: > "$marker"

found=$(printf '%s' "$plan" | head -c 3000 | python3 "$SCRIPT" search-stdin --limit 3 --format hook 2>/dev/null)
[ -z "$found" ] && exit 0

case "$USER_LANG" in
  ru) msg="🗂️ plan-recall (H19): по теме этого плана в отжатом слое уже есть разобранное — $found · Загляни перед исполнением: там могут быть решения, которые план повторяет или отменяет. Пусто — значит тему не разбирали, и это тоже ответ." ;;
  *)  msg="🗂️ plan-recall (H19): earlier work on this plan's topic already exists — $found · Check it before executing: it may hold decisions this plan repeats or overturns. Nothing found means the topic is new, which is also an answer." ;;
esac

jq -cn --arg c "$msg" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
