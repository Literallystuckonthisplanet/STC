"""Б3а — the critic commands are checked flag by flag, by position.

A command is not "mostly right": one missing flag is one open boundary, and
the isolation guarantee has already been written twice on the strength of flag
names alone and been fiction both times (§5). So every mandatory flag is
asserted where it stands, every forbidden one is asserted absent, and the
material is asserted never to reach argv.

# docs-checked: `claude --help` (2.1.227) and `codex exec --help`
# (codex-cli 0.147.0-alpha.6.5), executed 2026-08-12; every flag asserted below
# appears in that output. No SDK is involved — this is argv assembly.
"""

import importlib.util
import json
from pathlib import Path

ADAPTERS = (
    Path(__file__).resolve().parents[2]
    / "core" / "scripts" / "roundtable" / "adapters.py"
)
SPEC = importlib.util.spec_from_file_location("roundtable_adapters", ADAPTERS)
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)

SCHEMA = {"type": "object", "properties": {"findings": {"type": "array"}}}
MATERIAL = "СЕКРЕТНЫЙ ПАКЕТ МАТЕРИАЛОВ, который не должен попасть в argv"


def _claude():
    return A.build_claude_command(
        claude_bin="/opt/claude", model="opus", effort="high", schema=SCHEMA)


def _codex(tmp_path=Path("/tmp/rt")):
    return A.build_codex_command(
        codex_bin="/opt/codex",
        model="gpt-5.6-luna",
        effort="max",
        schema_path=tmp_path / "schema.json",
        answer_path=tmp_path / "answer.json",
        cd=tmp_path / "work",
    )


