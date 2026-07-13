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
#   - 🔒 SEC-2/I05: before `git commit` → scan the staged diff (+ tracked
#     unstaged on -a/--all) for real API-key/token formats → BLOCK (exit 2).
#     Length-gated (mirrors H05); `secret-ok` on a line vouches for a public
#     value. A key in git history is a leak → rotate, don't just delete.
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

# Normalize whitespace before matching: collapse runs of spaces/tabs to one
# space (do NOT lowercase — git flags are case-sensitive, `-D` ≠ `-d`; the
# greps below use -i for case). A literal single-space, case-sensitive match let
# `GIT RESET --HARD` or `git  reset  --hard` (extra spaces / tab) slip past a
# control documented as a hard-block. The realistic adversary is prompt-injected
# content instructing a slightly-reformatted destructive command.
NORM=$(printf '%s' "$COMMAND" | tr -s '[:space:]' ' ')

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
  if echo "$NORM" | grep -qiE "$pattern"; then
    echo "BLOCKED: '$COMMAND' matches dangerous pattern '$pattern'. The user has prevented this operation." >&2
    exit 2
  fi
done

# I08 — push to main/master = RELEASE. Allowed only by explicit "releasing".
ACK="${RELEASE_ACK_FILE}"

if echo "$NORM" | grep -qiE 'git[[:space:]]+push'; then
  TO_MAIN=0
  echo "$NORM" | grep -qiE '\b(main|master)\b' && TO_MAIN=1
  # bare push (no branch) → current branch; on release that is main
  echo "$NORM" | grep -qiE 'git[[:space:]]+push([[:space:]]+(-[^[:space:]]+))*([[:space:]]+origin)?[[:space:]]*$' && TO_MAIN=1
  if [ "$TO_MAIN" = "1" ]; then
    if [ -n "$ACK" ] && [ -f "$ACK" ]; then rm -f "$ACK"; exit 0; fi  # ack present → pass once
    case "$USER_LANG" in
      ru) echo "BLOCKED: push в main = РЕЛИЗ (I08). Только по явному «релизим» пользователя. Пользователь сказал → прогони security-deps, затем 'touch ${ACK}' и повтори push (маркер одноразовый). Не говорил → НЕ пушь, спроси." >&2 ;;
      *) echo "BLOCKED: push to main = RELEASE (I08). Only by explicit 'releasing' from the user. If the user said so → run security-deps, then 'touch ${ACK}' and repeat the push (one-shot marker). If not → do NOT push, ask first." >&2 ;;
    esac
    exit 2
  fi
fi

