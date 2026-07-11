#!/usr/bin/env python3
"""infra_graph.py — the STC infra-graph engine (harness-neutral).

Scans the deployed infra files for code-labels (I/S/A/H/R/T/N) and builds the
directed semantic graph (RELATED), so the whole infra is navigable as a graph
(in the doc backend's Graph view, or as plain data).

This is the neutral core extracted from the original `infra-gen.py`:
- collect() + RELATED + the md/sh parsers + the FuncRec/ArtifactRec structures.
- NO Notion code (the original `main()` + the Notion class are retired; the
  doc backend is markdown-local-first).

The retired-code registry (reference_retired_codes.md) is read so a retired
code is not flagged as an orphan and does not create a numbering gap.

Paths are resolved from env vars (set by deploy.py at render time, or by the
caller):
  STC_CORE_DIR  — the core/ source (where rules/memory/skills/commands/hooks/
                  agents/templates live). Used to scan for labels.
  STC_MEMORY_DIR — the deployed memory root (where reference_retired_codes.md
                  lives). Defaults to STC_CORE_DIR/memory.
  STC_HARNESS_DIR — the deployed harness dir (e.g. ~/.claude), for the
                  instruction file + settings artifacts. Optional.

Usage:
  python3 infra_graph.py            # collect + print a summary
  python3 infra_graph.py --json     # emit the graph as JSON (funcs + artifacts)
  python3 infra_graph.py --check    # collect + run the orphan/gap/dup checks
"""

import glob
import json
import os
import re
import sys
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Paths (resolved from env; defaults make it runnable from the repo root)
# ---------------------------------------------------------------------------

CORE_DIR = os.environ.get("STC_CORE_DIR") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
MEMORY_DIR = os.environ.get("STC_MEMORY_DIR") or os.path.join(CORE_DIR, "memory")
HARNESS_DIR = os.environ.get("STC_HARNESS_DIR") or ""  # empty → skip harness artifacts

# ---------------------------------------------------------------------------
# Code-label taxonomy
# ---------------------------------------------------------------------------

TYPE_NAMES = {
    "I": "Instruction",
    "S": "Skill",
    "A": "Agent",
    "H": "Hook",
    "R": "Reference",
    "T": "Template",
    "N": "Integration",
}

# md labels: one marker may carry several codes (<!-- I05 I06 -->)
RE_MD_LABEL = re.compile(r"<!--\s*([A-Z]\d{2}(?:\s+[A-Z]\d{2})*)\s*-->")
# sh labels: after the shebang, "# H01 — hook: <name>"
RE_SH_LABEL = re.compile(r"#\s*([A-Z]\d{2})\s+[—-]\s+hook:\s*(.*)")
# any code mention in text (for the orphan check)
RE_CODE_MENTION = re.compile(r"\b([ISAHRTN]\d{2})\b")
# Codes that collide with the STC label grammar but are EXTERNAL taxonomies, not
# infra labels — they appear in prose and must not read as orphans:
#   A10 — OWASP Top-10 "A10 SSRF" (in the security-arch agent/skill).
#   S26 — a YC batch tag ("YC S26", in the code-graph skill's graphify credit).
# The exclusion is CONTEXT-SCOPED (only when the external marker is on the same
# line), NOT a blanket set-subtraction: a blanket subtract would also hide a
# GENUINE orphan — a real A10/S26 whose own <!-- label --> got lost while text
# references remain — which is the exact failure this check exists to catch.
NON_INFRA_MENTIONS = {"A10", "S26"}
EXTERNAL_CTX = re.compile(r"OWASP|SSRF|YC\s+[SWF]\d|batch", re.I)
# retired-code registry: a line like "- I04 → H09 (date): ..."
RE_RETIRED = re.compile(r"-\s*([A-Z]\d{2})\s*(?:→|->)\s*([A-Z]\d{2})\b")
RETIRED_REGISTRY = os.path.join(MEMORY_DIR, "reference_retired_codes.md")

# md heading (## or #)
RE_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

# Where the auto-name is not enough (override to a readable name).
# NOTE: keep this minimal — the heading above a label is the default name.
NAME_OVERRIDE = {
    # seed entries; extend as the framework grows
}

