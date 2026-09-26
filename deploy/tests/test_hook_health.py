"""Страж для пересчёта срабатываний хуков по транскриптам.

Главное, что здесь стережётся, — различение слепого и осознанного повтора.
Первая версия скрипта их смешивала и записала соблюдение правила
(buy-vs-build: агент прочитал напоминание, ответил на него и повторил вызов)
в стопроцентный игнор. Метрика, которая называет соблюдение нарушением,
хуже отсутствия метрики: по ней снимают живые правила.
"""

import json
import sys
import pytest
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
    # Код — из реестра: из текста сообщения его брать нельзя, там мелькают чужие.
    res = hook_health.health(tmp_path, None, {"graphify-first": "H18"})
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["blind"][key] == 1
    assert res["aware"].get(key, 0) == 0


def test_repeat_after_saying_something_counts_as_aware(tmp_path):
    _write(tmp_path, "aware.jsonl",
           [_call("rg foo"), _block(), _said("нужен точный поиск строки"), _call("rg foo")])
    # Код — из реестра: из текста сообщения его брать нельзя, там мелькают чужие.
    res = hook_health.health(tmp_path, None, {"graphify-first": "H18"})
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["aware"][key] == 1
    assert res["blind"].get(key, 0) == 0


def test_a_different_next_call_is_neither_blind_nor_aware(tmp_path):
    """Агент послушался и сделал другое — это не повтор вообще."""
    _write(tmp_path, "obeyed.jsonl",
           [_call("rg foo"), _block(), _call("graphify query 'кто вызывает foo'")])
    # Код — из реестра: из текста сообщения его брать нельзя, там мелькают чужие.
    res = hook_health.health(tmp_path, None, {"graphify-first": "H18"})
    key = "graphify-first (H18)"
    assert res["fired"][key] == 1
    assert res["blind"].get(key, 0) == 0
    assert res["aware"].get(key, 0) == 0


def test_quiet_hooks_are_never_called_dead(tmp_path):
    """Тихий хук не оставляет следа и в норме — молчание не улика."""
    blocking, quiet, _codes = hook_health.declared_hooks(REPO)
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


def _stop_feedback(hook="link-integrity-guard", ts="2026-08-01T10:00:02Z"):
    """Возражение на конце ответа: обычная реплика, без слова «error»."""
    msg = (f"Stop hook feedback:\n[/Users/x/.claude/hooks/{hook}.stc.sh]: "
           "Broken [[wiki-links]] in the loaded memory")
    return _line({"timestamp": ts, "message": {"role": "user", "content": msg}})


def test_stop_hook_feedback_counts_as_a_firing(tmp_path):
    """Живой H08 числился мёртвым: фильтр искал слово «error», а его тут нет.

    Измеритель, построенный как лекарство от недостоверности, врал ровно тем
    способом, от которого лечит: 37 срабатываний в 37 сессиях он показывал
    нулём и предлагал снять работающее правило.
    """
    _write(tmp_path, "stop.jsonl", [_stop_feedback()])
    res = hook_health.health(tmp_path, None, {"link-integrity-guard": "H08"})
    assert res["fired"]["link-integrity-guard (H08)"] == 1


def test_code_comes_from_the_registry_not_from_the_message(tmp_path):
    """Сообщение хука упоминает чужие коды — по ним считать нельзя.

    По ним один block-dangerous-git разъезжался на три строки: 116, 5 и 2.
    """
    msg = ("PreToolUse:Bash hook error: [/Users/x/.claude/hooks/"
           "block-dangerous-git.stc.sh]: сгребающая команда; коммить путями (см. H19, H18)")
    _write(tmp_path, "codes.jsonl",
           [_line({"timestamp": "2026-08-01T10:00:00Z",
                   "message": {"role": "user",
                               "content": [{"type": "tool_result", "content": msg}]}})])
    res = hook_health.health(tmp_path, None, {"block-dangerous-git": "H01"})
    assert list(res["fired"]) == ["block-dangerous-git (H01)"]


def test_prompt_injection_counts_as_advice(tmp_path):
    _write(tmp_path, "inject.jsonl",
           [_line({"timestamp": "2026-08-01T10:00:00Z",
                   "message": {"role": "user",
                               "content": "UserPromptSubmit hook success: SELF-EXEC: …"}})])
    res = hook_health.health(tmp_path, None)
    assert res["advice"]["UserPromptSubmit"] == 1


@pytest.mark.skipif(not (Path.home() / "Work" / "transcripts" / "raw").is_dir(),
                    reason="нет корпуса транскриптов")
