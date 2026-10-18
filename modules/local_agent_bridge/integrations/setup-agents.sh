#!/usr/bin/env sh
# Module-owned replacement hook; pass -m local to enable local delegation, or --dry-run to preview.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)
RECEIPT_PATH="${HOME}/.local/share/local-agent/receipt.json"

SUBCMD="apply"
HAS_MODE=0
FORWARD_ARGS=""

for arg in "$@"; do
    case "$arg" in
        --dry-run|-n)
            SUBCMD="plan"
            ;;
        -m|--mode|-m=*|--mode=*)
            HAS_MODE=1
            FORWARD_ARGS="$FORWARD_ARGS $arg"
            ;;
        *)
            FORWARD_ARGS="$FORWARD_ARGS $arg"
            ;;
    esac
done

if [ "${DOTFILES_DRY_RUN:-0}" = "1" ]; then
    SUBCMD="plan"
fi

DEFAULT_MODE="generic"
if [ "$HAS_MODE" -eq 0 ] && [ -f "$RECEIPT_PATH" ]; then
    if grep -q '"local"' "$RECEIPT_PATH" 2>/dev/null; then
        DEFAULT_MODE="local"
    fi
fi

run_local_agent() {
    if command -v local_agent >/dev/null 2>&1; then
        local_agent "$@"
    elif [ -x "$REPO_ROOT/bin/local_agent" ]; then
        "$REPO_ROOT/bin/local_agent" "$@"
    elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        "$REPO_ROOT/.venv/bin/python" -m local_agent_bridge.commands "$@"
    elif [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
        "$REPO_ROOT/.venv/Scripts/python.exe" -m local_agent_bridge.commands "$@"
    else
        echo 'local_agent is missing. Install scripts/modules/local_agent_bridge first.' >&2
        exit 1
    fi
}

if [ "$HAS_MODE" -eq 1 ]; then
    # shellcheck disable=SC2086
    run_local_agent setup "$SUBCMD" $FORWARD_ARGS
else
    # shellcheck disable=SC2086
    run_local_agent setup "$SUBCMD" -m "$DEFAULT_MODE" $FORWARD_ARGS
fi
