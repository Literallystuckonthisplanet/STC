---
name: llm-wiki
description: "The Karpathy LLM-Wiki pattern: compile knowledge ONCE into a maintained markdown wiki, not re-derive it on every query like RAG. Three operations (Ingest / Query / Lint), three layers (raw sources / wiki / schema). Use for long-running research, a second-brain, or a knowledge base over a codebase/docs. graphify wiki/reflect is the primary implementation in STC."
---

# LLM Wiki (the Karpathy pattern)
<!-- S19 -->

A pattern by Andrej Karpathy (April 2026): treat the LLM as a **knowledge
compiler**, not a retrieval engine. In RAG the model re-derives knowledge
from scratch on every question — *"there's no accumulation"*. In an LLM Wiki
the knowledge is **compiled once** and then kept current: cross-references
are already made, contradictions already flagged, the synthesis already
reflects everything read.

> *"Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase."*
> — Karpathy

## The three operations

### 1. Ingest
Drop a new source into `raw/` and tell the LLM to process it. The LLM does
**not** just index it — it reads it, extracts the key information, and
**integrates** it into the existing wiki:
- writes a summary page for the source,
- updates the relevant entity and concept pages across the wiki,
- updates `index.md`,
- notes where new data contradicts old claims,
- appends an entry to `log.md`.

A single source may touch 10–15 wiki pages. The knowledge is *compiled once
and kept current*, not re-derived on every query.

### 2. Query
Ask a question against the wiki. The LLM searches for relevant pages, reads
them, and synthesizes an answer with citations. Good answers get **filed
back** into the wiki as new pages — so exploration compounds the same way
ingest does.

### 3. Lint
Run **periodically** (the maintenance pass). The LLM health-checks the wiki:
- contradictions between pages,
- stale claims superseded by newer sources,
- orphan pages with no inbound links,
- important concepts mentioned but lacking their own page,
- missing cross-references,
- data gaps that could be filled with a web search.

This is the whole point: humans abandon wikis because the maintenance burden
grows faster than the value. The LLM doesn't get bored and can touch 15 files
in one pass — so the cost of maintenance is near zero and the wiki stays
healthy as it grows.

## The three layers

1. **Raw sources** (`raw/`) — your curated source documents. **Immutable.**
   The LLM reads from them but never modifies them. This is the source of
   truth.
2. **The wiki** — a directory of LLM-generated markdown files: summaries,
   entity pages, concept pages, comparisons, an overview, a synthesis. The
   LLM **owns this layer entirely** — you read it, the LLM writes it.
3. **The schema** — the instruction file (`AGENTS.md` / `CLAUDE.md`) that
   tells the LLM how the wiki is structured, the conventions, and the
   workflows for ingest/query/lint. This is what makes the LLM a disciplined
   wiki maintainer rather than a generic chatbot. It co-evolves with the LLM.

## The two special files

- **`index.md`** — a content-oriented catalog. Each page listed with a link,
  a one-line summary, optional metadata (date, source count), organized by
  category. The LLM reads `index.md` first to find relevant pages, then
  drills in. Updated on every ingest.
- **`log.md`** — append-only, chronological. An entry per action, prefixed
  `## [YYYY-MM-DD] <op> | <title>`, so you can grep:
  `grep "^## \[" log.md | tail -5`.

## Conventions

- Plain markdown in a git repo (version history, branching, collaboration for
  free). Interlinked with `[[wikilinks]]`.
- YAML frontmatter on wiki pages (tags, dates, source counts) so a Dataview-
  capable editor (Obsidian) can query it.
- At moderate scale (~100 sources, hundreds of pages) the `index.md` alone is
  enough — no embedding-based RAG infrastructure needed.
- Past ~hundreds of pages, add a local search engine (qmd: BM25/vector hybrid
  + LLM re-ranking) when the index is no longer enough.

## When to use

- **Long-running research** (weeks/months of reading) → a wiki with an
  evolving thesis.
- **Second brain** — goals, health, journal, podcast notes, articles.
- **A knowledge base over a codebase/docs** → this is where it meets the
  `code-graph` skill: graphify `wiki`/`reflect` implement the LLM-Wiki
  pattern over a code graph.

## Implementations (in STC)

- **graphify** (`code-graph` skill) — `graphify wiki` builds an
  agent-crawlable markdown wiki from the code graph; `graphify reflect`
  generates/maintains `LESSONS.md` from the graph's work-memory. This is the
  **primary** path in STC (graphify is a required capability).
- **Manual** — an editor (Obsidian) + an agent following this skill, over
  your own `raw/` + wiki directory. The pattern is editor-agnostic; the wiki
  is just markdown.
- **qmd** — optional local search when the index outgrows grep.

## Source

Andrej Karpathy, *"llm-wiki"* (gist, April 4, 2026) — the canonical primary
source. The pattern is intentionally abstract ("describes the idea, not a
specific implementation"); implementations adapt it to their domain.
