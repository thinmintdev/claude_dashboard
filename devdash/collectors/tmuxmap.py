"""tmux map — which tmux pane hosts which Claude session.

Reads CLAUDE_CODE_SESSION_ID from /proc/<pid>/environ of each pane's process
subtree (own-user processes only, which is all we need).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _proc_children() -> dict[int, list[int]]:
    tree: dict[int, list[int]] = {}
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            parts = stat.read_text().rsplit(") ", 1)[-1].split()
            pid = int(stat.parent.name)
            ppid = int(parts[1])
        except (OSError, ValueError, IndexError):
            continue
        tree.setdefault(ppid, []).append(pid)
    return tree


def _session_id_of(pid: int) -> str:
    try:
        env = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return ""
    for chunk in env.split(b"\0"):
        if chunk.startswith(b"CLAUDE_CODE_SESSION_ID="):
            return chunk.split(b"=", 1)[1].decode(errors="replace")
    return ""


def collect() -> dict[str, str]:
    """Return {claude_session_id: 'tmux_session:window.pane'}."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F",
             "#{session_name}:#{window_index}.#{pane_index} #{pane_pid}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if out.returncode != 0:
        return {}
    tree = _proc_children()
    mapping: dict[str, str] = {}
    for line in out.stdout.splitlines():
        try:
            target, pid_s = line.rsplit(" ", 1)
            pane_pid = int(pid_s)
        except ValueError:
            continue
        # BFS the pane's process subtree, pane process included
        queue = [pane_pid]
        seen = set()
        while queue:
            pid = queue.pop()
            if pid in seen:
                continue
            seen.add(pid)
            sid = _session_id_of(pid)
            if sid:
                mapping.setdefault(sid, target)
            queue.extend(tree.get(pid, []))
    return mapping
