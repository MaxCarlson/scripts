#!/usr/bin/env sh
# Module-owned replacement hook; pass -m local to enable local delegation, or --dry-run to preview.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../.." && pwd)
RECEIPT_PATH="${HOME}/.local/share/local-agent/receipt.json"

SUBCMD="apply"
HAS_MODE=0
# Rotate the original arguments through positional parameters. Quoted "$@"
# preserves spaces and wildcard characters without eval or string splitting.
for arg do
    shift
    case "$arg" in
        --dry-run|-n)
            SUBCMD="plan"
            ;;
        -m|--mode|-m=*|--mode=*)
            HAS_MODE=1
            set -- "$@" "$arg"
            ;;
        *)
            set -- "$@" "$arg"
            ;;
    esac
done

if [ "${DOTFILES_DRY_RUN:-0}" = "1" ]; then
    SUBCMD="plan"
fi

DEFAULT_MODE="generic"
if [ "$HAS_MODE" -eq 0 ] && [ -f "$RECEIPT_PATH" ]; then
    if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
        MODE_PYTHON="$REPO_ROOT/.venv/bin/python"
    elif [ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
        MODE_PYTHON="$REPO_ROOT/.venv/Scripts/python.exe"
    elif command -v python3 >/dev/null 2>&1; then
        MODE_PYTHON="python3"
    else
        MODE_PYTHON="python"
    fi
    DEFAULT_MODE=$("$MODE_PYTHON" -m local_agent_bridge.setup.bootstrap "$RECEIPT_PATH" "$@")
fi

run_local_agent() {
    if command -v local-agent >/dev/null 2>&1; then
        local-agent "$@"
    elif command -v local_agent >/dev/null 2>&1; then
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
    run_local_agent setup "$SUBCMD" "$@"
else
    run_local_agent setup "$SUBCMD" -m "$DEFAULT_MODE" "$@"
fi
