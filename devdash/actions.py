"""Command layer — every mutation the dashboard can perform goes through
here. Phase 1: tmux navigation only. Phase 3 (kill/steer/release) lands
behind the same interface so the UI just grows keybinds.
"""

from __future__ import annotations

import os
import subprocess


def inside_tmux() -> bool:
    return bool(os.environ.get("TMUX"))


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
