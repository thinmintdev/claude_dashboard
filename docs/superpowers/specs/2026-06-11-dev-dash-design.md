# dev-dash — Claude Code session dashboard (Phase 1 design)

**Date:** 2026-06-11
**Status:** Approved (brainstorm session, hal0-dev)
**Owner:** halo

## Purpose

A glanceable, reusable dashboard for tracking, watching, and following Claude
Code activity on hal0-dev: live sessions, agent teams, git/PR state, todos,
and metrics (context fill, token usage, account quota, burn rate).

Launched via a `/dev-dash` skill — the user never types tmux commands.

## Decisions (locked during brainstorm)

| Decision | Choice |
|---|---|
| Form factor | tmux TUI first; backend reusable for web/phone front-end in Phase 2 |
| Stack | Python + Textual (`textual serve` gives an interim browser view for free) |
| Scope (Phase 1) | hal0-dev only — no remote hosts |
| Interactivity | Read + jump-to (Enter switches tmux to the session); architecture leaves room for full control (kill/steer/release) later |
| Layout | "Mission Control" — everything on one screen |
| Metrics | Core five (below) + all three usage tiers |
| Quota math | Derive from ccusage's approach (OSS, same JSONLs) rather than reverse-engineering |

**Core five metrics:** session age/idle time · model + speed mode · agent
tree (parent → subagents/teams) · per-repo dirty state + PRs + wip claims ·
tmux session map (also powers jump-to).

**Usage tiers:** per-session tokens (turn + cumulative) · account quota
window (5h + weekly, like `/usage`) · burn rate & trends (tokens/hour,
per-project hogs).

## Architecture

```
~/.claude/dev-dash/                    (own small repo)
├── devdash/
│   ├── collectors/        ← pure-Python readers, no Textual imports
│   │   ├── sessions.py    JSONL tail-parser → SessionInfo
│   │   ├── agents.py      teams/ + sidechain links → AgentTree
│   │   ├── gitrepos.py    git + gh + wip.json per watched repo
│   │   ├── quota.py       account window + burn rate (ccusage-derived math)
│   │   └── tmuxmap.py     tmux list-panes → session-id ↔ pane mapping
│   ├── snapshot.py        merges collectors → one Snapshot dataclass (JSON-serializable)
│   ├── app.py             Textual app: renders Snapshot, keybinds, jump-to
│   └── actions.py         command layer (Phase 1: jump-to only)
└── skill/                 → symlinked to ~/.claude/skills/dev-dash
```

### Hard rules (these make Phases 2–3 cheap)

1. **Collectors never render; the app never reads files.** Everything flows
   through `Snapshot`. The future web backend is `snapshot.to_json()` behind
   FastAPI + WebSocket — zero collector changes.
2. **All mutations go through `actions.py`.** Phase 1: only
   `tmux switch-client` / `select-window`. Kill/steer/release land behind the
   same interface later; the UI just adds keybinds.
3. **Incremental reads.** Session JSONLs are tail-parsed with remembered byte
   offsets (files reach hundreds of MB). Offset cache in `~/.cache/dev-dash/`.

### Refresh cadence

- Session JSONLs: watchdog filesystem events, debounced ~1s
- git local state: 10s poll · `gh` PRs: 60s poll (worker threads)
- tmux map: on every snapshot rebuild (i.e., whenever any collector updates)

## Data model

```python
Snapshot
├── quota:    QuotaWindow(pct_5h, pct_week, burn_tokens_per_hr, trend)
├── sessions: [SessionInfo(id, cwd, model, speed_mode, ctx_pct, tokens_turn,
│              tokens_total, idle_secs, status, tmux_target, last_text, todos)]
├── agents:   [AgentNode(session_id, label, kind=main|subagent|team_member,
│              parent_id, status)]
├── repos:    [RepoInfo(path, branch, ahead, behind, dirty_n, untracked_n,
│              prs=[PrInfo], wip_claims=[Claim])]
└── meta:     generated_at, errors=[CollectorError]
```

The `Snapshot → to_json() → from_json()` round-trip is the Phase-2 web API
contract and is pinned by test from day one.

**ctx_pct definition:** from the latest assistant event's usage —
`(input_tokens + cache_read_input_tokens + cache_creation_input_tokens) /
model_context_window`, with the window looked up from a small static
model→window table (overridable in `config.toml`).

## UI (Layout A: Mission Control)

- **Quota strip (top):** 5h-window bar, weekly %, burn rate + ▲▼ trend.
  Amber > 70%, red > 90%.
- **Sessions table (dominant, left):** one row per live main session — status
  dot (● active / ◐ idle-warn / ○ stale), short id, project dir, model,
  ctx% (red ≥ 85%), idle, turn tokens. Sorted: active first, then by idle.
- **Agent tree (right-top):** main sessions as roots; subagents/team members
  as children with ✔/⚙/✖ status. Children with tmux panes support jump-to.
- **Git panel (left-bottom):** watched repos (from `config.toml`; default scan
  `~/dev` + `/home/halo` for recently-active git dirs) — branch, ahead/behind,
  dirty/untracked counts, PRs with CI state (✓/✗/○), wip claims inline.
- **Drill-in (replaces right column, Esc closes):** selected session's last
  ~20 transcript lines (assistant text + tool names, not raw JSON), todo list,
  token breakdown (input/output/cache-read/cache-create), cumulative total.

**Keybinds:** `Enter` jump · `d` drill · `j/k/↑↓` navigate · `Tab` cycle
panels · `r` force refresh · `?` help/errors · `q` quit (window persists;
`/dev-dash` re-attaches).

**Liveness rule:** a session is "live" if its JSONL changed in the last 4h
*or* it holds a tmux pane; otherwise it drops off the board.

**Teams** render under the agent tree, not as a separate panel.

## `/dev-dash` skill behavior

If a `dev-dash` tmux window exists → switch to it. Else → create one running
`devdash` and switch. Single-instance guard via pidfile: a second launch
prints "already running in window X" and jumps there.

## Error handling

Degrade per-panel, never crash, never lie:

- Collector failure → panel keeps last-good data + dim `⚠ <name>: stale Ns`
  badge; details in `snapshot.meta.errors`, viewable with `?`.
- Malformed/truncated JSONL line → skip it, keep the offset, count it; never
  abort the file.
- `gh` offline/rate-limited → PR column `—` + offline badge; local git data
  stays fresh.
- No tmux (bare SSH) → jump-to disabled with a hint; board still renders.

## Testing

- **Collectors:** pure unit tests with fixture files — recorded real JSONLs
  (incl. truncated-line case), throwaway git repo in `tmp_path`, canned `gh`
  JSON. No Textual mocking, no tmux required.
- **Snapshot contract:** lossless JSON round-trip test (pins the web API).
- **App:** Textual `Pilot` headless smoke tests (navigate, drill-in, quit)
  against a stubbed snapshot.
- **Jump-to:** one integration test, skipped when tmux is absent.

## Phasing

- **Phase 1 (this spec):** TUI + `/dev-dash` skill, hal0-dev only, read +
  jump-to. `textual serve` available as interim browser view.
- **Phase 2:** web front-end (FastAPI + WS serving Snapshot JSON; React UI),
  remote hosts (CT105 first), *.thinmint.dev exposure via gateway Traefik.
- **Phase 3:** full control — kill/pause agents, release wip claims, git
  actions — added in `actions.py` behind confirmation UX.

## Non-goals (Phase 1)

- No mutations beyond tmux navigation
- No remote-host collection
- No cost-in-dollars precision (token counts and quota %, not billing)
- No persistence/history DB — live board only (trends computed over the
  current day's JSONLs)
