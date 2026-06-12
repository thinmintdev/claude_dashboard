# hub — shared read/write layer for agents & sessions

**Date:** 2026-06-11 · **Status:** Approved in conversation · **Owner:** halo

## Purpose

Let any Claude Code session/agent (and the human) read/write shared
coordination state — branch status marks, a global scratchpad, and
session-to-session messages — with no daemon, rendered live by dev-dash.

## Substrate decision

Files + a tiny CLI + hooks (matches existing `wip`/`tracker`/teams-inbox
primitives). No HTTP service: a hub daemon is a coordination SPOF and the
file substrate already survived real crashes. An MCP veneer can be layered
later without changing the store.

## Channels

### 1. Branch status — per-repo
`.claude/branch-status.json` (gitignored, beside `wip.json`):
- `hub branch set <wip|review|green|blocked|abandoned> "<note>" [--branch B]`
- entries: `{branch, status, note, sid, ts}`; one entry per branch (last write wins)
- dev-dash gitrepos collector renders a colored chip next to the branch;
  mirrored into BOARD.md.

### 2. Global scratchpad — append-only
`~/.claude/hub/scratchpad.md` (+ optional per-project via `-p <name>` →
`~/.claude/hub/pads/<name>.md`):
- `hub pad "<note>" [-p project]` — appends `## <ts> · <sid8>\n<note>`,
  flock-guarded
- append-only ⇒ corruption-proof under concurrency, doubles as decision log
- dev-dash drill-in shows tail; `p` key opens full pad.

### 3. A2A messages — inbox files + hook delivery
`~/.claude/hub/inbox/<sid>/<ts>.json` with `{from, to, text, ts, read}`:
- `hub send <sid-prefix|all> "<text>" [--nudge]` — `--nudge` additionally
  tmux send-keys a notice to the recipient's pane (uses dev-dash tmux map)
- `hub inbox [--mark-read]` — read own messages
- **Delivery:** `UserPromptSubmit` hook injects unread messages as context on
  the recipient's next turn (passive, no polling). dev-dash shows an unread
  badge (✉ N) on session rows.
- Boundary: same-team agents keep using native teams SendMessage; hub covers
  cross-session/cross-team/human-to-session.

## Hygiene

- All entries carry `sid` + `ts`; messages TTL-swept at 7d, branch marks
  shown stale after 7d without update
- All writes flock-guarded; reads never block
- `hub` CLI in `~/.claude/bin/` like `wip`/`tracker`; `/hub` skill documents
  verbs so spawned agents self-serve

## dev-dash integration

New `collectors/hub.py` → Snapshot fields: `RepoInfo.branch_marks`,
`SessionInfo.unread_msgs`, `scratchpad_tail`. UI: GIT panel chips, ✉ badge
in sessions table, scratchpad tail in drill-in. All mirrored into BOARD.md.

## Build order

1. `hub` CLI (branch/pad/send/inbox + flock + TTL sweep) + tests
2. `UserPromptSubmit` delivery hook
3. dev-dash collector + Snapshot fields + UI chips/badges + BOARD.md
4. `/hub` skill doc
