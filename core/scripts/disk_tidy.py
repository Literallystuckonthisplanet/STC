#!/usr/bin/env python3
"""Show what can be safely freed on the local disk, and free it on request.

Born from the 05.10.2026 audit: the disk was 93% full, mostly with leftovers
of agent work — Docker build cache, one test image rebuilt under a new name on
every run, package caches, merged worktrees, stale `.next` folders.

Default run only measures and prints a plan. `--apply` removes exactly the
plan's categories and nothing else:
- Docker: build cache and images older than 72 h with no container (image age
  is creation time, not last use; local-only images are rebuilt, not pulled);
- package caches through the tools' own clean commands (npm, uv, pip, pnpm);
- worktrees merged into main/master, with no edits, no new files, no ignored
  files beyond rebuildable folders, no rebase/bisect in progress, no process
  working inside, and no git activity for N days;
- `.next` folders untouched for N days while no Next dev server runs.
Never touched: Docker volumes (test databases), models (Ollama, Hugging Face,
Whisper), transcripts, main checkouts. Heavy commands run with background
priority so the interface keeps the processor and the disk.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

HOME = Path.home()
DEFAULT_REPO_ROOTS = (HOME / "Work" / "projects", HOME / "Work")
DEFAULT_MIN_AGE_DAYS = 7
BACKGROUND = ["taskpolicy", "-b"] if shutil.which("taskpolicy") else []
# Package caches: (tool, cleanup command, folders measured for the estimate).
CACHES = (
    ("npm", ["npm", "cache", "clean", "--force"], [HOME / ".npm" / "_cacache"]),
    ("uv", ["uv", "cache", "clean"], [HOME / ".cache" / "uv"]),
    ("pip", ["pip3", "cache", "purge"], [HOME / "Library" / "Caches" / "pip"]),
    ("pnpm", ["pnpm", "store", "prune"], [HOME / "Library" / "pnpm" / "store"]),
)
DOCKER_KEPT_TYPES = {"Images", "Build Cache"}
DOCKER_AGE = "until=72h"
WORTH_BYTES = 50 * 1024 ** 2  # smaller items are noise in the report
# Ignored folders a worktree may lose: each one is rebuilt by a command.
REBUILDABLE = {
    "node_modules", ".next", ".venv", "venv", "__pycache__", "dist", "build",
    ".turbo", ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
    "graphify-out", ".DS_Store",
}
IN_PROGRESS = ("rebase-merge", "rebase-apply", "BISECT_LOG", "MERGE_HEAD", "CHERRY_PICK_HEAD")


@dataclass(frozen=True)
class Worktree:
    path: Path
    is_main: bool
    merged: bool
    tracked_changes: int
    untracked: int
    age_days: int
    size_bytes: int
    status_ok: bool = True
    ignored_blockers: tuple[str, ...] = ()
    busy: str = ""


def worktree_verdict(wt: Worktree, min_age_days: int) -> tuple[bool, str]:
    if wt.is_main:
        return False, "основная копия"
    if not wt.status_ok:
        return False, "не удалось прочитать состояние"
    if wt.busy:
        return False, wt.busy
    if not wt.merged:
        return False, "не влита"
    if wt.tracked_changes:
        return False, "есть правки"
    if wt.untracked:
        return False, "есть новые файлы"
    if wt.ignored_blockers:
        return False, "есть скрытые файлы: " + ", ".join(wt.ignored_blockers[:3])
    if wt.age_days < min_age_days:
        return False, "недавно трогали"
    return True, "влита, без правок"


def ignored_blockers(status_lines: list[str]) -> list[str]:
    """Ignored entries that `git worktree remove` would lose and nobody rebuilds."""
    blockers = []
    for line in status_lines:
        if not line.startswith("!! "):
            continue
        entry = line[3:].rstrip("/")
        parts = entry.split("/")
        # The ignored folder itself, or a top-level output folder; a nested
        # `config/build/secrets.json` is not a build output.
        if parts[0] not in REBUILDABLE and parts[-1] not in REBUILDABLE:
            blockers.append(entry)
    return blockers


def build_dir_stale(
    mtime: float, now: float, min_age_days: int, dev_server_running: bool = False
) -> bool:
    if dev_server_running:
        return False
    return now - mtime >= min_age_days * 86400


def safe_build_dir(candidate: Path, worktree: Path) -> bool:
    """Only a real `.next` folder inside the worktree, never inside node_modules."""
    if candidate.is_symlink() or not candidate.is_dir():
        return False
    try:
        relative = candidate.resolve().relative_to(worktree.resolve())
    except ValueError:
        return False
    return "node_modules" not in relative.parts


def needs_nudge(free_bytes: int, threshold_gb: int) -> bool:
    return free_bytes < threshold_gb * 1024 ** 3


_UNITS = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def parse_size(text: str) -> float:
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*([kKMGT]?B)", text or "")
    if not match:
        return 0
    return float(match.group(1)) * _UNITS[match.group(2)]


def parse_docker_df(rows: list[str]) -> dict[str, float]:
    """Reclaimable bytes per Docker type; volumes are excluded on purpose.

    An upper estimate: the age filter of `--apply` may keep part of it.
    """
    result: dict[str, float] = {}
    for row in rows:
        try:
            item = json.loads(row)
        except json.JSONDecodeError:
            continue
        kind = item.get("Type")
        if kind not in DOCKER_KEPT_TYPES:
            continue
        # An inactive build cache is reclaimable in full, though Docker reports
        # only the part older than its own policy.
        field = "Size" if kind == "Build Cache" else "Reclaimable"
        result[kind] = parse_size(item.get(field, ""))
    return result


def human(size: float) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.0f} ГБ"
    return f"{size / 1024 ** 2:.0f} МБ"


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(cmd, 125, "", str(error))


def du_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    out = _run(BACKGROUND + ["du", "-sk", str(path)], timeout=600).stdout.split()
    return int(out[0]) * 1024 if out and out[0].isdigit() else 0


def free_bytes(path: Path = Path("/System/Volumes/Data")) -> int:
    target = path if path.exists() else Path("/")
    return shutil.disk_usage(target).free


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(repo), *args], timeout=timeout)


def _main_branch(repo: Path) -> str | None:
    for name in ("main", "master"):
        ref = f"refs/heads/{name}"
        if _git(repo, "rev-parse", "--verify", "-q", ref).returncode == 0:
            return ref
    return None


def find_repos(roots: tuple[Path, ...]) -> list[Path]:
    """Main checkouts (a `.git` directory, not a file) directly under the roots."""
    repos = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if (child / ".git").is_dir():
                repos.append(child)
    return repos


def process_cwds() -> set[Path] | None:
    """Working folders of all processes; None when they cannot be read."""
    probe = _run(["lsof", "-a", "-d", "cwd", "-Fn"], timeout=30)
    cwds = {Path(line[1:]).resolve() for line in probe.stdout.splitlines() if line.startswith("n/")}
    # This process itself has a working folder: an empty set means lsof failed.
    return cwds if probe.returncode in (0, 1) and cwds else None


def _last_activity(path: Path, gitdir: Path) -> float:
    """Latest of git's own bookkeeping and the last commit: folder mtime lies."""
    stamps = [path.stat().st_mtime]
    for name in ("HEAD", "index", "logs/HEAD"):
        file = gitdir / name
        if file.exists():
            stamps.append(file.stat().st_mtime)
    commit = _git(path, "log", "-1", "--format=%ct").stdout.strip()
    if commit.isdigit():
        stamps.append(float(commit))
    return max(stamps)


