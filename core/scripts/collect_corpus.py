#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборщик корпуса живых сообщений пользователя из транскриптов харнесса.

Зачем: правило линзы (H22) не попадает в прод, пока не посчитано по реальной
переписке — «кандидат ≠ баг» (см. core/memory/reference_cyrillic_regex.md).
Этот скрипт готовит корпус, по которому считает страж-тест и месячный аудит.

ЧИТАЕТ:  $STC_PROJECTS_DIR (по умолчанию ~/.claude/projects)/**/*.jsonl
ФИЛЬТР:  живые сообщения пользователя под --root; без tool_result, медиа,
         системных пастов и повторов
ПИШЕТ:   $STC_CORPUS (по умолчанию ~/.stc/.corpus/corpus.jsonl), права 600

⚠ КОРПУС — ЛИЧНЫЕ ДАННЫЕ. Он намеренно пишется ВНЕ репозитория: репо STC
имеет публичный remote, и `git add -A` не должен иметь ни единого шанса
утащить переписку наружу. Не переносить корпус внутрь репо ни под каким
предлогом (в .gitignore стоит второй замок).

Ничего не деплоит и не меняет конфиг — только читает jsonl.

Запуск:  python3 core/scripts/collect_corpus.py [--root ~/Work] [--limit N]
"""
from __future__ import annotations
import json, os, sys, statistics, glob, argparse
from pathlib import Path

# Правила линзы (нормализация + регулярки) — единый источник.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lens_rules import normalize, analyze  # noqa: E402

DEFAULT_ROOT = os.path.expanduser("~/Work")
PROJECTS_DIR = os.environ.get("STC_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")
DEFAULT_OUT = os.environ.get("STC_CORPUS") or os.path.expanduser("~/.stc/.corpus/corpus.jsonl")


def extract_text(content) -> str:
    """Чистый текст сообщения. content — str либо список блоков.

    tool_result и медиа отбрасываем: интересует то, что человек напечатал.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return ""


# Сигнатуры неживых user-записей: tool_result, системные префиксы,
# skill/config-пасты, agent-roleplay-инструкции.
SYSTEM_PREFIXES = (
    "[Request interrupted", "Caveat:", "<system-reminder>",
    "<command-name>", "<command-message>", "<command-args>",
    "<local-command", "<bash-input", "<bash-stdout",
)
NOISE_PREFIXES = (
    "tool_result", "<tool", "# Update Config", "# ", "Base directory for this skill",
    "Modify Claude Code", "---", "name:", "description:", "You are ", "Ты —",
    "<function_calls", "<antml", "<fence",
)
MAX_LIVE_LEN = 2000   # p90 живой реплики ≈ 730 знаков; 2000 — с запасом


def is_live_message(text: str) -> bool:
    t = text.strip()
    if len(t) < 2 or len(t) > MAX_LIVE_LEN:
        return False
    for p in SYSTEM_PREFIXES + NOISE_PREFIXES:
        if t.startswith(p):
            return False
    if t.startswith('"""') or t.startswith("'''") or t.startswith("```"):
        return False
    return True


def collect(root: str, limit: int | None = None):
    files = glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True)
    records = []
    seen = set()  # дедуп: один и тот же текст в той же сессии = повтор (resume/fork)
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "user":
                continue
            msg = o.get("message") or {}
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            cwd = o.get("cwd") or ""
            if not cwd.startswith(root):
                continue
            raw = extract_text(msg.get("content"))
            if not is_live_message(raw):
                continue
            norm = normalize(raw)
            key = (o.get("sessionId"), norm[:80])
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "sessionId": o.get("sessionId"),
                "timestamp": o.get("timestamp"),
                "cwd": cwd,
                "gitBranch": o.get("gitBranch"),
                "len": len(raw),
                "raw": raw,
                "norm": norm,
            })
            if limit and len(records) >= limit:
                return records
    return records


def metrics(records):
    """Частоты — считаны ТЕМ ЖЕ analyze(), что работает в хуке.

    Иначе цифры отчёта и реальные срабатывания разъезжаются (ровно эта
    ошибка была в первой версии аудита).
    """
    n = len(records)
    if n == 0:
        return {}
    lens = [r["len"] for r in records]
    fired = {}
    any_flag = 0
    for r in records:
        flags = analyze(r["raw"])
        if flags:
            any_flag += 1
        for f in {fl["rule"] for fl in flags}:
            fired[f] = fired.get(f, 0) + 1
    m = {
        "messages": n,
        "sessions": len({r["sessionId"] for r in records}),
        "len_median": int(statistics.median(lens)),
        "p90_len": int(statistics.quantiles(lens, n=10)[8]) if n >= 10 else 0,
        "any_flag_pct": round(100 * any_flag / n, 1),
    }
    for k, v in sorted(fired.items()):
        m[f"{k.lower()}_pct"] = round(100 * v / n, 1)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="куда писать корпус (по умолчанию $STC_CORPUS)")
    args = ap.parse_args()

    if os.path.abspath(args.out).startswith(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))):
        sys.exit("отказ: корпус пишется внутрь репозитория STC — это личные данные, "
                 "укажи путь вне репо (по умолчанию ~/.stc/.corpus/corpus.jsonl)")

    records = collect(args.root, args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.chmod(out, 0o600)
    try:
        os.chmod(out.parent, 0o700)
    except OSError:
        pass

    m = metrics(records)
    print(f"corpus: {out} (права 600)")
    print(f"records: {m.get('messages',0)} messages across {m.get('sessions',0)} sessions (root={args.root})")
    print("--- metrics (по тем же правилам, что в хуке) ---")
    for k, v in m.items():
        if k in ("messages", "sessions"):
            continue
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
