"""Actions (tmux command construction, wip release) + BOARD.md rendering."""

import json
import subprocess

import pytest

from devdash import actions, boarddoc
from devdash.models import (AgentNode, Claim, PrInfo, QuotaWindow, RepoInfo,
                            SessionInfo, Snapshot)


@pytest.fixture
def tmux_calls(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_handoff_types_slash_command(tmux_calls):
    assert actions.handoff("15:0.0") == ""
    assert tmux_calls[0] == ["tmux", "send-keys", "-t", "15:0.0", "-l", "/handoff"]
    assert tmux_calls[1] == ["tmux", "send-keys", "-t", "15:0.0", "Enter"]


def test_steer_sends_literal_text_then_enter(tmux_calls):
    assert actions.steer("15:0.0", "focus on the tests") == ""
    assert tmux_calls[0][-2:] == ["-l", "focus on the tests"]
    assert tmux_calls[1][-1] == "Enter"


def test_steer_rejects_empty(tmux_calls):
    assert actions.steer("15:0.0", "   ") != ""
    assert tmux_calls == []


def test_interrupt_sends_escape(tmux_calls):
    assert actions.interrupt("15:0.0") == ""
    assert tmux_calls[0][-1] == "Escape"


def test_kill_uses_kill_pane(tmux_calls):
    assert actions.kill_session("15:0.0") == ""
    assert tmux_calls[0][:3] == ["tmux", "kill-pane", "-t"]


def test_actions_require_target(tmux_calls):
    for fn in (actions.handoff, actions.interrupt, actions.kill_session):
        assert fn("") != ""
    assert tmux_calls == []


def test_release_claims(tmp_path):
    wip = tmp_path / ".claude"
    wip.mkdir()
    (wip / "wip.json").write_text(json.dumps([
        {"sid": "aaaa-1111", "intent": "mine", "ts": 1},
        {"sid": "bbbb-2222", "intent": "other", "ts": 1},
    ]))
    assert actions.release_claims(str(tmp_path), "aaaa") == ""
    left = json.loads((wip / "wip.json").read_text())
    assert [e["sid"] for e in left] == ["bbbb-2222"]
    assert actions.release_claims(str(tmp_path), "zzzz") == "no claims matched"


# -- BOARD.md -------------------------------------------------------------------

def _snap():
    return Snapshot(
        quota=QuotaWindow(pct_5h=62.0, tokens_5h=4_000_000,
                          burn_tokens_per_hr=300_000, trend="up"),
        sessions=[SessionInfo(
            id="aaaa1111-dead-beef", cwd="/home/halo/dev/hal0",
            model="claude-fable-5", ctx_pct=42.0, status="active",
            tmux_target="15:0.0", git_branch="fix/687",
            last_text="extraction tests green,\nstarting provider swap",
            todos=[{"content": "ship it", "status": "in_progress"},
                   {"content": "old", "status": "completed"}])],
        agents=[AgentNode(session_id="sub1", label="explore", kind="subagent",
                          parent_id="aaaa1111-dead-beef")],
        repos=[RepoInfo(path="/home/halo/dev/hal0", branch="fix/687",
                        dirty_n=3, prs=[PrInfo(number=705, title="rerank",
                                               checks="passing")],
                        wip_claims=[Claim(sid="aaaa1111-dead-beef",
                                          intent="phase E",
                                          files=["slots/x.toml"])])],
    )


def test_board_render_has_recovery_info():
    md = boarddoc.render(_snap())
    assert "claude --resume aaaa1111-dead-beef" in md
    assert "`15:0.0`" in md
    assert "fix/687" in md
    assert "⚙ ship it" in md
    assert "old" not in md                  # completed todos dropped
    assert "extraction tests green, starting provider swap" in md
    assert "PR #705 [passing] rerank" in md
    assert "⚑ claim by aaaa1111: phase E" in md
    assert "explore (subagent" in md


def test_board_write_atomic(tmp_path):
    out = tmp_path / "BOARD.md"
    boarddoc.write(_snap(), out)
    assert out.exists()
    assert not out.with_suffix(".md.tmp").exists()
    assert "dev-dash live board" in out.read_text()
