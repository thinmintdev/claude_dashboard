# dev-dash

Glanceable tmux TUI for **watching Claude Code work**: live sessions, agent
trees/teams, git + PR activity, todos, and usage metrics — context fill,
per-session tokens, account-quota burn, tokens/hour trend.

```
▌dev-dash  quota █████████░░░░░ 62% 5h  wk 5%   burn 2.1M/h ↗
┌──────────────────────────────────────────┐┌──────────────────────┐
│   session   project        model    ctx  ││▼ agents              │
│ ● 28f79e17  ~/dev/hal0     fable-5  38%  ││├─ ⚙ 28f79e17 hal0    │
│ ● a5c3828f  ~/.claude/dd   fable-5  96%  │││   └─ ⚙ explore-sub  │
│ ◐ 4d9badc8  /tmp           haiku    17%  ││├─ ✔ team 5daae676 (3)│
├──────────────────────────────────────────┤│                      │
│  GIT                                     ││                      │
│  hal0   fix/687…  3M  ⚑ phase E (28f79e) ││                      │
└──────────────────────────────────────────┘└──────────────────────┘
```

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
bash skill/launch.sh          # opens/jumps to the board in tmux
```

As a Claude Code skill: symlink `skill/` to `~/.claude/skills/dev-dash`,
then `/dev-dash` from any session.

**Keys:** `Enter` jump to the selected session's tmux pane · `d` drill-in
(transcript tail, todos, token breakdown) · `Esc` back · `r` refresh · `q` quit.

## How it works

- **collectors/** — pure-Python readers: incremental (byte-offset) tail-parse
  of `~/.claude/projects/*/*.jsonl`, teams dir, `git`/`gh` per repo,
  wip-claim boards, tmux pane↔session mapping via `/proc/<pid>/environ`.
- **snapshot.py** — merges everything into one JSON-serializable `Snapshot`;
  collector failures degrade per-panel (last-good data + ⚠ badge), never crash.
- **app.py** — Textual front-end rendering snapshots; all mutations go
  through `actions.py` (Phase 1: tmux jump only).

The Snapshot JSON round-trip is the API contract for the planned web
front-end (Phase 2); `textual serve` works today as an interim browser view.

Config: `~/.claude/dev-dash/config.toml` — quota caps, repo roots, model
context windows, poll cadences (see `devdash/config.py`).

Design doc: `docs/superpowers/specs/2026-06-11-dev-dash-design.md`.

## Tests

```bash
.venv/bin/pytest
```

Fixture-driven collector tests (incl. truncated-JSONL and restart-state
cases) + headless Textual Pilot smoke tests. No tmux or live sessions needed.
