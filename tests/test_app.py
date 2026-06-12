"""Headless smoke tests — drive the TUI with Textual's Pilot against a
stubbed SnapshotBuilder. No tmux, no real session files."""

import pytest

from devdash.app import AgentTreePanel, DevDashApp, DrillIn, SessionsTable
from devdash.config import Config
from devdash.models import (AgentNode, QuotaWindow, RepoInfo, SessionInfo,
                            Snapshot)


class StubBuilder:
    cfg = Config(gh_poll_secs=9999, git_poll_secs=9999)

    def __init__(self):
        self.snap = Snapshot(
            quota=QuotaWindow(pct_5h=62.0, burn_tokens_per_hr=312_000,
                              trend="up"),
            sessions=[
                SessionInfo(id="aaaa1111", cwd="/home/halo", model="claude-fable-5",
                            ctx_pct=42.0, status="active", tokens_turn=89_000,
                            last_text="doing things",
                            todos=[{"content": "ship it", "status": "in_progress"}]),
                SessionInfo(id="bbbb2222", cwd="/home/halo/dev/hal0",
                            model="claude-opus-4-8", ctx_pct=87.0, status="idle"),
            ],
            agents=[
                AgentNode(session_id="aaaa1111", label="aaaa1111 halo"),
                AgentNode(session_id="sub1", label="sub explore",
                          kind="subagent", parent_id="aaaa1111"),
            ],
            repos=[RepoInfo(path="/home/halo/dev/hal0", branch="main",
                            dirty_n=2)],
        )

    def build(self, include_git=False):
        return self.snap

    def refresh_prs(self):
        pass


@pytest.mark.asyncio
async def test_board_renders_and_navigates():
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        table = app.query_one(SessionsTable)
        assert table.row_count == 2
        tree = app.query_one(AgentTreePanel)
        assert len(tree.root.children) == 1          # one root agent
        assert len(tree.root.children[0].children) == 1  # one subagent
        await pilot.press("j")                        # move cursor — no crash
        assert app.query_one(DrillIn).styles.display == "none"


@pytest.mark.asyncio
async def test_drill_in_and_escape():
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        await pilot.press("d")
        drill = app.query_one(DrillIn)
        assert drill.styles.display == "block"
        text = str(drill.render())
        assert "aaaa1111" in text
        assert "ship it" in text
        await pilot.press("escape")
        assert drill.styles.display == "none"


@pytest.mark.asyncio
async def test_jump_without_tmux_notifies_not_crashes(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        await pilot.press("enter")   # no tmux target mapped → warning toast
        await pilot.pause()


@pytest.mark.asyncio
async def test_kill_requires_confirmation(monkeypatch):
    killed = []
    from devdash import actions as actions_mod
    monkeypatch.setattr(actions_mod, "kill_session",
                        lambda t: killed.append(t) or "")
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        await pilot.press("x")            # confirm modal opens
        await pilot.press("n")            # decline
        assert killed == []
        await pilot.press("x")
        await pilot.press("y")            # confirm
        assert len(killed) == 1


@pytest.mark.asyncio
async def test_steer_modal_sends_text(monkeypatch):
    sent = []
    from devdash import actions as actions_mod
    monkeypatch.setattr(actions_mod, "steer",
                        lambda t, txt: sent.append((t, txt)) or "")
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        await pilot.press("s")
        for ch in "go":
            await pilot.press(ch)
        await pilot.press("enter")
        assert sent == [("", "go")]


@pytest.mark.asyncio
async def test_handoff_confirm_flow(monkeypatch):
    sent = []
    from devdash import actions as actions_mod
    monkeypatch.setattr(actions_mod, "handoff", lambda t: sent.append(t) or "")
    app = DevDashApp(builder=StubBuilder())
    async with app.run_test() as pilot:
        await pilot.press("h")
        await pilot.press("y")
        assert len(sent) == 1
