#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)"
PKG_DIR="${DIR%/scripts}"

# Try to run the module's CLI within repo venv if available, else fallback
ROOT="$PKG_DIR/../../.."
if [ -x "$ROOT/.venv/bin/python" ]; then
  # Add the module to PYTHONPATH so it can be imported
  export PYTHONPATH="$PKG_DIR:${PYTHONPATH:-}"
  exec "$ROOT/.venv/bin/python" -m python_setup.cli "$@"
fi

# Fallback: use system python3 with PYTHONPATH
export PYTHONPATH="$PKG_DIR:${PYTHONPATH:-}"
exec python3 -m python_setup.cli "$@"

