# STC Core — Standard Template Construct

> _A Standard Template Construct stores the blueprints. The deploy pipeline reproduces them._
>
> In Warhammer 40k lore, an STC is a relic from the Dark Age of Technology — a terminal that holds complete, reproducible construction blueprints. You feed it a request, it emits a buildable design adapted to the materials at hand.
>
> This project borrows that idea. An AI coding agent (Claude Code, ZCode, or any harness) works well when its instructions, memory, skills, hooks, and tools are consistent across sessions. STC holds the blueprints of that configuration. A deploy command reproduces them into the concrete harness you use, adapted to its format.

## What it is

STC is a **template-construct pipeline for AI agent infrastructure**. It is not a single harness's config — it is the source of truth that generates one or many harness configs.

- **`core/`** — universal, harness-agnostic content: behavioral rules, memory references, skills, slash commands, hooks, project templates. Written in English (public standard). This is the part you publish and contribute to.
- **`user/`** — your private configuration: profile, project notes, secrets. Git-ignored. Never committed.
- **`adapters/`** — per-harness deployment descriptors (how `core/` maps onto `~/.claude`, `~/.zcode`, ...). Each adapter knows the target's instruction file format, hook binding, MCP config layout.
- **`deploy/`** — the pipeline itself: a Python `deploy.py` that renders `core/` + `user/` into a concrete harness directory. Docs are markdown-local-first (a `.md` file under `doc_backend.root`; an editor like Obsidian in vault mode is a view, not the store).

## Why

Hand-tuning `~/.claude` or `~/.zcode` works for one person and one harness. The moment you want the same behavior across two harnesses, or share your setup with someone else, the configs drift. STC exists to make drift impossible by construction: **edit once in `core/`, deploy to any target.**

## Quickstart

```bash
git clone https://github.com/Literallystuckonthisplanet/STC.git
cd STC

# 1. Fill your private config from the examples
cp stc.example.yaml stc.yaml                # edit: your name, role, workspace, MCP ports,
                                            #        models.<harness> per-target overrides
cp user/profile.example.md user/profile.md  # edit: your style, stack, voice dictionary
cp user/secrets.env.example user/secrets.env  # add tokens (GITHUB_*, GRAPHIFY_CLI, ...)

# 2. Preview what deploy would write (no live writes)
python3 deploy/deploy.py check
python3 deploy/deploy.py render --target claude --dry-run   # or zcode

# 3. Deploy into a harness (writes ~/.stc/ + the native dir; backs up first)
python3 deploy/deploy.py apply --target claude    # → ~/.claude
# python3 deploy/deploy.py apply --target zcode   # → ~/.zcode (as a plugin)

# Roll back a deploy if it went wrong:
python3 deploy/deploy.py restore <backup-id>      # id printed by apply
python3 deploy/deploy.py uninstall --target claude
```

`apply` is non-destructive by construction: every markdown artifact carries a
`.stc.md` / `.stc.sh` suffix (never collides with user files); `settings.json`
and `.mcp.json` are merged under the `_stc_managed` / `stc-` namespace (STC
entries are update-in-place on re-deploy, user entries are preserved); a
backup snapshot of every JSON touched is taken before any write.

## Model providers per harness

Each harness speaks one model family. Claude Code on an Anthropic subscription
resolves only the short aliases (`haiku`/`sonnet`/`opus`); ZCode maps
Anthropic names onto GLM ids. So `stc.yaml` lets you pin a provider per target:

```yaml
models:
  provider: glm               # default (used when a target has no override)
  claude:  claude             # Claude Code → sonnet/haiku/opus
  zcode:   glm                # ZCode → glm-5.2/glm-5-turbo
```

A global `provider: glm` is the legacy single-provider form and still works —
but a Claude Code harness on an Anthropic sub will silently fail to dispatch
typed sub-agents with `model: glm-5.2`. Set the per-target override.

## Testing

```bash
python3 deploy/tests/test_render.py    # zero-dependency stdlib runner
# or, if pytest is installed:
python3 -m pytest deploy/tests/        # the suite is pytest-compatible
```

The suite pins every deploy bug from the history (double-wiring merge,
idempotent re-deploy, legacy-hook absorption, provider-per-harness, naming
consistency, session-path warnings) so they cannot silently return.

## What goes where

```
STC/
├── core/        # universal blueprints (public)
├── user/        # your private config (gitignored)
├── adapters/    # how core maps onto each harness
├── deploy/      # the pipeline (render + apply + check + uninstall + restore)
│   └── tests/   # regression suite
└── docs/        # architecture, progress
```

See [`docs/PROGRESS.md`](docs/PROGRESS.md) for the architecture and progress,
and [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## Status

Early beta. Targets a small group first, then public. The `0.1.0` line carries
the deploy pipeline; breaking changes can happen between minor bumps until
`1.0.0`.

## License

MIT.
