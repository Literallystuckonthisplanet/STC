#!/usr/bin/env python3
"""toml_merge.py — add-only merge of STC TOML tables into a harness config.toml.

Codex keeps its settings in ~/.codex/config.toml (model, personality, marketplaces,
plugins, mcp_servers). This module merges STC's OWNED tables (namespaced under
`stc-`, e.g. [mcp_servers.stc-playwright]) into that file WITHOUT rewriting the
user's content — the same non-destructive guarantee stc_block.py gives for the
AGENTS.md/CLAUDE.md marker, extended to TOML.

Strategy (add-only, borrowed from ECC's merge-mcp-config.js):
  1. tomllib.parse the live file to DETECT which stc-* tables already exist.
  2. Append raw TOML text for ONLY the missing tables — preserves the existing
     file byte-for-byte (no parse→reserialise round-trip, which would lose the
     user's comments/formatting).
  3. Idempotent: a re-apply finds every stc-* table present → no-op.
  4. With overwrite=True: strip the STC-managed sections first (regex section
     removal including subtables like [mcp_servers.stc-x.env]), then re-append
     the current STC tables — so a server config change in stc.yaml propagates.

tomllib is stdlib since Python 3.11 (PEP 680) and READ-ONLY; there is no write
capability to add, and we don't need one — append + section-strip are string
ops, exactly the proven split ECC uses. Zero new dependencies.
"""

import os
import re
import tomllib


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _parse(path):
    """tomllib-parse the file. Returns (parsed_dict, ok). On a parse error
    returns ({}, False) — the caller (deploy) refuses to merge into a corrupt
    TOML rather than silently treating it as empty (same stance as the JSON
    _refuse_merge_into_corrupt_json guard)."""
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh), True
    except FileNotFoundError:
        return {}, True  # absent = fine, treated as empty
    except tomllib.TOMLDecodeError:
        return {}, False


def _managed_names(tables_text):
    """Extract the stc-* table names from the rendered STC TOML text (the
    [mcp_servers.stc-<name>] headers STC owns this render)."""
    return set(re.findall(r"^\[mcp_servers\.(stc-[A-Za-z0-9_-]+)\]", tables_text, re.M))


def _existing_stc_servers(parsed):
    """The stc-* server names already present in the live config.toml."""
    servers = parsed.get("mcp_servers", {}) or {}
    return {n for n in servers if isinstance(n, str) and n.startswith("stc-")}


