#!/usr/bin/env bash
# H03 — UserPromptSubmit: small, immediate reminders only.
#
# Durable memory is handled outside the harness by memory_ingest.py. H03 no
# longer infers task transitions, compact boundaries, or session end; those
# triggers were too unreliable and made the old memory protocol recidivate.
#
# Render-time vars: ${USER_LANG}, ${SECRETS_ENV}.

USER_LANG="${USER_LANG:-en}"
SECRETS_ENV="${SECRETS_ENV:-.env.local}"

case "$USER_LANG" in
  ru) echo "SELF-EXEC: docker/npm/pip/.env/сервис/браузер — делаю САМИ. Пользователю — только запрос значения или решения." ;;
  *) echo "SELF-EXEC: docker/npm/pip/.env/services/browser — I run these MYSELF. The user is only ever asked for a value or a decision." ;;
esac

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("prompt", "") or d.get("user_prompt", ""))
except Exception:
    pass
' 2>/dev/null)

SECRET_PATTERNS=(
  "Notion token (ntn_)|ntn_[A-Za-z0-9]{30,}"
  "OpenAI/secret key (sk-)|sk-[A-Za-z0-9_-]{20,}"
  "GitHub PAT (ghp_)|ghp_[A-Za-z0-9]{30,}"
  "Resend key (re_)|re_[A-Za-z0-9]{20,}"
  "JWT (eyJ...)|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"
  "SECRET/TOKEN/PASSWORD assignment|(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY)[A-Z_]*['\"]?[[:space:]]*[=:][[:space:]]*['\"]?[A-Za-z0-9_/+.-]{16,}"
)
for entry in "${SECRET_PATTERNS[@]}"; do
  label="${entry%%|*}"
  regex="${entry#*|}"
  if printf '%s' "$PROMPT" | grep -qE "$regex"; then
    case "$USER_LANG" in
      ru) echo "🔐 В промпте похоже на секрет [$label]. Первое действие — записать значение в ${SECRETS_ENV}; в память и ответ его не копировать." ;;
      *) echo "🔐 The prompt looks like a secret [$label]. First save it to ${SECRETS_ENV}; do not copy the value into memory or the reply." ;;
    esac
    break
  fi
done
exit 0
