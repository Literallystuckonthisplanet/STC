"""Страж для счётчика развилок без записанного отказа.

Стережётся здесь ровно то, на чём метрика ломалась при разработке:

* **знаменатель.** Первая версия опознавала развилку по форме ответа
  пользователя и намерила 190 штук, где почти всё — мои же нумерованные
  промпты субагентам и вставки файлов с номерами строк. Метрика, у которой
  знаменатель наполовину мусор, хуже отсутствия метрики;
* **дедуп.** Одна сессия лежит в нескольких файлах (resume/fork), и без
  дедупа та же развилка считалась трижды: 213 против 56 настоящих;
* **ноль как ответ.** Самодельный разбор транскриптов однажды вернул ноль на
  27 353 сообщениях, и ноль выглядел как «правило соблюдается». Поэтому здесь
  есть канарейка на живом корпусе: она валится, если разбор перестал видеть
  реальные развилки.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import decision_health as dh  # noqa: E402

TS = "2026-09-17T10:00:0{}Z"


def _line(payload):
    return json.dumps(payload, ensure_ascii=False)


def _fork(i=0, text="🗳️ Развилка: делать так или иначе?"):
    return _line({"timestamp": TS.format(i), "sessionId": "s1",
                  "message": {"role": "assistant",
                              "content": [{"type": "text", "text": text}]}})


def _human(i=1, text="вариант 1", session="s1"):
    return _line({"timestamp": TS.format(i), "sessionId": session,
                  "cwd": "/Users/x/Work/STC", "origin": {"kind": "human"},
                  "message": {"role": "user", "content": text}})


def _agent_prompt(i=1, text="Read-only exploration. Sources: 1. a 2. b"):
    """Промпт субагенту: роль тоже user, но origin не человек."""
    return _line({"timestamp": TS.format(i), "sessionId": "s1",
                  "message": {"role": "user", "content": text}})


def _reply(i=2, body="принято: делать так\nотклонено: делать иначе — дороже"):
    text = f"Записал.\n\n```decision\n{body}\n```\n"
    return _line({"timestamp": TS.format(i), "sessionId": "s1",
                  "message": {"role": "assistant",
                              "content": [{"type": "text", "text": text}]}})


def _plain_reply(i=2, text="Сделал, вот результат."):
    return _line({"timestamp": TS.format(i), "sessionId": "s1",
                  "message": {"role": "assistant",
                              "content": [{"type": "text", "text": text}]}})


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_marked_fork_counts_as_compliance(tmp_path):
    _write(tmp_path, "a.jsonl", [_fork(), _human(), _reply()])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1
    assert res["marked"] == 1
    assert res["records"][0]["kept"] == ["делать так"]
    assert res["records"][0]["dropped"] == [
        {"what": "делать иначе", "reason": "дороже"}]


def test_unmarked_fork_counts_against(tmp_path):
    _write(tmp_path, "a.jsonl", [_fork(), _human(), _plain_reply()])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1
    assert res["marked"] == 0
    assert dh.summarize(res)["marked_share"] == 0.0


def test_subagent_prompt_does_not_resolve_a_fork(tmp_path):
    """Промпт субагенту с нумерованным списком — не ответ человека.

    Ровно этот случай раздувал знаменатель вдвое: у промпта роль user.
    """
    _write(tmp_path, "a.jsonl", [_fork(), _agent_prompt(), _plain_reply()])
    assert dh.scan(tmp_path, None)["forks"] == 0


def test_fork_without_marker_is_not_counted(tmp_path):
    """Без моего маркера развилки нет — известная дыра, зафиксирована как есть."""
    _write(tmp_path, "a.jsonl",
           [_fork(text="Предлагаю два варианта: 1 так, 2 иначе"),
            _human(), _plain_reply()])
    assert dh.scan(tmp_path, None)["forks"] == 0


def test_same_session_in_two_files_counted_once(tmp_path):
    lines = [_fork(), _human(), _plain_reply()]
    _write(tmp_path, "a.jsonl", lines)
    _write(tmp_path, "b-copy.jsonl", lines)
    assert dh.scan(tmp_path, None)["forks"] == 1


def test_two_forks_in_one_session_both_counted(tmp_path):
    _write(tmp_path, "a.jsonl", [
        _fork(0), _human(1), _reply(2),
        _fork(3), _human(4), _plain_reply(5),
    ])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"]) == (2, 1)


def test_rejection_without_reason_is_recorded_not_invented(tmp_path):
    _write(tmp_path, "a.jsonl",
           [_fork(), _human(), _reply(body="принято: A\nотклонено: B")])
    res = dh.scan(tmp_path, None)
    assert res["records"][0]["dropped"] == [{"what": "B", "reason": ""}]
    assert dh.summarize(res)["no_reason_share"] == 1.0


def test_latin_lookalike_in_key_still_parses():
    """«отклонено» с латинскими о/е — артефакт раскладки, не другое слово."""
    body = "принято: A\noтклонено: B — потому что"   # первая «o» латинская
    assert "o" in body                               # страховка от правки вслепую
    rec = dh.parse_block(body)
    assert rec["dropped"] and rec["dropped"][0]["what"] == "B"


def test_block_in_a_later_reply_still_counts(tmp_path):
    """Разметка может лечь после долгой работы инструментами, не сразу."""
    _write(tmp_path, "a.jsonl",
           [_fork(), _human(), _plain_reply(2), _plain_reply(3), _reply(4)])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"]) == (1, 1)


def test_window_filter_excludes_older(tmp_path):
    from datetime import datetime, timezone
    _write(tmp_path, "old.jsonl", [
        _line({"timestamp": "2026-01-01T10:00:00Z", "sessionId": "s1",
               "message": {"role": "assistant",
                           "content": [{"type": "text", "text": "🗳️ выбор?"}]}}),
        _line({"timestamp": "2026-01-01T10:00:01Z", "sessionId": "s1",
               "origin": {"kind": "human"},
               "message": {"role": "user", "content": "первый"}}),
        _plain_reply(),
    ])
    since = datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert dh.scan(tmp_path, since)["forks"] == 0
    assert dh.scan(tmp_path, None)["forks"] == 1


@pytest.mark.skipif(not dh.RAW_DEFAULT.is_dir(), reason="нет корпуса транскриптов")
def test_canary_real_corpus_still_yields_forks():
    """Ноль на живом корпусе — это не «правило соблюдается», а сломанный разбор.

    База на 17.09: 56 развилок за 76 дней. Порог занижен намеренно — тест
    стережёт «разбор ослеп», а не конкретную цифру.
    """
    res = dh.scan(dh.RAW_DEFAULT, None)
    assert res["forks"] >= 20, f"развилок найдено {res['forks']} — разбор ослеп?"


def test_placeholder_example_is_not_a_record(tmp_path):
    """Блок-пример из объяснения формата — не решение.

    Иначе правило накручивается: объяснил формат — получил соблюдение.
    """
    body = "принято: <what we do>\nотклонено: <what we do not> — <reason>"
    assert dh.parse_block(body) == {"kept": [], "dropped": []}
    _write(tmp_path, "a.jsonl", [_fork(), _human(), _reply(body=body)])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"]) == (1, 0)