MAX_DESC = 500  # description truncation

# ---------------------------------------------------------------------------
# RELATED — directed semantic edges function<->function (dedup)
# Extend as new functions are added. An edge = "src relates to targets".
# ---------------------------------------------------------------------------

RELATED = {
    "I09": ["H01"],
    "I10": ["H03"],
    "I17": ["A02", "A04", "A07", "A08"],
    "I20": ["I15"],
    "I24": ["H11"],
    "H02": [],
    "H07": ["I09"],
    "H08": ["R07"],
    "H12": [],
    "H13": ["I18"],
    "H14": [],
    "H15": [],
    "H16": [],
    "R01": ["R06"],
    "R06": ["S12", "S13"],
    "R07": ["I02", "I05"],
    "R08": ["R05", "I13", "I15"],
    "R09": ["A02", "A05", "A07", "A04", "I15", "R02", "R03", "T02"],
    "S18": ["S19"],
    "T01": ["T02", "T03"],
}
# NOTE: the live infra's RELATED table is richer (it references the live file
# slugs). For STC, the edges are re-derived from the deployed core/ at scan
# time — extend this table as the canonical STC functions stabilize.

# ---------------------------------------------------------------------------
# Scan table: (relative path under CORE_DIR, type letter, artifact kind, loading)
# ---------------------------------------------------------------------------

MEM = lambda name: os.path.join(MEMORY_DIR, name)
RULE = lambda name: os.path.join(CORE_DIR, "rules", name)

# The `letters` field may hold MORE THAN ONE type letter: project_docs.md
# defines both I-rules (ADR/task/ERD conventions) and R-references (R05/R08, the
# project-memory format), so it is scanned under "IR" — a single letter would
# drop the R-codes and flag them as orphans.
SCAN_FILES = [
    (RULE("session.md"), "I", "rule", "always"),
    (RULE("behavior.md"), "I", "rule", "always"),
    (RULE("pev.md"), "I", "rule", "always"),
    (RULE("project_docs.md"), "IR", "rule", "lazy"),
    (MEM("playbook.md"), "R", "memory-lazy", "lazy"),
    (MEM("code_standard.md"), "R", "memory-lazy", "lazy"),
    (MEM("skills_triggers.md"), "R", "memory-lazy", "lazy"),
    (MEM("reference_defect_ledger.md"), "R", "memory-lazy", "lazy"),
    (MEM("reference_abuse_cases.md"), "R", "memory-lazy", "lazy"),
    (MEM("reference_failure_modes.md"), "R", "memory-lazy", "lazy"),
    (MEM("reference_retired_codes.md"), "R", "memory-lazy", "lazy"),
]

# glob locations: (pattern, letter, kind, loading, parser md|sh)
SCAN_GLOBS = [
    (os.path.join(CORE_DIR, "commands", "*.md"), "S", "command", "on-trigger", "md"),
    (os.path.join(CORE_DIR, "skills", "*", "SKILL.md"), "S", "skill", "on-trigger", "md"),
    (os.path.join(CORE_DIR, "agents", "*.md"), "A", "agent", "on-trigger", "md"),
    (os.path.join(CORE_DIR, "hooks", "*.sh"), "H", "hook", "on-event", "sh"),
    (os.path.join(CORE_DIR, "templates", "*.md"), "T", "template", "on-trigger", "md"),
    (os.path.join(CORE_DIR, "templates", "design-system", "*.md"), "T", "template", "on-trigger", "md"),
    (os.path.join(CORE_DIR, "templates", "vault", "*.md"), "T", "template", "on-trigger", "md"),
]


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


class FuncRec:
    __slots__ = ("code", "name", "description", "loading", "context", "artifact_path")

    def __init__(self, code, _letter=None):
        self.code = code
        self.name = ""
        self.description = ""
        self.loading = ""
        self.context = ""  # Why/Status (manual layer, optional)
        self.artifact_path = ""

    @property
    def letter(self):
        return self.code[0]

    def to_dict(self):
        return OrderedDict(
            [
                ("code", self.code),
                ("type", TYPE_NAMES.get(self.letter, self.letter)),
                ("name", self.name),
                ("description", self.description),
                ("loading", self.loading),
                ("artifact", self.artifact_path),
                ("related", RELATED.get(self.code, [])),
            ]
        )


