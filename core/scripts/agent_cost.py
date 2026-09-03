#!/usr/bin/env python3
"""Deterministic cost of sub-agent runs from Claude usage JSONL.

The transcript stores one cumulative usage snapshot per response fragment.  A
single API request can therefore appear on several JSONL lines.  This script
deduplicates those lines before pricing them and uses event timestamps for
windowing and ordering.

Modes:
  --latest             the most recent sub-agent by event time (default)
  --agent <id>         a specific agent-<id>
  --session <sid>      all sub-agents in session <sid>
  --type <agentType>   filter by type (research/general-purpose/...)
  --since YYYY-MM-DD   only usage events on or after this UTC date
  --json               machine output
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone


PROJECTS = os.environ.get("STC_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")

# Prices in $ / 1M tokens (input, output).  This is a dated API-equivalent
# catalog, not a subscription-quota formula.  Prefix matching handles dated
# model IDs such as claude-haiku-4-5-20251001.
PRICE_VERSION = "2026-08-14"
PRICE_DATE = "2026-08-14"
PRICES = {
    "claude-opus-5":     (5.0, 25.0),
    "claude-opus-4-8":   (5.0, 25.0),
    "claude-opus-4-7":   (5.0, 25.0),
    "claude-opus-4-6":   (5.0, 25.0),
    "claude-fable-5":    (10.0, 50.0),
    "claude-sonnet-5":   (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5":  (1.0, 5.0),
}
DEFAULT_PRICE = (5.0, 25.0)
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0
CACHE_READ_MULT = 0.10

USAGE_FIELDS = (
    "input",
    "cache_write_5m",
    "cache_write_1h",
    "cache_read",
    "output",
)


def find_jsonls():
    # <projects>/<project>/<session>/subagents/agent-<id>.jsonl
    return glob.glob(os.path.join(PROJECTS, "*", "*", "subagents", "agent-*.jsonl"))


def _token_count(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_components(usage):
    """Normalize a transcript usage payload into five billable components."""
    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        write_5m = _token_count(cache_creation.get("ephemeral_5m_input_tokens"))
        write_1h = _token_count(cache_creation.get("ephemeral_1h_input_tokens"))
        # Older payloads may carry only the merged field.  Keep those records
        # visible and compatible; current Claude payloads provide both TTLs.
        if not write_5m and not write_1h:
            write_5m = _token_count(usage.get("cache_creation_input_tokens"))
    else:
        write_5m = _token_count(usage.get("cache_creation_input_tokens"))
        write_1h = 0
    return {
        "input": _token_count(usage.get("input_tokens")),
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
        "cache_read": _token_count(usage.get("cache_read_input_tokens")),
        "output": _token_count(usage.get("output_tokens")),
    }


def _event_time(record):
    value = record.get("timestamp")
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _format_event_time(value):
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _request_key(record, message, line_no):
    request_id = record.get("requestId")
    if request_id:
        return "request:" + str(request_id)
    message_id = message.get("id")
    if message_id:
        return "message:" + str(message_id)
    # There is no safe deduplication key without either ID.  Preserve the
    # usage instead of silently dropping it, but do not merge unrelated rows.
    return f"line:{line_no}"


def price_for(model):
    """Return ``(input_price, output_price, matched_prefix_or_none)``."""
    matches = [prefix for prefix in PRICES if model.startswith(prefix)]
    if not matches:
        return DEFAULT_PRICE[0], DEFAULT_PRICE[1], None
    prefix = max(matches, key=len)
    pin, pout = PRICES[prefix]
    return pin, pout, prefix


def _weighted_usage(usage):
    tokens = sum(usage[field] for field in USAGE_FIELDS)
    context_eq = (
        usage["input"]
        + CACHE_WRITE_5M_MULT * usage["cache_write_5m"]
        + CACHE_WRITE_1H_MULT * usage["cache_write_1h"]
        + CACHE_READ_MULT * usage["cache_read"]
    )
    total_strong_eq = context_eq + 5.0 * usage["output"]
    return {
        **usage,
        "tokens": tokens,
        "context_eq": round(context_eq, 4),
        "total_strong_eq": round(total_strong_eq, 4),
    }


def _sum_usage(left, right):
    return {field: left[field] + right[field] for field in USAGE_FIELDS}


def _zero_usage():
    return {field: 0 for field in USAGE_FIELDS}


def _breakdown_from_groups(groups):
    per_model = {}
    unknown_models = set()
    for group in groups.values():
        model = group["model"]
        usage = per_model.setdefault(model, _zero_usage())
        for field in USAGE_FIELDS:
            usage[field] += group["usage"][field]

    breakdown = []
    total_usage = _zero_usage()
    total_usd = 0.0
    for model in sorted(per_model):
        usage = per_model[model]
        total_usage = _sum_usage(total_usage, usage)
        pin, pout, matched_prefix = price_for(model)
        if matched_prefix is None:
            unknown_models.add(model)
        usd = (
            usage["input"] * pin
            + usage["output"] * pout
            + usage["cache_write_5m"] * pin * CACHE_WRITE_5M_MULT
            + usage["cache_write_1h"] * pin * CACHE_WRITE_1H_MULT
            + usage["cache_read"] * pin * CACHE_READ_MULT
        ) / 1e6
        weighted = _weighted_usage(usage)
        breakdown.append({
            "model": model,
            **weighted,
            "price_prefix": matched_prefix,
            "usd": round(usd, 4),
        })
        total_usd += usd
    return breakdown, _weighted_usage(total_usage), total_usd, sorted(unknown_models)


def cost_of(jsonl, since=None):
    """Return one agent's deduplicated usage, price, and metadata.

    ``since`` is an aware UTC datetime (or an ISO/date string).  Filtering is
    applied to individual usage events before request aggregation, so file
    modification time cannot change the selected window.
    """
    if isinstance(since, str):
        since = _parse_since(since)

    meta_path = jsonl[:-6] + ".meta.json"
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            pass

    groups = {}
    latest_event = None
    try:
        fh = open(jsonl, encoding="utf-8")
    except OSError:
        return None
    with fh:
        for line_no, line in enumerate(fh, 1):
            try:
                record = json.loads(line)
            except (TypeError, ValueError):
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            usage_payload = message.get("usage")
            if not isinstance(usage_payload, dict):
                continue
            event_time = _event_time(record)
            if since is not None and (event_time is None or event_time < since):
                continue
            model = message.get("model") or "unknown"
            # Model is kept in the identity because pricing a request whose
            # model changed mid-stream as one model would silently lose usage.
            group_key = (_request_key(record, message, line_no), model)
            components = _usage_components(usage_payload)
            group = groups.get(group_key)
            if group is None:
                groups[group_key] = {
                    "model": model,
                    "usage": components,
                    "event_time": event_time,
                }
            else:
                group["usage"] = {
                    field: max(group["usage"][field], components[field])
                    for field in USAGE_FIELDS
                }
                if event_time is not None and (
                    group["event_time"] is None or event_time > group["event_time"]
                ):
                    group["event_time"] = event_time
            if event_time is not None and (
                latest_event is None or event_time > latest_event
            ):
                latest_event = event_time

    if not groups:
        return None

    breakdown, total_usage, total_usd, unknown_models = _breakdown_from_groups(groups)
    return {
        "agent_id": os.path.basename(jsonl)[len("agent-"):-len(".jsonl")],
        "type": meta.get("agentType"),
        "description": meta.get("description"),
        "session": os.path.basename(os.path.dirname(os.path.dirname(jsonl))),
        "event_time": _format_event_time(latest_event),
        "price_version": PRICE_VERSION,
        "price_date": PRICE_DATE,
        "usd": round(total_usd, 4),
        "unknown_model": bool(unknown_models),
        "unknown_models": unknown_models,
        "usage": total_usage,
        "breakdown": breakdown,
    }


def _parse_since(value):
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return parsed


def _event_sort_key(result):
    # Records without an event timestamp remain visible, but never outrank a
    # timestamped record for --latest.
    return (result.get("event_time") is not None, result.get("event_time") or "")


def _print_usage(label, usage):
    print(
        f"{label}: input={usage['input']} write_5m={usage['cache_write_5m']} "
        f"write_1h={usage['cache_write_1h']} read={usage['cache_read']} "
        f"output={usage['output']} tokens={usage['tokens']} "
        f"context_eq={usage['context_eq']} "
        f"total_strong_eq={usage['total_strong_eq']}"
    )


def main():
    ap = argparse.ArgumentParser(description="Cost of sub-agent runs")
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
    try:
        since = _parse_since(args.since) if args.since else None
    except ValueError:
        ap.error("--since must be YYYY-MM-DD")

    results = [r for r in (cost_of(j, since=since) for j in jsonls) if r]
    if args.type:
        results = [r for r in results if (r.get("type") or "") == args.type]
    results.sort(key=_event_sort_key, reverse=True)

    # --latest and default (no explicit selector) → only the most recent.
    if args.latest or not (args.agent or args.session or args.type or args.since):
        results = results[:1]

    if not results:
        print("no sub-agents match the filter", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return

    print(f"PRICE: version={PRICE_VERSION} date={PRICE_DATE}")
    grand = 0.0
    grand_usage = _zero_usage()
    for result in results:
        grand += result["usd"]
        when = result.get("event_time") or "unknown-event-time"
        flag = " [unknown-price model]" if result["unknown_model"] else ""
        desc = (result["description"] or "")[:50]
        print(f"${result['usd']:.4f}  [{result['type'] or '?'}] {when}  {desc}{flag}")
        for breakdown in result["breakdown"]:
            model_flag = " [unknown-price model]" if not breakdown["price_prefix"] else ""
            print(
                f"    {breakdown['model']}: input={breakdown['input']} "
                f"write_5m={breakdown['cache_write_5m']} "
                f"write_1h={breakdown['cache_write_1h']} "
                f"read={breakdown['cache_read']} output={breakdown['output']} "
                f"context_eq={breakdown['context_eq']} "
                f"total_strong_eq={breakdown['total_strong_eq']} "
                f"-> ${breakdown['usd']:.4f}{model_flag}"
            )
        _print_usage("    USAGE", result["usage"])
        grand_usage = _sum_usage(grand_usage, result["usage"])
    if len(results) > 1:
        print(f"TOTAL: ${grand:.4f} ({len(results)} runs)")
        _print_usage("USAGE TOTAL", _weighted_usage(grand_usage))


if __name__ == "__main__":
    main()
