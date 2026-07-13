#!/bin/bash
# H14 — hook: buy-vs-build inject + ORCHESTRATOR GATE (FR-24, FR-27→FR-28; ADR-001).
# Pain: process rules in always-text recur (ADR-001). FR-27's exec-slice gate
# blocked the FIRST edit after plan mode once ("produce the table") — after
# that single ack, expensive main slid back into writing all the code itself.
# FR-28 makes the slice table BINDING: after a plan, main is an orchestrator —
# code is executed by cheap sub-agents (builder/cleanup) or in worktrees; main
# edits code only as a justified exception.
# Three behaviours, per-session /tmp markers:
#   1. PreToolUse(EnterPlanMode) → JIT-inject buy-vs-build + the orchestrator
#      contract, AND arm the gate ($ARM). The gate stays armed for the WHOLE
#      session (a plan was made → execution is dispatched, not typed by main).
#   2. PreToolUse(Write|Edit|MultiEdit) ORCHESTRATOR GATE → while armed, an
#      edit to a project file from MAIN is BLOCKED (exit 2), acknowledge-once
#      PER FILE: the per-file ack is dropped BEFORE exit 2 → the retry of the
#      SAME file passes (a justified exception is never locked out; the
#      justification lands in the transcript = free audit), the NEXT file
#      blocks again. Sub-agents (agent_id) pass — they ARE the executors.
#      Excluded: memory/docs/harness dirs, *.md, .env*, STC infra — the
#      orchestrator's own artifacts (briefs, specs, plans, memory) stay free.
#      Sessions that never entered plan mode are not gated (S-tasks).
#      Honest limit: verifies the pause + a stated WHY, not the reason's merit.
#   3. PreToolUse(Write) buy-vs-build BACKSTOP → a NEW source file created
#      WITHOUT plan mode: injects the buy-vs-build reminder. Not a gate.
# Inject = hookSpecificOutput.additionalContext (bare stdout on PreToolUse does
# NOT reach the model); block = exit 2 with stderr. Paired with code_standard
# [DEP-4] + to-spec/to-tasks + H21 (exit-plan-gate) + H04 (agent contract).
#
# Render-time vars: ${SESSION_ID} (injected by the harness), ${USER_LANG},
# ${HARNESS_DIR}, ${MEMORY_DIR}, ${DOCS_ROOT}, ${STC_CORE}.

INPUT=$(cat)
SESSION="${SESSION_ID:-$(echo "$INPUT" | jq -r '.session_id // "nosession"')}"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // ""')
USER_LANG="${USER_LANG:-en}"
M="/tmp/stc-buyvsbuild-${SESSION}"          # buy-vs-build inject: once/session
ARM="/tmp/stc-execslice-armed-${SESSION}"   # orchestrator gate armed (plan entered)

# 1) ORCHESTRATOR GATE — main editing project code after a plan → block once
#    per file. Sub-agents are the executors; they pass untouched.
case "$TOOL" in
  Write|Edit|MultiEdit)
    [ -n "$AGENT_ID" ] && exit 0            # sub-agent = the executor tier
    if [ -f "$ARM" ]; then
      FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
      [ -z "$FILE" ] && exit 0
      case "$FILE" in
        "${HARNESS_DIR}"/*|"${MEMORY_DIR}"/*|"${DOCS_ROOT}"/*|"${STC_CORE}"/*) exit 0 ;;  # own artifacts/infra
        */STC/*|*/.stc/*) exit 0 ;;         # STC source repo (infra sessions)
        *.md|*.env|*.env.*|*/.env) exit 0 ;; # briefs/specs/plans, secrets
      esac
      FACK="/tmp/stc-orch-ack-${SESSION}-$(echo "$FILE" | cksum | cut -d' ' -f1)"
      if [ ! -f "$FACK" ]; then
        : > "$FACK"                          # acknowledge-once PER FILE
        case "$USER_LANG" in
          ru) echo "🎼 FR-28 оркестратор-гейт: после плана main НЕ пишет код — блок исполняет builder/cleanup-агент или worktree (диспатч от файла тасков, бриф = секция спеки). Этот файл: $FILE. Это правда исключение (мелкая правка в пару строк при доводке/Verify, merge-конфликт)? → напиши в ответе ПОЧЕМУ, и повтори правку — второй раз по этому файлу гейт пропустит. Иначе — задиспатчь блок агенту." >&2 ;;
          *)  echo "🎼 FR-28 orchestrator gate: after a plan, main does NOT write code — the block is executed by a builder/cleanup agent or in a worktree (dispatch from the tasks file; the brief = the spec section). This file: $FILE. Is this genuinely an exception (a few-line touch-up during Verify, a merge conflict)? → state WHY in your reply and retry the edit — the second pass on this file goes through. Otherwise dispatch the block to an agent." >&2 ;;
        esac
        exit 2
      fi
    fi
    ;;
esac

MSG="🛒 buy-vs-build: before writing a non-trivial piece by hand — a new domain capability >~50 lines OR the territory of typical libraries (parsing/validation/dates/rate-limit/retries/files/crypto/state-machines/HTTP-clients) — evaluate a READY solution: the docs agent (Context7, known-library API) or the research agent (find+compare maturity/support/size). Fix the decision as an ADR line in the spec: 'Took X / by hand, because Y'. Do not invent what a mature library closes; do not pull a library for something trivial — the threshold is deliberate."

emit() { : > "$M"; jq -cn --arg c "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'; exit 0; }

case "$TOOL" in
  EnterPlanMode)
    : > "$ARM"    # arm the orchestrator gate for the REST of the session
    [ -f "$M" ] && exit 0       # buy-vs-build already injected this session → just arm
    emit "$MSG (Plan phase) 🎼 orchestrator (FR-28): route EVERY plan block to its executor — builder agent (feature code per spec, sonnet) / cleanup agent (mechanical, haiku) / worktree isolation for shared files / cheap-session (needs dialogue: prepare a brief, the user opens a sonnet session) / main ONLY as a justified exception (few-line Verify touch-ups, merge conflicts) with WHY written down. Show a block/size/executor/model table before the user approves. After the plan, main edits of project code are hard-blocked once per file." ;;
  Write)
    [ -n "$AGENT_ID" ] && exit 0
    [ -f "$M" ] && exit 0
    [ -f "$ARM" ] && exit 0     # plan mode was used → gate handles discipline
    FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
    [ -z "$FILE" ] && exit 0
    case "$FILE" in *"/.claude/"*|*/memory/*|*test*|*spec*|*.config.*|*.d.ts) exit 0 ;; esac
    case "$FILE" in *.ts|*.tsx|*.js|*.jsx|*.mjs|*.py) : ;; *) exit 0 ;; esac
    [ -e "$FILE" ] && exit 0   # file already exists = not a new module
    emit "$MSG (backstop: you are creating a new module WITHOUT plan mode — evaluate a ready solution BEFORE code)." ;;
  *) exit 0 ;;
esac
