"""Command layer — every mutation the dashboard can perform goes through
here. Phase 1: tmux navigation only. Phase 3 (kill/steer/release) lands
behind the same interface so the UI just grows keybinds.
"""

from __future__ import annotations

import os
import subprocess


def inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


def _send(target: str, *keys: str) -> str:
    """Low-level tmux send-keys; '' on success, error text otherwise."""
    if not target:
        return "no tmux pane mapped for this session"
    try:
        res = subprocess.run(["tmux", "send-keys", "-t", target, *keys],
                             capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return res.stderr.strip() or "tmux send-keys failed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return ""


def interrupt(target: str) -> str:
    """Send Escape — interrupts the session's current turn."""
    return _send(target, "Escape")


def steer(target: str, text: str) -> str:
    """Type a message into the session's prompt and submit it."""
    if not text.strip():
        return "empty message"
    return _send(target, "-l", text) or _send(target, "Enter")


def handoff(target: str) -> str:
    """Trigger the session's /handoff skill (writes ~/.remember handoff)."""
    return _send(target, "-l", "/handoff") or _send(target, "Enter")


def kill_session(target: str) -> str:
    """Kill the tmux pane hosting the session. Destructive — the app must
    confirm before calling."""
    if not target:
        return "no tmux pane mapped for this session"
    try:
        res = subprocess.run(["tmux", "kill-pane", "-t", target],
                             capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return res.stderr.strip() or "tmux kill-pane failed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return ""


def release_claims(repo_path: str, sid_prefix: str) -> str:
    """Drop wip-board claims held by a session (matched by sid prefix)."""
    import json
    from pathlib import Path

    f = Path(repo_path) / ".claude" / "wip.json"
    try:
        entries = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return f"no wip board: {exc}"
    kept = [e for e in entries
            if not str(e.get("sid", "")).startswith(sid_prefix)]
    if len(kept) == len(entries):
        return "no claims matched"
    try:
        f.write_text(json.dumps(kept, indent=1))
    except OSError as exc:
        return str(exc)
    return ""


def jump_to(target: str) -> str:
    """Switch the attached tmux client to `target` ('sess:win.pane').
    Returns '' on success, error text otherwise."""
    if not target:
        return "no tmux pane mapped for this session"
    if not inside_tmux():
        return "not inside tmux — can't jump"
    try:
        res = subprocess.run(["tmux", "switch-client", "-t", target],
                             capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return res.stderr.strip() or "tmux switch-client failed"
        sess_win = target.rsplit(".", 1)[0]
        subprocess.run(["tmux", "select-window", "-t", sess_win],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return ""
