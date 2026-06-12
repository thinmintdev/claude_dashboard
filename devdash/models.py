"""Snapshot data model — the contract between collectors and every front-end.

Phase 2's web backend serves exactly `Snapshot.to_json()`; keep this module
free of any UI or filesystem imports.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class QuotaWindow:
    pct_5h: float = 0.0          # 0-100, share of 5h-window token cap burned
    pct_week: float = 0.0        # 0-100, share of weekly cap burned
    burn_tokens_per_hr: int = 0  # trailing-hour token burn
    trend: str = "flat"          # "up" | "down" | "flat" (vs previous hour)
    tokens_5h: int = 0
    tokens_week: int = 0


@dataclass
class SessionInfo:
    id: str
    cwd: str = ""
    model: str = ""
    speed_mode: str = "standard"
    ctx_pct: float = 0.0
    tokens_turn: int = 0
    tokens_total: int = 0
    idle_secs: int = 0
    status: str = "stale"        # "active" | "idle" | "stale"
    tmux_target: str = ""        # "session:window.pane" or "" if unmapped
    last_text: str = ""
    todos: list[dict] = field(default_factory=list)
    git_branch: str = ""
    version: str = ""
    unread: int = 0              # hub a2a messages waiting for this session


@dataclass
class AgentNode:
    session_id: str
    label: str
    kind: str = "main"           # "main" | "subagent" | "team_member"
    parent_id: str = ""          # "" for roots
    status: str = "running"      # "running" | "done" | "failed"
    tmux_target: str = ""


@dataclass
class PrInfo:
    number: int
    title: str = ""
    state: str = "open"
    checks: str = "pending"      # "passing" | "failing" | "pending"


@dataclass
class Claim:
    sid: str
    intent: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class RepoInfo:
    path: str
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    dirty_n: int = 0
    untracked_n: int = 0
    prs: list[PrInfo] = field(default_factory=list)
    wip_claims: list[Claim] = field(default_factory=list)
    # hub branch marks: {branch: {status, note, sid, ts}}
    branch_marks: dict[str, dict] = field(default_factory=dict)


@dataclass
class CollectorError:
    collector: str
    message: str
    at: float = 0.0


@dataclass
class Snapshot:
    quota: QuotaWindow = field(default_factory=QuotaWindow)
    sessions: list[SessionInfo] = field(default_factory=list)
    agents: list[AgentNode] = field(default_factory=list)
    repos: list[RepoInfo] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)
    errors: list[CollectorError] = field(default_factory=list)
    scratchpad_tail: str = ""    # hub global scratchpad, last ~1200 chars

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> "Snapshot":
        d = json.loads(raw)
        return cls(
            quota=QuotaWindow(**d["quota"]),
            sessions=[
                SessionInfo(**s) for s in d["sessions"]
            ],
            agents=[AgentNode(**a) for a in d["agents"]],
            repos=[
                RepoInfo(
                    **{
                        **r,
                        "prs": [PrInfo(**p) for p in r["prs"]],
                        "wip_claims": [Claim(**c) for c in r["wip_claims"]],
                    }
                )
                for r in d["repos"]
            ],
            generated_at=d["generated_at"],
            errors=[CollectorError(**e) for e in d["errors"]],
            scratchpad_tail=d.get("scratchpad_tail", ""),
        )
