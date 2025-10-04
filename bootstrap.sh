#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}" )" && pwd)"

# 1) Bootstrap Python tooling (uv/pipx/micromamba) best-effort
if [ -x "$ROOT_DIR/modules/python_setup/scripts/bootstrap.sh" ]; then
  "$ROOT_DIR/modules/python_setup/scripts/bootstrap.sh" "$@" || true
fi

# 2) Execute repo setup (creates .venv, installs core modules, wires bin wrappers)
#exec "${ROOT_DIR}/setup.py"

