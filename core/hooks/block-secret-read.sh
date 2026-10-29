#!/bin/bash
# H17 — Codex-native secret-read guard.
#
# Codex has no Claude-style permissions.deny engine. This hook covers the
# structured read tools and shell-shaped command tools without printing paths,
# commands, tool output, or possible secret values.
#
# Render-time vars: ${USER_LANG} (en|ru, default en).

INPUT=$(cat)
USER_LANG="${USER_LANG:-en}"
RESULT=$(printf '%s' "$INPUT" | python3 -I -c '
import fnmatch
import json
import os
import re
import shlex
import sys

# One policy list drives exact-path checks and mandatory directory exclusions.
PROTECTED = [
    (".env*", ".env", "!**/.env*", r"(^|[^a-z0-9_])\.env(?:\.[a-z0-9_*?-]+)*([^a-z0-9_-]|$)"),
    ("*.env*", ".env", "!**/*.env*", r"(^|[^a-z0-9_])\.env(?:\.[a-z0-9_*?-]+)*([^a-z0-9_-]|$)"),
    ("*.pem", "*.pem", "!**/*.pem", r"(^|[^a-z0-9_])[^\s]+\.pem([^a-z0-9_]|$)"),
    ("id_rsa*", "id_rsa", "!**/id_rsa*", r"(^|[^a-z0-9_])id_rsa([^a-z0-9_]|$)"),
    ("*credentials*", "credentials", "!**/*credentials*", r"(^|[^a-z0-9_])credentials([._-][a-z0-9_-]+)*([^a-z0-9_]|$)"),
]

def label_for_path(path):
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    for pattern, label, _, _ in PROTECTED:
        if fnmatch.fnmatchcase(name, pattern):
            return label
    return ""

def label_in_text(value):
    text = value.lower()
    for _, label, _, expression in PROTECTED:
        if re.search(expression, text):
            return label
    return ""

def finish(reason=""):
    print(reason)

try:
    event = json.load(sys.stdin)
except Exception:
    finish("allow")
    raise SystemExit

tool = event.get("tool_name") or event.get("tool") or ""
tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
shell_tools = {"Bash", "exec", "unified_exec", "unifiedExec", "LocalShell", "shell"}
read_tools = {"Read", "Glob", "Grep"}
if tool not in shell_tools | read_tools:
    finish("allow")
    raise SystemExit

cwd = tool_input.get("cwd") or event.get("cwd") or os.getcwd()
cwd = os.path.abspath(cwd)

def path_label(value):
    if not isinstance(value, str) or not value:
        return ""
    resolved = os.path.realpath(os.path.join(cwd, value))
    parts = resolved.split(os.sep)
    for part in parts:
        label = label_for_path(part)
        if label:
            return label
    return ""

def directory_needs_exclusions(target):
    resolved = os.path.realpath(os.path.join(cwd, target))
    return os.path.isdir(resolved)

def parse_rg(command):
    # Only plain, single-command invocations are considered for query/path
    # separation. shlex tokenizes; it never evaluates shell syntax.
    if not isinstance(command, str) or not command or "#" in command or any(c in command for c in "\0\n\r$`"):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except Exception:
        return None
    operators = "|&;<>()"
    if not words or words[0] != "rg" or any(w and all(c in operators for c in w) for w in words):
        return None

    expressions = []
    file_operands = []
    targets = []
    globs = []
    positional = []
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
        if word in ("-n", "-i", "-l"):
            i += 1
            continue
        if word == "-C" or (word.startswith("-C") and word != "-C"):
            if word == "-C":
                i += 1
                if i >= len(words) or not words[i].isdigit():
                    return None
            elif not word[2:].isdigit():
                return None
            i += 1
            continue
        if word in ("-e", "--regexp", "-f", "--file", "-g", "--glob"):
            if i + 1 >= len(words):
                return None
            value = words[i + 1]
            if value.startswith("~"):
                return None
            if word in ("-e", "--regexp"):
                expressions.append(value)
            elif word in ("-f", "--file"):
                file_operands.append(value)
            else:
                globs.append(value)
            i += 2
            continue
        if word.startswith("-"):
            return None
        positional.append(word)
        i += 1

    if not expressions and not file_operands:
        if not positional:
            return None
        expressions.append(positional.pop(0))
    targets = positional or ["."]
    # Patterns are deliberately not path operands. -f values are files read.
    path_values = targets + file_operands
    for value in path_values:
        if value.startswith("~"):
            return None
        if any(char in value for char in "*?[]{}"):
            return None
        label = path_label(value)
        if label:
            return ("blocked", label)

    has_directory = any(directory_needs_exclusions(t) for t in targets)
    if has_directory:
        required = {entry[2] for entry in PROTECTED}
        if not required.issubset(set(globs)):
            return ("unparsed", "")
        # Exclusions must remain complete and no include rule may re-open files.
        if any(g.startswith("!") is False and g not in required for g in globs):
            return ("unparsed", "")
    return ("safe", "")

label = ""
reason = ""
if tool in shell_tools:
    for key in ("file_path", "path"):
        label = path_label(tool_input.get(key))
        if label:
            break
    if not label and isinstance(tool_input.get("paths"), list):
        for value in tool_input["paths"]:
            label = path_label(value)
            if label:
                break
    command_fields = [(key, tool_input[key]) for key in ("command", "cmd") if isinstance(tool_input.get(key), str)]
    command_text = None
    recognized_field = None
    if len(command_fields) == 2 and command_fields[0][1] != command_fields[1][1]:
        reason = "unparsed"
    elif command_fields:
        recognized_field, command_text = command_fields[0]
    else:
        rg_fields = [(key, tool_input[key]) for key in ("input", "script")
                     if isinstance(tool_input.get(key), str) and tool_input[key].lstrip().startswith("rg ")]
        if len({value for _, value in rg_fields}) > 1:
            reason = "unparsed"
        elif rg_fields:
            recognized_field, command_text = rg_fields[0]
    if not label:
        parsed = parse_rg(command_text)
        if parsed and parsed[0] == "blocked":
            label = parsed[1]
        elif parsed and parsed[0] == "unparsed":
            reason = "unparsed"
        elif parsed is None:
            label = label_in_text(command_text) if isinstance(command_text, str) else ""
            if isinstance(command_text, str) and command_text.lstrip().startswith("rg "):
                reason = "unparsed"
            elif label and isinstance(command_text, str) and re.search(r"[;&|<>]|\$\(|`", command_text):
                reason = "unparsed"
    if not label:
        for key in ("command", "cmd", "input", "script"):
            if key == recognized_field or (key in ("command", "cmd") and command_fields and
                                             len(command_fields) == 2 and command_fields[0][1] == command_fields[1][1]):
                continue
            value = tool_input.get(key)
            if isinstance(value, str):
                label = label_in_text(value)
                if label:
                    break
else:
    # Grep.pattern is a search expression, not a file to read. Glob.pattern is
    # a target selector and remains subject to the protected-name check.
    keys = ["file_path", "path"]
    paths = tool_input.get("paths")
    if isinstance(paths, list):
        keys.extend([])
        for value in paths:
            label = path_label(value)
            if label:
                break
    if tool == "Glob":
        keys.append("pattern")
    for key in keys:
        if not label:
            label = path_label(tool_input.get(key))
    if not label and tool == "Grep":
        target = tool_input.get("path") or tool_input.get("paths")
        targets = target if isinstance(target, list) else [target] if target else []
        if not targets or any(directory_needs_exclusions(p) for p in targets if isinstance(p, str)):
            reason = "unparsed"

if reason == "unparsed":
    print("unparsed")
elif label:
    print("blocked:" + label)
else:
    print("allow")
')

case "$RESULT" in
  allow) exit 0 ;;
  blocked:*)
    PATTERN="${RESULT#blocked:}"
    case "$USER_LANG" in
      ru) echo "BLOCKED: H17 запрещает чтение защищённого шаблона ${PATTERN}. Значение, полный путь и команда не выводятся." >&2 ;;
      *)  echo "BLOCKED: H17 denies a protected read pattern ${PATTERN}. The value, full path, and command are not printed." >&2 ;;
    esac
    exit 2
    ;;
  unparsed)
    case "$USER_LANG" in
      ru) echo "BLOCKED: H17 не удалось безопасно разобрать команду чтения; защищённые данные не открыты." >&2 ;;
      *)  echo "BLOCKED: H17 could not safely analyze the read command; protected data was not opened." >&2 ;;
    esac
    exit 2
    ;;
  *) exit 0 ;;
esac