class ArtifactRec:
    __slots__ = ("path", "name", "kind", "codes")

    def __init__(self, path, name, kind):
        self.path = path
        self.name = name
        self.kind = kind
        self.codes = []

    def to_dict(self):
        return OrderedDict(
            [
                ("path", self.path),
                ("name", self.name),
                ("kind", self.kind),
                ("codes", list(self.codes)),
            ]
        )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _split_frontmatter(raw):
    """Return (frontmatter_dict, body_start_index)."""
    fm = {}
    if not raw or raw[0].strip() != "---":
        return fm, 0
    try:
        end = raw.index("---", 1)
    except ValueError:
        return fm, 0
    block = raw[1:end]
    j = 0
    while j < len(block):
        line = block[j]
        m = re.match(r"^([A-Za-z0-9_-]+):\s?(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-", ">+", "|+"):
                parts = []
                j += 1
                while j < len(block) and (
                    block[j].strip() == "" or block[j].startswith((" ", "\t"))
                ):
                    parts.append(block[j].strip())
                    j += 1
                fm[key] = " ".join(p for p in parts if p).strip()
                continue
            else:
                fm[key] = val.strip().strip('"').strip("'")
        j += 1
    return fm, end + 1


def _heading_above(lines, label_idx):
    for k in range(label_idx - 1, -1, -1):
        m = RE_HEADING.match(lines[k])
        if m:
            return m.group(2).strip()
    return ""


def _section_body(lines, label_idx):
    body = []
    for k in range(label_idx + 1, len(lines)):
        if RE_HEADING.match(lines[k]):
            break
        body.append(lines[k])
    return body


def _first_paragraph(body_lines):
    para, started = [], False
    for ln in body_lines:
        if ln.strip() == "":
            if started:
                break
            continue
        started = True
        para.append(ln.strip())
    return " ".join(para).strip()


def parse_md_file(path, letters, loading):
    """Return (funcs, found_codes). `letters` is one or more type letters (e.g.
    "I" or "IR") — a label whose first char is in `letters` is kept."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().splitlines()
    funcs, found = [], []
    for idx, line in enumerate(raw):
        m = RE_MD_LABEL.search(line)
        if not m:
            continue
        for code in m.group(1).split():
            if code[0] not in letters:
                continue
            rec = FuncRec(code)
            rec.loading = loading
            rec.name = NAME_OVERRIDE.get(code) or _heading_above(raw, idx) or code
            body = _section_body(raw, idx)
            rec.description = _first_paragraph(body)[:MAX_DESC]
            funcs.append(rec)
            found.append(code)
    return funcs, found


def parse_sh_file(path, loading):
    """Return (funcs, found_codes). A hook label = '# Hxx — hook: <name>'."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().splitlines()
    funcs, found = [], []
    for line in raw:
        m = RE_SH_LABEL.match(line)
        if not m:
            continue
        code = m.group(1)
        rec = FuncRec(code)
        rec.loading = loading
        rec.name = m.group(2).strip() or code
        # description: the next non-empty, non-comment lines up to a blank line
        idx = raw.index(line) if line in raw else -1
        if idx >= 0:
            body = _section_body(raw, idx)
            rec.description = _first_paragraph(body)[:MAX_DESC]
        funcs.append(rec)
        found.append(code)
    return funcs, found


# ---------------------------------------------------------------------------
# collect() — the graph engine
# ---------------------------------------------------------------------------


def load_retired():
    """Read reference_retired_codes.md → set of retired codes."""
    retired = set()
    if not os.path.exists(RETIRED_REGISTRY):
        return retired
    with open(RETIRED_REGISTRY, "r", encoding="utf-8") as f:
        for line in f:
            m = RE_RETIRED.search(line)
            if m:
                retired.add(m.group(1))
    return retired


