#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)"

VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
SETUP_ARGS=()
SKIP_REINSTALL_SEEN=0
NO_SKIP_REINSTALL_SEEN=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        -s|--skip-reinstall)
            SKIP_REINSTALL_SEEN=1
            SETUP_ARGS+=("--skip-reinstall")
            shift
            ;;
        --no-skip-reinstall)
            NO_SKIP_REINSTALL_SEEN=1
            SETUP_ARGS+=("--no-skip-reinstall")
            shift
            ;;
        -U|--no-update-help)
            SETUP_ARGS+=("--no-update-help")
            shift
            ;;
        --)
            shift
            while [ "$#" -gt 0 ]; do
                SETUP_ARGS+=("$1")
                shift
            done
            ;;
        *)
            SETUP_ARGS+=("$1")
            shift
            ;;
    esac
done

_ensure_pscripts_submodule() {
    if ! command -v git >/dev/null 2>&1; then
        if [ ! -f "$ROOT_DIR/pscripts/setup.py" ]; then
            echo "[ERROR] pscripts submodule is missing, and git is not available to initialize it." >&2
            exit 1
        fi
        return
    fi

    local expected=""
    expected="$(git -C "$ROOT_DIR" ls-tree HEAD pscripts 2>/dev/null | awk '{print $3}')"
    if [ -z "$expected" ]; then
        return
    fi

    local actual=""
    if [ -d "$ROOT_DIR/pscripts/.git" ] || [ -f "$ROOT_DIR/pscripts/.git" ]; then
        actual="$(git -C "$ROOT_DIR/pscripts" rev-parse HEAD 2>/dev/null || true)"
    fi

    if [ -f "$ROOT_DIR/pscripts/setup.py" ] && [ "$actual" = "$expected" ]; then
        return
    fi

    echo "[BOOTSTRAP] Ensuring pscripts submodule..."
    git -C "$ROOT_DIR" submodule sync -- pscripts >/dev/null 2>&1 || true
    if ! git -C "$ROOT_DIR" submodule update --init --recursive -- pscripts; then
        echo "[ERROR] Failed to initialize/update pscripts submodule." >&2
        echo "[ERROR] Check GitHub auth/network access, then rerun bootstrap." >&2
        exit 1
    fi

    if [ ! -f "$ROOT_DIR/pscripts/setup.py" ]; then
        echo "[ERROR] pscripts submodule initialized, but pscripts/setup.py is still missing." >&2
        exit 1
    fi
}

if [ "$SKIP_REINSTALL_SEEN" -eq 1 ] && [ "$NO_SKIP_REINSTALL_SEEN" -eq 1 ]; then
    echo "[ERROR] Use either --skip-reinstall or --no-skip-reinstall, not both." >&2
    exit 2
fi

_ensure_pscripts_submodule

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
env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" -m ensurepip --upgrade 2>/dev/null || true
env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" -m pip install --quiet --upgrade pip setuptools wheel

# 3) Install tomli if needed (for setup.py TOML parsing on Python < 3.11)
PYTHON_VERSION=$("$VENV_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if (( $(echo "$PYTHON_VERSION < 3.11" | bc -l) )); then
    echo "[BOOTSTRAP] Installing tomli for Python $PYTHON_VERSION..."
    env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV_PYTHON" -m pip install --quiet tomli
fi

# 4) Execute repo setup (installs core modules, wires bin wrappers)
echo "[BOOTSTRAP] Running setup.py with venv Python..."
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT_DIR:$ROOT_DIR/modules"
exec "$VENV_PYTHON" "$ROOT_DIR/setup.py" "${SETUP_ARGS[@]}"
