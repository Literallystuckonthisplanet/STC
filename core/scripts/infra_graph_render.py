#!/usr/bin/env python3
"""infra_graph_render.py — render the infra graph as doc-backend notes.

Reuses the graph engine in infra_graph.py (collect() + RELATED). Writes into
the doc backend's `infra/` folder, one note per function (code I/S/A/H/R/T/N),
plus artifact stubs for non-memory files (commands/agents/hooks/templates) so
the graph stays connected. Memory files link to their real notes.

Each note gets:
  name: <code>   (so it enters the link-checker registry; one-segment codes
                  like I21 are filtered by the hook anyway — harmless)
  tags: infra/<type>, load/<loading>
  [[code]] links to its Related functions.

Idempotent — the infra/ folder is rewritten on each run.

Output location: ${DOCS_ROOT}/infra/ (defaults to <CORE_DIR>/../deploy/_rendered/infra
for a dry preview; set STC_DOCS_ROOT to render into the real doc backend).

Usage:
  python3 infra_graph_render.py            # render + print a summary
  python3 infra_graph_render.py --dry-run  # do not write, print the plan only
"""

import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import infra_graph  # noqa: E402

CORE_DIR = infra_graph.CORE_DIR
MEMORY_DIR = infra_graph.MEMORY_DIR
DOCS_ROOT = os.environ.get("STC_DOCS_ROOT") or os.path.abspath(
    os.path.join(CORE_DIR, "..", "deploy", "_rendered")
)
INFRA_DIR = os.path.join(DOCS_ROOT, "infra")

TYPE_TAG = {
    "Instruction": "instruction",
    "Skill": "skill",
    "Agent": "agent",
    "Hook": "hook",
    "Reference": "reference",
    "Template": "template",
    "Integration": "integration",
}

# undirected Related adjacency — graph edges both ways
_rel = {}
for _s, _ts in infra_graph.RELATED.items():
    for _t in _ts:
        _rel.setdefault(_s, set()).add(_t)
        _rel.setdefault(_t, set()).add(_s)


def mem_slug(path):
    """If the artifact is a memory file, return its name: slug (its real note)."""
    if not path or not path.startswith(MEMORY_DIR):
        return None
    try:
        txt = open(path, encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^name:[ \t]*(.+)$", txt, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def art_slug(path):
    base = os.path.basename(path)
    return "art-" + re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")


def code_key(c):
    return (c[0], int(c[1:]))


def render(all_funcs, artifacts, write=True):
    """Render the infra notes into INFRA_DIR. Return (n_funcs, n_arts)."""
    if write:
        if os.path.isdir(INFRA_DIR):
            shutil.rmtree(INFRA_DIR)
        os.makedirs(INFRA_DIR, exist_ok=True)

    def w(slug, fm, body):
        if not write:
            return
        text = "---\n" + "\n".join(fm) + "\n---\n\n" + "\n".join(body) + "\n"
        with open(os.path.join(INFRA_DIR, slug + ".md"), "w", encoding="utf-8") as f:
            f.write(text)

    # --- function notes ---
    for code, rec in all_funcs.items():
        src = rec.artifact_path
        ms = mem_slug(src) if src else None
        src_link = (
            f"[[{ms}]]" if ms else (f"[[{art_slug(src)}]]" if src else "—")
        )
        related = " · ".join(
            f"[[{t}]]" for t in sorted(_rel.get(code, []), key=code_key)
        )
        type_name = infra_graph.TYPE_NAMES.get(rec.letter, rec.letter)
        fm = [
            f"name: {code}",
            f'aliases: ["{code}"]',
            f"tags: [infra/{TYPE_TAG.get(type_name, 'other')}, load/{rec.loading}]",
            f"type: {type_name}",
            f"loading: {rec.loading}",
        ]
        body = [
            f"# {code} — {rec.name}",
            "",
            f"**Type:** {type_name} · **Loading:** {rec.loading} · **Source:** {src_link}",
        ]
        if rec.description:
            body += ["", rec.description]
        if related:
            body += ["", f"**Related:** {related}"]
        w(code, fm, body)

    # --- artifact stubs (non-memory only; memory = real notes) ---
    n_art = 0
    for path, art in artifacts.items():
        if path.startswith(MEMORY_DIR):
            continue
        slug = art_slug(path)
        funcs = " · ".join(f"[[{c}]]" for c in sorted(art.codes, key=code_key))
        fm = [
            f"name: {slug}",
            f'aliases: ["{slug}"]',
            "tags: [infra/artifact]",
            f"kind: {art.kind}",
        ]
        body = [
            f"# {art.name}",
            "",
            f"**Path:** `{path}` · **Kind:** {art.kind}",
            "",
            f"**Functions:** {funcs}" if funcs else "**Functions:** —",
        ]
        w(slug, fm, body)
        n_art += 1

    # --- the infra-graph index (hub by type) ---
    by_type = {}
    for code, rec in all_funcs.items():
        type_name = infra_graph.TYPE_NAMES.get(rec.letter, rec.letter)
        by_type.setdefault(type_name, []).append(code)
    idx = [
        "---",
        "name: infra-index",
        'aliases: ["infra-index"]',
        "tags: [infra/index]",
        "---",
        "",
        "# 🔧 Infra graph (auto-generated)",
        "",
        "Generated by `infra_graph_render.py` from the code-labels in the core/ "
        "files. Open the Graph view, enable **Show tags** — clusters by type/loading.",
        "",
    ]
    for t in sorted(by_type):
        codes = " · ".join(f"[[{c}]]" for c in sorted(by_type[t], key=code_key))
        idx.append(f"**{t}:** {codes}")
        idx.append("")
    if write:
        with open(os.path.join(INFRA_DIR, "00-infra-index.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(idx) + "\n")

    return len(all_funcs), n_art


def main():
    dry = "--dry-run" in sys.argv
    all_funcs, artifacts, _dup, _blobs = infra_graph.collect()
    n_funcs, n_arts = render(all_funcs, artifacts, write=not dry)
    where = "(dry-run, not written)" if dry else INFRA_DIR
    print(f"OK: {n_funcs} functions, {n_arts} artifact stubs → {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
