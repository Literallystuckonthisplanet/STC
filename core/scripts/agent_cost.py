#!/usr/bin/env python3
"""agent_cost.py (FR-21) — deterministic cost of a sub-agent run.

Why: per-subagent cost is not exposed anywhere directly (neither /cost — that is
cumulative for the session — nor to hooks). The only verified source is the
sub-agent transcript `<session>/subagents/agent-<id>.jsonl` (per-message usage
+ model) + `.meta.json` (agentType/toolUseId). We sum Σ(usage × model price).
This replaces a manual /cost for FR-16 (filling the Cost column of the research
index) — the number is deterministic, not eyeballed.

Harness-neutral: the projects dir is resolved from STC_PROJECTS_DIR (set by
deploy.py at render time, or by the caller). Defaults to the Claude Code shape
(~/.claude/projects) so it runs out of the box on a Claude host; on ZCode or a
custom layout, point STC_PROJECTS_DIR at the harness's session/projects root.

Modes:
  --latest             the most recent sub-agent (by mtime) — DEFAULT
  --agent <id>         a specific agent-<id>
  --session <sid>      all sub-agents in session <sid>
  --type <agentType>   filter by type (research/general-purpose/...)
  --since YYYY-MM-DD   only sub-agents newer than date (by mtime)
  --json               machine output

Example for FR-16: after a research agent →
  python3 core/scripts/agent_cost.py --latest
insert the $-total into the Cost column of the research index.
"""
import argparse, glob, json, os, sys
from datetime import datetime, timezone

PROJECTS = os.environ.get("STC_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")

# Prices $ / 1M tokens (input, output). Cache: write(5m)=1.25×in, read=0.1×in.
# Source: claude-api skill (current as of 2026-06). Unknown model → opus default + flag.
PRICES = {
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-opus-4-6":   (5.0, 25.0),
    "claude-fable-5":    (10.0, 50.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
DEFAULT_PRICE = (5.0, 25.0)
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


def find_jsonls():
    # <projects>/<project>/<session>/subagents/agent-<id>.jsonl
    return glob.glob(os.path.join(PROJECTS, "*", "*", "subagents", "agent-*.jsonl"))


def cost_of(jsonl):
    """Return dict: per-model usage + cost + meta. None if the file is empty/broken."""
    meta_path = jsonl[:-6] + ".meta.json"
    meta = {}
    if os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path))
        except Exception:
            pass
    per_model = {}  # model -> [in, out, cache_write, cache_read]
    for line in open(jsonl):
        try:
            o = json.loads(line)
        except Exception:
            continue
        msg = o.get("message")
        if not isinstance(msg, dict):
            continue
        u = msg.get("usage")
        if not u:
            continue
        m = msg.get("model") or "unknown"
        acc = per_model.setdefault(m, [0, 0, 0, 0])
        acc[0] += u.get("input_tokens", 0) or 0
        acc[1] += u.get("output_tokens", 0) or 0
        acc[2] += u.get("cache_creation_input_tokens", 0) or 0
        acc[3] += u.get("cache_read_input_tokens", 0) or 0
    if not per_model:
        return None
    total_usd = 0.0
    unknown = False
    breakdown = []
    for m, (i, out, cw, cr) in per_model.items():
        price = PRICES.get(m)
        if price is None:
            unknown = True
            price = DEFAULT_PRICE
        pin, pout = price
        usd = (i * pin + out * pout + cw * pin * CACHE_WRITE_MULT + cr * pin * CACHE_READ_MULT) / 1e6
        total_usd += usd
        breakdown.append({"model": m, "input": i, "output": out,
                          "cache_write": cw, "cache_read": cr, "usd": round(usd, 4)})
    return {
        "agent_id": os.path.basename(jsonl)[len("agent-"):-len(".jsonl")],
        "type": meta.get("agentType"),
        "description": meta.get("description"),
        "session": os.path.basename(os.path.dirname(os.path.dirname(jsonl))),
        "mtime": os.path.getmtime(jsonl),
        "usd": round(total_usd, 4),
        "unknown_model": unknown,
        "breakdown": breakdown,
    }


def main():
    ap = argparse.ArgumentParser(description="Cost of a sub-agent run (FR-21).")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--latest", action="store_true")
    g.add_argument("--agent", metavar="ID")
    g.add_argument("--session", metavar="SID")
    ap.add_argument("--type", metavar="AGENT_TYPE")
    ap.add_argument("--since", metavar="YYYY-MM-DD")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    jsonls = find_jsonls()
    if args.agent:
        jsonls = [j for j in jsonls if f"agent-{args.agent}" in os.path.basename(j)]
    if args.session:
        jsonls = [j for j in jsonls if f"/{args.session}/" in j]
    if args.since:
        cut = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
        jsonls = [j for j in jsonls if os.path.getmtime(j) >= cut]

    results = [r for r in (cost_of(j) for j in jsonls) if r]
    if args.type:
        results = [r for r in results if (r.get("type") or "") == args.type]
    results.sort(key=lambda r: r["mtime"], reverse=True)

    # --latest and default (no explicit selector) → only the most recent
    if args.latest or not (args.agent or args.session or args.type or args.since):
        results = results[:1]

    if not results:
        print("no sub-agents match the filter", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return

    grand = 0.0
    for r in results:
        grand += r["usd"]
        when = datetime.fromtimestamp(r["mtime"]).strftime("%Y-%m-%d %H:%M")
        flag = " [unknown-price model]" if r["unknown_model"] else ""
        desc = (r["description"] or "")[:50]
        print(f"${r['usd']:.4f}  [{r['type'] or '?'}] {when}  {desc}{flag}")
        for b in r["breakdown"]:
            print(f"    {b['model']}: in={b['input']} out={b['output']} "
                  f"cw={b['cache_write']} cr={b['cache_read']} -> ${b['usd']:.4f}")
    if len(results) > 1:
        print(f"TOTAL: ${grand:.4f} ({len(results)} runs)")


if __name__ == "__main__":
    main()
