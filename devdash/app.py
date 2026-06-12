"""dev-dash — Mission Control TUI (layout A).

┌ quota strip ────────────────────────────────┐
│ sessions table          │ agent tree        │
│ git panel               │ (or drill-in)     │
└ footer ─────────────────────────────────────┘
"""

from __future__ import annotations

import os
import sys

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Static, Tree

from devdash import actions
from devdash.config import load
from devdash.models import SessionInfo, Snapshot
from devdash.snapshot import SnapshotBuilder

STATUS_DOT = {"active": ("●", "green"), "idle": ("◐", "yellow"),
              "stale": ("○", "grey50")}
AGENT_MARK = {"running": "⚙", "done": "✔", "failed": "✖"}


def _fmt_idle(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 1_000:
        return f"{n // 1000}k"
    return str(n)


def _bar(pct: float, width: int = 14) -> str:
    filled = min(width, round(width * pct / 100))
    return "█" * filled + "░" * (width - filled)


class QuotaStrip(Static):
    def update_quota(self, snap: Snapshot) -> None:
        q = snap.quota
        color = "red" if q.pct_5h > 90 else "yellow" if q.pct_5h > 70 else "green"
        arrow = {"up": "↗", "down": "↘", "flat": "→"}[q.trend]
        t = Text()
        t.append("▌dev-dash ", style="bold #feaf00")
        t.append(" quota ", style="dim")
        t.append(f"{_bar(q.pct_5h)} {q.pct_5h:.0f}%", style=color)
        t.append(" 5h", style="dim")
        t.append(f"  wk {q.pct_week:.0f}%", style="dim")
        t.append(f"   burn {_fmt_tok(q.burn_tokens_per_hr)}/h {arrow}",
                 style="cyan")
        if snap.errors:
            t.append(f"   ⚠{len(snap.errors)}", style="red")
        self.update(t)


class SessionsTable(DataTable):
    COLS = ("", "session", "project", "model", "ctx", "idle", "tok")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns(*self.COLS)

    def update_sessions(self, sessions: list[SessionInfo]) -> None:
        prev_key = None
        if self.row_count and self.cursor_row is not None:
            try:
                prev_key, _ = self.coordinate_to_cell_key(
                    (self.cursor_row, 0))
            except Exception:
                prev_key = None
        self.clear()
        for s in sessions:
            dot, color = STATUS_DOT[s.status]
            ctx_style = "red" if s.ctx_pct >= 85 else "green"
            model = s.model.split("-2")[0].replace("claude-", "")
            self.add_row(
                Text(dot, style=color),
                Text(s.id[:8], style="bold" if s.status == "active" else ""),
                _short_path(s.cwd),
                Text(model, style="cyan"),
                Text(f"{s.ctx_pct:.0f}%", style=ctx_style),
                _fmt_idle(s.idle_secs),
                _fmt_tok(s.tokens_turn),
                key=s.id,
            )
        if prev_key is not None:
            try:
                self.move_cursor(row=self.get_row_index(prev_key))
            except Exception:
                pass


class AgentTreePanel(Tree):
    def update_agents(self, snap: Snapshot) -> None:
        self.clear()
        self.root.label = "agents"
        self.root.expand()
        by_parent: dict[str, list] = {}
        for a in snap.agents:
            by_parent.setdefault(a.parent_id, []).append(a)
        for root_agent in by_parent.get("", []):
            mark = AGENT_MARK.get(root_agent.status, "?")
            node = self.root.add(
                f"{mark} {root_agent.label}", data=root_agent, expand=True)
            for child in by_parent.get(root_agent.session_id, []):
                cmark = AGENT_MARK.get(child.status, "?")
                node.add_leaf(f"{cmark} {child.label}", data=child)


class GitPanel(Static):
    def update_repos(self, snap: Snapshot) -> None:
        t = Text()
        t.append(" GIT\n", style="bold #feaf00")
        if not snap.repos:
            t.append("  no active repos found", style="dim")
        for r in snap.repos[:8]:
            t.append(f" {_short_path(r.path):<18}", style="")
            t.append(f"{r.branch:<12}", style="green")
            flux = []
            if r.ahead:
                flux.append(f"↑{r.ahead}")
            if r.behind:
                flux.append(f"↓{r.behind}")
            t.append(f"{' '.join(flux):<8}")
            dirt = []
            if r.dirty_n:
                dirt.append(f"{r.dirty_n}M")
            if r.untracked_n:
                dirt.append(f"{r.untracked_n}?")
            t.append(f"{' '.join(dirt) or 'clean':<10}",
                     style="red" if r.dirty_n else "dim")
            for pr in r.prs[:3]:
                mark, style = {"passing": ("✓", "green"),
                               "failing": ("✗", "red")}.get(
                                   pr.checks, ("○", "yellow"))
                t.append(f"#{pr.number}{mark} ", style=style)
            t.append("\n")
            for c in r.wip_claims:
                t.append(f"   ⚑ {c.intent[:40]} ({c.sid[:8]})\n",
                         style="magenta")
        self.update(t)


class DrillIn(Static):
    def show_session(self, s: SessionInfo) -> None:
        t = Text()
        t.append(f" {s.id[:8]} — {_short_path(s.cwd)}\n", style="bold #feaf00")
        t.append(f" {s.model}  ctx {s.ctx_pct:.0f}%  "
                 f"turn {_fmt_tok(s.tokens_turn)}  "
                 f"total {_fmt_tok(s.tokens_total)}\n\n", style="cyan")
        if s.todos:
            t.append(" TODOS\n", style="bold")
            for td in s.todos[:10]:
                mark = {"completed": "✔", "in_progress": "⚙"}.get(
                    td.get("status", ""), "·")
                t.append(f"  {mark} {td.get('content', td.get('subject', '?'))[:60]}\n",
                         style="dim" if mark == "✔" else "")
            t.append("\n")
        t.append(" LAST OUTPUT\n", style="bold")
        t.append(f" {s.last_text[:500]}\n", style="dim")
        t.append("\n [Esc] back", style="dim")
        self.update(t)


def _short_path(p: str) -> str:
    home = os.path.expanduser("~")
    return (p or "?").replace(home, "~")[:22]


class DevDashApp(App):
    TITLE = "dev-dash"
    CSS = """
    QuotaStrip { height: 1; padding: 0 1; background: $surface; }
    #body { height: 1fr; }
    #left { width: 62%; }
    SessionsTable { height: 60%; border: solid $primary 30%; }
    GitPanel { height: 40%; border: solid $primary 30%; padding: 0 1; }
    #right { width: 38%; }
    AgentTreePanel { border: solid $primary 30%; }
    DrillIn { border: solid $primary 30%; padding: 0 1; display: none; }
    """
    BINDINGS = [
        Binding("enter", "jump", "jump-to", priority=True),
        Binding("d", "drill", "drill-in"),
        Binding("escape", "undrill", show=False),
        Binding("r", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, builder: SnapshotBuilder | None = None):
        super().__init__()
        self.builder = builder or SnapshotBuilder(load())
        self.snap = Snapshot()

    def compose(self) -> ComposeResult:
        yield QuotaStrip()
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield SessionsTable()
                yield GitPanel()
            with Vertical(id="right"):
                yield AgentTreePanel("agents")
                yield DrillIn()
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_snapshot(include_git=True)
        self.set_interval(2.0, self.refresh_snapshot)
        self.set_interval(float(self.builder.cfg.git_poll_secs),
                          lambda: self.refresh_snapshot(include_git=True))
        self.set_interval(float(self.builder.cfg.gh_poll_secs),
                          self.refresh_prs_bg)
        self.refresh_prs_bg()

    def refresh_prs_bg(self) -> None:
        self.run_worker(self.builder.refresh_prs, thread=True,
                        group="prs", exclusive=True)

    def refresh_snapshot(self, include_git: bool = False) -> None:
        self.snap = self.builder.build(include_git=include_git)
        self.query_one(QuotaStrip).update_quota(self.snap)
        self.query_one(SessionsTable).update_sessions(self.snap.sessions)
        self.query_one(AgentTreePanel).update_agents(self.snap)
        self.query_one(GitPanel).update_repos(self.snap)

    # -- selection helpers ---------------------------------------------------

    def _selected_session(self) -> SessionInfo | None:
        table = self.query_one(SessionsTable)
        if not table.row_count or table.cursor_row is None:
            return None
        key, _ = table.coordinate_to_cell_key((table.cursor_row, 0))
        return next((s for s in self.snap.sessions
                     if s.id == (key.value if key else None)), None)

    # -- actions ---------------------------------------------------------------

    def action_jump(self) -> None:
        s = self._selected_session()
        if not s:
            return
        err = actions.jump_to(s.tmux_target)
        if err:
            self.notify(err, severity="warning", timeout=4)

    def action_drill(self) -> None:
        s = self._selected_session()
        if not s:
            return
        drill = self.query_one(DrillIn)
        drill.show_session(s)
        drill.styles.display = "block"
        self.query_one(AgentTreePanel).styles.display = "none"

    def action_undrill(self) -> None:
        self.query_one(DrillIn).styles.display = "none"
        self.query_one(AgentTreePanel).styles.display = "block"

    def action_refresh(self) -> None:
        self.refresh_prs_bg()
        self.refresh_snapshot(include_git=True)


def main() -> None:
    pidfile = os.path.expanduser("~/.cache/dev-dash/app.pid")
    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    if os.path.exists(pidfile):
        try:
            old = int(open(pidfile).read().strip())
            os.kill(old, 0)
            print(f"dev-dash already running (pid {old}) — "
                  f"use /dev-dash or 'tmux select-window -t dev-dash'")
            sys.exit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
    try:
        DevDashApp().run()
    finally:
        try:
            os.unlink(pidfile)
        except OSError:
            pass


if __name__ == "__main__":
    main()
