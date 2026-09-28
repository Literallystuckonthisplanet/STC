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
# Render-time vars: ${USER_LANG}, ${STC_CORE}, ${HARNESS_NAME}.

USER_LANG="${USER_LANG:-ru}"
HARNESS_NAME="${HARNESS_NAME:-claude}"
# Как в остальных хуках: ${STC_CORE} подставляется при сборке в ТЕКСТ
# скрипта, в окружении его нет. Первая редакция читала os.environ и
# потому в бою молчала всегда — тесты этого не поймали: они задавали её сами.
STC_CORE="${STC_CORE:-$HOME/.stc/core}"

INPUT=$(cat)

# Субагенты развилок пользователю не предъявляют.
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // ""' 2>/dev/null)
[ -n "$AGENT_ID" ] && exit 0

# Развилка опознаётся по МОЕМУ маркеру 🗳️ в последнем моём ХОДЕ (все реплики
# после прошлого сообщения человека), а ответ-вопрос («Сколько будет стоить A?»)
# развилку не закрывает. Оба правила живут в decision_health.py и общие со
# счётчиком: ревью 25.09 поймало, что сторож смотрел одну последнюю реплику,
# а счётчик — любую до ответа человека, и на «выбор → ещё реплика → выбрал A»
# они расходились. Почему опознаём по маркеру, а не по форме ответа, — в шапке
# decision_health.py (три шаблона по форме отбракованы замером).
FORK=$(printf '%s' "$INPUT" | python3 -c '
import json, os, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

path = data.get("transcript_path") or ""
if not path or not os.path.exists(path):
    sys.exit(0)

# Нужен только последний ход, поэтому читаем хвост файла, а не весь
# транскрипт: он растёт до десятков мегабайт, а хук висит на каждом
# сообщении пользователя. Хвост с запасом: живой ход 24.09 весил 765 КБ, и при
# 400 КБ значок развилки оказался за краем (ревью 26.09).
TAIL = 2_000_000
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
    # Codex keeps the session discriminator in the first session_meta record.
    # Re-read that one small line so a long conversation is still recognized
    # as Codex after the bounded tail has dropped its header.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            header = fh.readline(TAIL + 1).rstrip("\n")
        candidate = json.loads(header)
        payload = candidate.get("payload") if isinstance(candidate, dict) else None
        if (isinstance(candidate, dict) and candidate.get("type") == "session_meta"
                and isinstance(payload, dict)):
            lines.insert(0, header)
    except OSError:
        pass

# Codex native sessions must be scoped to the caller.  Claude legacy
# transcripts have no session_id and retain their historical behavior.
if not data.get("session_id"):
    try:
        first = json.loads(lines[0]) if lines else {}
        if isinstance(first, dict) and first.get("type") == "session_meta":
            sys.exit(0)
    except Exception:
        pass

sys.path.insert(0, os.path.join(sys.argv[1], "scripts"))
try:
    from decision_health import fork_turn_in_tail, reply_kind
except Exception:
    sys.exit(0)                # счётчик недоступен — молчим, а не гадаем
prompt = data.get("prompt") or ""
turn = fork_turn_in_tail(lines, prompt, data.get("session_id") or "")
if turn and reply_kind(prompt, turn) != "question":
    print("fork")
' "$STC_CORE" 2>/dev/null)

[ "$FORK" = "fork" ] || exit 0

HINT=$(
if [ "$USER_LANG" = "ru" ]; then
  cat <<'EOF'

[решение] Предыдущий ход предъявлял развилку. Если это сообщение ВЫБИРАЕТ
вариант — остальные отвергнуты, и это нигде не останется, если не записать.
Тогда в ЭТОТ ответ, после обычных слов, добавь служебный блок (не для чтения
человеком, его разбирает decision_health.py):

```decision
принято: <что делаем>
отклонено: <что не делаем>; причина: <только если прозвучала>
```

Одна строка «отклонено» на каждый отвергнутый вариант, на языке разговора.
Причину не выдумывай: не прозвучала — пиши строку без «причина:», доля таких
отказов считается отдельно и это метрика, а не дефект.

Если выбора в сообщении НЕТ — уточнение, вопрос, новая задача — блок НЕ
ставь: записанное «решение», которого не было, хуже пропущенного.
EOF
else
  cat <<'EOF'

[decision] The previous turn presented a fork. If this message CHOOSES an
option, the other options are now rejected and leave no trace unless recorded.
Then in THIS reply, after the prose, add the service block (not for a human to
read; decision_health.py parses it):

```decision
принято: <what we do>
отклонено: <what we do not>; причина: <only if voiced>
```

One "отклонено" line per rejected option, in the language of the conversation.
Never infer a reason: if none was voiced, write the line without "причина:".
The share of unreasoned rejections is a metric, not a defect.

If the message makes NO choice — a clarification, a question, a new task — do
NOT add the block: a recorded "decision" that never happened is worse than a
missing one.
EOF
fi
)

if [ "$HARNESS_NAME" = "codex" ]; then
  # Use the native envelope: the leading [решение] plain-text hint was
  # produced by the hook but absent from Codex's model-visible context.
  printf '%s' "$HINT" | python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": sys.stdin.read(),
}}, ensure_ascii=False))
'
else
  printf '%s\n' "$HINT"
fi

exit 0
