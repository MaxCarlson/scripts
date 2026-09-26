#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    for arg in "$@"; do
        if [ "$arg" = "--dry-run" ]; then
            echo "[DRY RUN] Would create .venv; package inventory unavailable until it exists."
            exit 0
        fi
    done
    echo "[BOOTSTRAP LATEST] Creating missing .venv..."
    if command -v uv >/dev/null 2>&1; then
        UV_LINK_MODE=copy uv venv --seed "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

if ! env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
    for arg in "$@"; do
        if [ "$arg" = "--dry-run" ]; then
            echo "[DRY RUN] pip is missing; would run ensurepip."
            exit 0
        fi
    done
    env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" -m ensurepip --upgrade
fi

exec env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" "$ROOT_DIR/bootstrap_latest.py" "$@"
