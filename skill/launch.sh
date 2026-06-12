#!/usr/bin/env bash
# dev-dash launcher — idempotent: jump to the board if it exists, else start it.
# The user never types tmux commands.
set -u
DEVDASH="$HOME/.claude/dev-dash/.venv/bin/devdash"

[ -x "$DEVDASH" ] || { echo "devdash not installed at $DEVDASH" >&2; exit 1; }

# existing board window anywhere on the server?
target=$(tmux list-windows -a -F '#{session_name}:#{window_index} #{window_name}' 2>/dev/null \
         | awk '$2=="dev-dash"{print $1; exit}')

if [ -z "${TMUX:-}" ]; then
  # outside tmux: make sure a board exists, then attach to its session
  if [ -z "$target" ]; then
    tmux new-session -d -s devdash -n dev-dash "$DEVDASH"
    target="devdash:0"
  fi
  exec tmux attach -t "${target%%:*}" \; select-window -t "$target"
fi

# inside tmux
if [ -n "$target" ]; then
  tmux switch-client -t "${target%%:*}" 2>/dev/null
  tmux select-window -t "$target"
  echo "dev-dash: jumped to existing board ($target)"
else
  tmux new-window -n dev-dash "$DEVDASH"
  echo "dev-dash: board started in new window"
fi
