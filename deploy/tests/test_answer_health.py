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


def _assistant(text: str, stamp: str = "2026-09-23T10:00:00Z") -> dict:
    return {"type": "assistant", "timestamp": stamp,
            "message": {"content": [{"type": "text", "text": text}]}}


def _anton(text: str, stamp: str = "2026-09-23T10:01:00Z") -> dict:
    return {"type": "user", "timestamp": stamp, "origin": {"kind": "human"},
            "message": {"content": text}}


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


def test_service_inserts_are_not_anton(tmp_path):
    raw = tmp_path / "claude"
    _write(raw, [
        {"type": "user", "timestamp": "2026-09-23T10:00:00Z",
         "message": {"content": "<task-notification>не понял</task-notification>"}},
        {"type": "user", "timestamp": "2026-09-23T10:00:00Z", "isSidechain": True,
         "message": {"content": "не понял"}},
    ])

    assert AH.scan(raw, since=None, strict=False).get("2026-09", {}).get("anton_msgs", 0) == 0
