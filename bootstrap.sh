#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)"

VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

echo "[BOOTSTRAP] Ensuring Python virtual environment..."

_create_venv() {
    # Try uv first (faster), fallback to python -m venv
    if command -v uv >/dev/null 2>&1; then
        echo "[BOOTSTRAP] Using uv to create venv..."
        # Set UV_LINK_MODE=copy for Termux/Android compatibility (suppress hardlink warnings)
        UV_LINK_MODE=copy uv venv --seed "$VENV_DIR" || return 1
    else
        echo "[BOOTSTRAP] Using python -m venv..."
        python3 -m venv "$VENV_DIR" || return 1
    fi
}

# 1) Create .venv if it doesn't exist, or recreate if Python version changed
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[BOOTSTRAP] Creating .venv using system Python..."
    _create_venv
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment" >&2
        exit 1
    fi
else
    # Detect Python version mismatch (e.g. Termux upgraded python 3.12 → 3.13)
    VENV_LIB_VER=$(ls "$VENV_DIR/lib/" 2>/dev/null | grep "^python" | head -1 | sed 's/^python//')
    SYS_PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
    if [ -n "$VENV_LIB_VER" ] && [ -n "$SYS_PYTHON_VER" ] && [ "$VENV_LIB_VER" != "$SYS_PYTHON_VER" ]; then
        echo "[BOOTSTRAP] Python version changed ($VENV_LIB_VER → $SYS_PYTHON_VER). Recreating venv..."
        rm -rf "$VENV_DIR"
        _create_venv
        if [ $? -ne 0 ]; then
            echo "[ERROR] Failed to recreate virtual environment" >&2
            exit 1
        fi
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