def _strip_section(text, header):
    """Remove a TOML section `[header]` and its body, INCLUDING subtables whose
    dotted path starts with the same key (e.g. header `[mcp_servers.stc-x]`
    also removes `[mcp_servers.stc-x.env]`).

    `header` is the full bracketed header line, e.g. `[mcp_servers.stc-x]`.
    Section body = from the header line up to (not including) the next top-level
    `[table]` or `[[array-of-tables]]` header at the SAME or shallower depth, or
    EOF. String manipulation, not a re-serialise — preserves everything else
    byte-for-byte.
    """
    # the bare dotted key inside the brackets, e.g. mcp_servers.stc-x
    inner = header.strip().lstrip("[").rstrip("]")
    escaped_inner = re.escape(inner)
    # exact-header line OR a subtable header [inner.<something>]
    header_re = re.compile(rf"^\s*\[\s*{escaped_inner}\s*\]\s*(#.*)?$")
    subtable_re = re.compile(rf"^\s*\[\s*{escaped_inner}\.[A-Za-z0-9_.-]+\s*\]")
    lines = text.split("\n")
    out = []
    skipping = False
    for line in lines:
        if header_re.match(line) or subtable_re.match(line):
            skipping = True
            continue
        if skipping and re.match(r"^\s*\[\[?", line):
            # a new top-level/array header ends the section body
            skipping = False
        if not skipping:
            out.append(line)
    result = "\n".join(out)
    # collapse 3+ consecutive newlines to 2 (avoids gaps accumulating on re-strip)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def merge_toml(path, tables_text, overwrite=False):
    """Add-only merge of STC's `tables_text` (rendered [mcp_servers.stc-*] TOML)
    into the live config.toml at `path`.

    Returns ('noop'|'appended'|'updated'|'created', bool changed).
      - absent file          → created (the STC tables written as the file body)
      - all stc-* present     → noop (idempotent re-apply)
      - some missing          → appended (raw text appended at end)
      - overwrite=True        → updated (stc-* sections stripped, current re-appended)

    A corrupt live TOML raises tomllib.TOMLDecodeError via _parse's False flag —
    the caller checks the `ok` return and refuses (never silently clobber).
    """
    want = _managed_names(tables_text)
    if not want:
        return ("noop", False)

    live = _read(path)
    if live is None:
        # file absent: create it with just the STC tables
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(tables_text if tables_text.endswith("\n") else tables_text + "\n")
        return ("created", True)

    parsed, ok = _parse(path)
    if not ok:
        raise ValueError(f"refusing to merge into corrupt TOML: {path}")

    if overwrite:
        # strip every STC-managed section the render owns, then re-append current
        new_text = live
        for name in want:
            new_text = _strip_section(new_text, f"[mcp_servers.{name}]")
        new_text = new_text.rstrip() + "\n\n" + tables_text
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        return ("updated", True)

    present = _existing_stc_servers(parsed)
    missing = want - present
    if not missing:
        return ("noop", False)

    # add-only: append the whole STC block once (the missing servers are in it;
    # present ones are a noop-detect, and append is cheaper than per-section split).
    # To stay byte-accurate we still only append servers that are actually missing:
    # split the tables_text into per-server blocks and append the missing ones.
    missing_blocks = _filter_blocks(tables_text, missing)
    if not missing_blocks:
        return ("noop", False)
    append = "".join(missing_blocks)
    body = live.rstrip() + "\n\n" + (append if append.endswith("\n") else append + "\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return ("appended", True)


def _filter_blocks(tables_text, names):
    """Return only the [mcp_servers.<name>] (+subtable) blocks whose name is in
    `names`, preserving their text. A block spans its header through the line
    before the next top-level header (or EOF)."""
    names = set(names)
    lines = tables_text.split("\n")
    blocks = []
    cur_name = None
    cur = []
    header_re = re.compile(r"^\[mcp_servers\.(stc-[A-Za-z0-9_-]+)\]\s*$")
    subtable_re = re.compile(r"^\[mcp_servers\.stc-[A-Za-z0-9_-]+\.")
    table_re = re.compile(r"^\s*\[\[?")
    for line in lines:
        m = header_re.match(line)
        if m:
            if cur_name in names and cur:
                blocks.append("\n".join(cur) + "\n")
            cur_name = m.group(1)
            cur = [line]
            continue
        if cur_name is not None:
            # subtable lines belong to the current server block
            if subtable_re.match(line) or not table_re.match(line):
                cur.append(line)
                continue
            # a different top-level header → flush the current block
            if cur_name in names and cur:
                blocks.append("\n".join(cur) + "\n")
            cur_name = None
            cur = []
    if cur_name in names and cur:
        blocks.append("\n".join(cur) + "\n")
    return blocks


def remove_stc_sections(path):
    """Strip ALL [mcp_servers.stc-*] sections (and their subtables) from the
    config.toml. Used by uninstall. Returns ('removed', bool changed)."""
    live = _read(path)
    if live is None:
        return ("absent", False)
    stc_headers = re.findall(r"^\[mcp_servers\.(stc-[A-Za-z0-9_-]+)\]", live, re.M)
    if not stc_headers:
        return ("absent", False)
    new_text = live
    for name in set(stc_headers):
        new_text = _strip_section(new_text, f"[mcp_servers.{name}]")
    new_text = new_text.rstrip() + "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return ("removed", True)
