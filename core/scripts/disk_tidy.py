#!/usr/bin/env python3
"""Show what can be safely freed on the local disk, and free it on request.

Born from the 05.10.2026 audit: the disk was 93% full, mostly with leftovers
of agent work — Docker build cache, one test image rebuilt under a new name on
every run, package caches, merged worktrees, stale `.next` folders.

Default run only measures and prints a plan. `--apply` removes exactly the
plan's categories and nothing else. Never touched: Docker volumes (test
databases), models (Ollama, Hugging Face, Whisper), transcripts, unmerged or
dirty worktrees, anything with untracked files. Every heavy command runs with
background priority so the interface keeps the processor and the disk.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
DEFAULT_REPO_ROOTS = (HOME / "Work" / "projects", HOME / "Work")
DEFAULT_THRESHOLD_GB = 50
DEFAULT_MIN_AGE_DAYS = 7
BACKGROUND = ["taskpolicy", "-b"] if shutil.which("taskpolicy") else []
# Package caches: (tool, cleanup command, folders measured for the estimate).
CACHES = (
    ("npm", ["npm", "cache", "clean", "--force"], [HOME / ".npm" / "_cacache"]),
    ("uv", ["uv", "cache", "clean"], [HOME / ".cache" / "uv"]),
    ("pip", ["pip3", "cache", "purge"], [HOME / "Library" / "Caches" / "pip"]),
    ("pnpm", ["pnpm", "store", "prune"], [HOME / "Library" / "Caches" / "pnpm"]),
)
DOCKER_KEPT_TYPES = {"Images", "Build Cache"}
WORTH_BYTES = 50 * 1024 ** 2  # smaller items are noise in the report


@dataclass(frozen=True)
class Worktree:
    path: Path
    is_main: bool
    merged: bool
    tracked_changes: int
    untracked: int
    age_days: int
    size_bytes: int


def worktree_verdict(wt: Worktree, min_age_days: int) -> tuple[bool, str]:
    if wt.is_main:
        return False, "основная копия"
    if not wt.merged:
        return False, "не влита"
    if wt.tracked_changes:
        return False, "есть правки"
    if wt.untracked:
        return False, "есть новые файлы"
    if wt.age_days < min_age_days:
        return False, "недавно трогали"
    return True, "влита, без правок"


def build_dir_stale(
    mtime: float, now: float, min_age_days: int, dev_server_running: bool = False
) -> bool:
    if dev_server_running:
        return False
    return now - mtime >= min_age_days * 86400


def needs_nudge(free_bytes: int, threshold_gb: int) -> bool:
    return free_bytes < threshold_gb * 1024 ** 3


_UNITS = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def parse_size(text: str) -> float:
    match = re.match(r"\s*([\d.]+)\s*([kKMGT]?B)", text or "")
    if not match:
        return 0
    return float(match.group(1)) * _UNITS[match.group(2)]


def parse_docker_df(rows: list[str]) -> dict[str, float]:
    """Reclaimable bytes per Docker type; volumes are excluded on purpose."""
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


def _run(cmd: list[str], timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(cmd, 1, "", str(error))


def du_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    out = _run(BACKGROUND + ["du", "-sk", str(path)], timeout=600).stdout.split()
    return int(out[0]) * 1024 if out and out[0].isdigit() else 0


def free_bytes(path: Path = Path("/System/Volumes/Data")) -> int:
    target = path if path.exists() else Path("/")
    return shutil.disk_usage(target).free


def _git(repo: Path, *args: str) -> str:
    return _run(["git", "-C", str(repo), *args], timeout=30).stdout


def _main_branch(repo: Path) -> str | None:
    for name in ("main", "master"):
        if _run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", name]).returncode == 0:
            return name
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


def inspect_worktree(path: Path, repo: Path, main: str | None) -> Worktree:
    status = _git(path, "status", "--porcelain").splitlines()
    merged = bool(main) and _run(
        ["git", "-C", str(path), "merge-base", "--is-ancestor", "HEAD", main]
    ).returncode == 0
    return Worktree(
        path=path,
        is_main=path.resolve() == repo.resolve(),
        merged=merged,
        tracked_changes=sum(1 for line in status if not line.startswith("??")),
        untracked=sum(1 for line in status if line.startswith("??")),
        age_days=int((time.time() - path.stat().st_mtime) // 86400),
        size_bytes=0,
    )


def scan_worktrees(repos: list[Path], measure: bool = True) -> list[Worktree]:
    found = []
    for repo in repos:
        main = _main_branch(repo)
        listing = _git(repo, "worktree", "list", "--porcelain")
        paths = [Path(line[9:]) for line in listing.splitlines() if line.startswith("worktree ")]
        found += [inspect_worktree(path, repo, main) for path in paths if path.is_dir()]
    if not measure:
        return found
    return [
        Worktree(**{**wt.__dict__, "size_bytes": du_bytes(wt.path)})
        if worktree_verdict(wt, 0)[0] else wt
        for wt in found
    ]


def dev_server_running() -> bool:
    return _run(["pgrep", "-f", r"next (dev|start)|next-server"]).returncode == 0


def find_build_dirs(worktrees: list[Worktree], min_age_days: int) -> list[tuple[Path, int]]:
    running = dev_server_running()
    now = time.time()
    stale = []
    for wt in worktrees:
        for candidate in (wt.path / ".next", *wt.path.glob("*/.next")):
            if candidate.is_dir() and build_dir_stale(
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
    worktrees = scan_worktrees(find_repos(roots))
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
        "builds": find_build_dirs(worktrees, min_age_days),
    }


def render(plan: dict) -> str:
    lines = [f"Свободно на диске: {human(plan['free'])}", ""]
    total = 0.0
    docker = sum(plan["docker"].values())
    if docker >= WORTH_BYTES:
        total += docker
        lines.append(f"- Docker, кэш сборок и неиспользуемые образы: ~{human(docker)}")
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
        lines += ["", f"Итого можно освободить: ~{human(total)}.",
                  "Тома Docker, модели, переписки и невлитые копии не трогаются."]
    return "\n".join(lines)


def apply(plan: dict) -> list[str]:
    done = []
    if sum(plan["docker"].values()) >= WORTH_BYTES:
        _run(BACKGROUND + ["docker", "builder", "prune", "-a", "-f"], timeout=1800)
        # Images built in the last 3 days may be about to run in another session.
        _run(BACKGROUND + ["docker", "image", "prune", "-a", "-f",
                           "--filter", "until=72h"], timeout=1800)
        done.append("Docker")
    for name, cmd, size in plan["caches"]:
        if size >= WORTH_BYTES and _run(BACKGROUND + cmd, timeout=1800).returncode == 0:
            done.append(f"кэш {name}")
    for wt in plan["worktrees"]:
        common = _git(wt.path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        if not common:
            continue
        repo = Path(common).parent
        # Re-check right before removal: another session may have started work.
        if not worktree_verdict(inspect_worktree(wt.path, repo, _main_branch(repo)), 0)[0]:
            continue
        if _run(["git", "-C", str(repo), "worktree", "remove", str(wt.path)]).returncode == 0:
            done.append(f"копия {wt.path.name}")
    for path, _ in plan["builds"]:
        shutil.rmtree(path, ignore_errors=True)
        done.append(f"сборка {path.parent.name}")
    return done


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
        done = apply(plan)
        print(f"\nОчищено: {', '.join(done) or 'ничего'}. "
              f"Свободно было {human(before)}, стало {human(free_bytes())}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
