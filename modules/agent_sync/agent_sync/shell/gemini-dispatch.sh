#!/usr/bin/env bash
set -euo pipefail
EVENT="${1:-unknown}"
python -m agent_sync.hooks.dispatch -e "$EVENT"
