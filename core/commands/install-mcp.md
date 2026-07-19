---
description: "Install, remove, configure, or debug an MCP server for the target harness. Contains the correct command format, typical errors, and fixes."
---

# Install MCP servers
<!-- S07 -->

## Requirements

- **OS:** macOS / Linux
- **Node:** v20+ with npx
- **Harness CLI:** installed and on PATH
- **MCP config location:** harness-specific (see adapter — e.g.
  `~/.claude.json` for Claude Code, the equivalent for other harnesses)

## Correct command format (Claude Code)

```bash
claude mcp add --transport stdio --env KEY=value <server-name> -- npx -y @namespace/package
```

### Critical rules
1. **All flags BEFORE the server name:** `--transport`, `--env`, `--scope`.
2. **`--` separates the run command** from the Claude CLI arguments.
3. **Always `-y` on npx** — otherwise npx waits for confirmation and stdio hangs.
4. **Default scope = local** (per-user config).

For other harnesses, the command differs — use `${MCP_ADD_CMD}` from the
adapter, which maps to the harness-native equivalent. The principles (flags
before name, `-y` on npx, separating the run command) carry over.

## Examples

### Playwright (browser)
```bash
claude mcp add --transport stdio playwright -- npx -y @playwright/mcp@latest --output-dir tmp/.playwright-mcp
```

### GitHub
```bash
claude mcp add --transport stdio --env GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx github -- npx -y @modelcontextprotocol/server-github
```

### graphify (code-graph — REQUIRED)
graphify is a **standalone CLI** (`~/.local/bin/graphify`), not an npx server.
Install the binary per the upstream (safishamsi/graphify), then wire it into
the harness as a skill (it copies its skill file into the harness config dir):

```bash
graphify --version                 # verify the binary
graphify install --platform claude # wire into Claude Code (also: codex|opencode|cursor|gemini|...)
```

It auto-detects `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for community labeling.
Optional: `GRAPHIFY_CLI=/path/to/graphify` to point at a non-default binary.
Per-repo output (`graphify-out/`) should be gitignored in target repos. See
the `code-graph` skill for usage.

### Notion
```bash
claude mcp add --transport stdio --env NOTION_TOKEN=xxx notion -- npx -y @notionhq/notion-mcp-server
```

### HTTP server (no npx)
```bash
claude mcp add --transport http <name> <url>
```

## Scope (Claude Code) — where it is saved

| Flag | File | When to use |
|------|------|-------------|
| (default / `--scope local`) | `~/.claude.json` | Personal server |
| `--scope project` | `.mcp.json` at project root | For a team (committed to git) |
| `--scope user` | `~/.claude.json` | Cross-project personal |

## Management & debugging

```bash
claude mcp list                 # all servers + status
claude mcp get <name>           # details of one
claude mcp remove <name>        # remove
```

Inside Claude Code: `/mcp` — status of all servers + OAuth authorization.

### If a server isn't working
1. Verify the package works: `npx -y @namespace/package --help`
2. Increase the timeout: `MCP_TIMEOUT=10000 claude`
3. Increase the output limit: `MAX_MCP_OUTPUT_TOKENS=50000 claude`
4. Check the logs: `~/.claude/logs/`

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| Flags ignored | Written after the server name | Move them before the name |
| Connection closed | npx is waiting for confirmation | Add `-y` |
| Timeout on start | Slow package load | `MCP_TIMEOUT=10000` |
| Duplicate configs | Both global and project configs exist | Remove the duplicate |
