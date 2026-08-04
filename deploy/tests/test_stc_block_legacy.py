"""Regression tests for retiring the known pre-managed STC rules tail."""

import sys
from pathlib import Path


DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

import stc_block as B  # noqa: E402


LEGACY_TAIL = """# Global rules

## Always-контекст старта
<!-- I01 -->
old always context

## Начало сессии
<!-- I02 -->
old audit reminder

## Session end ("завершаем сессию")
<!-- I03 -->
1. Memory rotation: update STATE/CHANGELOG.
2. Kill dev servers and run docker compose down.
"""


def test_strip_known_legacy_global_rules_tail():
    source = f"user-owned preface\n\n{B.STC_BEGIN}\n@import\n{B.STC_END}\n\n{LEGACY_TAIL}"

    cleaned, changed = B.strip_known_legacy_global_rules_tail(source)

    assert changed is True
    assert cleaned == f"user-owned preface\n\n{B.STC_BEGIN}\n@import\n{B.STC_END}\n"


def test_strip_legacy_tail_refuses_partial_or_user_owned_section():
    partial = f"{B.STC_BEGIN}\n@import\n{B.STC_END}\n\n# Global rules\nmy own rules\n"

    cleaned, changed = B.strip_known_legacy_global_rules_tail(partial)

    assert changed is False
    assert cleaned == partial


def test_inject_retires_legacy_tail_but_preserves_user_prefix(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_text(f"keep me\n\n{B.STC_BEGIN}\n@old\n{B.STC_END}\n\n{LEGACY_TAIL}")

    action, changed = B.inject_block(target, "@new", create=True)

    assert (action, changed) == ("replaced", True)
    assert target.read_text() == f"keep me\n\n{B.STC_BEGIN}\n@new\n{B.STC_END}\n"
