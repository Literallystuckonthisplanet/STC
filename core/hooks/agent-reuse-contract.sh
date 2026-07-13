#!/bin/bash
# H04 — hook: agent guard (PreToolUse Task)
#   - 🔒 reuse-before-reinvent: build-capable sub-agents (general-purpose /
#       claude / builder) must carry a reuse contract in their prompt, otherwise
#       they start cold and reinvent what the repo already has → block.
#   - 🔒 fork-protocol (FR-28): the same build-capable prompts must carry the
#       fork protocol (local trivia → DECIDED line; architectural/business
#       fork → STOP + FORK report, options + recommendation, parent decides).
#       Without it an executor silently picks a side on an architectural fork
#       mid-block — exactly the decision orchestrator mode reserves for main.
#   - 💉 I20 baseline (FR-23): a reviewer agent (security-deps/qa/code-reviewer/
#       e2e/security-arch) → nudge to pass the baseline of accepted/out-of-scope
#       problems in the prompt, so it doesn't re-report them (security
#       HIGH/CRITICAL never go under baseline). Inject.
#
# Render-time vars: ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
SUBAGENT=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // empty')
PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')

USER_LANG="${USER_LANG:-en}"

case "$SUBAGENT" in
  general-purpose|claude|builder)
    if ! echo "$PROMPT" | grep -qiF "reuse-before-reinvent"; then
      case "$USER_LANG" in
        ru) echo "BLOCKED: промпт build-агента ('$SUBAGENT') без reuse-before-reinvent контракта. Открой промпт agent-преамбулом (playbook §Контракт промпта агента): zoom-out + reuse-before-reinvent (grep/Explore существующие паттерны → переиспользуй) + fork-protocol + контракт возврата. Добавь и повтори запуск." >&2 ;;
        *) echo "BLOCKED: a build-agent prompt ('$SUBAGENT') without a reuse-before-reinvent contract. Open the prompt with an agent preamble (playbook § Agent prompt contract): zoom-out + reuse-before-reinvent (grep/Explore existing patterns → reuse) + fork-protocol + return contract. Add it and retry." >&2 ;;
      esac
      exit 2
    fi
    if ! echo "$PROMPT" | grep -qiF "fork-protocol"; then
      case "$USER_LANG" in
        ru) echo "BLOCKED (FR-28): промпт build-агента ('$SUBAGENT') без fork-protocol. Исполнитель обязан знать протокол развилок: локальная техническая мелочь → решить самому + строка DECIDED в отчёте; архитектурная/бизнес-развилка или бриф противоречит реальности → СТОП + FORK-репорт (варианты / trade-offs / рекомендация) — решает родитель. Добавь секцию fork-protocol в промпт и повтори запуск." >&2 ;;
        *) echo "BLOCKED (FR-28): a build-agent prompt ('$SUBAGENT') without a fork-protocol. The executor must know the fork rules: local technical trivia → decide + a DECIDED line in the report; an architectural/business fork or a brief-vs-reality conflict → STOP + a FORK report (options / trade-offs / recommendation) — the parent decides. Add a fork-protocol section to the prompt and retry." >&2 ;;
      esac
      exit 2
    fi
    ;;
  security-deps|qa|code-reviewer|e2e|security-arch)
    # I20: nudge the baseline (only if it's not already in the prompt)
    if ! echo "$PROMPT" | grep -qiF "baseline"; then
      case "$USER_LANG" in
        ru) MSG="🧪 I20 baseline ('$SUBAGENT'): если у репо есть baseline принятых/вне-скоупа проблем (с пометкой «почему accepted») — передай его в промпт, чтобы агент не репортил повторно. Новую осознанно принятую проблему из отчёта → дозапиши в baseline. Security HIGH/CRITICAL под baseline НЕ попадают (всегда блок). Детали → playbook §Baseline для агентов." ;;
        *) MSG="🧪 I20 baseline ('$SUBAGENT'): if the repo has a baseline of accepted/out-of-scope problems (with a 'why accepted' note) — pass it in the prompt so the agent doesn't re-report. A newly accepted problem from the report → append to the baseline. Security HIGH/CRITICAL never go under baseline (always a block). Details → playbook § Agent baseline." ;;
      esac
      jq -cn --arg c "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
    fi
    ;;
esac
exit 0
