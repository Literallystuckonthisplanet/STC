#!/usr/bin/env bash
# H15 — hook: exec-offload-guard — enforces the "offload expensive Bash" lever
# (PEV §Step2 / playbook §Token economy).
# Event: PreToolUse(Bash).
#
# Pain: the reflexes "noisy script → ephemeral agent" and "output triage →
# agent" lived only as text in the playbook (📝 layer). Discipline does not
# hold. Escalation 📝→🤖 per the defect-ledger: the hook turns the reflex into
# a hard block with a deliberate bypass — you cannot silently run an expensive
# command in the main context.
#
# Segment-by-segment parse (like H11): the command is split on ; && || \n.
# BLOCK if a segment is:
#   A) a noisy data-script — a runner (pnpm/npm/yarn/npx/node/tsx/ts-node/bun/python)
#      + an action import|seed|publish|scrape|backfill|sync → it writes
#      row-by-row, should go to an ephemeral agent (run → return the summary,
#      not stdout);
#   B) `audit` without `--json` and without a redirect — a wall into the
#      window (residual to H11; test-runners are NOT taken — the reporter is
#      in the suite config; migrate is NOT taken — a small self-exec).
# Do NOT block: stdout redirected (>,>>,&>), the command carries `--json`,
# or it is not a run context.
# Bypass marker: `# in-main` — a deliberate run in main (small / needs dialogue).

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$cmd" ] && exit 0
case "$cmd" in *"# in-main"*) exit 0 ;; esac

block() {
  echo "🚫 H15 — expensive Bash in main: $1" >&2
  echo "Offload it to an ephemeral agent (run → return the summary/errors/counters, not the whole stdout) — the 'offload reading' lever (PEV §Step2)." >&2
  echo "A deliberate run in main (small / needs dialogue) → add '# in-main' to the command." >&2
  exit 2
}

# stdout redirected to a file? (>,>>,&> — yes; 2> — no)
redir_stdout() { printf '%s' "$1" | grep -qE '(^|[[:space:]])(1?>>?|&>>?)'; }

norm=$(printf '%s' "$cmd" | sed -E 's/&&/;/g; s/\|\|/;/g' | tr '\n' ';')

IFS=';' read -ra SEGS <<< "$norm"
for seg in "${SEGS[@]}"; do
  [ -z "${seg// /}" ] && continue
  redir_stdout "$seg" && continue          # output to a file → not the window, skip

  # B) audit as a wall (without --json)
  if printf '%s' "$seg" | grep -qE '(^|[[:space:]])(pnpm|npm|yarn)[[:space:]]+audit\b'; then
    printf '%s' "$seg" | grep -qE '\-\-json' || block "audit as a wall into the window (add --json, or the security-deps agent)"
  fi

  # A) noisy data-script: runner + action
  if printf '%s' "$seg" | grep -qiE '(^|[[:space:]])(pnpm|npm|yarn|npx|node|tsx|ts-node|bun|python3?)\b' \
     && printf '%s' "$seg" | grep -qiE '(import|seed|publish|scrape|backfill|sync)'; then
    block "noisy data-script (import/seed/publish/scrape/sync) — lots of output, little judgment → a cleanup/ephemeral agent"
  fi
done

exit 0
