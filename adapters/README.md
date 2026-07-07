<!-- README -->

# Adapters

An **adapter** is the declarative contract between the harness-neutral STC
`core/` and one concrete harness's *native form*. The `core/` knows *what*
(a capability — research, qa, code-graph, a hook, a rule); the adapter knows
*how this harness realises it*.

> **The live-form problem.** Users reach the same model through different
> harnesses (Claude Code, ZCode, …), and each harness has a *different*
> native form: typed sub-agent files vs. untyped dispatch; `CLAUDE.md` vs.
> `AGENTS.md`; hooks wired in `settings.json` vs. a plugin manifest; `@import`
> vs. none. STC must not encode any of that into `core/` — that would freeze
> the framework to one harness. The adapter is where the live form lives.

## What an adapter is, and is not

**Is**
- a `adapter.yaml` (one per harness, under `adapters/<harness>/`) plus any
  harness-native glue the deploy step can't generate from the contract
  (e.g. `adapters/claude/statusline.sh`).
- declarative — it states *realisation per layer*, not imperative deploy logic.
- read by `deploy.py` (Stage 4); it owns no deploy-time behaviour itself.

**Is not**
- a copy of `core/`. The capability bodies (prompt, hook script, rule text)
  live once in `core/`. The adapter only *binds* them.
- a place for know-how. Methodology that travels across harnesses belongs in
  `core/skills/` (e.g. `code-reviewer`), not here.
- a place for **model ids**. The model is a *separate axis* — see below.

## Two orthogonal axes (do not confuse them)

| Axis | What it controls | Lives in | Examples |
|---|---|---|---|
| **Harness** | the live FORM — file layout, dispatch mechanism, hook wiring, import syntax | `adapters/<harness>/adapter.yaml` | claude, zcode, cursor |
| **Model** | the ENGINE — concrete model ids per tier, context windows, transport | `core/models/<provider>.yaml` | glm, claude, openai |

A harness does **not** dictate a model. Claude Code can run **GLM** behind the
Anthropic-compatible endpoint; ZCode can run Claude models. The two axes are
composed at deploy: the adapter gives the form, the provider gives the model
id, `registry.yaml` gives the tier an agent needs — **tier × provider = the
concrete id `deploy.py` renders**. The user picks the pairing in `stc.yaml`
(`deploy.targets` + `models.provider`). That is why `adapter.yaml` carries no
`model_tier_map` — it would wrongly tie a harness to one model family.

Concretely: "GLM in Claude Code" takes the **claude** adapter (CLAUDE.md,
typed agents, settings.json hooks — full native form) **× glm** provider
(tiers resolve to glm-5.2 / glm-5-turbo). No degradation of the form happens
— only the *harness* axis degrades form (claude→zcode loses typed agents
because zcode exposes none); the *model* axis never degrades form.

## The layer model

STC has six layers of capability. Each adapter declares, per layer:

```yaml
<layer>:
  realization: "<one line — the native mechanism this harness uses>"
  native_path: "<where the rendered artifact lives, e.g. ~/.claude/agents>"
  import_syntax: "<how one file includes another, e.g. @<path> | none>"
  capabilities:
    <capability-name>:
      supported: true | false | degrade
      native:    "<how the harness realises it, if supported != false>"
      fallback:  "<alternative layer + name, used when supported != true>"
      binding:   { ... }   # harness-specific values (model tier, tools, paths)
```

- **`supported: true`** — the layer exists natively; `native` describes the
  rendered artifact.
- **`supported: degrade`** — the layer exists in a *weaker* form (e.g. a
  typed agent becomes an untyped dispatch carrying a skill). `native`
  describes the degraded realisation; `fallback` names the methodology that
  fills the gap.
- **`supported: false`** — the layer is inert on this harness. `fallback`
  names the substitute layer (or `none`), and deploy skips the capability.

The principle is **capability ≠ realisation**: a capability is know-how
written once (neutral); a harness realises it differently. The adapter is the
mapping. Degrade gracefully — never lose the capability, only its native form.

## Layers

| Layer | `core/` source | Rendered by adapter to |
|---|---|---|
| `always_context` | `core/memory/MEMORY.md` (+ playbook, code_standard) | `CLAUDE.md` / `AGENTS.md` |
| `rules` | `core/rules/*.md` | inlined into always_context or hook-injected |
| `hooks` | `core/hooks/*.sh` | `settings.json` matchers / plugin `hooks.json` |
| `commands` | `core/commands/*.md` | `<harness>/commands/*.md` |
| `subagents` | `core/agents/*.md` + `registry.yaml` | typed agent files / untyped dispatch |
| `skills` | `core/skills/*/SKILL.md` | `<harness>/skills/<name>/SKILL.md` |
| `mcp` | `stc.yaml → mcp.*` | `<harness>/.mcp.json` / mcpServers |

## Canonical paths

- **Global home** — `~/.stc/` is the canonical STC home (shared across
  harnesses). The rendered harness files (`~/.claude`, `~/.zcode`) reference
  `~/.stc/core/...` so one update reaches every harness.
- **Per-harness native dir** — `~/.claude` (Claude), `~/.zcode` (ZCode). The
  adapter's `native_path` keys point here. These are *targets*, written only
  by `deploy.py` after the per-stage consent gate.

## What `deploy.py` (Stage 4) does with an adapter

1. Read `stc.yaml` (user) + `core/` (capabilities + tiers) +
   `core/models/<provider>.yaml` (model ids) + `adapters/<target>/adapter.yaml` (form).
2. For each layer, for each capability with `supported != false`:
   - copy / render the `core/` body into the adapter's `native_path`, applying
     the `binding`: **model tier** (from `registry.yaml`) × **provider** (from
     `core/models/<provider>.yaml`) → concrete model id; neutral **tools** →
     harness tool ids;
   - where `supported: degrade`, substitute the `fallback` (e.g. load a skill
     into a general-purpose dispatch instruction instead of a typed agent file).
3. Resolve render-time `${VARS}` (see `core/hooks/README.md`) from `stc.yaml`
   + the adapter's `vars:` block.
4. Write only inside the target harness dir (and `~/.stc/`). Never `~/.claude`
   or `~/.zcode` until the stage-5/6 consent gate.

## Adding a harness

Copy `adapters/_template/adapter.yaml` → `adapters/<your-harness>/adapter.yaml`,
fill the `realization` / `native_path` / `import_syntax` per layer, and set
`supported` per capability. Run `deploy.py --target <your-harness> --dry-run`
to preview. The capability bodies never change — only their binding.

## Files here

```
adapters/
├── README.md                    # this file
├── claude/
│   ├── adapter.yaml             # the live-form contract (typed agents, @import)
│   └── statusline.sh            # harness glue deploy can't generate from yaml
├── zcode/
│   └── adapter.yaml             # AGENTS.md, general-purpose degrade, plugin-fed
└── _template/
    └── adapter.yaml             # documented skeleton for a new harness
```
