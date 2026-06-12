---
name: hub
description: Shared coordination layer for Claude Code sessions and agents — mark branch status, write to the global scratchpad, send messages to other sessions. Use when the user invokes /hub, asks to message another session, mark a branch as review/blocked/green, or leave a note for other agents. Also brief spawned agents to use these commands.
---

# hub — agent/session coordination

One CLI, three channels, all file-backed (`~/.claude/bin/hub`, works from
any session or spawned agent via Bash):

## Branch status (per-repo, shows on dev-dash GIT panel + BOARD.md)

```bash
~/.claude/bin/hub branch set review "PR #723 up, needs CI"   # current branch
~/.claude/bin/hub branch set blocked "waiting on #719" --branch fix/687
~/.claude/bin/hub branch show
```

Statuses: `wip review green blocked abandoned`. Run inside the repo.

## Global scratchpad (append-only decision log)

```bash
~/.claude/bin/hub pad "GTT must stay under 80GB for img slots"
~/.claude/bin/hub pad "note" -p hal0      # per-project pad
~/.claude/bin/hub pad --show
```

## Session-to-session messages

```bash
~/.claude/bin/hub send a5c3 "main is frozen, rebase before push"  # sid prefix
~/.claude/bin/hub send all "deploying CT105 in 5 min" --nudge
~/.claude/bin/hub inbox --mark-read
```

Delivery is automatic: a `UserPromptSubmit` hook injects unread messages
into the recipient's context on their next turn. `--nudge` additionally
flashes the recipient's tmux status line. Messages expire after 7 days.

## Notes for agents

- Use `hub send` for cross-session/cross-team coordination; same-team
  teammates should keep using the native `SendMessage` tool.
- Leave a `hub pad` note when you make a decision other sessions must
  honor; mark your branch with `hub branch set` when its state changes
  (review-ready, blocked, abandoned).
- Everything you write appears live on the dev-dash board and in
  `~/.claude/dev-dash/BOARD.md`.
