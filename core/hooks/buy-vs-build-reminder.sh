#!/bin/bash
# H14 — hook: buy-vs-build inject + exec-slice HARD GATE (FR-24, FR-27; ADR-001).
# Pain: process rules in always-text recur (ADR-001). The exec-slice used to be
# a passive once-per-session nudge — discipline, which slips. This gate makes it
# a wall: an M/L task cannot slide into coding without routing its blocks.
# Three behaviours, three markers (all /tmp, per-session):
#   1. PreToolUse(EnterPlanMode) → JIT-inject buy-vs-build + the exec-slice
#      table reminder, AND arm the exec-slice gate ($ARM), clearing any prior
#      ack so each plan-entry gets one gate.
#   2. PreToolUse(Write|Edit|MultiEdit) exec-slice GATE → the FIRST code edit
#      after plan mode is BLOCKED (exit 2) until acknowledged. acknowledge-once:
#      the ack marker ($ACK) is dropped BEFORE exit 2 → the retry passes (like
#      H07/H13); a deliberate proceed is never locked out. Fires only when a
#      plan was entered ($ARM present) → small tasks that skip planning are not
#      gated. Honest limit: verifies the ACK, not the slice's quality.
#   3. PreToolUse(Write) buy-vs-build BACKSTOP → a NEW source file created
#      WITHOUT plan mode (skipped the plan, coding right away): a proxy for
#      "non-trivial". Injects the buy-vs-build reminder. Not a complexity meter.
# Inject = hookSpecificOutput.additionalContext (bare stdout on PreToolUse does
# NOT reach the model); block = exit 2 with stderr. Paired with code_standard
# [DEP-4] + to-spec. Marker $M gates the buy-vs-build inject to once/session.
#
# Render-time vars: ${SESSION_ID} (injected by the harness), ${USER_LANG}.

INPUT=$(cat)
SESSION="${SESSION_ID:-$(echo "$INPUT" | jq -r '.session_id // "nosession"')}"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
M="/tmp/stc-buyvsbuild-${SESSION}"          # buy-vs-build inject: once/session
ARM="/tmp/stc-execslice-armed-${SESSION}"   # exec-slice gate armed (plan entered)
ACK="/tmp/stc-execslice-acked-${SESSION}"   # exec-slice gate acknowledged

# 1) exec-slice HARD GATE — before the buy-vs-build once-marker, and independent
#    of it. Blocks the first code edit after plan mode, once.
case "$TOOL" in
  Write|Edit|MultiEdit)
    if [ -f "$ARM" ] && [ ! -f "$ACK" ]; then
      : > "$ACK"; rm -f "$ARM"
      echo "🚦 FR-27 exec-slice gate — first edit after plan mode. Before coding an M/L task, produce the block/size/executor/model table and route EACH block to its cheapest safe tier: sub-haiku (mechanical) / sub-sonnet (isolated judgment: review/tests/research) / cheap-session (needs dialogue, low error-risk — prepare a brief, user opens a sonnet session) / main (architecture/forks/uncertainty; in doubt → main, but write WHY). Retry the edit to proceed — acknowledged once for this plan." >&2
      exit 2
    fi
    ;;
esac

MSG="🛒 buy-vs-build: before writing a non-trivial piece by hand — a new domain capability >~50 lines OR the territory of typical libraries (parsing/validation/dates/rate-limit/retries/files/crypto/state-machines/HTTP-clients) — evaluate a READY solution: the docs agent (Context7, known-library API) or the research agent (find+compare maturity/support/size). Fix the decision as an ADR line in the spec: 'Took X / by hand, because Y'. Do not invent what a mature library closes; do not pull a library for something trivial — the threshold is deliberate."

emit() { : > "$M"; jq -cn --arg c "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'; exit 0; }

case "$TOOL" in
  EnterPlanMode)
    : > "$ARM"; rm -f "$ACK"    # arm the exec-slice gate for the first edit of THIS plan
    [ -f "$M" ] && exit 0       # buy-vs-build already injected this session → just arm
    emit "$MSG (Plan phase) ⚙️ exec-slice (FR-27): for every M/L plan block, mark its CHEAPEST safe executor — sub-haiku (mechanical) / sub-sonnet (isolated judgment: review/tests/research) / cheap-session (needs dialogue but low error-risk; prepare a brief file, user opens a sonnet session) / main (architecture, forks, uncertainty). Show a block/size/executor/model table before the user approves. In doubt → main, but write WHY main. The first edit after this will BE BLOCKED once until you produce the table." ;;
  Write)
    [ -f "$M" ] && exit 0
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -z "$FILE" ] && exit 0
    case "$FILE" in *"/.claude/"*|*/memory/*|*test*|*spec*|*.config.*|*.d.ts) exit 0 ;; esac
    case "$FILE" in *.ts|*.tsx|*.js|*.jsx|*.mjs|*.py) : ;; *) exit 0 ;; esac
    [ -e "$FILE" ] && exit 0   # file already exists = not a new module
    emit "$MSG (backstop: you are creating a new module WITHOUT plan mode — evaluate a ready solution BEFORE code)." ;;
  *) exit 0 ;;
esac
