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


def _reply(i=2, body="принято: делать так\nотклонено: делать иначе; причина: дороже"):
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


def _codex_line(kind, payload, ts="2026-09-27T10:00:00Z"):
    return _line({"timestamp": ts, "type": kind, "payload": payload})


def _codex_session(session="cx1", source="cli"):
    return _codex_line("session_meta", {"id": session, "session_id": session,
                                        "cwd": "/tmp/STC", "source": source})


def test_codex_repeated_real_choices_are_not_mirrors(tmp_path):
    rows = [_codex_session()]
    for minute in (1, 2):
        for second, kind, text in (
            (1, "agent_message", "🗳️ A или B?"),
            (2, "user_message", "берём A"),
            (3, "agent_message", "```decision\nпринято: A\nотклонено: B\n```"),
        ):
            rows.append(_codex_line("event_msg", {"type": kind, "message": text},
                                    f"2026-09-27T10:0{minute}:0{second}Z"))
    _write(tmp_path, "repeat.jsonl", rows)
    result = dh.scan(tmp_path, None)
    assert (result["forks"], result["marked"]) == (2, 2)


def _codex_message(role, text, session="cx1", turn="t1", phase=None):
    payload = {"type": "message", "role": role,
               "content": [{"type": "input_text" if role == "user" else "output_text",
                             "text": text}],
               "internal_chat_message_metadata_passthrough": {
                   "turn_id": turn, "content_item_kinds": ["user.text"]}}
    if phase:
        payload["phase"] = phase
    return _codex_line("response_item", payload)


def test_codex_transcript_counts_human_choice_and_ignores_mirrors(tmp_path):
    p = tmp_path / "codex.jsonl"
    _write(p.parent, p.name, [
        _codex_session(),
        _codex_message("assistant", "🗳️ Развилка: A или B?", turn="t0", phase="final_answer"),
        _codex_message("user", "берём A"),
        _codex_line("event_msg", {"type": "item_completed", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "берём A"}]}}),
        _codex_message("assistant", "```decision\nпринято: A\nотклонено: B\n```", turn="t2", phase="final_answer"),
    ])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"]) == (1, 1)
    assert res["records"][0]["harness"] == "codex"
    assert res["records"][0]["cwd"] == "/tmp/STC"


def test_codex_question_keeps_fork_open_until_later_choice(tmp_path):
    p = tmp_path / "codex.jsonl"
    _write(p.parent, p.name, [
        _codex_session(),
        _codex_message("assistant", "🗳️ Развилка: A или B?", turn="t0", phase="final_answer"),
        _codex_message("user", "сколько стоит A?", turn="t1"),
        _codex_message("assistant", "A стоит 5.", turn="t1", phase="final_answer"),
        _codex_message("user", "берём A", turn="t2"),
        _codex_message("assistant", "```decision\nпринято: A\nотклонено: B\n```", turn="t2", phase="final_answer"),
    ])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"], res["questions"]) == (1, 1, 1)


def test_codex_foreign_session_and_subagent_are_silent(tmp_path):
    foreign = tmp_path / "foreign.jsonl"
    _write(foreign.parent, foreign.name, [
        _codex_session("other"), _codex_message("assistant", "🗳️ A или B?", session="other", phase="final_answer"),
        _codex_message("user", "A", session="other"),
    ])
    sub = tmp_path / "sub.jsonl"
    _write(sub.parent, sub.name, [
        _codex_session("sub", source={"kind": "subagent"}),
        _codex_message("assistant", "🗳️ A или B?", session="sub", phase="final_answer"),
        _codex_message("user", "A", session="sub"),
    ])
    # Offline measurement has no caller session id, so it may measure the
    # foreign file; the subagent session itself must still be excluded.
    assert dh.scan(tmp_path, None)["forks"] == 1


def test_mixed_legacy_and_native_codex_history_keeps_prior_decision(tmp_path):
    p = tmp_path / "mixed.jsonl"
    _write(p.parent, p.name, [
        _codex_session(),
        _codex_line("event_msg", {"type": "agent_message", "turn_id": "t0", "message": "🗳️ A или B"}),
        _codex_line("event_msg", {"type": "user_message", "turn_id": "t1", "message": "берём A"}),
        _codex_line("event_msg", {"type": "agent_message", "turn_id": "t1", "message": "```decision\nпринято: A\nотклонено: B\n```"}),
        _codex_message("user", "новая задача", turn="t2"),
        _codex_message("assistant", "Готово.", turn="t2", phase="final_answer"),
    ])
    res = dh.scan(tmp_path, None)
    assert (res["forks"], res["marked"]) == (1, 1)


