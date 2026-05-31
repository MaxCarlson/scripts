#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec python -m agent_sync.hooks.dispatch \
    --provider codex \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
