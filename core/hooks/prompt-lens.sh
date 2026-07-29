#!/bin/bash
# H22 — hook: prompt lens (UserPromptSubmit, fires on every user message)
#
# Pain: по корпусу переписки (1994 сообщения, 186 сессий) проколы всплывают не
# уточняющим вопросом (2% случаев), а откатом после ~450–3000 знаков уже
# написанного. Причины повторяются: висячая ссылка («это», «там»), слово-градус
# без меры («немного нейтральнее»), открытый глагол без критерия готовности.
#
# What it does (линза): НЕ переписывает запрос — добавляет к нему короткую
# приписку-подсказку для агента. Исходный текст доходит в целости.
# Принципиальная разница с ИИ-прокладкой: всё детерминировано, без модели,
# ошибки не перемножаются.
#
# ГДЕ ЖИВУТ ПРАВИЛА: `${STC_CORE}/scripts/lens_rules.py` — единый источник для
# хука, месячного аудита (`scripts/prompt-audit.py`) и стража
# (`hooks/tests/prompt-lens.test.sh`). Раньше правила были размножены копипастой
# по трём файлам, и копия в аудите считала не то, что срабатывает. Правило и его
# измеритель — один код.
#
# ПОЧЕМУ НЕ ТИХО: если модуль правил не найден или упал, хук печатает об этом
# строкой, а не молчит. Молчащая линза неотличима от чистого запроса — а
# «правило, которое молча не срабатывает, хуже отсутствующего»
# (core/memory/reference_cyrillic_regex.md).
#
# Render-time vars (resolved by deploy.py from stc.yaml):
#   ${USER_LANG}     — message language (en|ru). Default ru.
#   ${STC_CORE}      — shared core root (~/.stc/core).
#   ${LENS_MIN_LEN}  — не анализировать сообщения короче этого. Default 4.
#   ${LENS_MAX_FLAGS}— максимум строк в приписке (анти-шум). Default 4.

USER_LANG="${USER_LANG:-ru}"
LENS_MIN_LEN="${LENS_MIN_LEN:-4}"
LENS_MAX_FLAGS="${LENS_MAX_FLAGS:-4}"

INPUT=$(cat)

# --- где модуль правил ------------------------------------------------------
# 1) явно заданный путь (тесты), 2) задеплоенный core, 3) раскладка репозитория.
RULES="${STC_LENS_RULES:-}"
if [ -z "$RULES" ] || [ ! -f "$RULES" ]; then
  RULES="${STC_CORE}/scripts/lens_rules.py"
fi
if [ ! -f "$RULES" ]; then
  alt="$(cd "$(dirname "$0")/../scripts" 2>/dev/null && pwd)/lens_rules.py"
  [ -f "$alt" ] && RULES="$alt"
fi
if [ ! -f "$RULES" ]; then
  case "$USER_LANG" in
    ru) printf '\n[линза] ⚠ модуль правил не найден (%s) — линза сейчас НИЧЕГО не проверяет.\n' "$RULES" ;;
    *)  printf '\n[lens] ⚠ rules module not found (%s) — the lens checks NOTHING right now.\n' "$RULES" ;;
  esac
  exit 0
fi

# Ядро на python3 (не grep): кириллица + нормализация латинских двойников.
# Скрипт передаётся через -c, чтобы stdin остался под payload.
LENS_PY='
import sys, json, os, importlib.util
rules_path, user_lang, min_len, max_flags = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
spec = importlib.util.spec_from_file_location("lens_rules", rules_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
d = json.load(sys.stdin)
prompt = d.get("prompt","") or d.get("user_prompt","")

# Есть ли уже контекст в разговоре: если ассистент ещё не сказал ни слова,
# висячая ссылка («это», «там») действительно не на что опереться. В середине
# разговора она почти всегда указывает на только что обсуждавшееся — по
# корпусу 130 срабатываний из 137 были именно такими, и подсказка врала.
fresh = None
tp = d.get("transcript_path") or ""
if tp and os.path.exists(tp):
    try:
        if os.path.getsize(tp) > 200000:
            fresh = False                     # длинный транскрипт = контекст точно есть
        else:
            with open(tp, encoding="utf-8", errors="ignore") as fh:
                fresh = not any("\"assistant\"" in line for line in fh)
    except OSError:
        fresh = None

for f in mod.analyze(prompt, min_len=min_len, fresh_context=fresh)[:max_flags]:
    print(f["ru"] if user_lang == "ru" else f["en"])
'

FLAGS=$(printf '%s' "$INPUT" | python3 -c "$LENS_PY" "$RULES" "$USER_LANG" "$LENS_MIN_LEN" "$LENS_MAX_FLAGS" 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
  # Не глушим ошибку: сломанная линза должна быть видна сразу.
  case "$USER_LANG" in
    ru) printf '\n[линза] ⚠ правила упали — линза не проверяет запрос. Проверь: python3 %s\n' "$RULES" ;;
    *)  printf '\n[lens] ⚠ rules crashed — the lens is not checking. Run: python3 %s\n' "$RULES" ;;
  esac
  exit 0
fi

if [ -n "$FLAGS" ]; then
  case "$USER_LANG" in
    ru) printf '\n[линза] приписка-подсказка (запрос НЕ переписан):\n' ;;
    *)  printf '\n[lens] additive hint (the prompt is NOT rewritten):\n' ;;
  esac
  printf '%s\n' "$FLAGS"
  case "$USER_LANG" in
    ru) printf '[линза] по флагу → FR-30 эхо-переформулировка, если далее дорогое действие.\n' ;;
    *)  printf '[lens] on a flag → FR-30 echo-reformulation if a costly action follows.\n' ;;
  esac
fi

exit 0