def test_malformed_codex_shapes_are_ignored(tmp_path):
    p = tmp_path / "bad.jsonl"
    _write(p.parent, p.name, [
        _line({"type": "session_meta", "payload": [1]}),
        _line({"type": "response_item", "payload": {"type": "message", "metadata": [1]}}),
        "null", "[]", "{broken",
    ])
    assert dh.scan(tmp_path, None)["forks"] == 0


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
    body = "принято: A\noтклонено: B; причина: потому что"   # первая «o» латинская
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


def test_marker_mentioned_is_not_a_fork_presented():
    """Разговор о маркере — не предъявленный выбор.

    20.09 хук сработал на фразе «развилка без маркера 🗳️ в знаменатель не
    попадает»: та же порода, что «считал упоминания вместо вызовов». По
    корпусу (264 реплики с маркером) правило отсекает ровно одно упоминание
    и ни одного живого предъявления.
    """
    assert dh.presents_fork("🗳️ Развилка: так или иначе?")
    assert dh.presents_fork("## 🗳️ Что нужно от тебя")          # после заголовка
    assert dh.presents_fork("**Шаг 3.** 🗳️ Развилка А")         # после жирного
    assert not dh.presents_fork("развилка без маркера 🗳️ не считается")
    assert not dh.presents_fork("| **Мой маркер 🗳️** | 56 |")
    # упоминание и предъявление в одной реплике — считается предъявлением
    assert dh.presents_fork("про маркер 🗳️ говорил\n\n🗳️ Развилка: A или B?")


def test_line_anchor_would_have_been_wrong():
    """Якорь на начало строки выбросил бы 87 настоящих развилок из 264.

    Тест стережёт от «упрощения» правила обратно к позиции в строке.
    """
    assert dh.presents_fork("## 🗳️ Развилка")
    assert dh.presents_fork("**Шаг 3.** 🗳️ гнать на круг или нет")


def test_mention_does_not_open_a_fork_in_the_scan(tmp_path):
    mention = _line({"timestamp": TS.format(0), "sessionId": "s1",
                     "message": {"role": "assistant", "content": [
                         {"type": "text", "text": "маркер 🗳️ я объяснял выше"}]}})
    _write(tmp_path, "a.jsonl", [mention, _human(), _plain_reply()])
    assert dh.scan(tmp_path, None)["forks"] == 0



# --- Ревью 25.09: сценарии, на которых журнал записывал то, чего не было ---


def test_a_dash_inside_an_option_name_is_not_a_reason():
    """«Пилот — неделя проверки без оплаты» — название варианта, причина не
    звучала. Причиной считается только явное «причина:»."""
    rec = dh.parse_block("принято: Полный запуск\nотклонено: Пилот — неделя проверки без оплаты")
    assert rec["dropped"] == [{"what": "Пилот — неделя проверки без оплаты", "reason": ""}]


def test_a_question_does_not_resolve_the_fork_and_a_block_after_it_is_phantom(tmp_path):
    """«Сколько будет стоить A?» — не выбор. Запись после такого ответа
    фиксирует решение, которого не было; в долю она не идёт."""
    _write(tmp_path, "a.jsonl",
           [_fork(), _human(text="Сколько будет стоить A?"), _reply()])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 0 and res["marked"] == 0
    assert res["phantom"] == 1 and res["questions"] == 1


def test_a_block_without_any_rejection_is_not_compliance(tmp_path):
    """Одно «принято» без единого отказа накручивало долю соблюдения."""
    _write(tmp_path, "a.jsonl",
           [_fork(), _human(), _reply(body="принято: делать так")])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1 and res["marked"] == 0
    assert res["without_rejection"] == 1


def test_an_unrelated_request_without_a_block_is_not_counted(tmp_path):
    """Новая задача вместо выбора: агент записи не ставит — развилки в доле нет."""
    _write(tmp_path, "a.jsonl",
           [_fork(), _human(text="дай инструкцию по экосбору"), _plain_reply()])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 0 and res["unclear"] == 1


def test_fork_earlier_in_the_same_turn_is_still_open(tmp_path):
    """Выбор → ещё одна моя реплика без значка → человек выбрал. Развилка
    открыта и для счётчика, и для сторожа (open_fork_in_tail) — раньше они
    расходились."""
    lines = [_fork(0), _plain_reply(1, "Подробности выше."), _human(2, text="вариант 1")]
    _write(tmp_path, "a.jsonl", lines + [_reply(3)])
    assert dh.scan(tmp_path, None)["marked"] == 1
    assert dh.open_fork_in_tail(lines[:2]) is True


def test_the_hook_steps_over_the_prompt_already_written_to_the_transcript():
    """Если харнесс записал новое сообщение до сторожа, оно не граница хода."""
    lines = [_fork(0), _human(1, text="вариант 1")]
    assert dh.open_fork_in_tail(lines, current_prompt="вариант 1") is True
    assert dh.open_fork_in_tail(lines, current_prompt="другое") is False


