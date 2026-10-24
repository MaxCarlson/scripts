# Plan Handoff: Shared Launchers and Invocation-History Infrastructure

**Plan Location:** `docs/plans/20261024-0925_shared-launchers-and-invocation-history/`
**Branch:** `shared-launchers-20261024-0925`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`
**Baseline:** `origin/main` at `6fa307f3bd84761f6fe21f3700dceb9889fe090b`
**Status:** Planning complete, baseline verified clean, ready for execution.

## Objective & Scope
Implement generated cross-platform native wrappers, central invocation recording, SQLite WAL persistence with atomic counter invariants, and a stable read-only consumer API in `modules/script_logging` and `scripts_setup`.
Excluded from this handoff: `scripts_help` TUI views and generic database browser (owned by separate agents/handoffs).

## Key Architectural Decisions
1. **Dedicated Invocation Storage:** Invocations and counters reside in `invocations.sqlite3` with platform-specific standard state paths (`%LOCALAPPDATA%\ScriptsToolkit\` on Windows, `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/` on POSIX) and `SCRIPT_LOGGING_INVOCATION_DB` override.
2. **Fail-Open Execution:** Invocation recording failure must NEVER block the child program from executing. Target resolution errors remain actionable launch failures (exit code 127).
3. **No Write Locks in Reader:** `ReadOnlyHistoryReader` uses SQLite URI `mode=ro` and strictly refuses to create files or directories.
4. **Non-Destructive Migration:** Shared wrapper generator defaults to `-n`/`--dry-run`. Applying migration requires explicit `-a`/`--apply` or `-w`/`--write` and creates automatic backups for instant rollback.

## Document Index
- `00_implementation-plan.md`: Master architectural overview and global constraints.
- `01_stage1-invocation-store-and-redaction.md`: Storage, redaction, and atomic counters.
- `02_stage2-readonly-reader-and-query-api.md`: Reader, pagination, and reconciliation.
- `03_stage3-launcher-engine-and-argv-fidelity.md`: Launcher runner, argv echo, and Windows fidelity.
- `04_stage4-manifest-generator-and-migration.md`: Scanner, manifest, wrappers, and migration.
- `05_stage5-validation-benchmarks-and-contract.md`: End-to-end suite, benchmarks, and CONTRACT.md.
- `checklist.md`: Feature-level progress tracking.
- `STATUS.md`: Compact operational ledger.
