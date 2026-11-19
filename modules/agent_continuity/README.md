# agent_continuity

Local-first GUI–Agent Session Continuity Module (`agents` CLI) for associating long-lived consumer ChatGPT GUI workflows with native OpenAI Codex CLI and Google Antigravity CLI (`agy`) sessions across Windows 11 and WSL2.

See [docs/agent-session-continuity-master-plan.md](./docs/agent-session-continuity-master-plan.md) for the governing Master Implementation Plan (v3.0) and [docs/adr/ADR-001-phase0-architecture-decisions.md](./docs/adr/ADR-001-phase0-architecture-decisions.md) for Phase 0 architecture decisions.

## Current Status

- **Phase 0 (Capability Verification & Repository Audit):** Complete
- **Phase 1 (M1 — Manual Continuity & Durable Event Foundation):** In progress / initial release

## Installation

From `modules/agent_continuity`:

```powershell
python -m pip install -e ".[dev]"
```

Or invoke directly without installation:

```powershell
python -m agent_continuity --help
```

## Quick Start (Phase 1 M1)

All mutating commands default to **dry-run** and require `-a` / `--apply` to persist changes.

```powershell
# 1. Register a ChatGPT GUI workflow
agents wf add -w procwatch -t "ProcWatch Development" -u "https://chatgpt.com/c/<uuid>" -r "C:\Users\mcarls\src\scripts" -a

# 2. Manually associate a native Codex or AGY session
agents link -w procwatch -p codex -s 019a1234-5678-7000-8000-abcdef012345 -e windows -a

# 3. Look up all sessions and continuity pointers for a workflow
agents find -w procwatch

# 4. Inspect unlinked, candidate, or conflicting associations
agents inbox

# 5. Rebuild the SQLite query index from durable events
agents rebuild -a

# 6. Run diagnostics
agents doctor -v
```

## Storage Layout

By default, state is stored under `~/.agent_continuity` (override with `AGENT_CONTINUITY_HOME`):

```text
~/.agent_continuity/
├── config.json                 # Optional user config & extra spool roots
├── environment.json            # Persistent local environment identity
├── events/
│   └── <environment_id>/       # Atomic per-event JSON files (durable source of truth)
│       └── <ts>_<event_id>.json
└── index.sqlite                # Derived SQLite WAL index (single designated writer)
```

## Testing

```powershell
cd modules/agent_continuity
python -m pytest
```
