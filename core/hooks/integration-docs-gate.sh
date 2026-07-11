#!/bin/bash
# H16 — hook: integration docs-first gate (defect-ledger; ADR-001, escalation advisory→block;
# generalized to all projects 2026-07-01, I25).
# PreToolUse(Write|Edit|MultiEdit): editing the CODE of a named integration is
# BLOCKED if there is no SAVED research on it — neither in the failure-modes
# reference nor in notes/research. Knowledge is persistent (cross-session): a
# record exists → pass + a pointer "check it, do NOT re-read the docs from
# scratch" (token economy). None anywhere → block: research + SAVE.
#
# The integration key is taken from the path AND from the edit content
# (a payment integration's logic may live in checkout/page.tsx — the path
# does not reveal it). A HYBRID detector (I25) derives the key three ways:
#   (1) LEXICON of known external services (cross-project, extensible);
#   (1.5) per-project REGISTRY (.claude-integrations) — a project declares its
#         own integrations without editing this hook;
#   (2) FALLBACK by external https-host — ONLY next to a network call
#       (fetch/axios/requests/…), so internal code with the word checkout is
#       not blocked; key = second-level domain;
#   (3) generic integration verbs (oauth/payment/sms) — ONLY with a network call.
# NETCALL (the flag from 2/3) GATES tiers 2-3, so internal code is never blocked.
#
# Bypass (the contract was read outside the tools): the marker
# `// docs-checked: <link>` or `// ds-exception:` in the edited code.
# No bypass marker (the block is not one-shot — it is lifted by saving the
# research or a docs-checked marker, not by a retry).
# Root cause: trial-and-error on integrations instead of reading the contract
# (a recurrence; the advisory inject of H10 was ignored).
#
# Render-time vars: ${MEMORY_DIR} (the global memory root), ${DOCS_ROOT} (the
#   doc-backend root, for notes/research), ${HARNESS_NAME} (infra-scope skip),
#   ${USER_LANG} (message language: en|ru).

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FILE" ] && exit 0

