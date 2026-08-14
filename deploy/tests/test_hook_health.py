"""Страж для пересчёта срабатываний хуков по транскриптам.

Главное, что здесь стережётся, — различение слепого и осознанного повтора.
Первая версия скрипта их смешивала и записала соблюдение правила
(buy-vs-build: агент прочитал напоминание, ответил на него и повторил вызов)
в стопроцентный игнор. Метрика, которая называет соблюдение нарушением,
хуже отсутствия метрики: по ней снимают живые правила.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import hook_health  # noqa: E402


def _line(payload):
    return json.dumps(payload, ensure_ascii=False)


def _call(sig, ts="2026-08-01T10:00:00Z"):
    return _line({
        "timestamp": ts,
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": sig}}]},
    })


def _said(text="подумал", ts="2026-08-01T10:00:01Z"):
    return _line({
        "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    })


def _block(hook="graphify-first", code="H18", ts="2026-08-01T10:00:02Z"):
    msg = f"PreToolUse:Bash hook error: [/Users/x/.claude/hooks/{hook}.stc.sh]: 🔎 ({code}): нельзя"
    return _line({
        "timestamp": ts,
        "message": {"role": "user", "content": [
            {"type": "tool_result", "content": msg}]},
    })


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_silent_repeat_counts_as_blind(tmp_path):
    _write(tmp_path, "blind.jsonl", [_call("rg foo"), _block(), _call("rg foo")])
    res = hook_health.health(tmp_path, None)
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["blind"][key] == 1
    assert res["aware"].get(key, 0) == 0


def test_repeat_after_saying_something_counts_as_aware(tmp_path):
    _write(tmp_path, "aware.jsonl",
           [_call("rg foo"), _block(), _said("нужен точный поиск строки"), _call("rg foo")])
    res = hook_health.health(tmp_path, None)
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["aware"][key] == 1
    assert res["blind"].get(key, 0) == 0


def test_a_different_next_call_is_neither_blind_nor_aware(tmp_path):
    """Агент послушался и сделал другое — это не повтор вообще."""
    _write(tmp_path, "obeyed.jsonl",
           [_call("rg foo"), _block(), _call("graphify query 'кто вызывает foo'")])
    res = hook_health.health(tmp_path, None)
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["blind"].get(key, 0) == 0
    assert res["aware"].get(key, 0) == 0


def test_quiet_hooks_are_never_called_dead(tmp_path):
    """Тихий хук не оставляет следа и в норме — молчание не улика."""
    blocking, quiet = hook_health.declared_hooks(REPO)
    assert "session-start-context (H06)" in quiet
    assert "prompt-safety-reminder (H03)" in quiet
    # а стерегущие блокировкой — в другой корзине
    assert any(h.startswith("graphify-first") for h in blocking)
    assert not (blocking & quiet)


def test_window_filter_excludes_older_events(tmp_path):
    from datetime import datetime, timezone
    _write(tmp_path, "old.jsonl", [
        _call("rg foo", ts="2026-01-01T10:00:00Z"),
        _block(ts="2026-01-01T10:00:02Z"),
    ])
    since = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert hook_health.health(tmp_path, since)["fired"] == {}
    assert hook_health.health(tmp_path, None)["fired"] != {}
