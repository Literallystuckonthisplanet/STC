#!/bin/bash
# H01 — hook: git guard (PreToolUse Bash, matcher: Bash)
#
# Pain: dangerous git (reset --hard, clean, branch -D, checkout .) and push to
# main = release are advisory-only rules and recidivised. The hook turns them
# into hard-blocks and JIT-injects verify/commit-invariant reminders.
#
# What it does:
#   - 🔒 BLOCK: dangerous git patterns (reset --hard, clean -f, branch -D,
#     checkout . / restore .). exit 2.
#   - 🔒 I08: `git push` to main/master = release → BLOCK without an ack
#     marker ("releasing"). One-shot ack via ${RELEASE_ACK_FILE}.
#   - 💉 I17/I09/FR-5: before `git commit` → JIT-inject verify-checklist +
#     commit-invariants (one task = one commit / don't commit unfinished / no
#     check = no commit). NOT a block. `--no-verify` gets an extra reminder
#     (pre-commit bypassed → run lint/tsc manually).
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${RELEASE_ACK_FILE} — per-session ack marker path; contains ${SESSION_ID},
#                         which is a RUNTIME bash var filled from stdin below
#                         (NOT a render-time value — deploy leaves it literal).
#   ${USER_LANG}        — message language (en|ru). Default en.
#
# Install via the /git-guardrails command.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command' 2>/dev/null)
if [ -z "$COMMAND" ]; then exit 0; fi

USER_LANG="${USER_LANG:-en}"

# session_id arrives in the hook's stdin JSON, NOT the environment. Parse it so
# ${RELEASE_ACK_FILE} (…/stc-release-${SESSION_ID}) resolves per-session; without
# this SESSION_ID is empty and the ack marker collapses to a single global path
# (`/tmp/stc-release-`), leaking one session's release-ack into every other.
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)

DANGEROUS_PATTERNS=(
  "git reset --hard"
  "git clean -fd"
  "git clean -f"
  "git branch -D"
  "git checkout \."
  "git restore \."
  "reset --hard"
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented this operation." >&2
    exit 2
  fi
done

# I08 — push to main/master = RELEASE. Allowed only by explicit "releasing".
ACK="${RELEASE_ACK_FILE}"

if echo "$COMMAND" | grep -qE 'git[[:space:]]+push'; then
  TO_MAIN=0
  echo "$COMMAND" | grep -qE '\b(main|master)\b' && TO_MAIN=1
  # bare push (no branch) → current branch; on release that is main
  echo "$COMMAND" | grep -qE 'git[[:space:]]+push([[:space:]]+(-[^[:space:]]+))*([[:space:]]+origin)?[[:space:]]*$' && TO_MAIN=1
  if [ "$TO_MAIN" = "1" ]; then
    if [ -n "$ACK" ] && [ -f "$ACK" ]; then rm -f "$ACK"; exit 0; fi  # ack present → pass once
    case "$USER_LANG" in
      ru) echo "BLOCKED: push в main = РЕЛИЗ (I08). Только по явному «релизим» пользователя. Пользователь сказал → прогони security-deps, затем 'touch ${ACK}' и повтори push (маркер одноразовый). Не говорил → НЕ пушь, спроси." >&2 ;;
      *) echo "BLOCKED: push to main = RELEASE (I08). Only by explicit 'releasing' from the user. If the user said so → run security-deps, then 'touch ${ACK}' and repeat the push (one-shot marker). If not → do NOT push, ask first." >&2 ;;
    esac
    exit 2
  fi
fi

# B2 — I17 verify-gate + I09 commit-invariants before commit (JIT-inject, NOT block, FR-5).
if echo "$COMMAND" | grep -qE 'git[[:space:]]+commit'; then
  case "$USER_LANG" in
    ru)
      MSG="✅ Перед коммитом — verify (I17) + инварианты коммита (I09).
VERIFY — проверил? СТАТИКА (lint/tsc/build по стеку). ГЛАЗАМИ (diff только нужное; нет секретов/ключей; для текстов — нет AI-маркеров). ДИНАМИКА (логика→тесты+code-reviewer; UI→Playwright/verify). Агентные по триггерам (security-arch/e2e/security-deps перед деплоем/legal).
ИНВАРИАНТЫ — одна задача=один коммит (логически цельный, не свалка); НЕ коммить незавершённое/сломанное даже «временно/чтобы не потерять»; нет проверки = нет коммита.
В ответе перечисли «Проверил: X✓ Y✓ Z✓»."
      ;;
    *)
      MSG="✅ Before commit — verify (I17) + commit-invariants (I09).
VERIFY — checked? STATIC (lint/tsc/build per the stack). EYES (diff = only the intended change; no secrets/keys; for text — no AI markers). DYNAMIC (logic → tests + code-reviewer; UI → Playwright/verify). Agent-triggered checks per playbook §Agent triggers.
INVARIANTS — one task = one commit (logically cohesive, not a dump); do NOT commit unfinished/broken even 'temporarily / to not lose it'; no check = no commit.
In your answer, list 'Checked: X✓ Y✓ Z✓'."
      ;;
  esac
  if echo "$COMMAND" | grep -qE '(--no-verify|[[:space:]]-n([[:space:]]|$))'; then
    case "$USER_LANG" in
      ru) MSG="$MSG
⚠️ --no-verify: pre-commit-гейт ОБОЙДЁН. Прогнал lint/tsc вручную? Обход оправдан только когда хук падает на генерируемом коде, не для пропуска реальных ошибок." ;;
      *) MSG="$MSG
⚠️ --no-verify: the pre-commit gate IS BYPASSED. Ran lint/tsc manually? Bypass is justified only when the hook fails on generated code, not to skip real errors." ;;
    esac
  fi
  jq -cn --arg c "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
  exit 0
fi

exit 0
