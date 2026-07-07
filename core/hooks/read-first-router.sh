#!/bin/bash
# H10 — hook: read-first router (FR-3; ADR-001 JIT-inject)
# PreToolUse(Write|Edit|MultiEdit): by the path DOMAIN, injects "read the rules
# + look at how it's already done" via hookSpecificOutput.additionalContext
# (NOT a block — bare stdout on PreToolUse does not reach the model).
# Collapses design-system(I19) + security + docs(integrations) + data + tdd +
# legal + I21a(reuse) into one event.
# Once-per-domain-per-session via markers (like dirty-tree/memory-guard).
# Several domains on a file fold into one message, each domain once per session.
# Scope: project code. Excludes the agent's own infra (${HARNESS_DIR}) and
# ${MEMORY_DIR} (those have their own hooks H05/H09).
#
# Render-time vars: ${HARNESS_DIR}, ${MEMORY_DIR}, ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION=$(echo "$INPUT" | jq -r '.session_id // "nosession"')
[ -z "$FILE" ] && exit 0

USER_LANG="${USER_LANG:-en}"

case "$FILE" in
  "${HARNESS_DIR}"/*) exit 0 ;;
  "${MEMORY_DIR}"/*) exit 0 ;;
esac

LOWER=$(printf '%s' "$FILE" | tr '[:upper:]' '[:lower:]')
HITS=""

emit() {  # $1=domain-key  $2=reminder ; once per domain per session
  local m="/tmp/stc-readfirst-${SESSION}-$1"
  [ -f "$m" ] && return 0
  : > "$m"
  HITS="${HITS}$2 "
}

# 1. DS-first (UI)
case "$LOWER" in
  *.tsx|*.jsx|*.css|*.scss|*/components/*|*/ui/*)
    case "$USER_LANG" in
      ru) emit ds "🎨 UI-файл (I19 ДС-first): есть DESIGN.md в репо → мапь элемент на токен/шкалу (тип/отступ/радиус/цвет); НЕТ токена → добавь токен (ревью), НЕ raw/arbitrary. Сверься с DESIGN.md — не угадывай размеры (дрейф заголовков уже кусал ×4)." ;;
      *) emit ds "🎨 UI file (I19 DS-first): is there a DESIGN.md in the repo → map the element to a token/scale (type/spacing/radius/color); no token → add a token (review), NOT raw/arbitrary. Cross-check DESIGN.md — don't guess sizes (heading-size drift bit ×4 already)." ;;
    esac
    ;;
esac

# 2. security
case "$LOWER" in
  *auth*|*/api/*|*route.ts|*route.tsx|*middleware*|*upload*|*session*)
    case "$USER_LANG" in
      ru) emit sec "🔒 Security-домен (auth/api/route/upload): СНАЧАЛА grep как сделано рядом (rate-limit, валидация входа, access-control, проверка владения ресурсом) → переиспользуй. Baseline → code_standard §Security baseline. Значимая правка → security-arch на Verify." ;;
      *) emit sec "🔒 Security domain (auth/api/route/upload): FIRST grep how it's done nearby (rate-limit, input validation, access-control, resource ownership check) → reuse. Baseline → code_standard § Security baseline. Meaningful change → security-arch at Verify." ;;
    esac
    ;;
esac

# 3. docs-first integrations/payments/webhooks
case "$LOWER" in
  *oauth*|*webhook*|*payment*|*checkout*|*/pay*|*integration*)
    case "$USER_LANG" in
      ru) emit docs "📚 Интеграция/платёж/вебхук: docs-first — НЕ угадывай API, запусти docs-агент (Context7) за актуальной докой ПЕРЕД кодом (trial-and-error жжёт токены). Секреты → .env, не в код." ;;
      *) emit docs "📚 Integration/payment/webhook: docs-first — do NOT guess the API, run the docs agent (Context7) for current docs BEFORE coding (trial-and-error burns tokens). Secrets → .env, not in code." ;;
    esac
    ;;
esac

# 4. data/schema/migrations
case "$LOWER" in
  *prisma*|*migration*|*schema*|*.sql)
    case "$USER_LANG" in
      ru) emit data "🗄 Данные/схема: глянь соседние миграции/модели (формат, нейминг). Решение по схеме → DATAMODEL.md в той же задаче." ;;
      *) emit data "🗄 Data/schema: look at neighboring migrations/models (format, naming). A schema decision → DATAMODEL.md in the same task." ;;
    esac
    ;;
esac

# 5. business logic → tdd
case "$LOWER" in
  */lib/*|*/services/*|*/utils/*|*calc*|*price*|*total*|*discount*|*validate*|*transform*)
    case "$USER_LANG" in
      ru) emit tdd "🧪 Файл логики (расчёт/валидация/трансформ): кандидат на TDD — рассмотри /tdd (тест до кода) для бизнес-правил; край-кейсы фиксируй тестом, не глазами." ;;
      *) emit tdd "🧪 Logic file (calc/validation/transform): a TDD candidate — consider /tdd (test before code) for the business rules; lock edge cases with a test, not by eye." ;;
    esac
    ;;
esac

# 6. legal
case "$LOWER" in
  *legal*|*consent*|*cookie*|*privacy*|*policy*|*terms*|*gdpr*|*offer*)
    case "$USER_LANG" in
      ru) emit legal "⚖️ Легал-домен (согласие/cookie/политика/оферта): сверься с применимым требованиям (РФ: 152-ФЗ/РКН, согласие per-цель) перед правкой формулировок; крупное изменение → легал-ревью." ;;
      *) emit legal "⚖️ Legal domain (consent/cookie/policy/terms): cross-check the applicable requirements (e.g. consent per-purpose) before editing wording; a major change → legal review." ;;
    esac
    ;;
esac

# 7. reuse — a general baseline on any project code, once per session
case "$LOWER" in
  *.ts|*.tsx|*.js|*.jsx|*.py)
    case "$USER_LANG" in
      ru) emit reuse "♻️ I21a reuse-before-reinvent: реализуешь concern (auth/доступ к данным/ошибки/логи/деньги/даты/id-sku) — СНАЧАЛА grep/Explore как уже сделано в репо → переиспользуй. Второй способ = только явное решение в instruction-file/ADR." ;;
      *) emit reuse "♻️ I21a reuse-before-reinvent: implementing a concern (auth/data access/errors/logs/money/dates/id-sku) — FIRST grep/Explore how it's already done in the repo → reuse. A second way = only an explicit decision in the instruction file / an ADR." ;;
    esac
    ;;
esac

[ -z "$HITS" ] && exit 0
jq -cn --arg c "📂 read-first ($(basename "$FILE")) — before writing: $HITS" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
