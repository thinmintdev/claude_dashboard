import json
import subprocess
import time
from pathlib import Path

from devdash.collectors import agents as agents_c
from devdash.collectors import gitrepos as git_c
from devdash.collectors import quota as quota_c
from devdash.collectors.sessions import FileState, SessionCollector


def _sessions_with_events(events_by_sid: dict[str, list[tuple]]) -> SessionCollector:
    c = SessionCollector(Path("/nonexistent"), {"default": 200_000})
    for sid, evs in events_by_sid.items():
        st = FileState(session_id=sid, last_event_ts=time.time())
        st.events = evs
        c.files[f"/x/{sid}.jsonl"] = st
    return c


def test_quota_windows_and_trend_up():
    now = time.time()
    c = _sessions_with_events({
        "a": [(now - 600, 4000, 100),       # last hour: 4100
              (now - 5400, 1000, 50),       # prev hour: 1050
              (now - 6 * 3600, 9000, 0),    # outside 5h, inside week
              (now - 8 * 86400, 5000, 0)],  # outside week
    })
    q = quota_c.collect(c, cap_5h=10_000, cap_week=100_000)
    assert q.tokens_5h == 4100 + 1050
    assert q.tokens_week == 4100 + 1050 + 9000
    assert q.burn_tokens_per_hr == 4100
    assert q.trend == "up"
    assert q.pct_5h == 51.5


def test_quota_trend_flat_and_down():
    now = time.time()
    flat = quota_c.collect(_sessions_with_events(
        {"a": [(now - 600, 1000, 0), (now - 5400, 1000, 0)]}), 1, 1)
    assert flat.trend == "flat"
    down = quota_c.collect(_sessions_with_events(
        {"a": [(now - 600, 100, 0), (now - 5400, 1000, 0)]}), 1, 1)
    assert down.trend == "down"


# -- git ----------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], cwd=repo, check=True, capture_output=True)


def make_repo(tmp_path: Path, name="repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def test_git_collect_dirty_and_untracked(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "a.txt").write_text("changed")
    (repo / "new.txt").write_text("n")
    info = git_c.collect_repo(repo, {})
    assert info.branch == "main"
    assert info.dirty_n == 1
    assert info.untracked_n == 1
    assert info.prs == []


def test_git_wip_claims(tmp_path):
    repo = make_repo(tmp_path)
    wip = repo / ".claude"
    wip.mkdir()
    (wip / "wip.json").write_text(json.dumps([
        {"sid": "s1", "intent": "fix things", "files": ["a.txt"],
         "ts": time.time()},
        {"sid": "s2", "intent": "ancient", "files": [], "ts": 1},  # expired
    ]))
    info = git_c.collect_repo(repo, {})
    assert len(info.wip_claims) == 1
    assert info.wip_claims[0].intent == "fix things"


def test_git_discover(tmp_path):
    make_repo(tmp_path, "active")
    (tmp_path / "notrepo").mkdir()
    found = git_c.discover([tmp_path], [])
    assert [p.name for p in found] == ["active"]


# -- agents ---------------------------------------------------------------------

def test_agent_tree_sidechain_parenting(tmp_path):
    now = time.time()
    c = SessionCollector(Path("/x"), {"default": 1})
    c.files["/x/main1.jsonl"] = FileState(
        session_id="main1", cwd="/p", last_event_ts=now - 10)
    c.files["/x/sub1.jsonl"] = FileState(
        session_id="sub1", cwd="/p", is_sidechain=True, last_event_ts=now - 5)
    c.files["/x/other.jsonl"] = FileState(
        session_id="other", cwd="/q", last_event_ts=now - 99)
    nodes = agents_c.collect(c, tmp_path / "noteams")
    by_id = {n.session_id: n for n in nodes}
    assert by_id["sub1"].parent_id == "main1"
    assert by_id["sub1"].kind == "subagent"
    assert by_id["main1"].kind == "main"


def test_agent_tree_teams(tmp_path):
    teams = tmp_path / "teams" / "abcd1234-x"
    (teams / "inboxes").mkdir(parents=True)
    (teams / "inboxes" / "worker-a.json").write_text("[]")
    nodes = agents_c.collect(
        SessionCollector(Path("/x"), {"default": 1}), tmp_path / "teams")
    kinds = {n.kind for n in nodes}
    assert "team_member" in kinds
    member = next(n for n in nodes if n.kind == "team_member")
    assert member.label == "worker-a"
    assert member.parent_id.startswith("team-")


def test_git_collect_includes_branch_marks(tmp_path):
    from devdash import hub
    repo = make_repo(tmp_path)
    hub.branch_set(repo, "main", "review", "ready", sid="s1")
    info = git_c.collect_repo(repo, {})
    assert info.branch_marks["main"]["status"] == "review"
