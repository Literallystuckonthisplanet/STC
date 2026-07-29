#!/usr/bin/env python3
"""prompt-audit.py (H22/FR-30) — офлайн-аудит линзы запроса раз в месяц.

Зачем: линза (H22) и правило эхо-переформулировки (FR-30) остаются гипотезой,
пока месяц живого трафика их не подтвердит. Единственный честный критерий —
упало ли число откатов. Этот отчёт отвечает на него и заодно показывает
мёртвые и шумные правила.

ЧТО ИСПРАВЛЕНО ПОСЛЕ РЕВЬЮ (важно для доверия к цифрам):
  1. Правила больше НЕ дублируются здесь копипастой. Всё считается через
     `lens_rules.analyze()` — ровно ту функцию, что работает в хуке, со всеми
     контекстными гейтами. Раньше копия в аудите гейтов не имела и показывала
     MULTI_TASK 206 там, где хук срабатывал 69 раз.
  2. «Шумное правило» больше не значит «после него не было отката» — по такой
     логике сработавшее и предотвратившее прокол правило считалось мусорным.
     Теперь шум = сработало, при этом ни отката, ни уточняющего вопроса
     агента НЕ последовало, и таких случаев подавляющее большинство.
  3. Реестр откатов дедуплицируется (одна и та же реплика лежит в нескольких
     файлах транскриптов после resume/fork) и требует, чтобы перед откатом
     реально была работа агента — иначе первое сообщение сессии со словом
     «не то» попадало в статистику как откат.
  4. Кандидаты в словарь берутся из ИСХОДНОГО русского текста, а не из
     нормализованного: иначе `task` превращался в `tаск`, и главным
     «кандидатом» становился осколок «аск» (273 раза).

Работает ТОЛЬКО офлайн, в рантайм-путь не попадает.

Harness-neutral: каталог сессий берётся из STC_PROJECTS_DIR (по умолчанию
~/.claude/projects).

Режимы:
  (без флагов)         полный аудит по всему окну
  --since 30d          окно: N дней (d), недель (w) или ISO-дата
  --root ~/Work        только сессии с cwd внутри дерева
  --json               машинный вывод

Пример (ежемесячно, вместе с аудитом инфры):
  python3 core/scripts/prompt-audit.py --since 30d
"""
from __future__ import annotations
import argparse, glob, json, os, re, sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lens_rules as L  # единый источник правил линзы

PROJECTS = os.environ.get("STC_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")
DEFAULT_ROOT = os.path.expanduser("~/Work")

# --- разбор payload (зеркалит collect_corpus.py) --------------------------
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
MAX_LIVE_LEN = 2000
ASSISTANT_KEEP = 600      # сколько знаков ответа держим (нужен только вопрос «?»)


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return ""


def is_live(text: str) -> bool:
    t = text.strip()
    if len(t) < 2 or len(t) > MAX_LIVE_LEN:
        return False
    for p in SYSTEM_PREFIXES + NOISE_PREFIXES:
        if t.startswith(p):
            return False
    if t.startswith('"""') or t.startswith("'''") or t.startswith("```"):
        return False
    return True


# --- окно -----------------------------------------------------------------
def parse_since(since: str | None) -> datetime | None:
    if not since:
        return None
    m = re.fullmatch(r"(\d+)([dw])", since)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return datetime.now(timezone.utc) - timedelta(days=n if unit == "d" else n * 7)
    try:
        return datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    except ValueError:
        raise SystemExit(f"плохой --since: {since!r} (нужно 30d, 4w или ГГГГ-ММ-ДД)")


def in_window(ts: str | None, since: datetime | None) -> bool:
    if since is None or not ts:
        return True
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) >= since
    except Exception:
        return True


# --- сборка разговоров ----------------------------------------------------
def load_sessions(root: str, since: datetime | None):
    """Отдаёт (sessionId, [ходы]) — реплики пользователя и ответы агента по порядку.

    Ответы агента нужны дважды: чтобы измерить, сколько написанного выброшено
    перед откатом, и чтобы увидеть, задал ли агент уточняющий вопрос.
    """
    for fp in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        turns, sid = [], None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = o.get("sessionId") or sid
            ts = o.get("timestamp")
            if not in_window(ts, since):
                continue
            msg = o.get("message") or {}
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "assistant":
                txt = extract_text(msg.get("content"))
                if txt:
                    turns.append({"role": "assistant", "len": len(txt),
                                  "text": txt[:ASSISTANT_KEEP], "ts": ts})
                continue
            if role != "user":
                continue
            cwd = o.get("cwd") or ""
            if root and not cwd.startswith(root):
                continue
            raw = extract_text(msg.get("content"))
            if not is_live(raw):
                continue
            turns.append({"role": "user", "raw": raw, "norm": L.normalize(raw),
                          "len": len(raw), "ts": ts})
        if turns and sid:
            yield sid, turns


