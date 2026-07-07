#!/usr/bin/env bash
# H02 — hook: playwright-mcp-guard — enforces CLI-first for e2e (FR-22) +
# real-browser preflight (FR-18).
# Event: PreToolUse(mcp__playwright__browser*).
#
# Pain: Playwright MCP is expensive (each snapshot/navigate/click drags the
# full a11y tree into context), and a former bare-echo never reached the model
# (PreToolUse stdout reaches only the user). Now — a JIT-inject via
# additionalContext, once per session: a terse channel-selection directive.
# NOT a block.
#
# Inject (once/session): pick the e2e channel — CLI / real-browser-in-main /
# e2e-subagent; + a preflight nudge to start the real browser on
# ${CDP_PORT} if it is needed (credentials, real session).
# Marker once-per-session: /tmp/stc-pwmcp-<session>. No escape hatch (not a block).
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${CDP_PORT}        — the CDP port the user's real browser listens on. Default 9222.
#   ${E2E_CLI_CMD}     — the project's CLI e2e command (e.g. "pnpm test:e2e").
#                        Empty → no CLI-channel suggestion.
#   ${USER_LANG}       — message language (en|ru). Default en.

input=$(cat)
session=$(printf '%s' "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
marker="/tmp/stc-pwmcp-${session}"
[ -f "$marker" ] && exit 0
touch "$marker"

USER_LANG="${USER_LANG:-en}"
CDP_PORT="${CDP_PORT:-9222}"
E2E_CLI_CMD="${E2E_CLI_CMD:-}"

# FR-18 — preflight: is the real browser up on the CDP port?
real_browser=""
curl -s -m 1 "http://localhost:${CDP_PORT}/json/version" >/dev/null 2>&1 \
  || real_browser=" Real browser :${CDP_PORT} is not up — if you need it (credentials, saved session), start it first (playbook § Playwright MCP)."

cli_branch=""
[ -n "$E2E_CLI_CMD" ] && cli_branch=" Regression/repeat → STOP, run CLI \`${E2E_CLI_CMD}\` (cheap)."

case "$USER_LANG" in
  ru)
    msg="🎭 Playwright MCP. Выбери канал по задаче:${cli_branch} Нужна реальная сессия/креды пользователя → MCP+реальный-браузер в main. Чистый исследовательский e2e → через e2e-сабагент (изоляция).${real_browser} После работы — browser_close."
    ;;
  *)
    msg="🎭 Playwright MCP. Pick the channel for the task:${cli_branch} Need a real session / user credentials → MCP + real browser in main. Pure exploratory e2e → via the e2e-subagent (isolation).${real_browser} When done — browser_close."
    ;;
esac
jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