# Scope: project CODE only. Harness infra/memory/docs — out.
case "$FILE" in
  *"/${HARNESS_NAME:-claude}/"* ) exit 0 ;;
  */memory/*) exit 0 ;;
esac
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.py|*.go|*.rb|*.php) : ;;
  *) exit 0 ;;
esac

BLOB=$(echo "$INPUT" | jq -r '.tool_input | tostring' 2>/dev/null)
HAY=$(printf '%s %s' "$FILE" "$BLOB" | tr '[:upper:]' '[:lower:]')

# Conscious bypass in the edited code (contract verified outside the tools).
case "$HAY" in
  *docs-checked:*|*ds-exception:*) exit 0 ;;
esac

KEY=""

# USAGE — a signal that the edit REALLY uses an integration, not just mentions
# its name in a comment, a string, a regex, or a secret-pattern DEFINITION
# (the H16 false-positive: `"OpenAI-style key"` + an `sk-` regex in a secret
# scanner is not an OpenAI integration). Signals: an import/require, the
# vendor's API host, a `*_api_key`/secret/token assignment, an SDK client, or a
# network call. Generic-English service names below are gated on this; niche /
# regional names are not (their mention is almost always a real integration).
USAGE=0
case "$HAY" in
  *fetch*|*axios*|*"http.request"*|*"http.client"*|*httpx*|*"requests."*|*urllib*|*"got("*|*"ky("*|*webhook* \
  |*"import "*|*"require("*|*"from '"*|*'from "'*|*_api_key*|*_secret*|*_token*|*".com/"*|*sdk*|*"client("*) USAGE=1 ;;
esac

# (1a) NICHE / regional / payment services — a bare mention is enough (these
# words don't collide with ordinary English/code, so no USAGE gate). EXTENSIBLE;
# a project's OWN integrations belong in .claude-integrations (tier 1.5).
case "$HAY" in
  *telegram*|*tgbot*)  KEY="telegram" ;;
  *whatsapp*)          KEY="whatsapp" ;;
  *vkid*|*vk-oauth*|*vk_oauth*|*vk.com*|*vk-api*) KEY="vk" ;;
  *yandex*map*|*ymaps*) KEY="yandex-maps" ;;
  *2gis*)              KEY="2gis" ;;
  *dadata*)            KEY="dadata" ;;
  *cdek*|*сдэк*)            KEY="cdek" ;;
  *boxberry*)               KEY="boxberry" ;;
  *modulbank*|*модуль*банк*) KEY="modulbank" ;;
  *dolyami*|*долями*)       KEY="dolyami" ;;
  *yookassa*|*юкасса*|*yoomoney*) KEY="yookassa" ;;
  *cloudpayments*)          KEY="cloudpayments" ;;
  *tinkoff*|*тинькофф*|*tbank*) KEY="tinkoff" ;;
  *robokassa*)              KEY="robokassa" ;;
  *ok.ru*|*odnoklassniki*)  KEY="ok" ;;
  *яндекс*карт*)            KEY="yandex-maps" ;;
  *gigachat*)               KEY="gigachat" ;;
  *yandexgpt*|*yandex*gpt*) KEY="yandexgpt" ;;
esac

# (1b) GENERIC-English service names — real English/code words (openai, aws,
# stripe, sheets, …) that appear in prose/tests/regexes. Only an integration
# WITH a USAGE signal, so a bare mention no longer blocks. anthropic already had
# its own strict form; the rest join the gate.
if [ -z "$KEY" ] && [ "$USAGE" = "1" ]; then
  case "$HAY" in
    *stripe*)            KEY="stripe" ;;
    *paypal*)            KEY="paypal" ;;
    *twilio*)            KEY="twilio" ;;
    *sendgrid*)          KEY="sendgrid" ;;
    *mailgun*)           KEY="mailgun" ;;
    *gspread*|*google*sheet*|*sheets.googleapis*) KEY="sheets" ;;
    *openai*)            KEY="openai" ;;
    *amazonaws*|*aws-sdk*|*@aws-sdk*|*boto3*) KEY="aws" ;;
    *cloudflare*)        KEY="cloudflare" ;;
    *@notionhq*|*notion*api*) KEY="notion" ;;
  esac
fi
# anthropic — real SDK/API only (a bare mention or an @anthropic.com e-mail must
# NOT trigger); kept as an explicit strict match independent of the USAGE gate.
if [ -z "$KEY" ]; then
  case "$HAY" in
    *api.anthropic*|*@anthropic-ai*|*"import anthropic"*|*"from anthropic "*|*anthropic.anthropic*|*anthropic_api_key*) KEY="anthropic" ;;
  esac
fi

# (1.5) Per-project REGISTRY — a safety net for services OUTSIDE the lexicon.
# File `.claude-integrations` at the project root: one key per line, `#` = comment.
# The hook walks up from the edited file to the first registry found; if a token
# from the registry appears in the edit → that is the key. Declared once at the
# start of a project. Precise, no false blocks.
if [ -z "$KEY" ]; then
  dir=$(dirname "$FILE"); depth=0
  while [ "$dir" != "/" ] && [ "$dir" != "." ] && [ "$depth" -lt 10 ]; do
    REG="$dir/.claude-integrations"
    if [ -f "$REG" ]; then
      while IFS= read -r line; do
        line=$(printf '%s' "$line" | sed -E 's/#.*//; s/^[[:space:]]+//; s/[[:space:]]+$//' | tr '[:upper:]' '[:lower:]')
        [ -z "$line" ] && continue
        case "$HAY" in *"$line"*) KEY="$line"; break ;; esac
      done < "$REG"
      break  # registry found — do not walk higher
    fi
    dir=$(dirname "$dir"); depth=$((depth+1))
  done
fi

# The flag of a real network call (needed for tiers 2-3, so internal code is
# never blocked just for containing the word checkout/payment).
NETCALL=0
case "$HAY" in
  *fetch*|*axios*|*"http.request"*|*"http.client"*|*httpx*|*"requests."*|*urllib*|*"got("*|*"ky("*|*webhook*) NETCALL=1 ;;
