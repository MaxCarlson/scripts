#!/usr/bin/env bash

#
# Sets a persistent status in each pane's border that is automatically
# cleared a set amount of time after the pane is first viewed.
#
# This robust version uses a dedicated background monitor process instead of
# relying on unreliable tmux hooks.
#

# --- Script Best Practices ---
set -e
set -u
set -o pipefail

# --- Default Configuration ---
DELAY_SECONDS=300
HELPER_DIR="${TMPDIR:-/tmp}/tmux_pane_clear_system"
MONITOR_SCRIPT_PATH="$HELPER_DIR/monitor.sh"
TIMER_SCRIPT_PATH="$HELPER_DIR/timer.sh"
FLAG_DIR="$HELPER_DIR/flags"
MONITOR_PID_FILE="$HELPER_DIR/monitor.pid"

# --- Help Function ---
usage() {
    cat <<EOF
Sets/clears a persistent status border in each tmux pane. The border is
automatically removed after the pane is viewed for a set amount of time.

USAGE:
  $(basename "$0") [OPTIONS] "COMMAND_TO_EXECUTE"
  $(basename "$0") --clear

COMMAND:
  "COMMAND_TO_EXECUTE"  The command to send to all eligible shell panes.

OPTIONS:
  -e, --expire-after SECONDS
                        The time in seconds before the border is cleared
                        after a pane is first viewed. Default: 300.

  --clear               Stops the monitor process and clears all status
                        borders set by this script.

  -h, --help            Display this help message and exit.
EOF
}

# --- Cleanup Function ---
clear_system() {
    echo "Deactivating system and clearing all remaining status borders..."
    if [ -f "$MONITOR_PID_FILE" ]; then
        MONITOR_PID=$(cat "$MONITOR_PID_FILE")
        # Kill the process and ignore errors if it's already gone
        if kill "$MONITOR_PID" >/dev/null 2>&1; then
            echo "✅ Monitor process (PID: $MONITOR_PID) stopped."
        else
            echo "⚠️  Monitor process (PID: $MONITOR_PID) was not found. It may have already been stopped."
        fi
    else
        # Fallback: if pid file is missing, try to find and kill the process
        pkill -f "$MONITOR_SCRIPT_PATH" || true
    fi

    while IFS= read -r PANE_ID; do
        tmux set-option -t "$PANE_ID" pane-border-status off
    done < <(tmux list-panes -a -F '#{pane_id}')
    echo "✅ All pane status borders have been turned off."

    if [ -d "$HELPER_DIR" ]; then
        rm -rf "$HELPER_DIR"
        echo "✅ Helper scripts and flags have been cleaned up from $HELPER_DIR."
    fi
    exit 0
}

# --- Argument Parsing ---
COMMAND_TO_SEND=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --clear) clear_system ;;
        -e|--expire-after)
            if [[ -n "${2-}" && "$2" =~ ^[0-9]+$ ]]; then
                DELAY_SECONDS="$2"; shift 2
            else echo "Error: --expire-after requires a numeric argument (seconds)." >&2; exit 1; fi ;;
        -*) echo "Error: Unknown option: $1" >&2; usage; exit 1 ;;
        *)
            if [ -n "$COMMAND_TO_SEND" ]; then
                echo "Error: Multiple commands provided." >&2; usage; exit 1
            fi
            COMMAND_TO_SEND="$1"; shift ;;
    esac
done

if [ -z "$COMMAND_TO_SEND" ]; then echo "Error: No command provided." >&2; usage; exit 1; fi

# ==============================================================================
# Main Execution Logic
# ==============================================================================

# --- Setup: Create helper scripts and directories ---
mkdir -p "$FLAG_DIR"

# 1. The Timer Script (single purpose)
cat <<'EOF' > "$TIMER_SCRIPT_PATH"
#!/usr/bin/env bash
PANE_ID="$1"
DELAY="$2"
(
    sleep "$DELAY"
    tmux set-option -t "$PANE_ID" pane-border-status off
) &
EOF
chmod +x "$TIMER_SCRIPT_PATH"

