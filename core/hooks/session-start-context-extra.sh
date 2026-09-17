#!/bin/bash
# Claude's second bounded H06 result: PEV and session rules.
# The primary hook owns behavior rules and the audit-cadence nudge.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN="$SCRIPT_DIR/session-start-context.stc.sh"
[ -f "$MAIN" ] || MAIN="$SCRIPT_DIR/session-start-context.sh"
STC_H06_PART=secondary exec bash "$MAIN"