esac

# (2) FALLBACK: an external https-host next to a network call → key = 2nd-level domain.
if [ -z "$KEY" ] && [ "$NETCALL" = "1" ]; then
  host=$(printf '%s' "$HAY" | grep -oE 'https?://[a-z0-9._-]+' \
    | grep -vE '://(localhost|127\.|0\.0\.0\.0|::1|[a-z0-9.-]*\.local|[a-z0-9.-]*\.internal|[a-z0-9.-]*\.test)' \
    | head -1)
  if [ -n "$host" ]; then
    dom=$(printf '%s' "$host" | sed -E 's#https?://##; s#/.*##')
    case "$dom" in
      fonts.googleapis.com|fonts.gstatic.com|schema.org|www.w3.org|example.com|example.org) dom="" ;;
    esac
    [ -n "$dom" ] && KEY=$(printf '%s' "$dom" | awk -F. '{ if (NF>=2) print $(NF-1); else print $0 }')
  fi
fi

# (3) Generic integration verbs — ONLY together with an external network call.
if [ -z "$KEY" ] && [ "$NETCALL" = "1" ]; then
  case "$HAY" in
    *oauth*)               KEY="oauth" ;;
    *payment*|*checkout*)  KEY="payment" ;;
    *" sms "*|*sms-*|*sendsms*) KEY="sms" ;;
  esac
fi

[ -z "$KEY" ] && exit 0

MEM="${MEMORY_DIR:-${DOCS_ROOT:-./docs}}"
FM="$MEM/reference_failure_modes.md"
RESEARCH="${MEM%/}/notes/research"

# Is there saved knowledge for this key (cross-session)?
FOUND=""
grep -qil "$KEY" "$FM" 2>/dev/null && FOUND="reference_failure_modes.md"
if [ -z "$FOUND" ] && [ -d "$RESEARCH" ]; then
  hit=$(grep -rils "$KEY" "$RESEARCH" 2>/dev/null | head -1)
  [ -n "$hit" ] && FOUND="notes/research/$(basename "$hit")"
fi

case "${USER_LANG:-en}" in
  ru)
    if [ -n "$FOUND" ]; then
      jq -cn --arg c "📚 Интеграция «$KEY»: ресёрч уже сохранён → $FOUND. Свернись с ним ПЕРЕД правкой (контракт/грабли известны) — НЕ перечитывай доку с нуля. Нашёл новое расхождение → допиши туда." \
        '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
      exit 0
    fi
    echo "🔒 docs-first БЛОК — интеграция «$KEY»: нет сохранённого ресёрча (ни reference_failure_modes.md, ни notes/research/). Trial-and-error на интеграциях уже рецидивил. СНАЧАЛА docs-ресёрч (Context7/docs-агент для SDK, research-агент для платформы) по контракту/lifecycle → СОХРАНИ (failure-modes per use-case или notes/research/) → повтори правку. Контракт уже проверял вне инструментов — пометь // docs-checked: <ссылка> в коде. Ложное срабатывание (не интеграция) — // ds-exception:." >&2
    ;;
  *)
    if [ -n "$FOUND" ]; then
      jq -cn --arg c "📚 Integration '$KEY': research already saved → $FOUND. Align with it BEFORE editing (contract/pitfalls are known) — do NOT re-read the docs from scratch. Found a new divergence → append it there." \
        '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
      exit 0
    fi
    echo "🔒 docs-first BLOCK — integration '$KEY': no saved research (neither the failure-modes reference nor notes/research). Trial-and-error on integrations has recurred before. FIRST do a docs-research (Context7/docs agent) on the contract/lifecycle → SAVE it (failure-modes per use-case, or notes/research/) → retry the edit. If the contract was already verified outside the tools — mark // docs-checked: <link> in the code. False positive (not an integration) — // ds-exception:." >&2
    ;;
esac
exit 2
