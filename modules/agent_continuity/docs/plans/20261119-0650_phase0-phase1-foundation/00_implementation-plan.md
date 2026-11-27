# Implementation Plan — Phase 0 & Phase 1 (M1)

**Plan ID:** `20261119-0650_phase0-phase1-foundation`  
**Governing Spec:** [Master Plan v3.0](../../agent-session-continuity-master-plan.md)  
**ADR:** [ADR-001](../../adr/ADR-001-phase0-architecture-decisions.md)

## Scope

1. **Stage 0 (Phase 0 Audit):** Complete capability verification for Codex CLI (`0.170.0` Windows, missing Linux binary in WSL2) and AGY (`1.5.12` Windows, `1.2.11` WSL2), repository audit, and ADRs.
2. **Stage 1 (Registry & Durable Event Foundation):** Implement models, ID/URL normalization, atomic per-event JSON spool, environment identity management, SQLite schema + migrations, transactional materializer, and atomic full-rebuild from durable events.
3. **Stage 2 (CLI, Provider Foundation & Diagnostics):** Implement provider adapter interface + read-only Codex/AGY detection & resume command builders, association conflict/candidate/rejection semantics, continuity queries, `agents` CLI (`wf add/list/show/archive/gui-add`, `find`, `link`, `unlink`, `reject`, `status`, `inbox`, `rebuild`, `doctor`) with dry-run-by-default and `-j/--json`, and `scripts_help` registration.
4. **Stage 3 (Acceptance Tests & Documentation):** Implement pytest unit & integration tests covering Scenarios A–I, run `ruff` + `pytest`, and verify `agents` CLI end-to-end.