# --- 1. реестр откатов ----------------------------------------------------
RE_ROLLBACK = re.compile(
    L.EDGE +
    r"(не то|не так|стоп|отмена|откат|я просил|я же просил|нет нет|не не|"
    r"верни как было|зачем ты|ты сделал не|переделай|отменим)" +
    L.EDGEE
)


def rollback_register(sessions):
    """Откаты + сколько знаков написанного выброшено перед каждым.

    Откат — это РЕАКЦИЯ на работу: если перед репликой не было ответа агента,
    это не откат, а обычное сообщение, где слова «не то» просто встретились.
    """
    register, seen = [], set()
    for sid, turns in sessions:
        asst_chars, prev_was_assistant = 0, False
        for t in turns:
            if t["role"] == "assistant":
                asst_chars += t["len"]
                prev_was_assistant = True
                continue
            if RE_ROLLBACK.search(t["norm"]) and prev_was_assistant:
                key = (sid, t["norm"][:80])
                if key not in seen:            # resume/fork кладёт одну реплику в разные файлы
                    seen.add(key)
                    register.append({"sessionId": sid, "ts": t.get("ts"),
                                     "discarded_chars": asst_chars,
                                     "message": t["raw"][:120]})
            asst_chars, prev_was_assistant = 0, False
    return register


# --- 2. кандидаты в словарь ----------------------------------------------
# Служебные слова русского: они всегда в топе частот и никогда не термины.
STOPWORDS = {
    "что", "это", "как", "для", "все", "если", "или", "только", "надо", "можно",
    "там", "тут", "так", "там", "тогда", "потом", "еще", "ещё", "уже", "нет",
    "да", "но", "и", "а", "же", "бы", "ли", "не", "ну", "вот", "тоже", "чтобы",
    "когда", "пока", "где", "кто", "чем", "тем", "том", "этот", "эта", "эти",
    "был", "была", "было", "были", "есть", "будет", "буду", "мне", "меня",
    "тебя", "тебе", "него", "нее", "них", "нас", "вас", "свой", "своя", "твой",
    "наш", "давай", "давайте", "просто", "очень", "может", "можешь", "нужно",
    "нужен", "нужна", "сейчас", "потому", "после", "перед", "через", "между",
    "лучше", "хорошо", "плохо", "думаю", "вижу", "понял", "поняла", "знаю",
}
WORD_RE = re.compile(r"[а-яё]{4,}")   # по ИСХОДНОМУ тексту, не по нормализованному


def _covered_words() -> set[str]:
    """Что уже покрыто глоссарием и правилами — нормализованно, чтобы «ё» не мешала."""
    words = set()
    for p in L.PROJECTS:
        words.update(L.normalize(a) for a in p["aliases"])
    for group in (L.DANGLING_WORDS, L.DEGREE_WORDS, L.OPEN_VERBS, L.TASK_VERBS):
        words.update(L.normalize(w) for w in group)
    words.update(L.normalize(w) for w in (
        "форест", "ворктри", "мвп", "репо", "прод", "лента", "отсев", "порция",
        "копилка", "ротация", "плейрайт", "playwright", "pev", "adr",
    ))
    return words


def dictionary_candidates(sessions, topn=15):
    covered = _covered_words()
    freq = Counter()
    for _sid, turns in sessions:
        for t in turns:
            if t["role"] != "user":
                continue
            for w in WORD_RE.findall(t["raw"].lower()):
                if w in STOPWORDS or L.normalize(w) in covered:
                    continue
                freq[w] += 1
    return freq.most_common(topn)


# --- 3 и 4. мёртвые / шумные правила -------------------------------------
RULE_NAMES = ("DANGLING", "DEGREE", "OPEN_VERB", "MULTI_TASK", "NICK")


