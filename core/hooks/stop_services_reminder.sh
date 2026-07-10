#!/bin/bash
# H03 — hook: session guard (UserPromptSubmit, fires on every user message)
#
# Pain: SELF-EXEC / compact / session-end are advisory rules and recidivised.
# The hook reinforces them every prompt (SELF-EXEC) and on short commands
# (compact / session-end protocols). Also: I05b/FR-23 — the user pasted what
# looks like a secret → first action goes to .env, not memory; the value is
# never echoed.
#
# What it does:
#   - Always: SELF-EXEC reminder (I10) — run services yourself, ask only for
#     a value or a decision.
#   - I05b/FR-23: length-gated secret patterns scan the prompt → directive
#     "value to .env first, not memory, don't echo". NOT a block (the value is
#     the user's own input; the directive shapes the agent's next action).
#   - On short command-like prompts (< 80 chars):
#       a) COMPACT trigger → save memory per behavior.md § Memory rotation
#          (I26) first, then ${COMPACT_CMD}.
#       b) SESSION END trigger → rotate memory (I26), then stop services.
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${USER_LANG}     — message language (en|ru). Default en.
#   ${USER_NAME}     — user's name (for the compact-trigger prompt). Empty → "the user".
#   ${DEV_PORTS}     — space-separated dev-server ports. Default "3000 3001 3002".
#   ${COMPACT_CMD}   — harness-native compact command. Default "/compact".
#   ${SECRETS_ENV}   — the .env file secrets go into. Default ".env.local".

USER_LANG="${USER_LANG:-en}"
USER_NAME="${USER_NAME:-}"
DEV_PORTS="${DEV_PORTS:-3000 3001 3002}"
COMPACT_CMD="${COMPACT_CMD:-/compact}"
SECRETS_ENV="${SECRETS_ENV:-.env.local}"

# --- 1. SELF-EXEC reminder (always) -------------------------------------
case "$USER_LANG" in
  ru) echo "SELF-EXEC: docker/npm/pip/.env/сервис/браузер — делаю САМИ. Пользователю — только запрос значения или решения." ;;
  *) echo "SELF-EXEC: docker/npm/pip/.env/services/browser — I run these MYSELF. The user is only ever asked for a value or a decision." ;;
esac

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('prompt', '') or d.get('user_prompt', ''))
except:
    pass
" 2>/dev/null)

# --- 2. I05b — secret in prompt (FR-23): value NOT echoed, only the pattern
# name + directive. Length-gated token body (like H05) → does not fire on a
# bare prefix mention.
SECRET_PATTERNS=(
  "Notion token (ntn_)|ntn_[A-Za-z0-9]{30,}"
  "OpenAI/secret key (sk-)|sk-[A-Za-z0-9_-]{20,}"
  "GitHub PAT (ghp_)|ghp_[A-Za-z0-9]{30,}"
  "Resend key (re_)|re_[A-Za-z0-9]{20,}"
  "JWT (eyJ...)|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"
  "SECRET/TOKEN/PASSWORD assignment|(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY)[A-Z_]*['\"]?[[:space:]]*[=:][[:space:]]*['\"]?[A-Za-z0-9_/+.-]{16,}"
)
for entry in "${SECRET_PATTERNS[@]}"; do
  label="${entry%%|*}"; regex="${entry#*|}"
  if printf '%s' "$PROMPT" | grep -qE "$regex"; then
    case "$USER_LANG" in
      ru) echo "🔐 I05b: в промпте похоже на секрет [$label]. ПЕРВОЕ действие — записать значение в ${SECRETS_ENV}, подтвердить запись, и только потом продолжать задачу. В память — запрещено (H05 заблокирует). Значение не повторять в ответе/логах." ;;
      *) echo "🔐 I05b: the prompt looks like a secret [$label]. FIRST action — write the value to ${SECRETS_ENV}, confirm it's saved, and only then continue. Memory is forbidden (H05 will block). Do not repeat the value in the answer/logs." ;;
    esac
    break
  fi
done

# --- 3. Short-command triggers ------------------------------------------
PROMPT_LEN=${#PROMPT}
if [ "$PROMPT_LEN" -ge 80 ]; then exit 0; fi

# 3a. COMPACT trigger
if echo "$PROMPT" | grep -iE "compact|compress (context|session)|squeeze|save and compact|сжать (сессию|контекст)|сожми (сессию|контекст)|сохрани и сожми|сохранить и сжать|сохрани сессию|сжимаем|пора сжать|жать контекст" > /dev/null 2>&1; then
  if [ -n "$USER_NAME" ]; then NAME_REF="$USER_NAME"; else NAME_REF="the user"; fi
  case "$USER_LANG" in
    ru) echo "COMPACT TRIGGER: сначала сохрани память по behavior.md § Memory rotation (I26: обнови STATE/CHANGELOG project_<name>.md, ротируй хвост в archive/), потом скажи ${NAME_REF} ввести ${COMPACT_CMD}." ;;
    *) echo "COMPACT TRIGGER: save memory first per behavior.md § Memory rotation (I26: update STATE/CHANGELOG of project_<name>.md, rotate the tail to archive/), then tell ${NAME_REF} to run ${COMPACT_CMD}." ;;
  esac
fi

# 3b. SESSION END trigger
if echo "$PROMPT" | grep -iE "ending session|wrap up|that's all for now|завершаем сессию|на сегодня всё|заканчиваем" > /dev/null 2>&1; then
  case "$USER_LANG" in
    ru)
      echo "=== ПРОТОКОЛ ЗАВЕРШЕНИЯ СЕССИИ (обязательно, по порядку) ==="
      echo "ШАГ 1: сохрани память по behavior.md § Memory rotation (I26) — обнови STATE/CHANGELOG project_<name>.md, ротируй хвост в archive/."
      echo "ШАГ 2: остановить сервисы."
      ;;
    *)
      echo "=== SESSION END PROTOCOL (mandatory, in order) ==="
      echo "STEP 1: save memory per behavior.md § Memory rotation (I26) — update STATE/CHANGELOG of project_<name>.md, rotate the tail to archive/."
      echo "STEP 2: stop running services."
      ;;
  esac

  RUNNING=""
  for PORT in $DEV_PORTS; do
    PID=$(lsof -ti:"$PORT" 2>/dev/null)
    if [ -n "$PID" ]; then
      PROCESS=$(ps -p "$PID" -o comm= 2>/dev/null)
      RUNNING+="  Port $PORT: $PROCESS (PID $PID)"$'\n'
    fi
  done

  DOCKER_OUT=""
  if command -v docker > /dev/null 2>&1; then
    DOCKER_OUT=$(docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null \
      | grep -v "^NAME" | grep -v "^$")
  fi

  case "$USER_LANG" in
    ru)
      if [ -n "$RUNNING" ] || [ -n "$DOCKER_OUT" ]; then
        echo "Сервисы для остановки:"
        [ -n "$RUNNING" ] && echo "$RUNNING"
        [ -n "$DOCKER_OUT" ] && echo "Docker:" && echo "$DOCKER_OUT"
      else
        echo "Активных сервисов нет."
      fi
      echo "Не спрашивать — выполнить оба шага и отчитаться."
      ;;
    *)
      if [ -n "$RUNNING" ] || [ -n "$DOCKER_OUT" ]; then
        echo "Services to stop:"
        [ -n "$RUNNING" ] && echo "$RUNNING"
        [ -n "$DOCKER_OUT" ] && echo "Docker:" && echo "$DOCKER_OUT"
      else
        echo "No active services."
      fi
      echo "Do not ask — execute both steps and report."
      ;;
  esac
fi

exit 0
