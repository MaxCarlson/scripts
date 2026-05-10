---
plan_index: 0007
origin: ai
status: implemented
source_file: status.md
---

# ytaedl Status

Status date: 2026-05-09

## Current State

- The large Claude CLI/archive/partial rewrite has been committed.
- The retained source plans remain in this directory for history.
- Follow-up work is focused on hardening, not replacing the existing TUI or
  downloader stack.

## Active Follow-up Items

- Keep `ytaedl.__version__` synchronized with `pyproject.toml`.
- Make setup version checks work for both `pyproject.toml` and legacy
  `setup.py` modules.
- Clear stale worker progress whenever a worker enters simulate or fallback
  phase.
- Preserve older plans under `plans/` instead of deleting them.

## Notes

Backwards-compatible fixes in local dependency modules such as `termdash`,
`procparsers`, and `pscripts/video/ytdlp-dl` are allowed if ytaedl validation
exposes a concrete latent bug there.