def test_canary_no_live_hook_is_reported_dead():
    """Страж от рецидива: живой хук в «мёртвых» — повод снять работающее правило."""
    raw = Path.home() / "Work" / "transcripts" / "raw"
    blocking, _quiet, codes = hook_health.declared_hooks(REPO)
    res = hook_health.health(raw, None, codes)
    seen = {k.split(" (")[0] for k in res["fired"]}
    dead = sorted(d for d in blocking if d.split(" (")[0] not in seen)
    assert dead == [], f"в мёртвых числятся: {dead}"


def test_empty_registry_is_reported_as_unknown_not_as_all_alive(tmp_path, capsys):
    """Нет реестра — значит «не знаю», а не «мёртвых нет».

    Развёрнутая копия лежит в ~/.stc, куда adapters/ не копируется. Пока код
    брался из текста сообщения, это не было видно; после перехода на реестр
    боевой счётчик печатал благополучное «нет», не имея списка для сравнения.
    Измеритель, чьё молчание выглядит как здоровье, — ровно тот дефект,
    который этот скрипт и чинит.
    """
    import os
    from unittest import mock
    fake = tmp_path / "no-adapters"
    (fake / "core" / "hooks").mkdir(parents=True)
    with mock.patch.dict(os.environ, {"STC_SOURCE": str(fake), "HOME": str(fake)}):
        blocking, quiet, codes = hook_health.declared_hooks(fake)
    assert blocking == set() and codes == {}


def test_registry_is_found_via_stc_source(tmp_path):
    """Развёрнутая копия находит реестр по указателю на исходники."""
    import os
    from unittest import mock
    with mock.patch.dict(os.environ, {"STC_SOURCE": str(REPO)}):
        blocking, _quiet, codes = hook_health.declared_hooks(tmp_path / "nowhere")
    assert codes.get("link-integrity-guard") == "H08"
    assert any(h.startswith("link-integrity-guard") for h in blocking)


def test_the_same_event_in_two_archive_copies_counts_once(tmp_path):
    """Ревью 25.09: оригинал и копия разговора давали два срабатывания."""
    def rec(line, uid):
        obj = json.loads(line)
        obj["uuid"] = uid
        return json.dumps(obj, ensure_ascii=False)
    lines = [rec(_call("ls"), "u1"), rec(_block(), "u2"), rec(_call("ls"), "u3")]
    _write(tmp_path, "original.jsonl", lines)
    _write(tmp_path, "copy.jsonl", lines)
    res = hook_health.health(tmp_path, None, {"graphify-first": "H18"})
    assert res["fired"] == {"graphify-first (H18)": 1}


def test_json_output_says_unverified_when_the_registry_is_missing(tmp_path):
    """Машинный вывод без реестра отдавал dead=[] и код 0 — то есть «всё живо»."""
    import shutil
    import subprocess
    deployed = tmp_path / "stc" / "core" / "scripts"
    deployed.mkdir(parents=True)
    shutil.copy(REPO / "core" / "scripts" / "hook_health.py", deployed)
    raw = tmp_path / "raw"
    raw.mkdir()
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    res = subprocess.run(["python3", str(deployed / "hook_health.py"), "--raw", str(raw), "--json"],
                         capture_output=True, text=True, env=env)
    out = json.loads(res.stdout)
    assert res.returncode == 3
    assert out["dead"] is None and "реестр" in out["unverified"]


def test_text_output_without_registry_says_unknown_and_exits_3(tmp_path):
    """Ревью 26.09: без реестра текстовый вывод всё ещё печатал «невидимы: нет» —
    та же «пустая правда», что уже была убрана из машинного вывода."""
    import shutil
    import subprocess
    deployed = tmp_path / "stc" / "core" / "scripts"
    deployed.mkdir(parents=True)
    shutil.copy(REPO / "core" / "scripts" / "hook_health.py", deployed)
    raw = tmp_path / "raw"
    raw.mkdir()
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    res = subprocess.run(["python3", str(deployed / "hook_health.py"), "--raw", str(raw)],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 3
    invisible = res.stdout.split("невидимы", 1)[1].splitlines()[1]
    assert "нет" != invisible.strip() and "не проверено" in invisible


def test_copies_without_uuid_are_matched_by_session_and_time(tmp_path):
    """Запасной ключ «сессия+время» — для записей без uuid (старые выгрузки)."""
    def rec(line):
        obj = json.loads(line)
        obj["sessionId"] = "s1"
        return json.dumps(obj, ensure_ascii=False)
    lines = [rec(_call("ls")), rec(_block()), rec(_call("ls"))]
    _write(tmp_path, "original.jsonl", lines)
    _write(tmp_path, "copy.jsonl", lines)
    res = hook_health.health(tmp_path, None, {"graphify-first": "H18"})
    assert res["fired"] == {"graphify-first (H18)": 1}