def _raises(exc, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except exc:
        return True
    raise AssertionError(f"expected {exc.__name__}")


# --------------------------------------------------------------------------
# Claude: four boundaries plus the answer envelope
# --------------------------------------------------------------------------

def test_claude_command_carries_all_four_boundaries():
    command = _claude()
    assert command[0] == "/opt/claude"
    assert "-p" in command, "headless mode is what makes stdin the input"
    for flag in ("--safe-mode", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in command, flag
    assert command[command.index("--tools") + 1] == "", 'built-in tools are disabled by ""'


def test_claude_command_pins_model_effort_and_answer_shape():
    command = _claude()
    assert command[command.index("--model") + 1] == "opus"
    assert command[command.index("--effort") + 1] == "high"
    assert command[command.index("--output-format") + 1] == "json"
    assert json.loads(command[command.index("--json-schema") + 1]) == SCHEMA


def test_claude_refuses_an_unknown_effort_and_an_empty_schema():
    _raises(A.CommandRefused, A.build_claude_command, "/opt/claude", "opus", "ultra", SCHEMA)
    _raises(A.CommandRefused, A.build_claude_command, "/opt/claude", "opus", "high", {})
    _raises(A.CommandRefused, A.build_claude_command, "/opt/claude", "", "high", SCHEMA)


# --------------------------------------------------------------------------
# Codex: three axes of the boundary plus the structured answer
# --------------------------------------------------------------------------

def test_codex_command_is_ephemeral_config_free_and_read_only():
    command = _codex()
    assert command[:2] == ["/opt/codex", "exec"]
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules"):
        assert flag in command, flag
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in command, "the working directory is not a repo"


def test_codex_has_no_execution_tool_at_all():
    # Ш1 measured that `--sandbox read-only` is not a read boundary: under that
    # very policy `codex sandbox -- /bin/cat <absolute path>` reads the file with
    # zero denials. Taking the execution tools away is what closes the axis.
    command = _codex()
    disabled = {command[i + 1] for i, arg in enumerate(command) if arg == "--disable"}
    assert {"shell_tool", "unified_exec"} <= disabled
    assert "--enable" not in command, "features are only ever narrowed here"


def test_codex_command_pins_model_effort_and_answer_paths():
    command = _codex(Path("/tmp/probe"))
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="max"' in command
    assert command[command.index("--cd") + 1] == "/tmp/probe/work"
    assert command[command.index("--output-schema") + 1] == "/tmp/probe/schema.json"
    assert command[command.index("--output-last-message") + 1] == "/tmp/probe/answer.json"


def test_codex_reads_instructions_from_stdin_not_from_a_positional_prompt():
    # `codex exec --help`: "If not provided as an argument (or if `-` is used),
    # instructions are read from stdin."
    command = _codex()
    assert command[-1] == "-"
    assert command.count("-") == 1, "only the stdin marker may be a bare dash"


# --------------------------------------------------------------------------
# the forbidden set — one negative assertion per flag, both vendors
# --------------------------------------------------------------------------

def test_no_command_carries_a_boundary_breaking_flag():
    forbidden = (
        "--enable",
        "--dangerously-bypass-hook-trust",
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--approve-for-me",
    )
    assert set(forbidden) <= set(A.FORBIDDEN_ARGUMENTS)
    for command in (_claude(), _codex()):
        for flag in forbidden:
            assert flag not in command, flag


def test_the_first_two_forbidden_flags_are_exactly_what_the_canary_uses():
    # codex_live_canary.py passes --enable hooks and --dangerously-bypass-hook-trust
    # deliberately: it is checking that STC's context loads. Copying its command
    # wholesale is how a critic would silently get hooks, so the canary is a
    # model for the *shape* of the builder and never a source for its flags.
    canary = (
        Path(__file__).resolve().parents[2] / "core" / "scripts" / "codex_live_canary.py"
    ).read_text(encoding="utf-8")
    assert "--dangerously-bypass-hook-trust" in canary
    assert "--dangerously-bypass-hook-trust" in A.FORBIDDEN_ARGUMENTS


def test_the_builder_itself_refuses_a_forbidden_argument():
    # The guard lives in the module, not only in this file: a future edit that
    # adds a flag cannot produce a command, it raises.
    _raises(A.CommandRefused, A._guard, ["/opt/claude", "--dangerously-skip-permissions"])


# --------------------------------------------------------------------------
# the material never reaches argv (§5.2, §6.9)
# --------------------------------------------------------------------------

def test_no_piece_of_the_material_can_appear_in_argv():
    for command in (_claude(), _codex()):
        for argument in command:
            assert MATERIAL not in argument
            assert "секрет" not in argument.lower()
    # Structural, not incidental: neither builder takes the material at all.
    for builder in (A.build_claude_command, A.build_codex_command):
        assert "material" not in builder.__code__.co_varnames
        assert "prompt" not in builder.__code__.co_varnames


def test_claude_has_no_positional_prompt_after_print():
    command = _claude()
    assert command[command.index("-p") + 1].startswith("--"), "a prompt would sit here"


# --------------------------------------------------------------------------
# environment: a whitelist, and the gateway variables stripped by name
# --------------------------------------------------------------------------

def test_environment_is_a_whitelist_and_not_a_copy_of_the_parent():
    source = {
        "PATH": "/usr/bin", "TERM": "xterm", "HOME": "/Users/xtoshin",
        "SSH_AUTH_SOCK": "/private/tmp/agent", "CLOUD_SECRET_ACCESS_KEY": "leak",
        "VENDOR_TOKEN": "leak",
    }
    environment = A.build_environment("claude", home="/tmp/clean-home", source=source)
    assert environment == {"PATH": "/usr/bin", "TERM": "xterm", "HOME": "/tmp/clean-home"}


def test_the_whitelist_carries_the_one_variable_the_keychain_needs():
    # Ш1 bisected it: without USER, Claude answers "Not logged in · Please run
    # /login". LOGNAME and __CF_USER_TEXT_ENCODING do not stand in for it.
    assert "USER" in A.ENVIRONMENT_WHITELIST
    environment = A.build_environment("claude", home="/tmp/h",
                                      source={"PATH": "/usr/bin", "USER": "xtoshin"})
    assert environment["USER"] == "xtoshin"


def test_the_gateway_and_credential_variables_are_stripped_by_name():
    # Without this a critic call can be pointed at a third-party gateway, and
    # the run would look completely normal.
    source = {
        "PATH": "/usr/bin",
        "ANTHROPIC_BASE_URL": "https://gateway.example",
        "ANTHROPIC_AUTH_TOKEN": "t",
        "ANTHROPIC_API_KEY": "k",
    }
    for vendor, extra in (("claude", {}), ("codex", {"codex_home": "/tmp/ch"})):
        environment = A.build_environment(vendor, home="/tmp/h", source=source, **extra)
        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            assert name not in environment, name
    assert set(A.STRIPPED_VARIABLES) == {
        "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    }


def test_home_is_always_the_throwaway_one_even_if_the_parent_has_its_own():
    source = {"HOME": "/Users/xtoshin", "PATH": "/usr/bin"}
    environment = A.build_environment("codex", home="/tmp/clean", codex_home="/tmp/ch",
                                      source=source)
    assert environment["HOME"] == "/tmp/clean"
    assert environment["CODEX_HOME"] == "/tmp/ch"


def test_codex_without_its_own_codex_home_is_refused():
    # `codex exec --help`: auth still uses CODEX_HOME. Silently reusing the real
    # one would re-open axis three.
    _raises(A.CommandRefused, A.build_environment, "codex", "/tmp/clean")
    _raises(A.CommandRefused, A.build_environment, "claude", "/tmp/clean", "/tmp/ch")
    _raises(A.CommandRefused, A.build_environment, "gemini", "/tmp/clean")
