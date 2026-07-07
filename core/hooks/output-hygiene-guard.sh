#!/usr/bin/env bash
# H11 — hook: output-hygiene-guard — enforces I24 / FR-15.
# Event: PreToolUse(Bash).
#
# Pain: rule I24 ("don't dump raw command output into the window, only a
# summary") recidivised because it lived only in always-text. The hook turns
# it into a hard block: a command whose raw output goes straight to the
# terminal is blocked (exit 2) — forcing the noise to be redirected to a file
# and only the summary printed, or the file read with the Read tool.
#
# Parsed PER-SEGMENT (otherwise any `>`/`|` in a compound command would mute
# the guard): the command is split on `;` `&&` `||` \n; in each segment only
# the last stage of a pipe writes to the terminal. BLOCK if that stage dumps
# raw output to the window:
#   - cat <file> (except a heredoc `cat <<`), sed -n, less/more, tail/head of
#     a file without `-c`  → read with the Read tool;
#   - ...| head -N / tail -N with N>20  → flooding through a pipe.
# NOT a block: stdout redirected (`>`,`>>`,`&>`; `2>` does NOT count — it's
#   stderr), piped into a processor (`| jq`,`| python`…), a small head/tail
#   reducer in a pipe, `head -c`, a heredoc.
# Escape hatch: add `# show-raw` to the command (raw output is genuinely
# needed).
#
# Render-time vars: ${USER_LANG} (en|ru, default en).

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$cmd" ] && exit 0
case "$cmd" in *"# show-raw"*) exit 0 ;; esac

USER_LANG="${USER_LANG:-en}"

block() {
  case "$USER_LANG" in
    ru)
      echo "🚫 I24/H11 — сырой вывод в окно: $1" >&2
      echo "Сверни: редирект шума в файл (>/tmp/x.log 2>&1) + печать только итога (счётчик/grep -c/одна строка), либо читай файл Read-инструментом." >&2
      echo "Если сырьё реально нужно (диагностика ошибки / пользователь просит) — добавь в команду '# show-raw'." >&2
      ;;
    *)
      echo "🚫 I24/H11 — raw output to the window: $1" >&2
      echo "Collapse it: redirect the noise to a file (>/tmp/x.log 2>&1) + print only the summary (counter / grep -c / one line), or read the file with the Read tool." >&2
      echo "If raw output is genuinely needed (diagnosing an error / the user asks) — add '# show-raw' to the command." >&2
      ;;
  esac
  exit 2
}

redir_stdout() { printf '%s' "$1" | grep -qE '(^|[[:space:]])(1?>>?|&>>?)'; }
has_grep_reducer() { printf '%s' "$1" | grep -qE '(^|[[:space:]])-[A-Za-z]*[clq]'; }

norm=$(printf '%s' "$cmd" | sed -E 's/&&/;/g; s/\|\|/;/g' | tr '\n' ';')

IFS=';' read -ra SEGS <<< "$norm"
for seg in "${SEGS[@]}"; do
  [ -z "${seg// /}" ] && continue
  laststage=${seg##*|}                 # the part after the last pipe = writes to terminal
  seg_has_pipe=0; [ "$seg" != "$laststage" ] && seg_has_pipe=1
  redir_stdout "$laststage" && continue # stdout redirected to a file/device → not the window
  s="${laststage#"${laststage%%[![:space:]]*}"}"

  case "$s" in
    cat\ *|cat)
      case "$s" in *"<<"*) : ;; *) block "cat файла в окно (используй Read-инструмент)";; esac ;;
    sed\ -n*)   block "sed -n печать в окно (Read с offset/limit)" ;;
    less\ *|more\ *) block "less/more в окно (Read-инструмент)" ;;
    head\ *|tail\ *)
      case "$s" in
        *"-c"*) : ;;   # byte reduction — ok
        *)
          n=$(printf '%s' "$s" | grep -oE '\-n?[[:space:]]*[0-9]+' | grep -oE '[0-9]+' | head -1)
          if [ "$seg_has_pipe" = 1 ]; then
            [ -n "$n" ] && [ "$n" -gt 20 ] && block "| ${s} (>20 строк в окно)"
          else
            block "tail/head файла в окно (Read-инструмент или сверни до счётчика)"
          fi ;;
      esac ;;
    git\ diff*|git\ log*|git\ show*)
      case "$s" in
        *--stat*|*--shortstat*|*--oneline*|*--name-only*|*--name-status*) : ;;
        *) block "git diff/log/show сырьём в окно (--stat/--oneline, | head -20, или > файл)";;
      esac ;;
    grep\ -r*|grep\ -R*|grep\ *-r*|grep\ *-R*)
      has_grep_reducer "$s" || block "grep -r без -c/-l в окно (добавь -c/-l, | head, или > файл)" ;;
    find\ *)
      case "$s" in
        *-exec*|*-delete*|*-print0*) : ;;
        *) block "find листингом в окно (сверни | wc -l, | head -20, или > файл)";;
      esac ;;
  esac
done

exit 0
