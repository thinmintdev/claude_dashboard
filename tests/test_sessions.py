import json
import time
from datetime import datetime, timezone
from pathlib import Path

from devdash.collectors.sessions import SessionCollector
from devdash.models import Snapshot, SessionInfo, QuotaWindow, AgentNode, RepoInfo, PrInfo, Claim, CollectorError

WINDOWS = {"default": 200_000, "claude-fable-5": 200_000}


def _ts(secs_ago: float) -> str:
    t = datetime.now(timezone.utc).timestamp() - secs_ago
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def make_session(tmp_path: Path, name: str, lines: list[dict]) -> Path:
    proj = tmp_path / "projects" / "-home-halo"
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / f"{name}.jsonl"
    f.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return f


def user_line(secs_ago=60, **kw):
    return {"type": "user", "timestamp": _ts(secs_ago), "cwd": "/home/halo",
            "gitBranch": "main", "sessionId": kw.get("sessionId", "s1"),
            "version": "2.1.173", **kw}


def assistant_line(secs_ago=30, out=500, inp=2, cache_read=80_000, cache_create=1_000,
                   text="working on it", model="claude-fable-5[1m]", **kw):
    return {"type": "assistant", "timestamp": _ts(secs_ago), "cwd": "/home/halo",
            "message": {"model": model,
                        "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": inp, "output_tokens": out,
                                  "cache_read_input_tokens": cache_read,
                                  "cache_creation_input_tokens": cache_create,
                                  "speed": "standard"}}, **kw}


def collector(tmp_path):
    return SessionCollector(tmp_path / "projects", WINDOWS)


def test_basic_parse(tmp_path):
    make_session(tmp_path, "aaa", [user_line(), assistant_line(model="claude-fable-5")])
    infos = collector(tmp_path).collect()
    assert len(infos) == 1
    s = infos[0]
    assert s.model == "claude-fable-5"
    assert s.status == "active"
    assert s.cwd == "/home/halo"
    assert s.git_branch == "main"
    assert s.tokens_turn == 500
    # ctx = (2 + 80000 + 1000) / 200000
    assert abs(s.ctx_pct - 40.5) < 0.1
    assert s.last_text == "working on it"


def test_incremental_offset(tmp_path):
    f = make_session(tmp_path, "aaa", [user_line(), assistant_line(out=100)])
    c = collector(tmp_path)
    c.collect()
    with f.open("a") as fh:
        fh.write(json.dumps(assistant_line(secs_ago=1, out=900)) + "\n")
    s = c.collect()[0]
    assert s.tokens_turn == 900
    assert s.tokens_total == 1000  # accumulated, not re-read


def test_truncated_line_skipped_and_resumed(tmp_path):
    f = make_session(tmp_path, "aaa", [user_line(), assistant_line(out=100)])
    with f.open("a") as fh:
        fh.write('{"type":"assistant", "broken": ')  # crash mid-write, no \n
    c = collector(tmp_path)
    s = c.collect()[0]
    assert s.tokens_total == 100
    # writer finishes the line later — but it's garbage JSON
    with f.open("a") as fh:
        fh.write('oops}\n' + json.dumps(assistant_line(secs_ago=1, out=50)) + "\n")
    s = c.collect()[0]
    assert s.tokens_total == 150          # malformed completed line skipped, next one parsed
    assert c.files[str(f)].malformed == 1


def test_idle_status_tiers(tmp_path):
    make_session(tmp_path, "fresh", [assistant_line(secs_ago=10)])
    make_session(tmp_path, "idle", [assistant_line(secs_ago=20 * 60)])
    make_session(tmp_path, "stale", [assistant_line(secs_ago=2 * 3600)])
    by_id = {s.id: s for s in collector(tmp_path).collect()}
    assert by_id["fresh"].status == "active"
    assert by_id["idle"].status == "idle"
    assert by_id["stale"].status == "stale"
    ids = [s.id for s in collector(tmp_path).collect()]
    assert ids[0] == "fresh"


def test_old_files_not_discovered(tmp_path):
    import os
    f = make_session(tmp_path, "ancient", [assistant_line()])
    old = time.time() - 10 * 3600
    os.utime(f, (old, old))
    assert collector(tmp_path).collect() == []


def test_sidechain_flag(tmp_path):
    make_session(tmp_path, "sub", [dict(user_line(), isSidechain=True), assistant_line()])
    c = collector(tmp_path)
    c.collect()
    assert c.sidechain_ids() == {"s1"}


def test_state_roundtrip(tmp_path):
    f = make_session(tmp_path, "aaa", [user_line(), assistant_line(out=100)])
    c = collector(tmp_path)
    c.collect()
    cache = tmp_path / "cache" / "state.json"
    c.save_state(cache)
    c2 = collector(tmp_path)
    c2.load_state(cache)
    s = c2.collect()[0]
    assert s.tokens_total == 100          # restored, file not re-read


def test_snapshot_json_contract():
    snap = Snapshot(
        quota=QuotaWindow(pct_5h=62.0, burn_tokens_per_hr=312_000, trend="up"),
        sessions=[SessionInfo(id="a", cwd="/x", todos=[{"t": "do"}])],
        agents=[AgentNode(session_id="a", label="main")],
        repos=[RepoInfo(path="/r", prs=[PrInfo(number=1)], wip_claims=[Claim(sid="s")])],
        errors=[CollectorError(collector="git", message="boom")],
    )
    assert Snapshot.from_json(snap.to_json()) == snap


def test_1m_context_window_suffix(tmp_path):
    make_session(tmp_path, "big", [assistant_line(cache_read=400_000,
                                                  model="claude-fable-5[1m]")])
    s = collector(tmp_path).collect()[0]
    assert s.ctx_pct < 100  # 401k of 1M window, not 200k
    assert abs(s.ctx_pct - 40.1) < 0.2


def test_window_inferred_when_usage_exceeds_it(tmp_path):
    make_session(tmp_path, "opus1m", [assistant_line(cache_read=300_000,
                                                     model="claude-opus-4-8")])
    s = collector(tmp_path).collect()[0]
    assert abs(s.ctx_pct - 30.1) < 0.2   # inferred 1M tier, not 150%


def test_events_survive_state_roundtrip(tmp_path):
    make_session(tmp_path, "aaa", [user_line(), assistant_line(out=100)])
    c = collector(tmp_path)
    c.collect()
    cache = tmp_path / "cache" / "state.json"
    c.save_state(cache)
    c2 = collector(tmp_path)
    c2.load_state(cache)
    evs = c2.files[str(tmp_path / "projects" / "-home-halo" / "aaa.jsonl")].events
    assert len(evs) == 1 and evs[0][1] == 100