def rule_health(sessions):
    """Считает ТЕМИ ЖЕ правилами, что и хук (включая гейты).

    Шум определяем честно: правило сработало, но дальше не случилось ни
    отката, ни уточняющего вопроса агента. Правило, за которым шёл вопрос
    (линза сработала — агент переспросил), шумом НЕ считается: это ровно то,
    ради чего она стоит.
    """
    hits = {k: 0 for k in RULE_NAMES}
    no_signal = {k: 0 for k in RULE_NAMES}
    for _sid, turns in sessions:
        first_user_seen = False
        for i, t in enumerate(turns):
            if t["role"] != "user":
                continue
            fresh = not first_user_seen
            first_user_seen = True
            fired = {f["rule"] for f in L.analyze(t["raw"], fresh_context=fresh)}
            if not fired:
                continue
            for k in fired:
                hits[k] += 1
            nxt_user = next((turns[j] for j in range(i + 1, len(turns))
                             if turns[j]["role"] == "user"), None)
            rollback = bool(nxt_user and RE_ROLLBACK.search(nxt_user["norm"]))
            asked = any("?" in turns[j].get("text", "")
                        for j in range(i + 1, min(i + 4, len(turns)))
                        if turns[j]["role"] == "assistant")
            if not rollback and not asked:
                for k in fired:
                    no_signal[k] += 1
    dead = [k for k in RULE_NAMES if hits[k] == 0]
    noisy = {k: no_signal[k] for k in RULE_NAMES
             if hits[k] > 0 and no_signal[k] == hits[k]}
    return hits, dead, noisy


def _median(xs):
    if not xs:
        return 0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2


# --- main -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=None, help="окно: 30d, 4w или ГГГГ-ММ-ДД")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="только сессии под этим деревом")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args()

    since = parse_since(args.since)
    sessions = list(load_sessions(args.root, since))
    n_msgs = sum(sum(1 for t in turns if t["role"] == "user") for _, turns in sessions)
    n_sessions = len(sessions)

    broken = L.self_check()
    rollbacks = rollback_register(sessions)
    candidates = dictionary_candidates(sessions)
    hits, dead, noisy = rule_health(sessions)

    if args.json:
        print(json.dumps({
            "window_since": since.isoformat() if since else None,
            "root": args.root,
            "messages": n_msgs, "sessions": n_sessions,
            "lens_self_check": broken,
            "rollbacks": {"count": len(rollbacks),
                          "median_discarded_chars": _median([r["discarded_chars"] for r in rollbacks])},
            "dictionary_candidates": candidates,
            "rule_hits": hits, "dead_rules": dead, "noisy_rules": noisy,
            "rollback_register": rollbacks[:20],
        }, ensure_ascii=False, indent=2))
        return

    print(f"prompt-audit — окно: {('с ' + since.date().isoformat()) if since else 'всё время'}, root: {args.root}")
    print(f"корпус: {n_msgs} сообщений в {n_sessions} сессиях\n")

    print("== 0. ЛИНЗА ЖИВА? ==")
    if broken:
        print("   ⚠ ЛИНЗА СЛОМАНА — цифры ниже не о чем:")
        for b in broken:
            print(f"   - {b}")
    else:
        print(f"   да — {len(L.CANARIES)} канареек и {len(L.SILENT_CANARIES)} обратных проходят")

    discarded = [r["discarded_chars"] for r in rollbacks]
    print("\n== 1. РЕЕСТР ОТКАТОВ ==")
    print(f"   откатов: {len(rollbacks)} ({round(100*len(rollbacks)/n_msgs,1) if n_msgs else 0}% сообщений)")
    print(f"   медиана выброшенного перед откатом: {_median(discarded)} знаков")
    for r in rollbacks[:8]:
        print(f"   - {r['discarded_chars']:>5} знаков впустую | {r['message']!r}")
    if len(rollbacks) > 8:
        print(f"   ... и ещё {len(rollbacks)-8}")

    print("\n== 2. КАНДИДАТЫ В СЛОВАРЬ (частые слова вне глоссария) ==")
    for w, c in candidates[:12]:
        print(f"   {c:>4}×  {w}")

    print("\n== 3. МЁРТВЫЕ ПРАВИЛА (0 срабатываний в окне → на удаление) ==")
    print(f"   {dead if dead else 'нет — каждое правило срабатывало'}")

    print("\n== 4. ШУМНЫЕ ПРАВИЛА (сработало, но ни отката, ни вопроса → поднять порог) ==")
    if noisy:
        for k, c in noisy.items():
            print(f"   {k}: {c} срабатываний, ни одного с последующим сигналом")
    else:
        print("   нет — за каждым сработавшим правилом был сигнал")

    print("\n== СРАБАТЫВАНИЯ ПО ПРАВИЛАМ (те же гейты, что в хуке) ==")
    for k in RULE_NAMES:
        share = f"{100*hits[k]/n_msgs:.1f}%" if n_msgs else "—"
        print(f"   {k:<11} {hits[k]:>5}   {share}")


if __name__ == "__main__":
    main()
