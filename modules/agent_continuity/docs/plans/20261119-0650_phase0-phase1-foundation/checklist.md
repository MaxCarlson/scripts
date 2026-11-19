# Checklist — `20261119-0650_phase0-phase1-foundation`

## Stage 0 — Phase 0 Capability Verification & Repository Audit
- [x] Inspect Windows & WSL2 Codex/AGY executables, versions, and native stores (read-only)
- [x] Inspect `scripts` repository conventions (`AGENTS.md`, `REPO_LLM_INSTRUCTIONS.md`, `PYTHON_REPO_STANDARDS.md`, `SCRIPTS_REPO_STANDARDS.md`)
- [x] Verify `agents` CLI name has no conflicts
- [x] Copy Master Plan v3.0 to `modules/agent_continuity/docs/agent-session-continuity-master-plan.md`
- [x] Record ADR-001 with all Phase 0 decisions

## Stage 1 — Registry, Event Spool, & SQLite Materializer
- [ ] Package skeleton (`pyproject.toml`, `__init__.py`, `__main__.py`, `.gitignore`, `conftest.py`)
- [ ] Core domain models, error taxonomy, ID/slug/URL normalization
- [ ] Environment identity & cross-OS SQLite safety guard
- [ ] Atomic per-event JSON spool writer/reader
- [ ] SQLite schema v1, migrations, idempotent transactional materializer, atomic rebuild

## Stage 2 — Association Engine, Provider Adapters, Diagnostics & CLI
- [ ] Continuity queries (`latest_created`, `latest_seen`, `latest_turn`, `latest_completed_turn`, `latest_by_provider`)
- [ ] Conflict detection, candidate/rejection/supersession semantics
- [ ] Provider adapter contract + read-only Codex/AGY detection & resume command builders
- [ ] `doctor` diagnostics
- [ ] `agents` CLI (`wf`, `find`, `link`, `unlink`, `reject`, `status`, `inbox`, `rebuild`, `doctor`) with dry-run default & `--json`
- [ ] Register in `modules/scripts_help/scripts_help/registry/registry.py`

## Stage 3 — Validation & Documentation
- [ ] Unit & integration tests covering Master Plan & Handoff Scenarios A–I
- [ ] Run `pytest` and `ruff`
- [ ] Verify CLI commands & rebuild end-to-end
- [ ] Finalize docs & checkpoints