# B1 — SEC-2/I05 secret-leak tripwire before commit (🤖 machine gate, hard-block).
# A real API-key/token in the staged diff is a LEAK the moment it's committed
# (git history is public/near-impossible to scrub, and vibe-coded keys reach
# public repos in minutes). Scan the diff that this commit will actually record;
# a hit blocks with exit 2. Length-gated patterns (mirrors H05) so a bare prefix
# mention or a placeholder does NOT fire. A line carrying `secret-ok` is the
# author's explicit vouch (a deliberate public value) and is skipped.
if echo "$NORM" | grep -qiE 'git[[:space:]]+commit'; then
  # Resolve the repo dir: a leading `cd <dir> && git commit …` means the commit
  # runs elsewhere than the hook's cwd — scan there, not here.
  GIT_DIR_ARG="."
  CD_DIR=$(printf '%s' "$COMMAND" | grep -oE 'cd[[:space:]]+[^&;|]+' | head -1 | sed -E 's/^cd[[:space:]]+//; s/[[:space:]]+$//' | tr -d '"'\''')
  if [ -n "$CD_DIR" ]; then GIT_DIR_ARG="${CD_DIR/#\~/$HOME}"; fi

  if git -C "$GIT_DIR_ARG" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # Added lines the commit will record: staged always; tracked-unstaged too
    # when -a/--all/-am sweeps them in.
    ADDED=$(git -C "$GIT_DIR_ARG" diff --cached --no-color 2>/dev/null | grep '^+' | grep -v '^+++')
    if echo "$NORM" | grep -qiE 'git[[:space:]]+commit([[:space:]]+-[a-z]*a[a-z]*| .*--all)'; then
      ADDED="$ADDED
$(git -C "$GIT_DIR_ARG" diff --no-color 2>/dev/null | grep '^+' | grep -v '^+++')"
    fi
    # Drop author-vouched lines before scanning.
    SCAN=$(printf '%s\n' "$ADDED" | grep -vE 'secret-ok')

    # label|ERE-pattern — token body required so a prefix mention won't fire.
    SECRET_PATTERNS=(
      "Notion token (ntn_)|ntn_[A-Za-z0-9]{30,}"
      "OpenAI/secret key (sk-)|sk-[A-Za-z0-9_-]{20,}"
      "GitHub PAT (ghp_)|ghp_[A-Za-z0-9]{30,}"
      "GitHub fine-grained PAT|github_pat_[A-Za-z0-9_]{60,}"
      "AWS access key id|AKIA[0-9A-Z]{16}"
      "Slack token (xox)|xox[baprs]-[A-Za-z0-9-]{20,}"
      "Resend key (re_)|re_[A-Za-z0-9]{20,}"
      "Google API key (AIza)|AIza[A-Za-z0-9_-]{30,}"
      "JWT (eyJ...)|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"
      "SECRET/TOKEN/PASSWORD assignment|(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY)[A-Z_]*['\"]?[[:space:]]*[=:][[:space:]]*['\"][A-Za-z0-9_/+.-]{16,}"
      "private key material|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"
    )
    for entry in "${SECRET_PATTERNS[@]}"; do
      label="${entry%%|*}"
      regex="${entry#*|}"
      if printf '%s' "$SCAN" | grep -qE "$regex"; then
        # Value is NEVER printed (audit lesson) — only the pattern name.
        case "$USER_LANG" in
          ru) echo "BLOCKED: похоже на секрет [$label] в staged-изменениях этого коммита (SEC-2/I05). Ключ в git = утечка (историю не вычистить), удалить из файла НЕДОСТАТОЧНО. Убери значение из кода → перевыпусти ключ (revoke+reissue) → подключи через \${SECRETS_ENV}. Значение не выведено. Ложное срабатывание / заведомо публичный ключ → допиши 'secret-ok' в ту строку. Разъяснение → SEC-2 в code_standard." >&2 ;;
          *)  echo "BLOCKED: looks like a secret [$label] in this commit's staged diff (SEC-2/I05). A key in git = a LEAK (history can't be scrubbed); deleting it from the file is NOT enough. Remove the value from code → ROTATE the key (revoke+reissue) → wire it via \${SECRETS_ENV}. Value not printed. False positive / deliberate public value → add 'secret-ok' on that line. Rationale → SEC-2 in code_standard." >&2 ;;
        esac
        exit 2
      fi
    done
  fi
fi

# B2 — I17 verify-gate + I09 commit-invariants before commit (JIT-inject, NOT block, FR-5).
if echo "$NORM" | grep -qiE 'git[[:space:]]+commit'; then
  case "$USER_LANG" in
    ru)
      MSG="✅ Перед коммитом — verify (I17) + инварианты коммита (I09).
VERIFY — проверил? СТАТИКА (lint/tsc/build по стеку). ГЛАЗАМИ (diff только нужное; нет секретов/ключей; для текстов — нет AI-маркеров). ДИНАМИКА (логика→тесты+code-reviewer; UI→Playwright/verify). Агентные по триггерам (security-arch/e2e/security-deps перед деплоем/legal).
ИНВАРИАНТЫ — одна задача=один коммит (логически цельный, не свалка); НЕ коммить незавершённое/сломанное даже «временно/чтобы не потерять»; нет проверки = нет коммита.
ПАМЯТЬ (I26) — коммит = точка завершения задачи с кодом: если он меняет состояние/решения проекта, обнови project_<name>.md (STATE/CHANGELOG) ДО коммита.
В ответе перечисли «Проверил: X✓ Y✓ Z✓»."
      ;;
    *)
      MSG="✅ Before commit — verify (I17) + commit-invariants (I09).
VERIFY — checked? STATIC (lint/tsc/build per the stack). EYES (diff = only the intended change; no secrets/keys; for text — no AI markers). DYNAMIC (logic → tests + code-reviewer; UI → Playwright/verify). Agent-triggered checks per playbook §Agent triggers.
INVARIANTS — one task = one commit (logically cohesive, not a dump); do NOT commit unfinished/broken even 'temporarily / to not lose it'; no check = no commit.
MEMORY (I26) — the commit is the completion point of a code task: if it changes project state/decisions, update project_<name>.md (STATE/CHANGELOG) BEFORE committing.
In your answer, list 'Checked: X✓ Y✓ Z✓'."
      ;;
  esac
  if echo "$NORM" | grep -qiE '(--no-verify|[[:space:]]-n([[:space:]]|$))'; then
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
