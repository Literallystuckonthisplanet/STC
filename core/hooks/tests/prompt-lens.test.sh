#!/bin/bash
# Страж-тест хука H22 prompt-lens.sh.
#
# Три части — все обязательны («правило, молча не срабатывающее, хуже
# отсутствующего», см. core/memory/reference_cyrillic_regex.md):
#
# 1. CONTROL — хук целиком, через stdin: флаг поднялся / не поднялся, включая
#    контекстные гейты и поведение при потерянном модуле правил.
# 2. CANARIES — канарейки из lens_rules.py (правило + обратное правило).
# 3. CORPUS  — каждое ПРАВИЛО и каждая КЛИЧКА ловят ≥ MIN_TP реальных
#    сообщений. Проверка на уровне клички принципиальна: раньше страж считал
#    только по правилу, и мёртвые латинские `fe`/`stc`/`driada` проходили за
#    счёт живого «фе».
#
# Корпус — ЛИЧНЫЕ ДАННЫЕ и лежит ВНЕ репозитория: $STC_CORPUS
# (по умолчанию ~/.stc/.corpus/corpus.jsonl), собирается
# `core/scripts/collect_corpus.py`. Нет корпуса — тест ПАДАЕТ: раньше он
# печатал «пропускаю» и всё равно выходил «ВСЁ ПРОШЛО», то есть гарантия
# «каждое правило посчитано» исчезала молча.
#
# Запуск:  bash core/hooks/tests/prompt-lens.test.sh
# Выход:   0 = всё прошло, 1 = провал (печатает, что именно).

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"       # ~/Work/STC  (tests→hooks→core→STC)
HOOK="$REPO/core/hooks/prompt-lens.sh"
RULES="$REPO/core/scripts/lens_rules.py"
CORPUS="${STC_CORPUS:-$HOME/.stc/.corpus/corpus.jsonl}"
MIN_TP="${LENS_TEST_MIN_TP:-3}"

export STC_LENS_RULES="$RULES"

PASS=0; FAIL=0
fail() { echo "FAIL: $1"; FAIL=$((FAIL+1)); }
pass() { echo "ok:   $1"; PASS=$((PASS+1)); }

json() { python3 -c 'import json,sys; print(json.dumps({"prompt": sys.argv[1]}))' "$1"; }

# --- CONTROL: expect_flag <desc> <prompt> <substr|EMPTY> -------------------
expect_flag() {
  local desc="$1" prompt="$2" substr="${3:-}" out
  out=$(json "$prompt" | USER_LANG=ru bash "$HOOK" 2>/dev/null)
  if [ -z "$substr" ]; then
    if [ -z "$out" ]; then pass "$desc (молчит, как ожидалось)"
    else fail "$desc — должен молчать, но вывел: $(echo "$out" | tr '\n' ' ')"
    fi
  else
    if echo "$out" | grep -qF "$substr"; then pass "$desc"
    else fail "$desc — ожидался флаг «$substr», вывод: $(echo "$out" | tr '\n' ' ')"
    fi
  fi
}

echo "=== CONTROL (хук целиком, контекстные гейты) ==="
expect_flag "висячая ссылка «это»"            "посмотри это и поправь тоже"            "висячая ссылка"
expect_flag "градус ПРИ правке текста"        "стиль немного нейтральнее сделай"       "градус без меры"
expect_flag "градус БЕЗ правки"               "я немного устал сегодня"                ""
expect_flag "мульти-задача ≥3"                "сделай x, проверь y, поправь z"         "задач"
expect_flag "открытый глагол"                 "посмотри логи"                          "открытый глагол"
expect_flag "критерий уже назван"             "поправь заголовок, готово когда тесты зелёные"  ""
expect_flag "объект уже назван"               "посмотри ~/Work/STC/core/hooks/prompt-lens.sh"  ""
expect_flag "глаголы в цитате — не задачи"    "заказчик пишет: «сделай проверь поправь» — про что он" ""
expect_flag "кличка кириллицей"               "фе собери и задеплой"                   "forest-echoes-www"
expect_flag "кличка латиницей (была мертва)"  "собери fe и выложи"                     "forest-echoes-www"
expect_flag "кличка stc (была мертва)"        "почини stc деплой"                      "~/Work/STC"
expect_flag "кличка driada (была мертва)"     "обнови driada каталог"                  "driada-www"
expect_flag "кличка в ссылке не нужна"        "открой https://forest-echoes.com/catalog" ""
expect_flag "слишком коротко"                 "да"                                     ""

