#!/bin/bash
# STC statusline (Claude Code) — shows model, dir, context-window fill.
# Threshold alerts by % usage: <50 green, 50–75 yellow, >75 red.
# Data source: JSON on stdin from Claude Code (statusLine).
#
# This is harness glue: deploy.py can't derive it from adapter.yaml, so it
# lives next to the adapter and is referenced by harness_facts.statusline.
# Wired in settings.json under the `statusLine` key.

input=$(cat)

# --- model and dir (defensive: several possible keys) ---
model=$(printf '%s' "$input" | jq -r '.model.display_name // .model.id // "claude"' 2>/dev/null)
dir=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // ""' 2>/dev/null)
dir=$(basename "$dir" 2>/dev/null)

# --- context: try used_percentage, else compute from tokens ---
used_pct=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty' 2>/dev/null)
in_tok=$(printf '%s'  "$input" | jq -r '.context_window.total_input_tokens // empty' 2>/dev/null)
win=$(printf '%s'     "$input" | jq -r '.context_window.context_window_size // empty' 2>/dev/null)

if [ -z "$used_pct" ] && [ -n "$in_tok" ] && [ -n "$win" ] && [ "$win" != "0" ]; then
  used_pct=$(awk "BEGIN{printf \"%.0f\", ($in_tok/$win)*100}")
fi

# ANSI colors
G='\033[32m'; Y='\033[33m'; R='\033[31m'; DIM='\033[2m'; RST='\033[0m'

ctx=""
if [ -n "$used_pct" ]; then
  pct=$(printf '%.0f' "$used_pct" 2>/dev/null || echo "$used_pct")
  if   [ "$pct" -ge 75 ]; then col="$R";  mark="🔴"
  elif [ "$pct" -ge 50 ]; then col="$Y";  mark="🟡"
  else                         col="$G";  mark="🟢"
  fi
  tok_note=""
  [ -n "$in_tok" ] && tok_note=" ${in_tok}tok"
  ctx=" ${col}${mark} ctx ${pct}%${tok_note}${RST}"
  [ "$pct" -ge 75 ] && ctx="${ctx} ${R}→ /save-and-compact${RST}"
else
  ctx=" ${DIM}ctx n/a${RST}"
fi

printf "${DIM}%s${RST}  ${DIM}%s${RST}%b" "$model" "$dir" "$ctx"