def test_reply_kind_on_real_shapes():
    assert dh.reply_kind("Сколько будет стоить A?") == "question"
    assert dh.reply_kind("А что насчёт второго?") == "question"
    assert dh.reply_kind("1 - это хорошо") == "choice"
    assert dh.reply_kind("делаем вместе с идеей. а как это будет?") == "choice"
    assert dh.reply_kind("сохрани выводы в память") == "unclear"   # «в» — не вариант «В»
    assert dh.reply_kind("эмоджи не мешают") == "unclear"


# ── Повторное ревью 26.09: ответ человека на живых данных ─────────────────

_REVIEW_PASTE = ("посмотри ревью: \"🔎 Вердикт: нужны правки. " + "Проверил всё по списку. " * 30
                 + "\nВ [tables.py:935] неизвестная версия принимается за совпадение. "
                 + "Автор говорит «да», но тест этого не ловит.\"")


def test_reply_kind_reads_only_the_persons_own_words():
    """Вставленное ревью и цитаты — не слова человека. Раньше «да» и строка
    «В [tables.py…]» глубоко во вставке делали из просьбы «посмотри ревью» выбор."""
    assert dh.reply_kind(_REVIEW_PASTE) == "unclear"
    assert dh.reply_kind('<pasted_content id="1">\nда, берём\n</pasted_content>') == "unclear"
    assert dh.reply_kind("🔎 **Три находки закрыты.** " + "Подробности. " * 60) == "unclear"
    # Ответ через цитату: процитирована строка развилки с «?», ответ — ниже.
    assert dh.reply_kind("<!-- reply -->\n> 🗳️ Развилка: A или B?\n\nвторой") == "choice"


def test_reply_kind_explicit_option_beats_a_question_mark():
    """Выбор с попутным вопросом — всё равно выбор («1 - вариант 1 … ?»)."""
    assert dh.reply_kind("1 - вариант 1\n2 - а как это будет?") == "choice"
    assert dh.reply_kind("вариант 2, но сколько это стоит?") == "choice"
    assert dh.reply_kind("сделай Б и потом распиши план реализации") == "choice"
    # Привычка Антона: повторить вариант и дописать «- это». Живой ответ 17.09 —
    # тот самый выбор, с которого начался журнал решений.
    assert dh.reply_kind("я правильно понимаю, что журнал в поиске?\n\n"
                         "Сужаем до отказов - это\n\nЧем ловить — реши сам") == "choice"
    # Заглавная буква в начале фразы — не метка варианта.
    assert dh.reply_kind("В общем, я пока не решил.") == "unclear"
    # Вопрос про вариант — всё ещё вопрос.
    assert dh.reply_kind("А что будет с вариантом 2?") == "question"


def test_reply_kind_recognises_a_choice_by_the_option_name():
    fork = ("🗳️ Как поступаем?\n- **Влить в ветку ВК сейчас (советую).** Меньше слияний.\n"
            "- **Оставить отдельно.** Проще откатить.")
    assert dh.reply_kind("Влить в ветку ВК сейчас", fork) == "choice"
    assert dh.reply_kind("сделай инструкцию по экосбору", fork) == "unclear"


def test_a_fork_stays_open_through_a_clarifying_question(tmp_path):
    """«🗳️ A или B?» → «Сколько стоит A?» → ответ без значка → «берём A».
    Раньше развилка терялась: и счётчик, и сторож смотрели только на ход
    перед последним сообщением."""
    lines = [_fork(0, "🗳️ Развилка: A или B?"), _human(1, text="Сколько будет стоить A?"),
             _plain_reply(2, "A — 5000 ₽, B — 3000 ₽."), _human(3, text="берём A")]
    _write(tmp_path, "a.jsonl", lines + [_reply(4)])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1 and res["marked"] == 1 and res["questions"] == 1
    assert dh.open_fork_in_tail(lines[:3]) is True
    assert dh.open_fork_in_tail(lines, current_prompt="берём A") is True


def test_a_record_after_an_unclear_reply_does_not_raise_the_share(tmp_path):
    """Запись после «продолжай» раньше засчитывалась соблюдением, а неясный
    ответ без записи из доли выпадал — долю можно было только поднять."""
    _write(tmp_path, "a.jsonl", [
        _fork(0), _human(1, text="вариант 1"), _plain_reply(2),
        _fork(3), _human(4, text="продолжай"), _reply(5),
    ])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1 and res["marked"] == 0
    assert res["after_unclear"] == 1


