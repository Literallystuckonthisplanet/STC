import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core" / "scripts"))

import disk_tidy as tidy  # noqa: E402


DAY = 86400
GB = 1024 ** 3


def _wt(**overrides):
    base = dict(
        path=Path("/w/repo-feature"),
        is_main=False,
        merged=True,
        tracked_changes=0,
        untracked=0,
        age_days=30,
        size_bytes=GB,
    )
    base.update(overrides)
    return tidy.Worktree(**base)


def test_merged_clean_old_worktree_is_removable():
    assert tidy.worktree_verdict(_wt(), min_age_days=7) == (True, "влита, без правок")


def test_main_checkout_is_never_removable():
    removable, _ = tidy.worktree_verdict(_wt(is_main=True), min_age_days=7)
    assert removable is False


def test_unmerged_worktree_is_kept():
    removable, reason = tidy.worktree_verdict(_wt(merged=False), min_age_days=7)
    assert removable is False
    assert "не влита" in reason


def test_tracked_changes_keep_the_worktree():
    removable, reason = tidy.worktree_verdict(_wt(tracked_changes=2), min_age_days=7)
    assert removable is False
    assert "правки" in reason


def test_untracked_files_keep_the_worktree():
    """An untracked note in a merged worktree was real work on 05.10.2026."""
    removable, reason = tidy.worktree_verdict(_wt(untracked=1), min_age_days=7)
    assert removable is False
    assert "новые файлы" in reason


def test_recently_touched_worktree_is_kept():
    removable, reason = tidy.worktree_verdict(_wt(age_days=2), min_age_days=7)
    assert removable is False
    assert "недавно" in reason


def test_build_dir_is_stale_only_after_the_age_limit():
    now = 100 * DAY
    assert tidy.build_dir_stale(mtime=now - 8 * DAY, now=now, min_age_days=7) is True
    assert tidy.build_dir_stale(mtime=now - 1 * DAY, now=now, min_age_days=7) is False


def test_build_dirs_are_kept_while_a_dev_server_runs():
    now = 100 * DAY
    assert tidy.build_dir_stale(
        mtime=now - 30 * DAY, now=now, min_age_days=7, dev_server_running=True
    ) is False


def test_nudge_fires_only_below_threshold():
    assert tidy.needs_nudge(free_bytes=40 * GB, threshold_gb=50) is True
    assert tidy.needs_nudge(free_bytes=60 * GB, threshold_gb=50) is False


def test_docker_reclaimable_parses_system_df_rows():
    rows = [
        '{"Type":"Images","Reclaimable":"8.76GB (33%)","Size":"26.48GB"}',
        '{"Type":"Containers","Reclaimable":"53.25kB (46%)","Size":"114.7kB"}',
        '{"Type":"Local Volumes","Reclaimable":"1.134GB (27%)","Size":"4.062GB"}',
        '{"Type":"Build Cache","Reclaimable":"9.695GB","Size":"36.97GB"}',
    ]
    parsed = tidy.parse_docker_df(rows)
    # Volumes may hold test databases: never counted, never pruned.
    assert set(parsed) == {"Images", "Build Cache"}
    assert round(parsed["Images"] / 1e9, 2) == 8.76
    # Build cache with no active builds is reclaimable in full.
    assert round(parsed["Build Cache"] / 1e9, 2) == 36.97


def test_parse_size_handles_docker_units():
    assert tidy.parse_size("1.5GB") == 1.5e9
    assert tidy.parse_size("53.25kB") == 53250
    assert tidy.parse_size("0B") == 0
    assert tidy.parse_size("garbage") == 0


def test_human_size_is_readable():
    assert tidy.human(52 * GB) == "52 ГБ"
    assert tidy.human(300 * 1024 ** 2) == "300 МБ"
