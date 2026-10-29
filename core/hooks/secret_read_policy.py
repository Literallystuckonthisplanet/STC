#!/usr/bin/env python3
"""Shared H17 policy for structured reads and Codex shell commands.

Input is one hook event as JSON on stdin. Output is exactly one of:
``allow``, ``blocked:<fixed pattern label>``, or ``unparsed``.
This module never reads target file contents or echoes paths, queries, or values.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import sys


# This is the canonical H17 policy. The same entries drive path checks,
# protected textual hints, and the exact -g exclusions accepted for rg scans.
PROTECTED = [
    (
        ".env*",
        ".env",
        "!**/.env*",
        r"(^|[^a-z0-9_])\.env(?:\.[a-z0-9_*?-]+)*([^a-z0-9_-]|$)",
    ),
    (
        "*.env*",
        ".env",
        "!**/*.env*",
        r"(^|[^a-z0-9_])\.env(?:\.[a-z0-9_*?-]+)*([^a-z0-9_-]|$)",
    ),
    (
        "*.pem",
        "*.pem",
        "!**/*.pem",
        r"(^|[^a-z0-9_])[^\s]+\.pem([^a-z0-9_]|$)",
    ),
    (
        "id_rsa*",
        "id_rsa",
        "!**/id_rsa*",
        r"(^|[^a-z0-9_])id_rsa([^a-z0-9_]|$)",
    ),
    (
        "*credentials*",
        "credentials",
        "!**/*credentials*",
        r"(^|[^a-z0-9_])credentials([._-][a-z0-9_-]+)*([^a-z0-9_]|$)",
    ),
]

SHELL_TOOLS = {"Bash", "exec", "unified_exec", "unifiedExec", "LocalShell", "shell"}
READ_TOOLS = {"Read", "Grep", "Glob"}
RG_SAFE_FLAGS = {"-n", "-i", "-l"}
RG_VALUE_FLAGS = {"-e", "--regexp", "-f", "--file", "-g", "--glob"}
SHELL_OPERATORS = "|&;<>()"


def label_for_component(component: str) -> str:
    value = component.rstrip("/").rsplit("/", 1)[-1].lower()
    for pattern, label, _, _ in PROTECTED:
        if fnmatch.fnmatchcase(value, pattern):
            return label
    return ""


def label_in_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.lower()
    for _, label, _, expression in PROTECTED:
        if re.search(expression, text):
            return label
    return ""


def resolved_path(value: str, cwd: str) -> str:
    return os.path.realpath(os.path.join(cwd, value))


def path_label(value: object, cwd: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    for component in resolved_path(value, cwd).split(os.sep):
        label = label_for_component(component)
        if label:
            return label
    return ""


def target_status(value: object, cwd: str) -> tuple[str, str]:
    if not isinstance(value, str) or not value:
        return "unparsed", ""
    # A literal shell home token is not the path the shell will execute.
    if value.startswith("~"):
        return "unparsed", ""
    label = path_label(value, cwd)
    if label:
        return "blocked", label
    return "safe", ""


def _rg_operators_are_present(words: list[str]) -> bool:
    return any(word and all(char in SHELL_OPERATORS for char in word) for word in words)


def parse_rg(command: object, cwd: str) -> tuple[str, str]:
    """Parse the deliberately small read-only rg subset.

    Unsupported syntax returns ``unparsed`` only when a protected hint is
    present; ordinary unknown commands keep the existing pass behavior.
    Directory scans have a known scope, so they require the complete exclusion
    set even when the query itself contains no protected hint.
    """
    if not isinstance(command, str) or not command:
        return "unknown", ""
    if "#" in command or any(char in command for char in "\0\n\r$`"):
        return "unknown", ""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return "unknown", ""
    if not words or words[0] != "rg" or _rg_operators_are_present(words):
        return "unknown", ""

    expressions: list[str] = []
    file_operands: list[str] = []
    globs: list[str] = []
    positional: list[str] = []
    i = 1
    end_options = False
    while i < len(words):
        word = words[i]
        if end_options:
            positional.append(word)
            i += 1
            continue
        if word == "--":
            end_options = True
            i += 1
            continue
        if word in RG_SAFE_FLAGS:
            i += 1
            continue
        if word == "-C" or (word.startswith("-C") and word != "-C"):
            if word == "-C":
                i += 1
                if i >= len(words) or not words[i].isdigit():
                    return "unknown", ""
            elif not word[2:].isdigit():
                return "unknown", ""
            i += 1
            continue
        if word in RG_VALUE_FLAGS:
            if i + 1 >= len(words):
                return "unknown", ""
            value = words[i + 1]
            if value.startswith("~"):
                return "unparsed", ""
            if word in ("-e", "--regexp"):
                expressions.append(value)
            elif word in ("-f", "--file"):
                file_operands.append(value)
            else:
                globs.append(value)
            i += 2
            continue
        if word.startswith("-"):
            return "unknown", ""
        positional.append(word)
        i += 1

    if not expressions and not file_operands:
        if not positional:
            return "unknown", ""
        expressions.append(positional.pop(0))
    targets = positional or ["."]

    for value in targets + file_operands:
        if value.startswith("~") or any(char in value for char in "*?[]{}"):
            return "unparsed", ""
        status, label = target_status(value, cwd)
        if status != "safe":
            return status, label

    if any(os.path.isdir(resolved_path(target, cwd)) for target in targets):
        required = {entry[2] for entry in PROTECTED}
        if not required.issubset(set(globs)):
            return "unparsed", ""
        # Positive globs could re-open protected files after exclusions.
        if any(not glob.startswith("!") and glob not in required for glob in globs):
            return "unparsed", ""
    return "safe", ""


def _raw_fields(tool_input: dict, event: dict) -> list[tuple[str, object]]:
    values: list[tuple[str, object]] = []
    for key in ("command", "cmd", "input", "script"):
        if key in tool_input:
            values.append(("tool_input." + key, tool_input[key]))
    args = tool_input.get("args")
    if isinstance(args, list):
        values.extend(("tool_input.args", value) for value in args)
    for key in ("command", "input"):
        if key in event:
            values.append(("event." + key, event[key]))
    return values


def _codex_shell_decision(tool_input: dict, event: dict, cwd: str) -> tuple[str, str]:
    for key in ("file_path", "path"):
        value = tool_input.get(key)
        if not value:
            continue
        status, label = target_status(value, cwd)
        if status != "safe":
            return status, label
    paths = tool_input.get("paths")
    if isinstance(paths, list):
        for value in paths:
            status, label = target_status(value, cwd)
            if status != "safe":
                return status, label

    command_fields = [
        (key, tool_input[key])
        for key in ("command", "cmd")
        if isinstance(tool_input.get(key), str)
    ]
    if len(command_fields) == 2 and command_fields[0][1] != command_fields[1][1]:
        return "unparsed", ""

    selected_field = None
    command = None
    if command_fields:
        selected_field = "tool_input." + command_fields[0][0]
        command = command_fields[0][1]
    else:
        rg_fields = [
            ("tool_input." + key, tool_input[key])
            for key in ("input", "script")
            if isinstance(tool_input.get(key), str) and tool_input[key].lstrip().startswith("rg ")
        ]
        rg_fields.extend(
            ("event." + key, event[key])
            for key in ("command", "input")
            if isinstance(event.get(key), str) and event[key].lstrip().startswith("rg ")
        )
        if len({value for _, value in rg_fields}) > 1:
            return "unparsed", ""
        if rg_fields:
            selected_field, command = rg_fields[0]

    if command is not None:
        status, label = parse_rg(command, cwd)
        if status == "unknown":
            label = label_in_text(command)
            if label:
                if command.lstrip().startswith("rg ") or re.search(r"[;&|<>]|\$\(|`", command):
                    return "unparsed", ""
                return "blocked", label
            # Unsupported command/syntax without protected hints retains the
            # baseline pass behavior.
        elif status != "safe":
            return status, label

    same_duplicate_command = (
        len(command_fields) == 2 and command_fields[0][1] == command_fields[1][1]
    )
    raw_values = _raw_fields(tool_input, event)
    for field, value in raw_values:
        if selected_field and field == selected_field:
            continue
        if same_duplicate_command and field in ("tool_input.command", "tool_input.cmd"):
            continue
        if selected_field and field in ("event.command", "event.input") and value == command:
            continue
        if selected_field and field in ("event.command", "event.input") and value == command:
            continue
        label = label_in_text(value)
        if label:
            if isinstance(value, str) and re.search(r"[;&|<>]|\$\(|`", value):
                return "unparsed", ""
            return "blocked", label
    return "safe", ""


def _codex_shell_cwd(tool_input: dict, event: dict) -> tuple[str, str]:
    """Resolve the actual shell working directory without shell expansion."""
    event_cwd = event.get("cwd") or os.getcwd()
    if not isinstance(event_cwd, str) or not event_cwd:
        return "unparsed", ""
    context = os.path.abspath(event_cwd)

    candidates: list[str] = []
    for key in ("cwd", "workdir"):
        if key not in tool_input or tool_input[key] is None:
            continue
        value = tool_input[key]
        if not isinstance(value, str) or not value or value.startswith("~"):
            return "unparsed", ""
        candidates.append(os.path.realpath(os.path.join(context, value)))

    if len(candidates) == 2 and candidates[0] != candidates[1]:
        return "unparsed", ""
    resolved = candidates[0] if candidates else os.path.realpath(context)
    status, label = target_status(resolved, context)
    if status != "safe":
        return status, label
    return "safe", resolved


def _structured_decision(tool: str, tool_input: dict, cwd: str) -> tuple[str, str]:
    if tool == "Read":
        paths = [tool_input.get("file_path"), tool_input.get("path")]
        paths = [path for path in paths if path]
        if not paths:
            return "unparsed", ""
        for value in paths:
            status, label = target_status(value, cwd)
            if status != "safe":
                return status, label
        return "safe", ""

    if tool == "Grep":
        # `pattern` is search data. Only actual path operands are inspected.
        targets: list[object] = []
        for key in ("path", "file_path"):
            value = tool_input.get(key)
            if value:
                targets.append(value)
        paths = tool_input.get("paths")
        if isinstance(paths, list):
            targets.extend(paths)
        if not targets:
            return "unparsed", ""
        for value in targets:
            status, label = target_status(value, cwd)
            if status != "safe":
                return status, label
            if os.path.isdir(resolved_path(value, cwd)):
                # These structured adapter schemas do not expose the complete
                # canonical exclusion set as a repeatable field. Refuse folder
                # walks instead of guessing at partial `glob` filters.
                return "unparsed", ""
        return "safe", ""

    if tool == "Glob":
        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return "unparsed", ""
        if pattern.startswith("~"):
            return "unparsed", ""
        label = label_in_text(pattern)
        if label:
            return "blocked", label
        for key in ("path", "base_path"):
            base_path = tool_input.get(key)
            if base_path:
                status, label = target_status(base_path, cwd)
                if status != "safe":
                    return status, label
        if any(char in pattern for char in "*?[]{}"):
            # Glob reports matching names, not file contents. Ordinary
            # wildcard patterns are safe; explicit protected hints were
            # rejected above, and any supplied base path was checked.
            return "safe", ""
        return target_status(pattern, cwd)

    return "allow", ""


def decide(event: dict, harness: str) -> tuple[str, str]:
    if not isinstance(event, dict):
        return "unparsed", ""
    tool = event.get("tool_name") or event.get("tool") or ""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if harness == "codex" and tool in SHELL_TOOLS:
        status, shell_cwd = _codex_shell_cwd(tool_input, event)
        if status != "safe":
            return status, ""
        return _codex_shell_decision(tool_input, event, shell_cwd)
    cwd_value = tool_input.get("cwd") or event.get("cwd") or os.getcwd()
    if not isinstance(cwd_value, str):
        return "unparsed", ""
    cwd = os.path.abspath(cwd_value)

    if tool in READ_TOOLS:
        return _structured_decision(tool, tool_input, cwd)
    return "allow", ""


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--harness", required=True, choices=("claude", "codex", "zcode"))
    args = parser.parse_args()
    try:
        event = json.load(sys.stdin)
        status, label = decide(event, args.harness)
    except Exception:
        # Malformed hook data must never leak raw input or fail open.
        status, label = "unparsed", ""
    if status == "blocked":
        print("blocked:" + label)
    elif status == "safe" or status == "allow":
        print("allow")
    else:
        print("unparsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
