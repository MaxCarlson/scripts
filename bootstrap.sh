#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)"

VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

echo "[BOOTSTRAP] Ensuring Python virtual environment..."

# 1) Create .venv if it doesn't exist
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[BOOTSTRAP] Creating .venv using system Python..."

    # Try uv first (faster), fallback to python -m venv
    if command -v uv >/dev/null 2>&1; then
        echo "[BOOTSTRAP] Using uv to create venv..."
        # Set UV_LINK_MODE=copy for Termux/Android compatibility (suppress hardlink warnings)
        UV_LINK_MODE=copy uv venv --seed "$VENV_DIR"
    else
        echo "[BOOTSTRAP] Using python -m venv..."
        python3 -m venv "$VENV_DIR"
    fi

    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment" >&2
        exit 1
    fi
fi

# 2) Ensure pip is available in venv
echo "[BOOTSTRAP] Ensuring pip is available in venv..."
"$VENV_PYTHON" -m ensurepip --upgrade 2>/dev/null || true
"$VENV_PYTHON" -m pip install --quiet --upgrade pip setuptools wheel

# 3) Install tomli if needed (for setup.py TOML parsing on Python < 3.11)
PYTHON_VERSION=$("$VENV_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if (( $(echo "$PYTHON_VERSION < 3.11" | bc -l) )); then
    echo "[BOOTSTRAP] Installing tomli for Python $PYTHON_VERSION..."
    "$VENV_PYTHON" -m pip install --quiet tomli
fi

# 4) Execute repo setup (installs core modules, wires bin wrappers)
echo "[BOOTSTRAP] Running setup.py with venv Python..."
exec "$VENV_PYTHON" "$ROOT_DIR/setup.py" "$@"

