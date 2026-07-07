#!/bin/bash
# H07 — hook: task-start guard (PreToolUse Write|Edit|MultiEdit)
#
# On the FIRST edit in a given project repo during a session
# (acknowledge-once, marker until exit):
#   - 🔒 I09 dirty-tree: a dirty tree → block once (uncommitted work may be a
#       parallel session's WIP — resolve/commit/unscramble BEFORE starting).
#   - 💉 I07 worktree (FR-23): >1 git-worktree → nudge `git worktree list`
#       (same repo in flight at a parallel session; a worktree of the same
#       area → merge BEFORE starting).
#       When the tree is dirty, the note attaches to the block; when clean —
#       JIT-inject (exit 0).
# Scope: only git repositories; ${HARNESS_DIR} is skipped (own infra, no
# concern about a parallel session's WIP).
#
# Render-time vars: ${HARNESS_DIR} (the global agent config dir, e.g.
# ~/.claude or ~/.zcode), ${USER_LANG} (en|ru, default en).

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
      echo "BLOCKED (один раз): грязное дерево в '$ROOT' перед первой правкой (I09). Незакоммиченное ниже — это ТВОЙ WIP или чужой (параллельная сессия)? Реши/закоммить/разгреби до старта, иначе смешаешь изменения.${WT_NOTE} Повтори правку после проверки." >&2
      echo "--- git status --porcelain ---" >&2
      ;;
    *)
      echo "BLOCKED (once): dirty tree in '$ROOT' before the first edit (I09). The uncommitted work below — is it YOUR WIP or someone else's (a parallel session)? Resolve/commit/unscramble before starting, or you'll mix changes.${WT_NOTE} Retry the edit after checking." >&2
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
