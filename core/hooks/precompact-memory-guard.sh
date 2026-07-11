#!/usr/bin/env bash
# H19 — hook: precompact-memory-guard — memory safety at the compaction boundary (I26/FR-7).
# Event: PreCompact (fires before a manual ${COMPACT_CMD} AND before auto-compaction).
#
# Pain: rule I26 ("facts → memory immediately") leans on in-the-moment discipline,
# and the single highest-loss moment is context compaction — the summary can drop
# facts that were never written down. STC used to assume the harness had NO
# PreCompact hook (FR-7) and relied only on POST-compact recovery (H06, after the
# fact). This hook restores the PROACTIVE reminder: before the summary is built,
# rotate memory so nothing is lost.
#
# Reach: on a MANUAL compact an agent turn is available → act on this before running
# ${COMPACT_CMD}. On a SILENT auto-compact there may be no turn before the summary;
# there the real defense stays continuous I26-live writing + H06 post-compact recovery.
# This hook is the belt; live writing is the suspenders.
#
# Render-time vars: ${USER_LANG} (en|ru, default en).

cat >/dev/null            # drain stdin (PreCompact payload unused; the directive is static)
USER_LANG="${USER_LANG:-en}"

case "$USER_LANG" in
  ru)
    echo "=== 🔻 СЕЙЧАС ПРОИЗОЙДЁТ СЖАТИЕ КОНТЕКСТА (H19/I26) ==="
    echo "ДО того как саммари заменит контекст — сохрани память по behavior.md § Memory rotation (I26):"
    echo "  1. Обнови STATE/CHANGELOG в project_<name>.md (сделано / в работе / next step / новые факты и решения)."
    echo "  2. Любой важный факт (ID/конфиг/решение/результат), которого ещё нет в файле памяти → запиши СЕЙЧАС."
    echo "  3. Ротируй устаревший хвост STATE/CHANGELOG в archive/."
    echo "Сжатие не должно ничего потерять."
    ;;
  *)
    echo "=== 🔻 CONTEXT COMPACTION IS ABOUT TO HAPPEN (H19/I26) ==="
    echo "BEFORE the summary replaces context — save memory per behavior.md § Memory rotation (I26):"
    echo "  1. Update STATE/CHANGELOG in project_<name>.md (done / in-progress / next step / new facts & decisions)."
    echo "  2. Any important fact (ID/config/decision/result) not yet in a memory file → record it NOW."
    echo "  3. Rotate the stale STATE/CHANGELOG tail into archive/."
    echo "Compaction must not lose anything."
    ;;
esac
exit 0
