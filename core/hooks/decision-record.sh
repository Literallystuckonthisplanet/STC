#!/bin/bash
# H23 — hook: decision-record (UserPromptSubmit)
#
# Pain: выбирая один вариант, пользователь МОЛЧА отвергает остальные. Принятое
# оставляет след в коде, отвергнутое — нигде, и через месяц предлагается
# заново. Замер 04.09: поиск по прошлым разговорам звался 15 раз за всё время
# против 121 чтения снапшотов; разобранная заметка о поздних кругах ревью
# пролежала сиротой месяц, и тот же вопрос разбирался с нуля.
#
# Что делает: когда пользователь ОТВЕТИЛ на предъявленную развилку (моя
# предыдущая реплика несла маркер 🗳️), добавляет к его запросу короткую
# приписку — поставить в ответ служебный блок ```decision с принятым и
# отвергнутыми вариантами. Не блокирует и ничего не переписывает.
#
# ПОЧЕМУ ХУКОМ, А НЕ ПРАВИЛОМ В ALWAYS-КОНТЕКСТЕ: ядро правил забито под
# завязку — 9989 байт из лимита 10 000 (страж
# `test_h06_kernel_fits_codex_visible_context_budget`, лимит от видимого
# контекста codex). Правило весом килобайт туда физически не влезает, а
# ужимать чужие правила ради своего — не мой размен. Точечная доставка ещё и
# дешевле: развилок по корпусу ~22 в месяц, то есть в остальное время приписка
# не стоит ничего. Это тот же приём, которым H01 подаёт чек-лист перед
# коммитом, а H19 — прошлые решения перед показом плана.
#
# ПОЧЕМУ НЕ ПРИНУЖДЕНИЕ: Антон 17.09 выбрал сперва месяц ПОМЕРИТЬ, как часто
# разметка забывается, и только потом решать про принуждение. Блокировать тут
# нечего: реплика пользователя уже пришла, а гейт на конце ответа — отдельное
# решение, которое пока не принято.
#
# Счёт соблюдения — `${STC_CORE}/scripts/decision_health.py` (доля развилок с
# блоком, доля отказов без названной причины). База на 17.09: 56 развилок за
# 76 дней, размечено 0.
#
# Render-time vars: ${USER_LANG}, ${STC_CORE}.

USER_LANG="${USER_LANG:-ru}"

INPUT=$(cat)

# Субагенты развилок пользователю не предъявляют.
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // ""' 2>/dev/null)
[ -n "$AGENT_ID" ] && exit 0

# Развилка опознаётся по МОЕМУ маркеру в последней реплике, а не по форме
# ответа пользователя. Три шаблона по форме ответа отбракованы замером: они
# ловили мои же нумерованные промпты субагентам, вставки файлов с номерами
# строк и цитаты моего текста (подробности — в шапке decision_health.py).
FORK=$(printf '%s' "$INPUT" | python3 -c '
import json, os, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

path = data.get("transcript_path") or ""
if not path or not os.path.exists(path):
    sys.exit(0)

# Нужна ровно последняя реплика ассистента, поэтому читаем хвост файла, а не
# весь транскрипт: он растёт до десятков мегабайт, а хук висит на каждом
# сообщении пользователя.
TAIL = 400_000
try:
    with open(path, "rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        fh.seek(max(0, size - TAIL))
        chunk = fh.read().decode("utf-8", "replace")
except OSError:
    sys.exit(0)

lines = chunk.splitlines()
if size > TAIL and lines:
    lines = lines[1:]          # первая строка хвоста обрезана посередине

for line in reversed(lines):
    if "assistant" not in line:
        continue               # быстрый отсев без разбора JSON
    try:
        obj = json.loads(line)
    except Exception:
        continue
    msg = obj.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        continue
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    else:
        text = ""
    if not text.strip():
        continue               # реплика без слов (только вызов инструмента)
    print("fork" if "\U0001f5f3" in text else "")
    break
' 2>/dev/null)

[ "$FORK" = "fork" ] || exit 0

if [ "$USER_LANG" = "ru" ]; then
  cat <<'EOF'

[решение] Ответ на развилку получен — значит остальные варианты отвергнуты, и
это нигде не останется, если не записать. В ЭТОТ ответ, после обычных слов,
добавь служебный блок (не для чтения человеком, его разбирает
decision_health.py):

```decision
принято: <что делаем>
отклонено: <что не делаем> — <причина, ТОЛЬКО если прозвучала>
```

Одна строка «отклонено» на каждый отвергнутый вариант, на языке разговора.
Причину не выдумывай: не прозвучала — оставь строку без неё, доля таких
отказов считается отдельно и это метрика, а не дефект.
EOF
else
  cat <<'EOF'

[decision] A fork was just resolved — the other options are now rejected, and
that leaves no trace unless recorded. In THIS reply, after the prose, add the
service block (not for a human to read; decision_health.py parses it):

```decision
принято: <what we do>
отклонено: <what we do not> — <reason, ONLY if voiced>
```

One "отклонено" line per rejected option, in the language of the conversation.
Never infer a reason: if none was voiced, leave the line without one. The share
of unreasoned rejections is a metric, not a defect.
EOF
fi

exit 0
