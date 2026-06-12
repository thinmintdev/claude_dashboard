"""SnapshotBuilder — orchestrates collectors into one Snapshot.

Collector failures degrade to last-good data + an entry in snapshot.errors;
nothing here may raise out of build().
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from devdash.collectors import agents as agents_c
from devdash.collectors import gitrepos as git_c
from devdash.collectors import quota as quota_c
from devdash.collectors import tmuxmap as tmux_c
from devdash.collectors.sessions import SessionCollector
from devdash import boarddoc, hub
from devdash.config import Config
from devdash.models import CollectorError, PrInfo, Snapshot


class SnapshotBuilder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sessions = SessionCollector(cfg.projects_dir, cfg.model_windows,
                                         cfg.liveness_hours)
        self.sessions.load_state(cfg.cache_dir / "state.json")
        self.repos = git_c.discover(cfg.repo_roots, cfg.repos)
        self.pr_cache: dict[str, list[PrInfo]] = {}
        self._last: Snapshot = Snapshot()
        self._last_git: list = []

    # slow path, driven by the app on gh_poll_secs cadence (worker thread)
    def refresh_prs(self) -> None:
        for repo in self.repos:
            self.pr_cache[str(repo)] = git_c.fetch_prs(repo)

    def _todos_for(self, sid: str) -> list[dict]:
        for f in self.cfg.todos_dir.glob(f"{sid}*.json"):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return []

    def build(self, include_git: bool = True) -> Snapshot:
        errors: list[CollectorError] = []

        def guard(name, fn, fallback):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 — degrade, never crash
                errors.append(CollectorError(collector=name, message=str(exc),
                                             at=time.time()))
                return fallback

        sess = guard("sessions", self.sessions.collect, self._last.sessions)
        quota = guard("quota", lambda: quota_c.collect(
            self.sessions, self.cfg.cap_5h_tokens, self.cfg.cap_week_tokens),
            self._last.quota)
        agents = guard("agents", lambda: agents_c.collect(
            self.sessions, self.cfg.teams_dir), self._last.agents)
        tmux_map = guard("tmux", tmux_c.collect, {})
        if include_git:
            self._last_git = guard("git", lambda: git_c.collect(
                self.repos, self.pr_cache), self._last_git)

        unread = guard("hub", hub.unread_counts, {})
        pad_tail = guard("hub", hub.pad_tail, "")

        sidechains = self.sessions.sidechain_ids()
        sess = [s for s in sess if s.id not in sidechains]
        for s in sess:
            s.tmux_target = tmux_map.get(s.id, "")
            s.todos = self._todos_for(s.id)
            s.unread = unread.get(s.id, 0)
        for a in agents:
            a.tmux_target = tmux_map.get(a.session_id, "")

        snap = Snapshot(quota=quota, sessions=sess, agents=agents,
                        repos=self._last_git, errors=errors,
                        scratchpad_tail=pad_tail)
        self._last = snap
        guard("cache", lambda: self.sessions.save_state(
            self.cfg.cache_dir / "state.json"), None)
        guard("board", lambda: boarddoc.write(snap), None)
        return snap
