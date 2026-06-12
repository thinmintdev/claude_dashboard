"""Agent-tree collector — main sessions as roots, sidechains and team
members as children.

Sidechain transcripts don't record their parent session id, so parentage is
a heuristic: a sidechain hangs off the most recently active main session
sharing its cwd. Good enough for a glance board; flagged in the spec.
"""

from __future__ import annotations

import time
from pathlib import Path

from devdash.collectors.sessions import SessionCollector
from devdash.models import AgentNode


def _label(cwd: str, sid: str) -> str:
    tail = Path(cwd).name or cwd if cwd else "?"
    return f"{sid[:8]} {tail}"


def collect(sessions: SessionCollector, teams_dir: Path) -> list[AgentNode]:
    mains: list = []
    subs: list = []
    for st in sessions.files.values():
        if not st.last_event_ts:
            continue
        (subs if st.is_sidechain else mains).append(st)

    nodes: list[AgentNode] = []
    for st in sorted(mains, key=lambda s: -s.last_event_ts):
        nodes.append(AgentNode(
            session_id=st.session_id,
            label=_label(st.cwd, st.session_id),
            kind="main",
            status="running" if time.time() - st.last_event_ts < 3600 else "done",
        ))
    for st in subs:
        parent = next(
            (m for m in sorted(mains, key=lambda s: -s.last_event_ts)
             if m.cwd == st.cwd), None)
        nodes.append(AgentNode(
            session_id=st.session_id,
            label=_label(st.cwd, st.session_id),
            kind="subagent",
            parent_id=parent.session_id if parent else "",
            status="running" if time.time() - st.last_event_ts < 600 else "done",
        ))

    # teams: each team dir is a root; inbox files name the members
    try:
        team_dirs = sorted(teams_dir.iterdir())
    except OSError:
        team_dirs = []
    cutoff = time.time() - 24 * 3600
    for td in team_dirs:
        inboxes = td / "inboxes"
        if not inboxes.is_dir():
            continue
        members = sorted(inboxes.glob("*.json"))
        if not members:
            continue
        try:
            fresh = max(m.stat().st_mtime for m in members) >= cutoff
        except OSError:
            fresh = False
        if not fresh:
            continue
        team_id = f"team-{td.name[:8]}"
        nodes.append(AgentNode(session_id=team_id,
                               label=f"team {td.name[:8]} ({len(members)})",
                               kind="main", status="running"))
        for m in members:
            nodes.append(AgentNode(session_id=f"{team_id}/{m.stem}",
                                   label=m.stem, kind="team_member",
                                   parent_id=team_id, status="running"))
    return nodes
