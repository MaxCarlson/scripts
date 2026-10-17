#!/usr/bin/env sh
# Module-owned replacement hook; pass -m local to enable local delegation.
set -eu
if ! command -v local_agent >/dev/null 2>&1; then
    echo 'local_agent is missing. Install scripts/modules/local_agent_bridge first.' >&2
    exit 1
fi
exec local_agent setup apply -m generic "$@"
