# dev-dash

Glanceable tmux TUI for **watching Claude Code work**: live sessions, agent
trees/teams, git + PR activity, todos, and usage metrics — context fill,
per-session tokens, account-quota burn, tokens/hour trend. Plus control:
jump to, steer, interrupt, hand off, or kill any session from the board.

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
 ⏎ jump  d drill  h handoff  s steer  i interrupt  x kill  w release-wip
```

## Requirements

- Linux (reads `/proc` for the tmux↔session map)
- Python ≥ 3.11
- tmux (the board lives in a tmux window; jump/steer/kill drive tmux)
- Claude Code (sessions are discovered from `~/.claude/projects/`)
- optional: `gh` CLI authenticated — enables the PR column

## Setup

```bash
# 1. clone (any path works; ~/.claude/dev-dash is the conventional spot)
git clone https://github.com/thinmintdev/claude_dashboard ~/.claude/dev-dash
cd ~/.claude/dev-dash

# 2. install into a local venv
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. (recommended) install the /dev-dash skill for Claude Code
ln -sfn ~/.claude/dev-dash/skill ~/.claude/skills/dev-dash

# 4. launch
bash skill/launch.sh
```

`launch.sh` is idempotent: if a board window already exists anywhere on the
tmux server it jumps there; otherwise it creates a `dev-dash` window (or a
detached `devdash` tmux session when invoked outside tmux) and attaches.
With the skill installed, typing `/dev-dash` in any Claude Code session does
the same — you never run tmux commands by hand.

> If you cloned somewhere other than `~/.claude/dev-dash`, edit the
> `DEVDASH` path at the top of `skill/launch.sh`.

## Keys

| Key | Action |
|---|---|
| `Enter` | jump to the selected session's tmux pane |
| `d` / `Esc` | drill-in (transcript tail, todos, token breakdown) / back |
| `h` | handoff — types `/handoff` into the session (confirm) |
| `s` | steer — type a message, it's sent to the session's prompt |
| `i` | interrupt the session's current turn (sends Escape) |
| `x` | kill the session's pane (confirm) |
| `w` | release the session's wip-board claims (confirm) |
| `r` | force refresh (git + PRs) |
| `q` | quit |

Destructive actions are confirmation-gated.

## Configuration (optional)

`~/.claude/dev-dash/config.toml` — everything has defaults:

```toml
# token budgets the quota bars are drawn against — tune to your plan
cap_5h_tokens   = 8_000_000
cap_week_tokens = 150_000_000

# where to look for git repos (scanned one level deep at startup)
repo_roots = ["~/dev"]
repos      = ["~/some/other/repo"]      # explicit additions

liveness_hours = 4        # sessions idle longer than this drop off
git_poll_secs  = 10
gh_poll_secs   = 60

[model_windows]           # context-window sizes for ctx%% (per model prefix)
default = 200000
```

If a session's observed prompt tokens exceed its configured window, the 1M
tier is inferred automatically (model id strings carry no context marker).

## Enabling agent teams in tmux (recommended companion setup)

dev-dash gets dramatically more useful when Claude Code's **agent teams**
run as visible tmux panes — every teammate becomes a real pane the board
can map, jump to, steer, and kill. Two settings in `~/.claude/settings.json`:

```json
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "teammateMode": "tmux"
}
```

- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enables the experimental teams
  feature (the `TeamCreate` / `SendMessage` tools and teammate spawning).
- `"teammateMode": "tmux"` makes every spawned teammate open as a tmux
  pane/window in the session Claude is running in, instead of running
  invisibly. The main agent stays in pane 0; teammates appear as new
  windows or splits.

For this to work, **run Claude Code inside tmux** (`tmux new -s work`,
then `claude`). With both set:

- teammates show up in dev-dash's sessions table with a tmux target, so
  `Enter`/`s`/`i`/`x` work on them like any session
- team inboxes (`~/.claude/teams/<id>/inboxes/`) render under the agent
  tree automatically
- a crashed teammate is recoverable: `tmux kill-pane` on the wedged pane
  leaves the main session intact (or use `x` from the board)

Useful raw tmux moves when you're outside the board: `tmux attach -t
<session> -r` (read-only follow), `C-b w` (window/pane picker),
`tmux capture-pane -t <target> -p -S -2000` (read a teammate's scrollback
without attaching).

## hub — shared state for agents & sessions

`hub` (installed as `~/.claude/bin/hub`, also a `/hub` skill) lets any
session, agent, or human read/write coordination state that the board and
BOARD.md render live:

```bash
hub branch set review "PR up, needs CI"     # mark branch status (per-repo)
hub branch set blocked "waiting on #719" --branch fix/687
hub pad "decision: GTT stays under 80GB"    # global append-only scratchpad
hub send a5c3 "rebase before pushing"       # message another session
hub send all "deploying in 5min" --nudge    # broadcast + tmux status flash
hub inbox --mark-read                       # read your messages
```

Branch marks (`wip/review/green/blocked/abandoned`) show as chips in the
GIT panel; unread message counts show as a ✉ column on session rows.
**Delivery is hook-based**: register the `UserPromptSubmit` hook so unread
messages are injected into the recipient's context on their next turn:

```json
{ "hooks": { "UserPromptSubmit": [ { "hooks": [ { "type": "command",
  "command": "~/.claude/dev-dash/.venv/bin/hub deliver-hook" } ] } ] } }
```

Same-team agents should keep using the native teams `SendMessage`; hub
covers cross-session, cross-team, and human-to-session messaging.
Messages TTL out after 7 days. Spec:
`docs/superpowers/specs/2026-06-11-hub-design.md`.

## Crash recovery

The board continuously (atomically) rewrites **`BOARD.md`** in the repo
root: per-session `claude --resume <id>` commands with cwd, tmux pane,
branch, open todos, and last output, plus repo/PR/wip-claim state. After a
crash of tmux, a session, or the whole box:

```bash
cat ~/.claude/dev-dash/BOARD.md
```

…and resume each piece from where it left off. Parser offsets and quota
events persist separately in `~/.cache/dev-dash/state.json`, so metrics
survive dashboard restarts too.

## How it works

- **`devdash/collectors/`** — pure-Python readers: incremental (byte-offset)
  tail-parse of `~/.claude/projects/*/*.jsonl`, teams dir, `git`/`gh` per
  repo, wip-claim boards, tmux pane↔session mapping via `/proc/<pid>/environ`.
- **`devdash/snapshot.py`** — merges everything into one JSON-serializable
  `Snapshot`; collector failures degrade per-panel (last-good data + ⚠
  badge), never crash the board.
- **`devdash/app.py`** — Textual front-end rendering snapshots.
- **`devdash/actions.py`** — every mutation (jump/steer/kill/…) goes through
  this one command layer.
- **`devdash/boarddoc.py`** — the BOARD.md writer.

The Snapshot JSON round-trip is a pinned test contract, so a future web
front-end can consume the same data unchanged (`textual serve` also works
today as an interim browser view).

Design docs: `docs/superpowers/specs/`.

## Tests

```bash
.venv/bin/pytest
```

Fixture-driven collector tests (truncated-JSONL, restart-state, quota-window
cases) + headless Textual Pilot tests for keybinds and modals. No tmux or
live sessions required.

## Roadmap

- remote hosts (collect from other machines over SSH)
- web front-end on the Snapshot contract
