#!/usr/bin/env bash
# H12 — hook: acquire-dedup-guard — FR-17 (soft) anti-duplicate information
# gathering (the local channel).
# Event: PreToolUse(Read|Grep|Glob|Bash).
#
# Pain: in a session the same searches/reads repeat (re-grep, re-read the same
# file/chunk) → re-inject of already-gathered data into context, extra turns.
# An advisory rule doesn't hold this. The hook keeps a session log of
# normalized targets and on an EXACT repeat softly nudges (the result is
# already above in context).
#
# INJECT (additionalContext, NOT a block), once-per-target: a repeat target →
#   "already gathered this in the session, don't duplicate". Keys:
#   read:<file> · grep:<pattern>:<path> · glob:<pattern>:<path> ·
#   bash:<normalized command> (only if the command is a search: grep/rg/ag/find).
#   For Read the TARGET is the FILE (any range): re-reading the same file — even
#   a different chunk/offset — nudges, because the file is already in context.
#   This is the near-dup fix (2026-07-12): keying on file+offset made the guard
#   "forget" — a slightly different range read the same file in again silently.
#   Different pattern/path = different target (grep/glob/bash unchanged).
# Logs: /tmp/stc-acquire-<session>.log (seen hashes) +
#   /tmp/stc-acquire-<session>-<hash>.nudged (nudged once). No escape hatch
#   (not a block — repeat if the data changed / you need it fresh).

input=$(cat)
tool=$(echo "$input" | jq -r '.tool_name // ""' 2>/dev/null)
session=$(echo "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
ti() { echo "$input" | jq -r ".tool_input.$1 // \"\"" 2>/dev/null; }

case "$tool" in
  Read)  key="read:$(ti file_path)" ;;   # near-dup: the FILE is the target (any range) — re-reading it any-which-way nudges
  Grep)  key="grep:$(ti pattern):$(ti path):$(ti glob)" ;;
  Glob)  key="glob:$(ti pattern):$(ti path)" ;;
  Bash)  cmd=$(ti command)
         printf '%s' "$cmd" | grep -qE '(^|[|;&[:space:]])(grep|rg|ag|find)[[:space:]]' || exit 0
         key="bash:$(printf '%s' "$cmd" | tr -s '[:space:]' ' ')" ;;
  *) exit 0 ;;
esac
[ -z "${key//[a-z:]/}" ] && exit 0   # empty target → skip

log="/tmp/stc-acquire-${session}.log"
h=$(printf '%s' "$key" | cksum | cut -d' ' -f1)

if grep -qx "$h" "$log" 2>/dev/null; then
  nudged="/tmp/stc-acquire-${session}-${h}.nudged"
  if [ ! -f "$nudged" ]; then
    touch "$nudged"
    short=$(printf '%s' "$key" | cut -c1-70)
    msg="🔁 FR-17: «${short}» already gathered this session — the result is above in context, don't duplicate. (Data changed / need it fresh → continue.)"
    jq -cn --arg c "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
  fi
else
  echo "$h" >> "$log"
fi
exit 0