# Потерянный модуль правил обязан быть ВИДЕН, а не проглочен. Копия хука в
# пустом каталоге: так не сработает и запасной путь «рядом с хуком».
TMPHOOK="$(mktemp -d)/prompt-lens.sh"
cp "$HOOK" "$TMPHOOK"
out=$(json "посмотри логи" | USER_LANG=ru STC_LENS_RULES=/nonexistent/lens_rules.py \
      STC_CORE=/nonexistent bash "$TMPHOOK" 2>/dev/null)
rm -rf "$(dirname "$TMPHOOK")"
case "$out" in
  *"НИЧЕГО не проверяет"*) pass "потерянный модуль правил — виден в выводе" ;;
  *) fail "потерянный модуль правил — хук промолчал или скрыл: $(echo "$out" | tr '\n' ' ')" ;;
esac

# --- CANARIES -------------------------------------------------------------
echo ""
echo "=== CANARIES (правила + обратные правила из lens_rules.py) ==="
if python3 "$RULES"; then pass "канарейки"; else fail "канарейки — см. вывод выше"; fi

# --- CORPUS ---------------------------------------------------------------
echo ""
echo "=== CORPUS (правило И кличка ловят ≥ $MIN_TP реальных сообщений) ==="
if [ ! -f "$CORPUS" ]; then
  fail "корпус не найден: $CORPUS
      собери его: python3 core/scripts/collect_corpus.py
      (без корпуса правила не посчитаны — «кандидат ≠ баг»)"
else
  python3 - "$CORPUS" "$RULES" "$MIN_TP" <<'PY'
import json, sys, importlib.util, re
corpus, rules_path, min_tp = sys.argv[1], sys.argv[2], int(sys.argv[3])
spec = importlib.util.spec_from_file_location("lens_rules", rules_path)
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

recs = [json.loads(l) for l in open(corpus, encoding="utf-8")]
# Первое сообщение сессии = у агента ещё нет контекста. Считаем ровно так же,
# как решает хук в рантайме, иначе цифры стража разойдутся с реальностью.
recs.sort(key=lambda r: (r["sessionId"] or "", r["timestamp"] or ""))
_seen_sessions = set()
for r in recs:
    r["_fresh"] = r["sessionId"] not in _seen_sessions
    _seen_sessions.add(r["sessionId"])

rule_hits, rule_sample, flagged = {}, {}, 0
for r in recs:
    flags = L.analyze(r["raw"], fresh_context=r["_fresh"])
    if flags:
        flagged += 1
    for rule in {f["rule"] for f in flags}:
        rule_hits[rule] = rule_hits.get(rule, 0) + 1
        rule_sample.setdefault(rule, r["raw"][:60].replace("\n", " "))

fails = 0
for rule in ("DANGLING", "DEGREE", "OPEN_VERB", "MULTI_TASK", "NICK"):
    n = rule_hits.get(rule, 0)
    ok = n >= min_tp
    fails += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] правило {rule:<11} TP={n:>4}  пример: {rule_sample.get(rule,'—')!r}")

# Кличка считается отдельно: правило может быть живым, а половина его
# альтернатив — мёртвой (так и было с латинскими fe/stc/driada).
print("  --- по кличкам ---")
for p in L.PROJECTS:
    for alias in p["aliases"]:
        rx = re.compile(L.NICK_EDGE + re.escape(L.normalize(alias)) + L.NICK_EDGEE)
        n = sum(1 for r in recs if rx.search(L.normalize(r["raw"])))
        ok = n >= min_tp
        fails += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] кличка {alias:<10} TP={n:>4}  → {p['key']}")

print(f"  сообщений в корпусе: {len(recs)}, с любым флагом: {flagged} "
      f"({100*flagged/len(recs):.1f}%)")
sys.exit(1 if fails else 0)
PY
  if [ $? -ne 0 ]; then
    fail "правило или кличка не набрали $MIN_TP реальных срабатываний"
  else
    pass "корпус: все правила и клички посчитаны"
  fi
fi

echo ""
echo "=== ИТОГ: pass=$PASS fail=$FAIL ==="
[ "$FAIL" -eq 0 ] && echo "ВСЁ ПРОШЛО" || echo "ЕСТЬ ПРОВАЛЫ"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
