#!/bin/bash
# H14 — hook: buy-vs-build reminder (FR-24; ADR-001 JIT-inject).
# Two entry points, one shared once-per-session marker (fires on whichever is
# earlier):
#   1. PreToolUse(EnterPlanMode) — on entering planning.
#   2. PreToolUse(Write) BACKSTOP — creating a NEW source file without plan
#      mode (a hole: skipped the plan, coding right away). A proxy for
#      "non-trivial": a new file (not yet on disk) under a code extension,
#      outside test/config/infra/memory. Does not detect complexity — a
#      backstop, not a precise measure.
# Injects via hookSpecificOutput.additionalContext (bare stdout on PreToolUse
# does NOT reach the model). Paired with code_standard [DEP-4] and to-spec.
#
# Render-time vars: ${SESSION_ID} (injected by the harness), ${USER_LANG}.

INPUT=$(cat)
SESSION="${SESSION_ID:-$(echo "$INPUT" | jq -r '.session_id // "nosession"')}"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
M="/tmp/stc-buyvsbuild-${SESSION}"
[ -f "$M" ] && exit 0

MSG="🛒 buy-vs-build: before writing a non-trivial piece by hand — a new domain capability >~50 lines OR the territory of typical libraries (parsing/validation/dates/rate-limit/retries/files/crypto/state-machines/HTTP-clients) — evaluate a READY solution: the docs agent (Context7, known-library API) or the research agent (find+compare maturity/support/size). Fix the decision as an ADR line in the spec: 'Took X / by hand, because Y'. Do not invent what a mature library closes; do not pull a library for something trivial — the threshold is deliberate."

emit() { : > "$M"; jq -cn --arg c "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'; exit 0; }

case "$TOOL" in
  EnterPlanMode)
    emit "$MSG (Plan phase)" ;;
  Write)
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -z "$FILE" ] && exit 0
    case "$FILE" in *"/.claude/"*|*/memory/*|*test*|*spec*|*.config.*|*.d.ts) exit 0 ;; esac
    case "$FILE" in *.ts|*.tsx|*.js|*.jsx|*.mjs|*.py) : ;; *) exit 0 ;; esac
    [ -e "$FILE" ] && exit 0   # file already exists = not a new module
    emit "$MSG (backstop: you are creating a new module WITHOUT plan mode — evaluate a ready solution BEFORE code)." ;;
  *) exit 0 ;;
esac
