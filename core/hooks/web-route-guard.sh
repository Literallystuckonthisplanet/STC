#!/usr/bin/env bash
# H13 — hook: web-route-guard — FR-17 (Sol 2, web channel): the web must go
# through a sub-agent.
# Event: PreToolUse(WebSearch|WebFetch).
#
# Pain: WebSearch/WebFetch from main dump results into the main context
# (expensive, like Playwright-in-main) and repeat. Rule I18 "web only via the
# research/docs sub-agent" is advisory, recidivised. A sub-agent isolates the
# output: a repeat by main doesn't hit.
#
# BLOCK (hard, acknowledge-once): a call from main (no agent_id) → exit 2
#   once/session, force a route choice. In a sub-agent (agent_id present) →
#   silently pass.
# OBSERVE: each call writes agent_id/agent_type to
#   /tmp/stc-web-route-observe.log (harmless telemetry; confirms the field
#   populates in this harness).
# Marker acknowledge-once: /tmp/stc-webroute-<session>.acked is set BEFORE
#   exit 2 → a repeat of the same call passes (deliberate web-in-main is not
#   locked forever, like H07).

input=$(cat)
session=$(echo "$input" | jq -r '.session_id // "nosess"' 2>/dev/null)
agent_id=$(echo "$input" | jq -r '.agent_id // ""' 2>/dev/null)
agent_type=$(echo "$input" | jq -r '.agent_type // ""' 2>/dev/null)
tool=$(echo "$input" | jq -r '.tool_name // ""' 2>/dev/null)

# OBSERVE — collect facts about field population in this harness
echo "$(date +%H:%M:%S) tool=${tool} agent_id=[${agent_id}] agent_type=[${agent_type}] session=${session}" \
  >> /tmp/stc-web-route-observe.log

# Sub-agent (agent_id present) → sanctioned path, stay silent
[ -n "$agent_id" ] && exit 0

# main → HARD-BLOCK once/session (acknowledge-once: marker BEFORE exit 2, retry passes)
marker="/tmp/stc-webroute-${session}.acked"
[ -f "$marker" ] && exit 0
: > "$marker"
echo "🌐 BLOCKED (once, I18/FR-17): ${tool} from main dumps output into the main context (expensive) and breeds duplicates. Run it through the research/docs sub-agent — it isolates the result; only a summary returns to main. If you deliberately need it in main → repeat the call, it will pass." >&2
exit 2
