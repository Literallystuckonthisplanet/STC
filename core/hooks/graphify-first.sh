#!/bin/bash
# H18 — hook: project-first (snapshot + code-graph before poking around)
#
# Two branches, one question: "what is the first place to look in this project?"
#
# 1. PreToolUse(Grep|Bash-grep) — in a repo where a code-graph is already built
#    (graphify-out/graph.json exists), the FIRST grep-style search is BLOCKED
#    once with a nudge to use `graphify query` for "how/why/connect/what-calls"
#    questions — a built graph that nobody queries is wasted. acknowledge-once:
#    the marker is set BEFORE exit 2, so repeating the same call passes (grep is
#    still right for an exact-string lookup; the block just forces one conscious
#    choice).
#
# 2. PreToolUse(Read|Glob|Bash) — the FIRST touch of a project directory injects
#    a pointer to that project's generated SNAPSHOT.md and graph, once per
#    project per session. NOT a block: reading is legitimate, the snapshot is
#    just cheaper than reconstructing status by hand. This branch closes the gap
#    that `ls`/`find`/`Read` opened — branch 1 gates content search only, so a
#    plain directory walk used to reach the project with no pointer at all,
#    while the routing rule (session.md "Named project → its SNAPSHOT.md") had
#    no enforcement anywhere.
#
# Scope: a directory that carries a project marker (SNAPSHOT.md or
# graphify-out/graph.json). The agent's own infra (${HARNESS_DIR}, ${MEMORY_DIR},
# ${STC_CORE}) is excluded — it has its own routing. Reading the snapshot or the
# graph itself never fires (that IS the desired behaviour).
#
# Bypass: after the one-shot block the retry passes; or set the marker yourself.
#
# Render-time vars: ${SESSION_ID} (per-session ack; runtime from stdin below),
# ${USER_LANG} (message language: en|ru, default en), ${HARNESS_DIR},
# ${MEMORY_DIR}, ${STC_CORE} (excluded roots).

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
USER_LANG="${USER_LANG:-en}"

# --- classify the call ------------------------------------------------------
# GREP_STYLE=1 → branch 1 (block once). Otherwise → branch 2 (pointer once).
GREP_STYLE=0
TARGET=""
case "$TOOL" in
  Grep)
    GREP_STYLE=1
    TARGET=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
    ;;
  Bash)
    CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    if echo "$CMD" | grep -qE '(^|[|&;[:space:]])(grep|rg|ag)[[:space:]]' || \
       echo "$CMD" | grep -qE 'git[[:space:]]+grep'; then
      GREP_STYLE=1
      TARGET=$(pwd)
    else
      # A path lookup (ls/find/cat/...) still lands in a project — take the
      # first path-looking token so `ls ~/Work/projects/foo` is attributed to
      # foo and not to the shell's cwd.
      TARGET=$(printf '%s' "$CMD" | tr ' \t' '\n\n' \
        | sed "s|^~|${HOME}|" \
        | grep -E '^/' | head -1)
      [ -z "$TARGET" ] && TARGET=$(pwd)
    fi
    ;;
  Read)
    TARGET=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    ;;
  Glob)
    TARGET=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
    ;;
  *) exit 0 ;;
esac
[ -z "$TARGET" ] && TARGET=$(pwd)

# Reading the snapshot or the graph itself is already the right move.
case "$TARGET" in
  */SNAPSHOT.md|*/graph.json) exit 0 ;;
esac

# Strip a trailing glob segment so `.../foo/**/*.ts` still resolves to a dir.
TARGET="${TARGET%%\**}"
[ -f "$TARGET" ] && TARGET=$(dirname "$TARGET")
[ -d "$TARGET" ] || TARGET=$(dirname "$TARGET")
[ -d "$TARGET" ] || exit 0

# The agent's own infra routes itself — never gate it.
for excluded in "${HARNESS_DIR}" "${MEMORY_DIR}" "${STC_CORE}"; do
  [ -n "$excluded" ] || continue
  case "$TARGET/" in "${excluded%/}/"*) exit 0 ;; esac
done

