#!/data/data/com.termux/files/usr/bin/bash

HOST="slice"   # Change this to match your SSH config alias or IP
LOG_ENABLED=false
LOG_DIR="$HOME/logs"
LOG_FILE="$LOG_DIR/ssh_connection.log"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --log)
            LOG_ENABLED=true
            shift
            ;;
        *)
            echo "❌ Unknown argument: $1"
            echo "Usage: $0 [--log]"
            exit 1
            ;;
    esac
done

# Ensure log directory exists if logging is enabled
if [[ "$LOG_ENABLED" == true ]]; then
    mkdir -p "$LOG_DIR"
    echo "🔄 Logging enabled. Logs will be stored in: $LOG_FILE"
    echo "=== New SSH Test Started at $(date) ===" >> "$LOG_FILE"
fi

echo "🔄 Starting SSH connection test to $HOST..."
start_time=$(date +%s)

if [[ "$LOG_ENABLED" == true ]]; then
    ssh "$HOST" "bash -c 'while true; do sleep 60; echo \"\$(date) - Connection alive\"; done'" | tee -a "$LOG_FILE"
else
    ssh "$HOST" "bash -c 'while true; do sleep 60; echo \"\$(date) - Connection alive\"; done'"
fi

end_time=$(date +%s)
elapsed=$((end_time - start_time))

echo "🚨 Connection lost! Total uptime: $((elapsed / 60)) minutes, $((elapsed % 60)) seconds."

if [[ "$LOG_ENABLED" == true ]]; then
    echo "🚨 Connection lost at $(date). Uptime: $((elapsed / 60)) minutes, $((elapsed % 60)) seconds." >> "$LOG_FILE"
fi
