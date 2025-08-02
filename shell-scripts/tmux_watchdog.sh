#!/usr/bin/env bash
set -euo pipefail

# tmux_watchdog.sh
# Monitors a host via ping; when it comes back up, automatically
# clones a tmux session, restores pane layouts, replays last allowed commands,
# cds into each pane’s previous working directory on the remote, and activates env.

# Configuration
PING_TARGET="your.remote.host"      # Host or IP to ping
CHECK_INTERVAL=30                   # Seconds between health checks
ALLOWED_CMDS=(yt-dlp)               # Commands allowed to replay
SSH_CMD="sshspn"
SSH_ARGS=(-t)
POST_LOGIN_CMD="mamba activate dlpn"

usage() {
  echo "Usage: $0 <old-session> [<new-session>]" >&2
  exit 1
}

clone_and_replay() {
  local OLD_SESSION="$1"
  local NEW_SESSION="${2:-${OLD_SESSION}-reconnect}"
  local DELIM=$'\x1f'
  local entry idx name layout panes pane last_cmd cd_cmd

  tmux has-session -t "$OLD_SESSION" || { echo "Session '$OLD_SESSION' not found"; exit 1; }
  tmux kill-session -t "$NEW_SESSION" 2>/dev/null || true

  mapfile -t WINFO < <(
    tmux list-windows -t "$OLD_SESSION" \
      -F "#{window_index}${DELIM}#{window_name}${DELIM}#{window_layout}${DELIM}#{window_panes}"
  )

  declare -A replay_map path_map

  # capture last allowed command & last cd command per pane
  for entry in "${WINFO[@]}"; do
    IFS="$DELIM" read -r idx name layout panes <<< "$entry"
    for (( pane=0; pane<panes; pane++ )); do
      last_cmd=$(
        tmux capture-pane -pt "${OLD_SESSION}:${idx}.${pane}" -S -100 \
          | sed '/^[[:space:]]*$/d' \
          | tail -n1
      )
      cd_cmd=$(
        tmux capture-pane -pt "${OLD_SESSION}:${idx}.${pane}" -S -1000 \
          | sed '/^[[:space:]]*$/d' \
          | grep -E '^cd ' \
          | tail -n1 \
          | awk '{print $2}'
      )
      path_map["${idx}.${pane}"]="${cd_cmd:-\$HOME}"
      for cmd in "${ALLOWED_CMDS[@]}"; do
        if [[ $last_cmd == $cmd* ]]; then
          replay_map["${idx}.${pane}"]="$last_cmd"
          break
        fi
      done
    done
  done

  local first=true
  for entry in "${WINFO[@]}"; do
    IFS="$DELIM" read -r idx name layout panes <<< "$entry"
    if $first; then
      tmux new-session -d -s "$NEW_SESSION" -n "$name"
      first=false
    else
      tmux new-window -t "$NEW_SESSION" -n "$name"
    fi

    for (( i=1; i<panes; i++ )); do
      tmux split-window -t "$NEW_SESSION:$idx"
    done

    tmux select-layout -t "$NEW_SESSION:$idx" "$layout"

    mapfile -t PIDS < <(
      tmux list-panes -t "$NEW_SESSION:$idx" -F "#{pane_index}"
    )
    for pane in "${PIDS[@]}"; do
      tmux respawn-pane -k -t "$NEW_SESSION:$idx.$pane" "$SSH_CMD" "${SSH_ARGS[@]}"
      tmux send-keys -t "$NEW_SESSION:$idx.$pane" "cd ${path_map["${idx}.${pane}"]}" C-m
      tmux send-keys -t "$NEW_SESSION:$idx.$pane" "$POST_LOGIN_CMD" C-m
      if [[ -n "${replay_map["${idx}.${pane}"]:-}" ]]; then
        tmux send-keys -t "$NEW_SESSION:$idx.$pane" "${replay_map["${idx}.${pane}"]}" C-m
      fi
    done
  done

  tmux attach-session -t "$NEW_SESSION"
}

[[ $# -ge 1 ]] || usage
OLD_SESSION="$1"
NEW_SESSION="${2:-}"

echo "Watching ${PING_TARGET} every ${CHECK_INTERVAL}s for session '${OLD_SESSION}'..."

down=false
while true; do
  if ping -c1 -W1 "$PING_TARGET" &>/dev/null; then
    if $down; then
      echo "[watchdog] ${PING_TARGET} is back online."
      clone_and_replay "$OLD_SESSION" "$NEW_SESSION"
      down=false
    fi
  else
    if ! $down; then
      echo "[watchdog] ${PING_TARGET} is unreachable."
      down=true
    fi
  fi
  sleep "$CHECK_INTERVAL"
done
