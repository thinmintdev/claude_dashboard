import json
import subprocess
import time
from pathlib import Path

import pytest

from devdash import hub


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    return r


def test_branch_set_and_read(repo):
    hub.branch_set(repo, "fix/1", "review", "PR up", sid="aaaa-bbbb")
    hub.branch_set(repo, "main", "green", "", sid="cccc-dddd")
    hub.branch_set(repo, "fix/1", "blocked", "CI red", sid="aaaa-bbbb")
    marks = hub.branch_marks(repo)
    assert marks["fix/1"]["status"] == "blocked"      # last write wins
    assert marks["fix/1"]["note"] == "CI red"
    assert marks["main"]["status"] == "green"
    # board file kept out of version control
    assert ".claude/branch-status.json" in (repo / ".gitignore").read_text()


def test_branch_set_rejects_bad_status(repo):
    with pytest.raises(ValueError):
        hub.branch_set(repo, "x", "amazing", "", sid="s")


def test_pad_append_and_tail(tmp_path):
    hub.pad_append("first note", sid="aaaa1111", hub_dir=tmp_path)
    hub.pad_append("second note", sid="bbbb2222", hub_dir=tmp_path)
    tail = hub.pad_tail(hub_dir=tmp_path)
    assert "first note" in tail and "second note" in tail
    assert "aaaa1111" in tail
    # project pads are separate files
    hub.pad_append("proj note", sid="s", project="hal0", hub_dir=tmp_path)
    assert "proj note" in hub.pad_tail("hal0", hub_dir=tmp_path)
    assert "proj note" not in hub.pad_tail(hub_dir=tmp_path)


def test_send_inbox_mark_read(tmp_path):
    hub.send("dest-sid", "hello there", from_sid="src-sid", hub_dir=tmp_path)
    msgs = hub.inbox("dest-sid", hub_dir=tmp_path)
    assert len(msgs) == 1
    assert msgs[0]["text"] == "hello there"
    assert msgs[0]["from"] == "src-sid"
    hub.mark_read(msgs)
    assert hub.inbox("dest-sid", hub_dir=tmp_path) == []
    assert len(hub.inbox("dest-sid", unread_only=False,
                         hub_dir=tmp_path)) == 1


def test_unread_counts(tmp_path):
    hub.send("s1", "a", from_sid="x", hub_dir=tmp_path)
    hub.send("s1", "b", from_sid="x", hub_dir=tmp_path)
    hub.send("s2", "c", from_sid="x", hub_dir=tmp_path)
    read = hub.inbox("s2", hub_dir=tmp_path)
    hub.mark_read(read)
    assert hub.unread_counts(hub_dir=tmp_path) == {"s1": 2}


def test_sweep_ttl(tmp_path):
    import os
    f = hub.send("s1", "old", from_sid="x", hub_dir=tmp_path)
    old = time.time() - 8 * 24 * 3600
    os.utime(f, (old, old))
    hub.send("s1", "fresh", from_sid="x", hub_dir=tmp_path)
    assert hub.sweep(hub_dir=tmp_path) == 1
    msgs = hub.inbox("s1", hub_dir=tmp_path)
    assert [m["text"] for m in msgs] == ["fresh"]


def test_resolve_sid(tmp_path):
    proj = tmp_path / "proj" / "-home-x"
    proj.mkdir(parents=True)
    (proj / "abcd1234-x.jsonl").write_text("{}\n")
    (proj / "zzzz9999-y.jsonl").write_text("{}\n")
    assert hub.resolve_sid("abcd", tmp_path / "proj") == ["abcd1234-x"]
    assert sorted(hub.live_sids(tmp_path / "proj")) == \
        ["abcd1234-x", "zzzz9999-y"]


def test_deliver_hook_prints_and_marks(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hub, "HUB_DIR", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "hook-sid")
    hub.send("hook-sid", "wake up", from_sid="other", hub_dir=tmp_path)
    hub.main(["deliver-hook"])
    out = capsys.readouterr().out
    assert "unread messages" in out and "wake up" in out
    assert hub.inbox("hook-sid", hub_dir=tmp_path) == []   # marked read
    hub.main(["deliver-hook"])                              # idempotent/quiet
    assert capsys.readouterr().out == ""
