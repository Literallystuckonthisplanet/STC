#!/bin/bash
# _apply_patch_normalize.sh — Codex apply_patch → Claude-shape stdin normalizer.
#
# PROBLEM: Codex edits go through the `apply_patch` tool. Unlike Claude's
# Write/Edit/MultiEdit, apply_patch carries the file path INSIDE the patch text
# (tool_input.command = "*** Begin Patch\n*** Update File: <path>\n..."),
# NOT in a separate tool_input.file_path field. STC's hooks (H05/H07/H09/H10/H16)
# read .tool_input.file_path and .tool_input.content — they'd see empty values.
#
# SOLUTION: this helper, sourced right after `INPUT=$(cat)` in a hook, rewrites
# $INPUT in place to add the Claude-shape fields when tool_name == apply_patch.
# The hook body then runs UNCHANGED (same jq accessors work). On non-apply_patch
# tools (Read/Glob/Grep/Bash) it is a no-op.
#
# Patch format (verified via learn.chatgpt.com/docs/hooks.md + OpenClaw + prempti):
#   *** Begin Patch
#   *** Add File: path/to/new.txt       (+content follows)
#   *** Update File: src/index.ts       (hunks follow)
#   *** Delete File: obsolete.txt
#   *** End Patch
# A single apply_patch call may touch MULTIPLE files. We surface the FIRST file
# path in tool_input.file_path (the hooks scope on "is this a memory/config/edit
# target" — one path is enough for the routing decision), and the full patch text
# in tool_input.content (so H05 can scan every line for secrets).
#
# Usage in a hook (right after reading stdin):
#   INPUT=$(cat)
#   source "${STC_NORMALIZE:-$NATIVE_DIR/hooks/_apply_patch_normalize.sh}" 2>/dev/null || true
#   # ... rest of hook reads .tool_input.file_path / .tool_input.content as before
#
# The `|| true` makes the source a safe no-op when the file is absent (Claude/
# ZCode never invoke apply_patch, and $NATIVE_DIR may be unset on those harnesses).
# On Codex the file is always present and $NATIVE_DIR resolves to ~/.codex.

_stc_normalize_apply_patch_input() {
  local tool_name
  tool_name=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
  [ "$tool_name" = "apply_patch" ] || return 0

  local patch first_file
  patch=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // .tool_input.input // empty' 2>/dev/null)
  # first *** (Add|Update|Delete) File: <path>  — path up to end of line
  first_file=$(printf '%s' "$patch" \
    | grep -m1 -oE '^\*\*\* (Add|Update|Delete) File: .+' \
    | sed -E 's/^\*\*\* (Add|Update|Delete) File: //')

  # Rewrite $INPUT: inject file_path + content so the hook body's jq accessors work.
  INPUT=$(printf '%s' "$INPUT" \
    | jq --arg fp "$first_file" --arg ct "$patch" \
        '.tool_input.file_path = $fp | .tool_input.content = $ct')
}

# run immediately on source (defines the fn, then applies it to $INPUT)
_stc_normalize_apply_patch_input

