"""Config loading — ~/.claude/dev-dash/config.toml, everything optional."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path.home() / ".claude" / "dev-dash" / "config.toml"


@dataclass
class Config:
    projects_dir: Path = Path.home() / ".claude" / "projects"
    teams_dir: Path = Path.home() / ".claude" / "teams"
    todos_dir: Path = Path.home() / ".claude" / "todos"
    cache_dir: Path = Path.home() / ".cache" / "dev-dash"
    repo_roots: list[Path] = field(default_factory=lambda: [Path.home() / "dev"])
    repos: list[Path] = field(default_factory=list)   # explicit additions
    liveness_hours: float = 4.0
    # token caps the quota bars are drawn against — tune to your plan
    cap_5h_tokens: int = 8_000_000
    cap_week_tokens: int = 150_000_000
    model_windows: dict[str, int] = field(
        default_factory=lambda: {"default": 200_000})
    gh_poll_secs: int = 60
    git_poll_secs: int = 10


def load(path: Path = CONFIG_PATH) -> Config:
    cfg = Config()
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return cfg
    for key in ("liveness_hours", "cap_5h_tokens", "cap_week_tokens",
                "gh_poll_secs", "git_poll_secs"):
        if key in data:
            setattr(cfg, key, data[key])
    for key in ("projects_dir", "teams_dir", "todos_dir", "cache_dir"):
        if key in data:
            setattr(cfg, key, Path(data[key]).expanduser())
    if "repo_roots" in data:
        cfg.repo_roots = [Path(p).expanduser() for p in data["repo_roots"]]
    if "repos" in data:
        cfg.repos = [Path(p).expanduser() for p in data["repos"]]
    if "model_windows" in data:
        cfg.model_windows.update(data["model_windows"])
    return cfg
