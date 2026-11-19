# Module Handoff — `agent_continuity`

- **Updated:** 2026-11-19
- **Repository:** `scripts`
- **Worktree:** `../scripts-agent-session-continuity`
- **Branch:** `feature/gui-agent-session-continuity`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`
- **Active Plan:** [docs/plans/20261119-0650_phase0-phase1-foundation/STATUS.md](./plans/20261119-0650_phase0-phase1-foundation/STATUS.md)

## Current State

- **Phase 0:** Completed and documented in [ADR-001](./adr/ADR-001-phase0-architecture-decisions.md).
- **Phase 1 (M1):** Implemented and validated in isolated worktree:
  - Durable environment-isolated atomic per-event JSON spools (`events/<environment_id>/`)
  - SQLite WAL materialized index (`index.sqlite`) with schema v1, idempotent replay, and atomic rebuild
  - Workflow registry, multi-GUI URL support, compound `(provider, environment_id, native_session_id)` sessions
  - Manual linking/unlinking, candidate rejection, conflict detection, and `--supersede` provenance tracking
  - Provider adapter foundation (`CodexAdapter`, `AgyAdapter`) with read-only detection and verified resume command generation
  - `agents` CLI (dry-run by default, `-a/--apply`, `-j/--json`, short+long flags) and `scripts_help` registration
  - 19 pytest tests + `ruff check` passing on Windows; live CLI & `/mnt/c` cross-OS SQLite guard verified in WSL2 Ubuntu

## Next Action (Phase 2 — M2)

1. Capture and verify live Codex `0.170.0` hook payloads (`SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`) on Windows in a controlled test directory without altering default user hooks until explicitly approved.
2. Capture and verify live AGY `1.5.12` (Windows) and `1.2.11` (WSL2) hook payloads (`SessionStart`, `PreInvocation`, `PostInvocation`, `Stop`) per `hooks.md`.
3. Implement normalized hook event ingestion, `Workflow-ID: <id>` marker parser, session lineage inheritance, turn-level association transitions, and `--apply` hook install/rollback tooling.
