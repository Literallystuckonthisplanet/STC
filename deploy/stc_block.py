#!/usr/bin/env python3
"""stc_block.py — the STC managed-block marker mechanism.

The ONE place deploy.py touches a pre-existing user-owned markdown file.
Every other STC artifact is a separate `.stc.md` file (collision-proof);
this is the narrow bridge that makes the user's always-context file
(CLAUDE.md / AGENTS.md) load the STC always-context bundle via a single
@import line.

Model:
  - A managed block is delimited by STC_BEGIN / STC_END marker lines.
  - inject_block() is IDEMPOTENT: if a block already exists, its content is
    replaced between the markers; otherwise the block is appended. User
    content before/after/outside is never modified.
  - remove_block() deletes the block + the markers. If the file becomes
    empty AND deploy created it, the caller may delete it.

The block body is a single @import line pointing at the harness's
always-context bundle file (e.g. ~/.claude/CLAUDE.stc.md), so re-pointing
the bundle on re-deploy is just an inject_block() with new content.
"""

import os

# Marker lines. The leading "# " makes them valid comments in both CLAUDE.md
# and AGENTS.md (and harmless noise in any markdown viewer).
STC_BEGIN = "# >>> STC BEGIN (managed — do not edit) >>>"
STC_END = "# <<< STC END <<<"


def _read(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None  # signal: file does not exist (caller decides)


def _split(text):
    """Split text into (before, block_body, after).

    Returns (before, None, after) if no managed block is present, where
    `after` is the whole text and `before` is '' (so append == before+block).
    """
    if text is None:
        return "", None, ""
    begin_idx = text.find(STC_BEGIN)
    if begin_idx == -1:
        return "", None, text  # no block → append after existing content
    end_idx = text.find(STC_END, begin_idx)
    if end_idx == -1:
        # Dangling BEGIN without END (a user deleted the END line by hand).
        # Swallowing everything from BEGIN to EOF as "block body" would let
        # inject_block OVERWRITE any real user content that followed the removed
        # END marker — the exact data-loss this module promises never happens.
        # Treat it as "no recognizable block" instead: append a fresh block and
        # leave the dangling line as inert user content for the user to clean up.
        return "", None, text
    before = text[:begin_idx]
    body = text[begin_idx + len(STC_BEGIN):end_idx]
    after = text[end_idx + len(STC_END):]
    return before, body, after


def _compose(before, body, after):
    """Reassemble: before + markers-with-body + after, trimming stray blanks."""
    parts = []
    if before:
        # ensure exactly one blank line separates user content from the block
        parts.append(before.rstrip() + "\n\n")
    parts.append(STC_BEGIN + "\n")
    b = body.strip("\n")
    if b:
        parts.append(b + "\n")
    parts.append(STC_END + "\n")
    if after:
        # one blank line after the block, then the user content verbatim
        parts.append("\n" + after.lstrip("\n"))
    return "".join(parts)


def inject_block(filepath, content, create=True):
    """Insert/replace the managed block in `filepath` with `content`.

    Idempotent: a second call with the same content yields the same file.
    Returns ('replaced'|'inserted'|'created', bool changed).
    If the file does not exist: created it (with just the block) when
    `create=True`; raise FileNotFoundError when `create=False`.
    """
    text = _read(filepath)
    if text is None and not create:
        raise FileNotFoundError(filepath)

    before, old_body, after = _split(text)
    new_body = content.strip("\n")

    if old_body is None:
        action = "created" if text is None else "inserted"
    elif old_body.strip("\n") == new_body:
        return ("noop", False)  # identical block → nothing to do
    else:
        action = "replaced"

    composed = _compose(before, new_body, after)
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(composed)
    return (action, True)


def remove_block(filepath):
    """Delete the managed block + markers from `filepath`.

    Returns ('removed', True) if a block was present, ('absent', False) if
    none. Leaves user content untouched. If the file holds only the block
    (becomes empty/whitespace), the file is left in place — the caller
    decides whether to delete it (it may be a user file they want to keep).
    """
    text = _read(filepath)
    if text is None:
        return ("absent", False)

    before, body, after = _split(text)
    if body is None:
        return ("absent", False)

    remainder = (before + after).strip("\n")
    if not remainder:
        # only the block was present → truncate to empty
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write("")
    else:
        with open(filepath, "w", encoding="utf-8") as fh:
            # collapse the gap left by the removed block to a single blank line
            fh.write(before.rstrip() + "\n\n" + after.lstrip("\n").rstrip() + "\n")
    return ("removed", True)


def has_block(filepath):
    """True if a managed block is currently present in `filepath`."""
    text = _read(filepath)
    if text is None:
        return False
    return STC_BEGIN in text and text.find(STC_END, text.find(STC_BEGIN)) != -1