def inspect_worktree(
    path: Path, repo: Path, main: str | None, cwds: set[Path] | None = None
) -> Worktree:
    real = path.resolve()
    status = _git(path, "status", "--porcelain", "--ignored", "--untracked-files=all", timeout=180)
    lines = status.stdout.splitlines()
    gitdir_raw = _git(path, "rev-parse", "--path-format=absolute", "--git-dir").stdout.strip()
    gitdir = Path(gitdir_raw) if gitdir_raw else path / ".git"
    busy = ""
    if any((gitdir / marker).exists() for marker in IN_PROGRESS):
        busy = "идёт rebase/merge/bisect"
    elif cwds is None:
        busy = "не удалось проверить, кто работает в копии"
    elif any(cwd == real or real in cwd.parents for cwd in cwds):
        busy = "в копии сейчас работает программа"
    merged = bool(main) and _git(path, "merge-base", "--is-ancestor", "HEAD", main).returncode == 0
    return Worktree(
        path=path,
        is_main=path.resolve() == repo.resolve(),
        merged=merged,
        tracked_changes=sum(1 for line in lines if line[:2] not in ("??", "!!")),
        untracked=sum(1 for line in lines if line.startswith("??")),
        age_days=int((time.time() - _last_activity(path, gitdir)) // 86400),
        size_bytes=0,
        status_ok=status.returncode == 0 and bool(gitdir_raw),
        ignored_blockers=tuple(ignored_blockers(lines)),
        busy=busy,
    )


def scan_worktrees(repos: list[Path], min_age_days: int, measure: bool = True) -> list[Worktree]:
    cwds = process_cwds()
    found = []
    for repo in repos:
        main = _main_branch(repo)
        listing = _git(repo, "worktree", "list", "--porcelain").stdout
        paths = [Path(line[9:]) for line in listing.splitlines() if line.startswith("worktree ")]
        found += [inspect_worktree(path, repo, main, cwds) for path in paths if path.is_dir()]
    if not measure:
        return found
    return [
        replace(wt, size_bytes=du_bytes(wt.path))
        if worktree_verdict(wt, min_age_days)[0] else wt
        for wt in found
    ]


def dev_server_from_returncode(code: int) -> bool:
    """pgrep: 0 found, 1 none; anything else is an error → assume running."""
    return code != 1


def dev_server_running() -> bool:
    return dev_server_from_returncode(_run(["pgrep", "-f", r"next (dev|start)|next-server"]).returncode)


def find_build_dirs(
    worktrees: list[Worktree], removable: list[Worktree], min_age_days: int
) -> list[tuple[Path, int]]:
    running = dev_server_running()
    now = time.time()
    leaving = {wt.path for wt in removable}
    stale = []
    for wt in worktrees:
        if wt.path in leaving:  # goes away with its worktree; no double count
            continue
        for candidate in (wt.path / ".next", *wt.path.glob("*/.next")):
            if safe_build_dir(candidate, wt.path) and build_dir_stale(
                candidate.stat().st_mtime, now, min_age_days, running
            ):
                stale.append((candidate, du_bytes(candidate)))
    return stale


def docker_reclaimable() -> dict[str, float]:
    if not shutil.which("docker"):
        return {}
    probe = _run(["docker", "system", "df", "--format", "{{json .}}"], timeout=20)
    if probe.returncode != 0:
        return {}
    return parse_docker_df(probe.stdout.splitlines())


def build_plan(roots: tuple[Path, ...], min_age_days: int) -> dict:
    worktrees = scan_worktrees(find_repos(roots), min_age_days)
    removable = [wt for wt in worktrees if worktree_verdict(wt, min_age_days)[0]]
    caches = [
        (name, cmd, sum(du_bytes(p) for p in paths))
        for name, cmd, paths in CACHES if shutil.which(cmd[0])
    ]
    return {
        "free": free_bytes(),
        "docker": docker_reclaimable(),
        "caches": caches,
        "worktrees": removable,
        "builds": find_build_dirs(worktrees, removable, min_age_days),
        "min_age_days": min_age_days,
    }


def render(plan: dict) -> str:
    lines = [f"Свободно на диске: {human(plan['free'])}", ""]
    total = 0.0
    docker = sum(plan["docker"].values())
    if docker >= WORTH_BYTES:
        total += docker
        lines.append(f"- Docker, кэш сборок и образы старше 3 дней без контейнеров: до ~{human(docker)}")
    for name, _, size in plan["caches"]:
        if size >= WORTH_BYTES:
            total += size
            lines.append(f"- кэш {name}: ~{human(size)}")
    for wt in plan["worktrees"]:
        total += wt.size_bytes
        lines.append(f"- копия работы {wt.path} (влита, без правок): ~{human(wt.size_bytes)}")
    for path, size in plan["builds"]:
        total += size
        lines.append(f"- папка сборки {path}: ~{human(size)}")
    if total == 0:
        lines.append("Безопасно освобождать нечего.")
    else:
        lines += ["", f"Итого можно освободить: до ~{human(total)}.",
                  "Тома Docker, модели, переписки и невлитые копии не трогаются."]
    return "\n".join(lines)


def apply(plan: dict) -> tuple[list[str], list[str]]:
    done, failed = [], []

    def record(label: str, ok: bool) -> None:
        (done if ok else failed).append(label)

    if sum(plan["docker"].values()) >= WORTH_BYTES:
        cache = _run(BACKGROUND + ["docker", "builder", "prune", "-a", "-f",
                                   "--filter", DOCKER_AGE], timeout=1800)
        images = _run(BACKGROUND + ["docker", "image", "prune", "-a", "-f",
                                    "--filter", DOCKER_AGE], timeout=1800)
        record("Docker", cache.returncode == 0 and images.returncode == 0)
    for name, cmd, size in plan["caches"]:
        if size >= WORTH_BYTES:
            record(f"кэш {name}", _run(BACKGROUND + cmd, timeout=1800).returncode == 0)
    cwds = process_cwds()
    for wt in plan["worktrees"]:
        common = _git(wt.path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        if not common:
            record(f"копия {wt.path.name}", False)
            continue
        repo = Path(common).parent
        # Re-check right before removal: another session may have started work.
        fresh = inspect_worktree(wt.path, repo, _main_branch(repo), cwds)
        if not worktree_verdict(fresh, plan["min_age_days"])[0]:
            continue
        removed = _git(repo, "worktree", "remove", "--force", str(wt.path)).returncode == 0
        record(f"копия {wt.path.name}", removed)
    for path, _ in plan["builds"]:
        if dev_server_running() or not path.is_dir() or path.is_symlink():
            continue
        shutil.rmtree(path, ignore_errors=True)
        record(f"сборка {path.parent.name}", not path.exists())
    return done, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="free what the plan lists")
    parser.add_argument("--min-age-days", type=int, default=DEFAULT_MIN_AGE_DAYS)
    parser.add_argument("--root", action="append", type=Path,
                        help="folder whose git checkouts are scanned (repeatable)")
    parser.add_argument("--nudge", type=int, metavar="GB",
                        help="print one warning line if free space is below GB, then exit")
    args = parser.parse_args(argv)

    if args.nudge is not None:
        free = free_bytes()
        if needs_nudge(free, args.nudge):
            print(f"{human(free)} < {args.nudge} ГБ")
        return 0

    roots = tuple(args.root) if args.root else DEFAULT_REPO_ROOTS
    before = free_bytes()
    plan = build_plan(roots, args.min_age_days)
    print(render(plan))
    if args.apply:
        done, failed = apply(plan)
        print(f"\nОчищено: {', '.join(done) or 'ничего'}. "
              f"Свободно было {human(before)}, стало {human(free_bytes())}.")
        if failed:
            print(f"Не получилось: {', '.join(failed)}.")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