# 2. The Monitor Script (the new core logic)
cat <<EOF > "$MONITOR_SCRIPT_PATH"
#!/usr/bin/env bash
DELAY_SECONDS="\$1"
HELPER_DIR="\$2"
TIMER_SCRIPT="\${HELPER_DIR}/timer.sh"
FLAG_DIR="\${HELPER_DIR}/flags"

while true; do
    # Get the ID of the currently active pane in the current window
    ACTIVE_PANE_ID=\$(tmux display-message -p '#{pane_id}')
    FLAG_FILE="\${FLAG_DIR}/\${ACTIVE_PANE_ID}"

    # If a timer has not been started for this pane yet...
    if [ ! -f "\$FLAG_FILE" ]; then
        # Mark it as "handled"
        touch "\$FLAG_FILE"
        # Launch the timer for it
        "\$TIMER_SCRIPT" "\$ACTIVE_PANE_ID" "\$DELAY_SECONDS"
    fi
    # Wait a second before checking again to avoid high CPU usage
    sleep 1
done
EOF
chmod +x "$MONITOR_SCRIPT_PATH"

# --- Activation ---
echo "Activating system with an expiration of $DELAY_SECONDS seconds..."
echo "Using temporary directory: $HELPER_DIR"

# 1. Launch the monitor script in the background using nohup
# This ensures it keeps running even if the terminal that launched it closes.
nohup "$MONITOR_SCRIPT_PATH" "$DELAY_SECONDS" "$HELPER_DIR" >/dev/null 2>&1 &
# Store the Process ID (PID) of the monitor for easy cleanup
echo $! > "$MONITOR_PID_FILE"
echo "✅ Monitor process launched with PID: $(cat "$MONITOR_PID_FILE")."

# 2. Set initial borders for all panes
echo "✅ Setting initial status borders on all panes..."
SHELLS_TO_TARGET=("bash" "-bash" "zsh" "-zsh" "fish" "-fish" "sh" "-sh")
while IFS= read -r PANE_DATA; do
    PANE_ID=$(echo "$PANE_DATA" | cut -d' ' -f1)
    PANE_PID=$(echo "$PANE_DATA" | cut -d' ' -f2)
    
    tmux set-option -t "$PANE_ID" pane-border-status top
    
    if ! PANE_COMMAND=$(ps -o comm= -p "$PANE_PID" 2>/dev/null); then
        tmux set-option -t "$PANE_ID" pane-border-format "#[align=centre]#[fg=yellow,bold]⚠️ Unknown State#[default]"
        continue
    fi
    PANE_COMMAND=$(echo "$PANE_COMMAND" | tr -d '[:space:]')

    IS_SHELL=0
    for shell in "${SHELLS_TO_TARGET[@]}"; do
        if [ "$PANE_COMMAND" = "$shell" ]; then IS_SHELL=1; break; fi
    done

    if [ "$IS_SHELL" -eq 1 ]; then
        tmux send-keys -l -t "$PANE_ID" "$COMMAND_TO_SEND"; tmux send-keys -t "$PANE_ID" C-m
        tmux set-option -t "$PANE_ID" pane-border-format "#[align=centre]#[fg=green,bold]✅ Applied: ${COMMAND_TO_SEND}#[default]"
    else
        tmux set-option -t "$PANE_ID" pane-border-format "#[align=centre]#[fg=red,bold]❌ Skipped (Busy: ${PANE_COMMAND})#[default]"
    fi
done < <(tmux list-panes -a -F '#{pane_id} #{pane_pid}')

echo "-------------------------------------------------------------------------"
echo "System activated. Borders will clear $DELAY_SECONDS seconds after a pane is viewed."
echo "Run './$(basename "$0") --clear' to deactivate and clean up everything."
