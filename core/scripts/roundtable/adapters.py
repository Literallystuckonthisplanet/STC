#!/usr/bin/env python3
"""Roundtable — build the final critic invocations. Nothing is started here.

Review round 6 found a cycle: the isolation spike Ш1 must test the *final*
command, yet the runner that would produce it was to be written after the spike
passed. The cycle is broken by splitting the work — Б3а builds commands as pure
functions, Ш1 fires them, Б3б runs them for real — so this module deliberately
has no subprocess call and no I/O.

Every flag below is a boundary, and each one was read out of the installed CLI
rather than remembered:

    claude --help            # 2.1.227
    codex exec --help        # codex-cli 0.147.0-alpha.6.5

# docs-checked: `claude --help` and `codex exec --help`, executed 2026-08-12 on
# the pinned versions above; every flag used here appears in that output. The
# vendors have no SDK contract in play — this module only assembles argv.

Four Claude flags are four different boundaries and are needed together
(§5.1 of docs/roundtable.md): `--safe-mode` drops user instructions, skills,
hooks and plugins; `--tools ""` drops the built-in tools; `--strict-mcp-config`
drops MCP servers; `--no-session-persistence` stops the session from being
written to disk.

🚩 The material never travels in argv. argv is visible in the process list and
bounded in length, so both commands are built to read their instructions from
stdin — Claude from a piped `-p`, Codex from the explicit `-` positional.
"""

from __future__ import annotations

import json
import os

# Values `claude --effort` accepts. Codex takes the same names through
# `-c model_reasoning_effort="…"`; `max` is the one already in production use
# (core/scripts/codex_live_canary.py).
EFFORTS = ("low", "medium", "high", "xhigh", "max")

VENDORS = ("claude", "codex")

# Arguments that would undo the boundary this module exists to build. The
# canary (codex_live_canary.py) passes the first two on purpose — it *wants*
# hooks loaded, because it is checking that STC's own context arrives. A critic
# must never get them, which is why its command is built here and not copied
# from there.
FORBIDDEN_ARGUMENTS = (
    "--enable",
    "--dangerously-bypass-hook-trust",
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--approve-for-me",
)

# The environment is a whitelist, not a filtered copy: a copy leaks whatever
# the parent happens to carry, and the leak is silent.
ENVIRONMENT_WHITELIST = ("PATH", "TMPDIR", "LANG", "LC_ALL", "TERM")

# Stripped by name as well, so that widening the whitelist above cannot quietly
# hand a critic a third-party gateway. The base URL would route the call
# somewhere else entirely; the two credentials would pay for it.
STRIPPED_VARIABLES = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)


class CommandRefused(ValueError):
    """The requested command could not be built as a safe one."""


def _guard(command: list[str]) -> list[str]:
    """Refuse to hand back a command carrying a boundary-breaking argument."""
    for argument in command:
        if argument in FORBIDDEN_ARGUMENTS:
            raise CommandRefused(f"forbidden argument: {argument}")
    return command


def _text(name: str, value) -> str:
    text = str(value).strip()
    if not text:
        raise CommandRefused(f"{name} must not be empty")
    return text


def _effort(value: str) -> str:
    if value not in EFFORTS:
        raise CommandRefused(f"unknown effort {value!r}, expected one of {EFFORTS}")
    return value


def build_claude_command(claude_bin, model: str, effort: str, schema: dict) -> list[str]:
    """Build the headless Claude invocation for one critic call.

    The prompt is absent on purpose: `-p` with no positional argument makes
    Claude read the material from stdin.
    """
    if not isinstance(schema, dict) or not schema:
        raise CommandRefused("a critic call needs a non-empty JSON schema")
    return _guard([
        _text("claude_bin", claude_bin),
        "-p",
        "--model", _text("model", model),
        "--effort", _effort(effort),
        "--safe-mode",
        "--no-session-persistence",
        "--tools", "",
        "--strict-mcp-config",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, ensure_ascii=False, sort_keys=True),
    ])


def build_codex_command(
    codex_bin,
    model: str,
    effort: str,
    schema_path,
    answer_path,
    cd,
) -> list[str]:
    """Build the headless Codex invocation for one critic call.

    `--skip-git-repo-check` is required rather than optional: the working
    directory is a throwaway one outside every repository (§5.2, axis one), and
    Codex refuses to start outside a git repository without it.

    The trailing `-` is the documented way to say "instructions come from
    stdin" (`codex exec --help`).
    """
    return _guard([
        _text("codex_bin", codex_bin),
        "exec",
        "--model", _text("model", model),
        "-c", f'model_reasoning_effort="{_effort(effort)}"',
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--cd", _text("cd", cd),
        "--output-schema", _text("schema_path", schema_path),
        "--output-last-message", _text("answer_path", answer_path),
        "-",
    ])


def build_environment(vendor: str, home, codex_home=None, source=None) -> dict:
    """Build the whitelisted environment for one critic process.

    `home` is the throwaway HOME that closes axis two: Codex loads its 24 user
    skills from `$HOME/.agents/skills` (adapters/codex/adapter.yaml:225), not
    from CODEX_HOME, so an empty CODEX_HOME alone would leave them in place.

    `codex_home` closes axis three and is mandatory for Codex: authentication
    still reads CODEX_HOME even under `--ignore-user-config`, so the process
    does not start without one.
    """
    if vendor not in VENDORS:
        raise CommandRefused(f"unknown vendor {vendor!r}, expected one of {VENDORS}")
    source = os.environ if source is None else source

    environment = {name: source[name] for name in ENVIRONMENT_WHITELIST if name in source}
    environment["HOME"] = _text("home", home)

    if vendor == "codex":
        if codex_home is None:
            raise CommandRefused("codex needs its own CODEX_HOME: auth still reads it")
        environment["CODEX_HOME"] = _text("codex_home", codex_home)
    elif codex_home is not None:
        raise CommandRefused("claude has no CODEX_HOME; passing one hides a vendor mix-up")

    for name in STRIPPED_VARIABLES:
        environment.pop(name, None)
    return environment
