#!/bin/bash
# H07 — hook: task-start guard (PreToolUse Write|Edit|MultiEdit)
#
# On the FIRST edit in a given project repo during a session
# (acknowledge-once, marker until exit):
#   - 🔒 I09/I07 dirty-tree: a dirty tree → block once. The uncommitted work may
#       belong to a parallel session, and a session cannot tell whose it is —
#       so the block does not ask, it directs: take a worktree of your own.
#       Answering the old "is this yours?" question by eye produced a mixed
#       commit on 2026-09-02 (hook H19 swallowed by a Roundtable commit).
#   - 💉 I07 worktree (FR-23): >1 git-worktree → nudge `git worktree list`
#       (same repo in flight at a parallel session; a worktree of the same
#       area → merge BEFORE starting).
#       When the tree is dirty, the note attaches to the block; when clean —
#       JIT-inject (exit 0).
# Scope: only git repositories; ${HARNESS_DIR} is skipped (own infra, no
# concern about a parallel session's WIP).
#
# Render-time vars: ${HARNESS_DIR} (the global agent config dir, e.g.
# ~/.claude), ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
SESSION=$(echo "$INPUT" | jq -r '.session_id // "nosession"')
[ -z "$FILE" ] && exit 0

USER_LANG="${USER_LANG:-en}"
HARNESS_DIR="${HARNESS_DIR}"

# Own infra/memory under ${HARNESS_DIR} — not our concern (no parallel WIP).
case "$FILE" in
  "${HARNESS_DIR}"/*) exit 0 ;;
esac

DIR=$(dirname "$FILE")
ROOT=$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -z "$ROOT" ] && exit 0

REPOHASH=$(printf '%s' "$ROOT" | shasum | cut -c1-12)

# --- метка активной сессии (I07) --------------------------------------------
# Замок H01 не даёт УНЕСТИ чужое, но не разводит сессии заранее: проверка
# грязного дерева молчит, если вторая сессия придёт на чистое. Метка закрывает
# именно это — репозиторий занят, приходи со своим worktree.
#
# Продлевается при каждой правке, а не только при первой: между правками бывают
# долгие паузы (обсуждение), и метка не должна протухать под работающей
# сессией. Срок годности — 120 минут: столько живёт самая долгая пауза, что я
# видел, и настолько же умершая сессия задержит репозиторий. Снять руками
# сказано в самом сообщении: гадать, жив ли владелец, из хука нельзя.
#
# Субагент не считается чужой сессией: у него свой session_id, но работает он
# от имени основной, и без этой ветки первый же builder блокировал бы себя.
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // ""' 2>/dev/null)
CLAIM="/tmp/stc-repo-claim-${REPOHASH}"
if [ -z "$AGENT_ID" ]; then
  NOW=$(date +%s)
  if [ -f "$CLAIM" ]; then
    OWNER=$(head -1 "$CLAIM" 2>/dev/null)
    STAMP=$(sed -n '2p' "$CLAIM" 2>/dev/null)
    AGE=$(( NOW - ${STAMP:-0} ))
    if [ "$OWNER" != "$SESSION" ] && [ "$AGE" -lt 7200 ]; then
      MINS=$(( AGE / 60 ))
      case "$USER_LANG" in
        ru) echo "BLOCKED (I07): в '$ROOT' уже работает другая сессия (отметилась $MINS мин назад). Индекс git общий — две сессии в одном дереве смешивают коммиты (так 02.09 хук H19 уехал в чужой коммит). Возьми свой worktree: 'git worktree add ../$(basename "$ROOT")-<задача> -b <ветка>' и правь там. Та сессия точно мертва — сними метку: 'rm $CLAIM' и повтори." >&2 ;;
        *)  echo "BLOCKED (I07): another session is already working in '$ROOT' (claimed $MINS min ago). The git index is shared — two sessions in one tree mix commits (that is how hook H19 landed in someone else's commit on 2026-09-02). Take your own worktree: 'git worktree add ../$(basename "$ROOT")-<task> -b <branch>' and edit there. If that session is certainly dead — drop the claim: 'rm $CLAIM' and retry." >&2 ;;
      esac
      exit 2
    fi
  fi
  printf '%s\n%s\n' "$SESSION" "$NOW" > "$CLAIM"
fi

MARKER="/tmp/stc-dirty-check-${SESSION}-${REPOHASH}"
[ -f "$MARKER" ] && exit 0

STATUS=$(git -C "$ROOT" status --porcelain 2>/dev/null)
# I07: worktree count (main + linked). >1 = parallel work on the repo.
WT_COUNT=$(git -C "$ROOT" worktree list 2>/dev/null | grep -c .)
: > "$MARKER"   # acknowledge-once: set before a possible block, retry passes

WT_NOTE=""
[ "${WT_COUNT:-0}" -gt 1 ] && \
  case "$USER_LANG" in
    ru) WT_NOTE=" ⚠️ I07: у репо $WT_COUNT worktree — проверь 'git worktree list'; ворктри той же области смержи ПЕРЕД стартом." ;;
    *) WT_NOTE=" ⚠️ I07: repo has $WT_COUNT worktrees — check 'git worktree list'; a worktree of the same area → merge BEFORE starting." ;;
  esac

if [ -n "$STATUS" ]; then
  case "$USER_LANG" in
    ru)
      echo "BLOCKED (один раз): грязное дерево в '$ROOT' перед первой правкой (I09/I07). Спрашивать «твой это WIP или чужой» бесполезно — из сессии это неразличимо, а 02.09 такой ответ на глаз стоил смешанного коммита. Решение принято: параллельные работы разводятся по worktree. Если незакоммиченное ниже не твоё — не разгребай его, а уйди в свой: 'git worktree add ../$(basename "$ROOT")-<задача> -b <ветка>' и работай там (скилл worktree). Если твоё — доведи и закоммить ЯВНЫМИ путями, без add -A.${WT_NOTE} Повтори правку после решения." >&2
      echo "--- git status --porcelain ---" >&2
      ;;
    *)
      echo "BLOCKED (once): dirty tree in '$ROOT' before the first edit (I09/I07). Asking whether this is YOUR WIP is useless — a session cannot tell, and answering by eye cost a mixed commit on 2026-09-02. The decision stands: parallel work goes into worktrees. If the uncommitted work below is not yours, do not unscramble it — take your own: 'git worktree add ../$(basename "$ROOT")-<task> -b <branch>' and work there (worktree skill). If it is yours, finish it and commit by EXPLICIT paths, never add -A.${WT_NOTE} Retry the edit once decided." >&2
      echo "--- git status --porcelain ---" >&2
      ;;
  esac
  echo "$STATUS" >&2
  exit 2
fi

# Clean tree, but parallel worktrees exist → JIT-nudge (not a block)
if [ -n "$WT_NOTE" ]; then
  case "$USER_LANG" in
    ru) MSG="🌿 task-start (I07):${WT_NOTE}" ;;
    *) MSG="🌿 task-start (I07):${WT_NOTE}" ;;
  esac
  jq -cn --arg c "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
fi
exit 0