def collect():
    """Scan all files. Return (funcs, artifacts, dup_index, text_blobs)."""
    all_funcs = OrderedDict()  # code -> FuncRec
    artifacts = OrderedDict()  # path -> ArtifactRec
    dup_index = {}  # code -> [path, ...]
    text_blobs = []  # (path, content) for the orphan check

    def register(rec, art_path):
        rec.artifact_path = art_path
        dup_index.setdefault(rec.code, [])
        if art_path not in dup_index[rec.code]:
            dup_index[rec.code].append(art_path)
        if rec.code not in all_funcs:
            all_funcs[rec.code] = rec
        if art_path in artifacts and rec.code not in artifacts[art_path].codes:
            artifacts[art_path].codes.append(rec.code)

    for path, letter, kind, loading in SCAN_FILES:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        text_blobs.append((path, content))
        artifacts[path] = ArtifactRec(path, os.path.basename(path), kind)
        funcs, _ = parse_md_file(path, letter, loading)
        for rec in funcs:
            register(rec, path)

    for pattern, letter, kind, loading, parser in SCAN_GLOBS:
        for path in sorted(glob.glob(pattern)):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            text_blobs.append((path, content))
            artifacts[path] = ArtifactRec(path, os.path.basename(path), kind)
            funcs, _ = (
                parse_md_file(path, letter, loading)
                if parser == "md"
                else parse_sh_file(path, loading)
            )
            for rec in funcs:
                register(rec, path)

    return all_funcs, artifacts, dup_index, text_blobs


# ---------------------------------------------------------------------------
# Checks (orphan / gap / dup) — the audit layer
# ---------------------------------------------------------------------------


def check(all_funcs, dup_index, text_blobs, retired):
    """Return a dict of findings: orphans, gaps, dups."""
    defined = set(all_funcs.keys())
    mentioned = set()
    for _path, content in text_blobs:
        for line in content.splitlines():
            for code in RE_CODE_MENTION.findall(line):
                # skip a collision code ONLY when its external-taxonomy context is
                # on this line (OWASP A10 SSRF / YC S26). A genuine orphan is a
                # reference with no such context → it still surfaces.
                if code in NON_INFRA_MENTIONS and EXTERNAL_CTX.search(line):
                    continue
                mentioned.add(code)
    # RELATED targets are also "mentions"
    for _src, targets in RELATED.items():
        mentioned.update(targets)

    orphans = sorted(
        c for c in (mentioned - defined) if c not in retired
    )
    # numbering gaps per letter (excluding retired)
    gaps = {}
    by_letter = {}
    for c in defined:
        by_letter.setdefault(c[0], []).append(int(c[1:]))
    for letter, nums in by_letter.items():
        nums = sorted(set(nums))
        full = set(range(1, max(nums) + 1)) if nums else set()
        missing = sorted(full - set(nums))
        # subtract retired codes of this letter
        retired_nums = {
            int(r[1:]) for r in retired if r.startswith(letter)
        }
        missing = [n for n in missing if n not in retired_nums]
        if missing:
            gaps[letter] = missing
    dups = {c: paths for c, paths in dup_index.items() if len(set(paths)) > 1}
    return {"orphans": orphans, "gaps": gaps, "dups": dups, "retired": sorted(retired)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--summary"
    all_funcs, artifacts, dup_index, text_blobs = collect()
    retired = load_retired()

    if mode == "--json":
        out = OrderedDict(
            [
                ("functions", [f.to_dict() for f in all_funcs.values()]),
                ("artifacts", [a.to_dict() for a in artifacts.values()]),
                ("related", RELATED),
            ]
        )
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    findings = check(all_funcs, dup_index, text_blobs, retired)

    if mode == "--check":
        print("orphan codes:", findings["orphans"] or "(none)")
        print("numbering gaps:", findings["gaps"] or "(none)")
        print("duplicates:", list(findings["dups"]) or "(none)")
        print("retired:", findings["retired"] or "(none)")
        return 0

    # default: summary
    by_type = {}
    for code in all_funcs:
        by_type[code[0]] = by_type.get(code[0], 0) + 1
    print("infra-graph summary")
    print("  functions:", len(all_funcs), dict(sorted(by_type.items())))
    print("  artifacts:", len(artifacts))
    print("  related edges:", sum(len(v) for v in RELATED.values()))
    print("  retired:", len(retired))
    print("  orphans:", len(findings["orphans"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
