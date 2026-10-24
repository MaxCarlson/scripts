# Status: Shared Launchers and Invocation-History Infrastructure

**Plan:** `docs/plans/20261024-0925_shared-launchers-and-invocation-history/`
**Branch:** `shared-launchers-20261024-0925`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`
**Current Stage:** Stage 2 complete (Ready for Stage 3: Launcher Execution Engine & Diagnostic Argv-Echo)

## Operational Ledger
- **2026-10-24**: Isolated git worktree created at `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925` on branch `shared-launchers-20261024-0925`.
- **2026-10-24**: Verified clean baseline tests: `modules/script_logging` tests pass (3 passed in 0.28s).
- **2026-10-24**: Authored comprehensive implementation plan in 5 stages (`00_implementation-plan.md` through `05_stage5-validation-benchmarks-and-contract.md`, `checklist.md`, `HANDOFF.md`, `STATUS.md`).
- **2026-10-24**: Stage 1 implemented and verified:
  - Task 1.1: Added `models.py` dataclasses (`InvocationRecord`, `CommandPattern`, `ProgramStatistics`, `AliasStatistics`, `Page`, `ReconciliationReport`), SQLite schema setup with WAL mode, and platform path resolver (`resolve_invocation_db_path`). Commit `864f1dd2`.
  - Task 1.2: Implemented privacy filtering and redaction in `redaction.py` (sensitive flags, URL userinfo/query scrubbing, explicit truncation bounds markers, SHA-256 pattern fingerprints). Commit `aa6af0f2`.
  - Task 1.3: Implemented atomic `start_invocation` and `finish_invocation` lifecycle with transaction-safe counter invariants and idempotent completion handling. Commit `3d581fb9`.
  - Task 1.4: Added concurrency tuning, SQLite WAL mode, 15000ms busy timeout, and fail-open error handling. All 20 tests pass. Commit `a10d0b54`.
- **2026-10-24**: Stage 2 implemented and verified:
  - Task 2.1: Implemented `ReadOnlyHistoryReader` in `reader.py` using SQLite URI `mode=ro` ensuring no write locks or missing database creation. Commit `3efeea34`.
  - Task 2.2: Implemented deterministic sorting, Base64 keyset cursor pagination, query filters, pattern metrics, and public API exports in `reader.py` and `__init__.py` with `__version__ = "0.2.0"`. Commit `b172f9a8`.
  - Task 2.3: Implemented summary counter reconciliation tooling (`reconcile_invocation_summaries`) in `reconciliation.py` restoring summary invariants from raw invocation rows with atomic transaction execution. Commit `9e232c19`.
  - Task 2.4: Added synthetic history fixture (`synthetic_history.py`) and verified consumer contract queries for `scripts_help`. Commit `2d688237`.
  - Total 32 tests passing cleanly in `modules/script_logging`.

## Next Action
Execute Stage 3: Launcher Execution Engine & Diagnostic Argv-Echo (`03_stage3-launcher-engine-and-argv-fidelity.md`).
