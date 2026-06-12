---
name: dev-dash
description: Open the dev-dash tmux dashboard — live board of Claude Code sessions, agent teams, git/PR activity, todos, and usage metrics (ctx %, tokens, quota, burn rate). Use when the user invokes /dev-dash or asks to see/open/jump to the session dashboard or dev dashboard.
---

# dev-dash — Claude Code session dashboard

Launch or jump to the dev-dash board with ONE command:

```bash
bash ~/.claude/dev-dash/skill/launch.sh
```

That's it. The launcher is idempotent:
- board already running somewhere → switches the tmux client to it
- no board → creates a `dev-dash` tmux window running it (or a detached
  `devdash` session when invoked outside tmux) and jumps there

Report the launcher's one-line output to the user. Do not run any other
tmux commands; do not start `devdash` directly.

## Board keys (tell the user if asked)

`Enter` jump to selected session's tmux pane · `d` drill-in (transcript
tail, todos, token breakdown) · `Esc` back · `r` force refresh · `q` quit.

## Maintenance notes

- Repo: `~/.claude/dev-dash` (tests: `.venv/bin/pytest`)
- Config: `~/.claude/dev-dash/config.toml` (quota caps, repo roots,
  model context windows) — see `devdash/config.py` for keys
- Spec: `docs/superpowers/specs/2026-06-11-dev-dash-design.md`
