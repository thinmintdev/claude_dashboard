"""hub — shared read/write coordination layer for agents & sessions.

Three file-backed channels (no daemon):
  branch marks   <repo>/.claude/branch-status.json
  scratchpad     ~/.claude/hub/scratchpad.md (+ pads/<project>.md), append-only
  a2a messages   ~/.claude/hub/inbox/<sid>/<ts>.json

Library functions take explicit paths (testable); the CLI wires defaults.
All writes flock-guarded; reads never block. Spec:
docs/superpowers/specs/2026-06-11-hub-design.md
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

HUB_DIR = Path.home() / ".claude" / "hub"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
MSG_TTL = 7 * 24 * 3600
BRANCH_STATUSES = ("wip", "review", "green", "blocked", "abandoned")


def session_id() -> str:
    sid = (os.environ.get("CLAUDE_CODE_SESSION_ID")
           or os.environ.get("CLAUDE_SESSION_ID", ""))
    if sid:
        return sid
    import getpass
    import socket
    tty = ""
    try:
        tty = os.ttyname(0).replace("/", "")
    except OSError:
        pass
    return f"{getpass.getuser()}@{socket.gethostname()}-{tty}"


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# -- branch marks ---------------------------------------------------------------

def branch_set(repo: Path, branch: str, status: str, note: str,
               sid: str) -> None:
    if status not in BRANCH_STATUSES:
        raise ValueError(f"status must be one of {BRANCH_STATUSES}")
    f = repo / ".claude" / "branch-status.json"
    with _locked(f):
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        data[branch] = {"status": status, "note": note, "sid": sid,
                        "ts": time.time()}
        f.write_text(json.dumps(data, indent=1))
    gi = repo / ".gitignore"
    line = ".claude/branch-status.json"
    try:
        existing = gi.read_text().splitlines()
    except OSError:
        existing = []
    if line not in existing:
        try:
            with gi.open("a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def branch_marks(repo: Path) -> dict[str, dict]:
    f = repo / ".claude" / "branch-status.json"
    try:
        data = json.loads(f.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# -- scratchpad -------------------------------------------------------------------

def pad_path(project: str = "", hub_dir: Path = HUB_DIR) -> Path:
    if project:
        return hub_dir / "pads" / f"{project}.md"
    return hub_dir / "scratchpad.md"


def pad_append(note: str, sid: str, project: str = "",
               hub_dir: Path = HUB_DIR) -> Path:
    f = pad_path(project, hub_dir)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with _locked(f):
        with f.open("a") as fh:
            fh.write(f"\n## {stamp} · {sid[:8]}\n{note.rstrip()}\n")
    return f


def pad_tail(project: str = "", hub_dir: Path = HUB_DIR,
             max_chars: int = 1200) -> str:
    try:
        return pad_path(project, hub_dir).read_text()[-max_chars:]
    except OSError:
        return ""


# -- a2a messages ------------------------------------------------------------------

def live_sids(projects_dir: Path = PROJECTS_DIR,
              hours: float = 4.0) -> list[str]:
    cutoff = time.time() - hours * 3600
    out = []
    for f in projects_dir.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime >= cutoff:
                out.append(f.stem)
        except OSError:
            continue
    return out


def resolve_sid(prefix: str, projects_dir: Path = PROJECTS_DIR) -> list[str]:
    return [s for s in live_sids(projects_dir) if s.startswith(prefix)]


def send(to_sid: str, text: str, from_sid: str,
         hub_dir: Path = HUB_DIR) -> Path:
    box = hub_dir / "inbox" / to_sid
    box.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    f = box / f"{ts:.6f}.json"
    f.write_text(json.dumps({"from": from_sid, "to": to_sid, "text": text,
                             "ts": ts, "read": False}))
    return f


def inbox(sid: str, unread_only: bool = True,
          hub_dir: Path = HUB_DIR) -> list[dict]:
    box = hub_dir / "inbox" / sid
    out = []
    for f in sorted(box.glob("*.json")):
        try:
            m = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if unread_only and m.get("read"):
            continue
        m["_path"] = str(f)
        out.append(m)
    return out


def mark_read(messages: list[dict]) -> None:
    for m in messages:
        p = Path(m.pop("_path", ""))
        if p.exists():
            m["read"] = True
            p.write_text(json.dumps(m))


def unread_counts(hub_dir: Path = HUB_DIR) -> dict[str, int]:
    counts: dict[str, int] = {}
    root = hub_dir / "inbox"
    if not root.is_dir():
        return counts
    for box in root.iterdir():
        n = sum(1 for m in inbox(box.name, hub_dir=hub_dir))
        if n:
            counts[box.name] = n
    return counts


def sweep(hub_dir: Path = HUB_DIR, ttl: float = MSG_TTL) -> int:
    """Delete messages past TTL; drop empty inboxes. Returns removed count."""
    cutoff = time.time() - ttl
    removed = 0
    root = hub_dir / "inbox"
    if not root.is_dir():
        return 0
    for box in list(root.iterdir()):
        for f in list(box.glob("*.json")):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                continue
        try:
            next(box.iterdir())
        except StopIteration:
            box.rmdir()
        except OSError:
            pass
    return removed


def nudge(to_sid: str, text: str) -> str:
    """Flash a status-line notice on the recipient's tmux pane (does NOT
    type into their prompt). Returns '' on success."""
    from devdash.collectors import tmuxmap
    target = tmuxmap.collect().get(to_sid, "")
    if not target:
        return f"{to_sid[:8]} has no tmux pane"
    try:
        res = subprocess.run(
            ["tmux", "display-message", "-t", target, "-d", "8000",
             f"hub ✉ {text[:80]}"],
            capture_output=True, text=True, timeout=5)
        return "" if res.returncode == 0 else res.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)


# -- CLI ------------------------------------------------------------------------------

def _repo_root() -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    sys.exit("hub: not inside a git repo")


def _current_branch(repo: Path) -> str:
    out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                         cwd=repo, capture_output=True, text=True)
    return out.stdout.strip() or "HEAD"


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="hub", description="shared agent coordination: branch marks, "
        "scratchpad, session-to-session messages")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("branch", help="mark branch status (in current repo)")
    bsub = b.add_subparsers(dest="bcmd", required=True)
    bset = bsub.add_parser("set")
    bset.add_argument("status", choices=BRANCH_STATUSES)
    bset.add_argument("note", nargs="?", default="")
    bset.add_argument("--branch", default="")
    bsub.add_parser("show")

    pad = sub.add_parser("pad", help="append to (or show) the scratchpad")
    pad.add_argument("note", nargs="?", default="")
    pad.add_argument("-p", "--project", default="")
    pad.add_argument("--show", action="store_true")

    snd = sub.add_parser("send", help="message another session")
    snd.add_argument("to", help="session-id prefix, or 'all'")
    snd.add_argument("text")
    snd.add_argument("--nudge", action="store_true",
                     help="also flash the recipient's tmux status line")

    inb = sub.add_parser("inbox", help="read this session's messages")
    inb.add_argument("--mark-read", action="store_true")
    inb.add_argument("--json", action="store_true")

    sub.add_parser("deliver-hook",
                   help="(UserPromptSubmit hook) print+mark unread messages")
    sub.add_parser("sweep", help="delete messages older than 7d")

    a = p.parse_args(argv)
    sid = session_id()

    if a.cmd == "branch":
        repo = _repo_root()
        if a.bcmd == "set":
            branch = a.branch or _current_branch(repo)
            branch_set(repo, branch, a.status, a.note, sid)
            print(f"hub: {repo.name}:{branch} → {a.status}")
        else:
            for br, m in branch_marks(repo).items():
                age = int((time.time() - m.get("ts", 0)) / 3600)
                print(f"{br:<28} {m['status']:<10} {m.get('note','')} "
                      f"({m.get('sid','?')[:8]}, {age}h ago)")
    elif a.cmd == "pad":
        if a.show or not a.note:
            print(pad_tail(a.project, hub_dir=HUB_DIR, max_chars=4000) or "(empty)")
        else:
            f = pad_append(a.note, sid, a.project, hub_dir=HUB_DIR)
            print(f"hub: appended to {f}")
    elif a.cmd == "send":
        targets = (live_sids() if a.to == "all"
                   else resolve_sid(a.to))
        targets = [t for t in targets if t != sid]
        if not targets:
            sys.exit(f"hub: no live session matches '{a.to}'")
        for t in targets:
            send(t, a.text, sid, hub_dir=HUB_DIR)
            if a.nudge:
                err = nudge(t, a.text)
                if err:
                    print(f"hub: nudge failed: {err}", file=sys.stderr)
        print(f"hub: sent to {len(targets)} session(s)")
        sweep(hub_dir=HUB_DIR)
    elif a.cmd == "inbox":
        msgs = inbox(sid, hub_dir=HUB_DIR)
        if a.json:
            print(json.dumps([{k: v for k, v in m.items()
                               if not k.startswith("_")} for m in msgs]))
        else:
            for m in msgs:
                ts = time.strftime("%H:%M", time.localtime(m["ts"]))
                print(f"[{ts}] {m['from'][:8]}: {m['text']}")
            if not msgs:
                print("(no unread messages)")
        if a.mark_read:
            mark_read(msgs)
    elif a.cmd == "deliver-hook":
        msgs = inbox(sid, hub_dir=HUB_DIR)
        if msgs:
            lines = ["[hub] unread messages for this session:"]
            for m in msgs:
                ts = time.strftime("%H:%M", time.localtime(m["ts"]))
                lines.append(f"  [{ts}] from {m['from'][:8]}: {m['text']}")
            print("\n".join(lines))
            mark_read(msgs)
        sweep(hub_dir=HUB_DIR)
    elif a.cmd == "sweep":
        print(f"hub: removed {sweep(hub_dir=HUB_DIR)} expired message(s)")


if __name__ == "__main__":
    main()
