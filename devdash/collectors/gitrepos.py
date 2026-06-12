"""Git/PR/wip collector for watched repos.

Repo discovery happens once at startup (configured roots scanned one level
deep + explicit repos). Local git state is cheap; `gh pr list` is polled on
its own slower cadence by the app and merged in here via `pr_cache`.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from devdash.models import Claim, PrInfo, RepoInfo

_WIP_TTL = 6 * 3600


def _run(args: list[str], cwd: Path, timeout: int = 5) -> str:
    res = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                         timeout=timeout)
    return res.stdout.strip() if res.returncode == 0 else ""


def discover(roots: list[Path], explicit: list[Path],
             active_days: int = 14) -> list[Path]:
    repos = {p.resolve() for p in explicit if (p / ".git").exists()}
    cutoff = time.time() - active_days * 86400
    for root in roots:
        if (root / ".git").exists():
            repos.add(root.resolve())
        if not root.is_dir():
            continue
        for child in root.iterdir():
            git_dir = child / ".git"
            try:
                if git_dir.exists() and git_dir.stat().st_mtime >= cutoff:
                    repos.add(child.resolve())
            except OSError:
                continue
    return sorted(repos)


def _wip_claims(repo: Path) -> list[Claim]:
    f = repo / ".claude" / "wip.json"
    try:
        entries = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    now = time.time()
    out = []
    for e in entries:
        if not isinstance(e, dict) or now - e.get("ts", 0) > _WIP_TTL:
            continue
        out.append(Claim(sid=str(e.get("sid", "?")),
                         intent=str(e.get("intent", "")),
                         files=[str(x) for x in e.get("files", [])]))
    return out


def fetch_prs(repo: Path) -> list[PrInfo]:
    """Slow path — `gh pr list`. Called by the app on its own cadence."""
    raw = _run(["gh", "pr", "list", "--json",
                "number,title,statusCheckRollup"], cwd=repo, timeout=20)
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    prs = []
    for r in rows:
        checks = r.get("statusCheckRollup") or []
        states = {c.get("conclusion") or c.get("state") or "" for c in checks}
        if any(s in ("FAILURE", "ERROR") for s in states):
            status = "failing"
        elif states and states <= {"SUCCESS", "NEUTRAL", "SKIPPED", ""}:
            status = "passing"
        else:
            status = "pending"
        prs.append(PrInfo(number=r.get("number", 0),
                          title=r.get("title", "")[:60], checks=status))
    return prs


def collect_repo(repo: Path, pr_cache: dict[str, list[PrInfo]]) -> RepoInfo:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    ahead = behind = 0
    counts = _run(["git", "rev-list", "--left-right", "--count",
                   "@{upstream}...HEAD"], cwd=repo)
    if counts:
        try:
            behind, ahead = (int(x) for x in counts.split())
        except ValueError:
            pass
    dirty_n = untracked_n = 0
    for line in _run(["git", "status", "--porcelain"], cwd=repo).splitlines():
        if line.startswith("??"):
            untracked_n += 1
        elif line.strip():
            dirty_n += 1
    return RepoInfo(
        path=str(repo), branch=branch, ahead=ahead, behind=behind,
        dirty_n=dirty_n, untracked_n=untracked_n,
        prs=pr_cache.get(str(repo), []),
        wip_claims=_wip_claims(repo),
    )


def collect(repos: list[Path], pr_cache: dict[str, list[PrInfo]]) -> list[RepoInfo]:
    out = []
    for repo in repos:
        try:
            out.append(collect_repo(repo, pr_cache))
        except (OSError, subprocess.TimeoutExpired):
            continue
    # repos with something happening float to the top
    out.sort(key=lambda r: (not (r.dirty_n or r.untracked_n or r.prs
                                 or r.wip_claims or r.ahead), r.path))
    return out
