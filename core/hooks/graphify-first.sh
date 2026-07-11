#!/bin/bash
# H18 — hook: graphify-first (code-graph over grep-chains)
# PreToolUse(Grep|Bash): in a repo where a code-graph is already built
# (graphify-out/graph.json exists), the FIRST grep-style search is BLOCKED once
# with a nudge to use `graphify query` for "how/why/connect/what-calls"
# questions — a built graph that nobody queries is wasted. acknowledge-once: the
# marker is set BEFORE exit 2, so repeating the same call passes (grep is still
# right for an exact-string lookup; the block just forces one conscious choice).
#
# Scope: only Grep, or a Bash grep/rg/ag/git-grep. A plain path lookup (find/ls)
# is not gated. Repos WITHOUT a graph are never gated (nothing to query).
#
# Bypass: after the one-shot block the retry passes; or set the marker yourself.
#
# Render-time vars: ${SESSION_ID} (per-session ack; runtime from stdin below).

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
USER_LANG="${USER_LANG:-en}"

# Determine the search target dir + whether this is a grep-style search.
TARGET=""
case "$TOOL" in
  Grep)
    TARGET=$(echo "$INPUT" | jq -r '.tool_input.path // empty')
    ;;
  Bash)
    CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
    # only real grep-style content search (not a bare filename find)
    echo "$CMD" | grep -qE '(^|[|&;[:space:]])(grep|rg|ag)[[:space:]]' || \
      echo "$CMD" | grep -qE 'git[[:space:]]+grep' || exit 0
    TARGET=$(pwd)
    ;;
  *) exit 0 ;;
esac
[ -z "$TARGET" ] && TARGET=$(pwd)
# resolve to a directory
[ -f "$TARGET" ] && TARGET=$(dirname "$TARGET")
[ -d "$TARGET" ] || exit 0

# Walk up to a repo root that has a built graph (graphify-out/graph.json).
GRAPH=""
dir="$TARGET"; depth=0
while [ "$dir" != "/" ] && [ "$dir" != "." ] && [ "$depth" -lt 12 ]; do
  for cand in "$dir/graphify-out/graph.json" "$dir/src/graphify-out/graph.json"; do
    [ -f "$cand" ] && GRAPH="$cand" && break
  done
  [ -n "$GRAPH" ] && break
  dir=$(dirname "$dir"); depth=$((depth+1))
done
[ -z "$GRAPH" ] && exit 0   # no graph in this repo → nothing to enforce

# acknowledge-once per repo per session.
REPO_SLUG=$(printf '%s' "$dir" | tr -c 'a-zA-Z0-9' '-')
MARKER="/tmp/stc-graphify-${SESSION_ID:-nosession}-${REPO_SLUG}"
[ -f "$MARKER" ] && exit 0
: > "$MARKER"   # set BEFORE exit 2 so the retry passes (acknowledge-once)

case "$USER_LANG" in
  ru)
    echo "🔎 graphify-first (H18): в этом репо УЖЕ построен code-graph ($GRAPH). Для вопросов «как связано / что вызывает / где используется / радиус изменения» — \`graphify query \"<вопрос>\" --graph $GRAPH\` (или \`affected\`/\`explain\`/\`path\`) даёт ответ по графу, а не grep-цепочкой (граф компаундится, grep — нет). Нужен именно точный поиск строки — повтори вызов (этот блок одноразовый на сессию/репо)." >&2
    ;;
  *)
    echo "🔎 graphify-first (H18): this repo already has a built code-graph ($GRAPH). For 'how does X connect / what calls this / where is it used / blast radius' questions, \`graphify query \"<q>\" --graph $GRAPH\` (or \`affected\`/\`explain\`/\`path\`) answers from the graph instead of a grep-chain (the graph compounds, grep does not). If you truly need an exact-string search — repeat the call (this block is one-shot per session/repo)." >&2
    ;;
esac
exit 2
