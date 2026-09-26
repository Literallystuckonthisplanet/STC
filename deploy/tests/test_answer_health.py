"""Замер понятности ответов считает дефект, а не упоминание о нём."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "scripts"))

import answer_health as AH  # noqa: E402


def _write(raw: Path, records: list[dict]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "session.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8",
    )


def _assistant(text: str, stamp: str = "2026-09-23T10:00:00Z", uuid: str | None = None) -> dict:
    return {"type": "assistant", "timestamp": stamp, "uuid": uuid,
            "message": {"content": [{"type": "text", "text": text}]}}


def _anton(text: str, stamp: str = "2026-09-23T10:01:00Z") -> dict:
    return {"type": "user", "timestamp": stamp, "origin": {"kind": "human"},
            "message": {"content": text}}


FORKS = ROOT / "deploy" / "tests" / "fixtures" / "answer_forks"


def test_labelled_forks_are_classified_as_labelled():
    """Эталонный набор: имя файла — ожидаемый вердикт.

    Два «clear_*» взяты из живых ответов Claude и Codex, которые ревью 24.09
    назвало полноценными, а прежняя версия счётчика — слепыми.
    """
    cases = sorted(FORKS.glob("*.md"))
    assert len(cases) >= 10
    for case in cases:
        text = case.read_text(encoding="utf-8")
        if case.name.startswith("notfork_"):
            assert not AH.fork_blocks(text), f"{case.name}: упоминание значка засчитано развилкой"
            continue
        blind = AH.is_blind_fork(text)
        if case.name.startswith("blind_"):
            assert blind, f"{case.name}: слепая развилка засчитана как понятная"
        else:
            assert not blind, f"{case.name}: понятная развилка засчитана как слепая"
        if case.name.startswith("noadvice_"):
            assert AH.lacks_advice(text), f"{case.name}: не замечено отсутствие совета"
        if case.name.startswith("clear_"):
            assert not AH.lacks_advice(text), f"{case.name}: совет есть, но не распознан"


def test_fork_with_options_is_not_blind_and_backref_is():
    assert AH.is_blind_fork("🗳️ Как идём?\n1. (советую) так\n2. иначе") is False
    assert AH.is_blind_fork("🗳️ Прежняя развилка всё ещё за тобой:\n1. так\n2. иначе") is True
    assert AH.is_blind_fork("🗳️ Решай сам, что делаем дальше.") is True


def test_numbered_list_outside_the_fork_does_not_count(tmp_path):
    text = "Нашёл три штуки:\n1. одна\n2. вторая\n3. третья\n\n🗳️ Что дальше — реши сам."
    assert AH.is_blind_fork(text) is True


def test_scan_counts_shares_by_month(tmp_path):
    raw = tmp_path / "claude"
    _write(raw, [
        _assistant("🗳️ Как идём?\n1. (советую) так\n2. иначе"),
        _assistant("Готово, этап Ш2 закрыт по правилу FR-26."),
        _anton("не понял, что от меня надо"),
        _anton("ок, делай"),
    ])

    months = AH.scan(raw, since=None, strict=False)
    row = months["2026-09"]

    assert row["answers"] == 2
    assert row["forks"] == 1 and row["blind_forks"] == 0
    assert row["with_code"] == 1          # Ш2 и FR-26 в одном ответе — один ответ
    assert row["anton_msgs"] == 2 and row["confused"] == 1



def test_until_cuts_the_period_but_not_the_freshness_line(tmp_path):
    """База «до» и замер «после» считаются одним счётчиком по одному архиву.

    Ревью 26.09: база в задаче на 08.10 была посчитана прошлой версией
    счётчика по прошлому срезу архива, и сравнение было бы нечестным.
    Строка свежести по-прежнему смотрит на весь архив.
    """
    raw = tmp_path / "claude"
    _write(raw, [
        _assistant("до внедрения", stamp="2026-09-24T23:59:00Z", uuid="a"),
        _assistant("в день внедрения", stamp="2026-09-25T00:01:00Z", uuid="b"),
    ])
    months = AH.scan(raw, since=None, strict=False, until="2026-09-25")
    assert months["2026-09"]["answers"] == 1
    assert months["_newest"]["claude"].startswith("2026-09-25")

def test_section_after_the_fork_is_not_its_options(tmp_path):
    """«Нужно решение» + раздел «Сделано» с нумерацией — развилка всё равно слепая."""
    text = "🗳️ Нужно твоё решение.\n\n## ✅ Сделано\n1. первое\n2. второе"
    assert AH.is_blind_fork(text) is True


def test_letter_options_count_as_options():
    assert AH.is_blind_fork("🗳️ Порядок работы?\n- **A — сначала проверка.** Рекомендую.\n"
                            "- **B — сразу блоки.**") is False


def test_same_message_in_several_files_counts_once(tmp_path):
    raw = tmp_path / "claude"
    raw.mkdir(parents=True)
    record = _assistant("ответ" * 500, uuid="u-1")
    for name in ("copy-a.jsonl", "copy-b.jsonl", "copy-c.jsonl"):
        (raw / name).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    row = AH.scan(raw, since=None, strict=False)["2026-09"]

    assert row["answers"] == 1 and row["long"] == 1


def test_compact_summary_is_not_anton(tmp_path):
    raw = tmp_path / "claude"
    _write(raw, [{"type": "user", "timestamp": "2026-09-23T10:00:00Z",
                  "isCompactSummary": True,
                  "message": {"content": "пересказ, где он писал «не понял»"}}])

    assert AH.scan(raw, since=None, strict=False).get("2026-09", {}).get("anton_msgs", 0) == 0


def test_codex_transcripts_are_counted(tmp_path):
    raw = tmp_path / "codex"
    raw.mkdir(parents=True)
    records = [
        {"timestamp": "2026-09-23T10:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "m1", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Готово по правилу FR-26."}]}},
        {"timestamp": "2026-09-23T10:01:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "m2", "role": "user",
                     "content": [{"type": "input_text", "text": "не понял"}]}},
        {"timestamp": "2026-09-23T10:02:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "m3", "role": "user",
                     "content": [{"type": "input_text", "text": "<recommended_context>шум"}]}},
    ]
    (raw / "s.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")

    row = AH.scan(raw, since=None, strict=False, harness="codex")["2026-09"]

    assert row["answers"] == 1 and row["with_code"] == 1
    assert row["anton_msgs"] == 1 and row["confused"] == 1


def test_service_inserts_are_not_anton(tmp_path):
    raw = tmp_path / "claude"
    _write(raw, [
        {"type": "user", "timestamp": "2026-09-23T10:00:00Z",
         "message": {"content": "<task-notification>не понял</task-notification>"}},
        {"type": "user", "timestamp": "2026-09-23T10:00:00Z", "isSidechain": True,
         "message": {"content": "не понял"}},
    ])

    assert AH.scan(raw, since=None, strict=False).get("2026-09", {}).get("anton_msgs", 0) == 0
