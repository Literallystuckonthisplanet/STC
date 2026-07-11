---
name: code-graph
description: "Turn a codebase into a queryable knowledge graph via graphify (REQUIRED core capability). Use when entering an unfamiliar repo, asking 'how does X connect to Y', before an architectural change (impact analysis), or when grep-escalations aren't enough. Builds the graph once, queries it on demand. Wraps the graphify CLI."
---

# Code graph (graphify)
<!-- S18 -->

A **required** STC capability. graphify (safishamsi/graphify) turns a folder
of code (sources, SQL schemas, scripts, docs, papers, images) into a
queryable knowledge graph: tree-sitter AST extraction (36 grammars) +
LLM-driven entity/relation clustering. Build once, query on demand — the
graph compounds; grep does not.

## Prerequisite

graphify CLI is installed (`${GRAPHIFY_CLI}`, default `graphify`). Part of
the STC base set — like Playwright for e2e. Verify:

```bash
graphify --version
```

Not installed → install per the upstream (safishamsi/graphify), then
`graphify install --platform <harness>` to wire the harness skill. See
`install-mcp.md` for the per-harness wiring.

## When to use

- **Entering an unfamiliar repo** → `extract .`, then `query`/`explain` to get
  the lay of the land faster than reading files linearly.
- **"How does X connect to Y" / "what calls this"** → `path` (shortest path
  between two nodes) or `affected` (reverse traversal — what a change to X
  impacts).
- **Before an architectural change or refactor** → `affected "<node>"` for
  the blast radius; `query` for the rationale context.
- **Cross-repo question** → `merge-graphs` then query the merged graph.
- **Ongoing work in a repo** → `query` instead of escalating grep chains;
  `save-result` after a good Q&A so the graph's feedback loop learns.

## When NOT to use

- A trivial repo (a few files, obvious structure) — the graph is overhead.
- A one-off single-file lookup — grep is faster than a full extract.
- The question is about a *running* system's behavior, not its code
  structure → use Playwright/e2e, not the code graph.

## Commands (by group)

`${G} = ${GRAPHIFY_CLI}` (default `graphify`). Run inside the repo root
unless noted. Output lands in `graphify-out/` (gitignored in target repos).

### Build / refresh
- `${G} extract .` — initial build. Extracts code → graph.json + report +
  communities. Heaviest step; run once per repo, then maintain incrementally.
  (`--backend`/`--model` pick the clustering LLM.) NOTE: there is no `ingest`
  command in graphify 0.9.x — build is `extract`, refresh is `update`.
- `${G} update` — re-extract changed code files, update the graph (no LLM
  needed unless new communities). Use after edits. `--force` overwrites even
  if the rebuild has fewer nodes (after a deletion-heavy refactor).
- `${G} watch <path>` — watch a folder, rebuild on code changes. For active
  sessions.
- `${G} cluster-only <path>` — rerun clustering on an existing graph.json,
  regenerate the report. `--no-viz` for large graphs / CI.
- `${G} label <path>` — (re)name communities with the configured LLM.
  `--missing-only` to keep existing labels.

### Query
- `${G} query "<question>"` — BFS traversal of graph.json for a question.
  `--dfs`, `--context <edge>`, `--budget <tokens>` (default 2000).
- `${G} affected "<node>"` — reverse traversal: what is impacted by X.
  `--relation <R>`, `--depth <N>` (default 2).
- `${G} path "A" "B"` — shortest path between two nodes.
- `${G} explain "<node>"` — plain-language explanation of a node + neighbors.
- `${G} diagnose multigraph` — report same-endpoint edge-collapse risk.

### Lessons / feedback (the Karpathy pattern over the graph)
- `${G} reflect` — generate/update `LESSONS.md` from the graph's `memory/`
  (the work-memory feedback loop; aggregates saved `save-result` outcomes).
- `${G} add <url>` — fetch a source into `./raw` and fold it into the graph
  (the Ingest step of the llm-wiki pattern for external docs/papers).
  NOTE: graphify 0.9.x has **no `wiki` command** — the llm-wiki pattern is
  realised via `add` (ingest) + `query` + `save-result`/`reflect` (lessons),
  not a single `wiki` builder. See the `llm-wiki` skill for the pattern.

### Cross-repo / git
- `${G} merge-graphs <g1> <g2>` — merge two graph.json files into one
  cross-repo graph. `--out <path>`.
- `${G} merge-driver <base> <current> <other>` — git merge driver for
  graph.json (union-merge; set up via `hook install`).
- `${G} clone <github-url>` — clone a repo locally for `/graphify`.
- `${G} add <url>` — fetch a URL into `./raw`, then update the graph
  (docs/papers as additional sources).

### Feedback loop
- `${G} save-result` — save a Q&A result to `graphify-out/memory/` so the
  graph's feedback loop incorporates it. `--question <Q>`.

## Output

`graphify-out/`:
- `graph.json` — the graph (nodes = entities, edges = relations).
- `report` — human-readable summary (communities, stats).
- `memory/` — the feedback-loop work-memory (feeds `reflect`).
- `graph.html` — interactive viz (skippable for large graphs / CI).

This folder is **gitignored in target repos** (it is derived, not source).

## Workflow

1. **First contact with a repo** → `${G} extract .`. Then a couple of
   `query`/`explain` to orient.
2. **During work** → `query` for "how/why" questions instead of escalating
   grep. `affected` before a non-trivial change.
3. **After a good Q&A** → `${G} save-result` (the feedback loop).
4. **At session/milestone boundaries** → `${G} update` (refresh) and
   optionally `${G} reflect` (lessons).

## Notes

- **Reference implementation:** graphify (safishamsi/graphify, YC S26). The
  skill is written neutrally, but graphify is the only supported path in STC.
- graphify auto-detects the LLM backend for community labeling
  (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). No per-query cost for `query`/
  `affected`/`path`/`explain` (graph traversal) — LLM cost is only on
  `extract` (clustering), `label`, `reflect`.
- For the *knowledge-wiki* angle (compile-once, not RAG), see the `llm-wiki`
  skill — over a code graph the pattern is realised via `add` (ingest) +
  `query` + `reflect` (there is no single `wiki` command in graphify 0.9.x).