def test_a_reply_typed_while_the_agent_works_is_a_human_reply(tmp_path):
    """Сообщение, набранное во время работы агента, пишется вложением
    queued_command, а не репликой user. Раньше его не видел никто, и запись
    приписывалась чужой развилке."""
    queued = _line({"timestamp": TS.format(1), "sessionId": "s1", "type": "attachment",
                    "attachment": {"type": "queued_command", "prompt": "вариант 1",
                                   "commandMode": "prompt", "origin": {"kind": "human"}}})
    notification = _line({"timestamp": TS.format(1), "sessionId": "s1", "type": "attachment",
                          "attachment": {"type": "queued_command",
                                         "prompt": "<task-notification>готово</task-notification>",
                                         "commandMode": "task-notification"}})
    _write(tmp_path, "a.jsonl", [_fork(0), notification, queued, _reply(2)])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1 and res["marked"] == 1


def test_an_empty_rejection_is_not_a_rejection():
    assert dh.parse_block("принято: делать так\nотклонено: —")["dropped"] == []


# ── Ревью 26.09, вторая волна ──────────────────────────────────────────────

_PAY_FORK = ("🗳️ Как поступим?\n"
             "- **Подключить оплату сейчас (советую)** — покупатели смогут платить сразу.\n"
             "- **Отложить оплату на месяц** — пока принимаем заказы вручную.")


def test_naming_an_option_inside_a_question_is_not_a_choice():
    """«Почему советуешь Подключить оплату сейчас?» закрывал развилку выбором."""
    assert dh.reply_kind("Почему советуешь Подключить оплату сейчас?", _PAY_FORK) == "question"
    assert dh.reply_kind("Не понял. Почему советуешь Подключить оплату сейчас?", _PAY_FORK) \
        == "question"
    assert dh.reply_kind("Влить в ветку ВК?",
                         "🗳️ Как?\n- **Влить в ветку ВК сейчас (советую).**\n- **Оставить.**") \
        == "question"
    assert dh.reply_kind("объясни, чем отличаются варианты") == "unclear"


def test_a_choice_followed_by_a_question_is_a_choice():
    """«Первый. Сколько времени займёт?» — выбор, а вопрос попутный."""
    assert dh.reply_kind("Первый. Сколько времени займёт?") == "choice"
    assert dh.reply_kind("Подключить оплату сейчас. Сколько времени займёт?", _PAY_FORK) \
        == "choice"


def test_a_question_naming_an_option_keeps_the_fork_open(tmp_path):
    _write(tmp_path, "a.jsonl", [
        _fork(0, _PAY_FORK), _human(1, text="Почему советуешь Подключить оплату сейчас?"),
        _plain_reply(2, "Потому что покупатели уже спрашивают."),
        _human(3, text="Тогда вариант 1"), _reply(4)])
    res = dh.scan(tmp_path, None)
    assert res["forks"] == 1 and res["marked"] == 1 and res["questions"] == 1


def test_the_hook_does_not_reopen_a_fork_already_answered_by_name():
    """Выбор названием + попутный вопрос → запись → «Ок». Сторож судил старый
    ответ без карточки, принимал его за вопрос и снова просил записать."""
    lines = [_fork(0, _PAY_FORK),
             _human(1, text="Подключить оплату сейчас. Сколько времени займёт?"),
             _reply(2), _human(3, text="Ок")]
    assert dh.open_fork_in_tail(lines, current_prompt="Ок") is False
    assert dh.open_fork_in_tail(lines[:3], current_prompt="Ок") is False


def test_the_order_of_archive_copies_does_not_change_the_result(tmp_path):
    """Короткая копия (до записи) и полная (с записью): итог не должен
    зависеть от того, какой файл идёт первым по имени."""
    short = [_fork(0), _human(1)]
    full = short + [_reply(2)]
    for first, second in (("a", "b"), ("z", "b")):
        d = tmp_path / first
        d.mkdir()
        _write(d, f"{first}-short.jsonl", short)
        _write(d, f"{second}-full.jsonl", full)
        assert dh.scan(d, None)["marked"] == 1, first


def test_a_short_option_name_said_on_its_own_is_a_choice():
    """Живая проба Codex 28.09: «Паста. А что нужно купить?» на карточке
    «Паста / Суп» сочлась вопросом — название короче восьми букв не узнавалось."""
    fork = "🗳️ **Развилка: ужин?**\n\n- **Паста (советую)** — быстро.\n- **Суп** — легче."
    assert dh.reply_kind("Паста. А что нужно купить?", fork) == "choice"
    assert dh.reply_kind("суп", fork) == "choice"
    assert dh.reply_kind("Паста?", fork) == "question"
    assert dh.reply_kind("Суповой набор есть?", fork) == "question"
