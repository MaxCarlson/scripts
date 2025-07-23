#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <old-session> [new-session]" >&2
  exit 1
fi

OLD_SESSION=$1
NEW_SESSION=${2:-"${OLD_SESSION}-reconnect"}

SSH_CMD="sshspn"
SSH_ARGS=(-t)
POST_LOGIN_CMD="mamba activate dlpn"

# 1) make sure the source session exists
tmux has-session -t "$OLD_SESSION" || { 
  echo "Error: session '$OLD_SESSION' not found" >&2
  exit 1
}

# 2) clean up any stale target session
tmux kill-session -t "$NEW_SESSION" 2>/dev/null || true

# 3) pick a real delimiter (unit separator) for safe splitting
DELIM=$'\x1f'

# 4) capture every window’s index, name, layout & pane-count
mapfile -t WINFO < <(
  tmux list-windows -t "$OLD_SESSION" \
    -F "#{window_index}${DELIM}#{window_name}${DELIM}#{window_layout}${DELIM}#{window_panes}"
)

# 5) rebuild into the new session
first=true
for entry in "${WINFO[@]}"; do
  IFS="$DELIM" read -r idx name layout panes <<< "$entry"

  if $first; then
    tmux new-session -d -s "$NEW_SESSION" -n "$name"
    first=false
  else
    tmux new-window -t "$NEW_SESSION" -n "$name"
  fi

  # split to match original pane count
  for ((i=1; i<panes; i++)); do
    tmux split-window -t "$NEW_SESSION:$idx"
  done

  # restore the exact layout
  tmux select-layout -t "$NEW_SESSION:$idx" "$layout"

  # respawn each pane: sshspn → then mamba activate
  mapfile -t PIDS < <(tmux list-panes -t "$NEW_SESSION:$idx" -F "#{pane_index}")
  for pane in "${PIDS[@]}"; do
    tmux respawn-pane -k -t "$NEW_SESSION:$idx.$pane" \
      "$SSH_CMD" "${SSH_ARGS[@]}"
    tmux send-keys -t "$NEW_SESSION:$idx.$pane" "$POST_LOGIN_CMD" C-m
  done
done

# 6) attach to your fresh session
tmux attach-session -t "$NEW_SESSION"

