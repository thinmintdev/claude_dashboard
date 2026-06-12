"""Live board document — a human/agent-readable BOARD.md rewritten on every
snapshot so a crash (of tmux, the box, or a session) leaves a paper trail:
what was running, where, on which branch, doing what, and how to resume it.

Written atomically (tmp + rename) so a crash mid-write can't truncate it.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from devdash.models import Snapshot

DEFAULT_PATH = Path.home() / ".claude" / "dev-dash" / "BOARD.md"


def _age(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def render(snap: Snapshot) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.generated_at))
    q = snap.quota
    lines = [
        "# dev-dash live board",
        "",
        f"Updated {ts} — rewritten continuously while the dashboard runs.",
        "Crash recovery: each session below lists its resume command,",
        "tmux pane, branch, todos, and last output.",
        "",
        f"Quota: {q.pct_5h:.0f}% of 5h window ({q.tokens_5h:,} tok) · "
        f"week {q.pct_week:.0f}% · burn {q.burn_tokens_per_hr:,}/h ({q.trend})",
        "",
        "## Sessions",
        "",
    ]
    for s in snap.sessions:
        lines.append(f"### {s.id[:8]} — {s.cwd}  [{s.status}]")
        lines.append(f"- resume: `claude --resume {s.id}`  (cwd `{s.cwd}`)")
        tmux = f"`{s.tmux_target}`" if s.tmux_target else "none (not in tmux)"
        lines.append(f"- tmux pane: {tmux} · model {s.model} · "
                     f"ctx {s.ctx_pct:.0f}% · idle {_age(s.idle_secs)}")
        if s.git_branch:
            lines.append(f"- branch: `{s.git_branch}`")
        open_todos = [t for t in s.todos
                      if t.get("status") not in ("completed", "deleted")]
        if open_todos:
            lines.append("- open todos:")
            for t in open_todos[:8]:
                mark = "⚙" if t.get("status") == "in_progress" else "·"
                lines.append(
                    f"  - {mark} {t.get('content', t.get('subject', '?'))}")
        if s.last_text:
            snippet = " ".join(s.last_text.split())[:240]
            lines.append(f"- last output: {snippet}")
        lines.append("")

    subs = [a for a in snap.agents if a.parent_id]
    if subs:
        lines += ["## Subagents / team members", ""]
        for a in subs:
            lines.append(f"- {a.label} ({a.kind}, {a.status}) "
                         f"under {a.parent_id[:8]}"
                         + (f" — tmux `{a.tmux_target}`" if a.tmux_target else ""))
        lines.append("")

    lines += ["## Repos", ""]
    for r in snap.repos:
        flux = []
        if r.ahead:
            flux.append(f"↑{r.ahead}")
        if r.behind:
            flux.append(f"↓{r.behind}")
        if r.dirty_n:
            flux.append(f"{r.dirty_n} modified")
        if r.untracked_n:
            flux.append(f"{r.untracked_n} untracked")
        lines.append(f"- `{r.path}` on `{r.branch}` "
                     f"({', '.join(flux) or 'clean'})")
        for pr in r.prs:
            lines.append(f"  - PR #{pr.number} [{pr.checks}] {pr.title}")
        for c in r.wip_claims:
            lines.append(f"  - ⚑ claim by {c.sid[:8]}: {c.intent} "
                         f"({', '.join(c.files[:4])})")
    lines.append("")
    if snap.errors:
        lines += ["## Collector errors", ""]
        lines += [f"- {e.collector}: {e.message}" for e in snap.errors]
        lines.append("")
    return "\n".join(lines)


def write(snap: Snapshot, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(render(snap))
    os.replace(tmp, path)