# --- walk up to the project root -------------------------------------------
# A project root carries a built graph and/or a generated snapshot.
GRAPH=""; SNAP=""; ROOT=""
dir="$TARGET"; depth=0
while [ "$dir" != "/" ] && [ "$dir" != "." ] && [ "$depth" -lt 12 ]; do
  for cand in "$dir/graphify-out/graph.json" "$dir/src/graphify-out/graph.json"; do
    [ -f "$cand" ] && GRAPH="$cand" && break
  done
  [ -f "$dir/SNAPSHOT.md" ] && SNAP="$dir/SNAPSHOT.md"
  if [ -n "$GRAPH" ] || [ -n "$SNAP" ]; then ROOT="$dir"; break; fi
  dir=$(dirname "$dir"); depth=$((depth+1))
done
[ -n "$ROOT" ] || exit 0

REPO_SLUG=$(printf '%s' "$ROOT" | tr -c 'a-zA-Z0-9' '-')

# --- branch 1: grep-style search in a graphed repo → block once -------------
if [ "$GREP_STYLE" = "1" ]; then
  [ -z "$GRAPH" ] && exit 0   # no graph in this repo → nothing to enforce
  MARKER="/tmp/stc-graphify-${SESSION_ID:-nosession}-${REPO_SLUG}"
  [ -f "$MARKER" ] && exit 0
  : > "$MARKER"   # set BEFORE exit 2 so the retry passes (acknowledge-once)
  case "$USER_LANG" in
    ru)
      echo "🔎 graphify-first (H18): в этом репо УЖЕ построен code-graph ($GRAPH). Для вопросов «как связано / что вызывает / где используется / радиус изменения» — \`graphify query \"<вопрос>\" --graph $GRAPH\` (или \`affected\`/\`explain\`/\`path\`) даёт ответ по графу, а не grep-цепочкой (граф компаундится, grep — нет). Полезный ответ → \`graphify save-result\` (наполняет LESSONS, llm-wiki-петля; reflect в регулярном maintenance или по запросу). Нужен именно точный поиск строки — повтори вызов (этот блок одноразовый на сессию/репо)." >&2
      ;;
    *)
      echo "🔎 graphify-first (H18): this repo already has a built code-graph ($GRAPH). For 'how does X connect / what calls this / where is it used / blast radius' questions, \`graphify query \"<q>\" --graph $GRAPH\` (or \`affected\`/\`explain\`/\`path\`) answers from the graph instead of a grep-chain (the graph compounds, grep does not). A useful answer → \`graphify save-result\` (feeds LESSONS, the llm-wiki loop; reflect in scheduled maintenance or on request). If you truly need an exact-string search — repeat the call (this block is one-shot per session/repo)." >&2
      ;;
  esac
  exit 2
fi

# --- branch 2: first touch of a project → pointer once ----------------------
ENTRY_MARKER="/tmp/stc-projectfirst-${SESSION_ID:-nosession}-${REPO_SLUG}"
[ -f "$ENTRY_MARKER" ] && exit 0
: > "$ENTRY_MARKER"

PROJECT=$(basename "$ROOT")
PARTS=""
if [ -n "$SNAP" ]; then
  SNAP_AGE=$(date -r "$SNAP" '+%d.%m' 2>/dev/null || echo '?')
  case "$USER_LANG" in
    ru) PARTS="снапшот $SNAP (сгенерирован $SNAP_AGE)" ;;
    *)  PARTS="snapshot $SNAP (generated $SNAP_AGE)" ;;
  esac
fi
if [ -n "$GRAPH" ]; then
  GRAPH_AGE=$(date -r "$GRAPH" '+%d.%m' 2>/dev/null || echo '?')
  case "$USER_LANG" in
    ru) PARTS="${PARTS:+$PARTS, }граф $GRAPH (построен $GRAPH_AGE)" ;;
    *)  PARTS="${PARTS:+$PARTS, }graph $GRAPH (built $GRAPH_AGE)" ;;
  esac
fi

case "$USER_LANG" in
  ru)
    MSG="🗺️ project-first (H18): проект «$PROJECT» — первое место, куда смотреть: $PARTS. Статус, ветка, HEAD, указатели на память и открытые вопросы уже собраны там; про связи кода спрашивай граф (\`graphify query\`), а не обход каталогов. Восстанавливать это руками через ls/find — дороже и врёт (сборка свежее ручного обхода)."
    ;;
  *)
    MSG="🗺️ project-first (H18): project '$PROJECT' — look here first: $PARTS. Status, branch, HEAD, memory pointers and open items are already collected there; for code relationships ask the graph (\`graphify query\`) instead of walking directories. Reconstructing this by hand with ls/find costs more and drifts (the generated view is fresher)."
    ;;
esac

jq -cn --arg c "$MSG" \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
exit 0
