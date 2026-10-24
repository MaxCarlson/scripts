# Plan Handoff: Shared Launchers and Invocation-History Infrastructure

**Plan Location:** `docs/plans/20261024-0925_shared-launchers-and-invocation-history/`
**Branch:** `shared-launchers-20261024-0925`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`
**Baseline:** `origin/main` at `a0028473523f6208ea298218e0e666d56d083c9c`
**Status:** Stages 1-3 complete; Stage 4 rehearsal and setup script integration complete; awaiting user approval before applying changes to production `bin/`.

## Objective & Scope
Implement generated cross-platform native wrappers, central invocation recording, SQLite WAL persistence with atomic counter invariants, and a stable read-only consumer API in `modules/script_logging` and `scripts_setup`.
Excluded from this handoff: `scripts_help` TUI views and generic database browser (owned by separate agents/handoffs).

## Key Architectural Decisions & Verification
1. **Dedicated Invocation Storage:** Invocations and counters reside in `invocations.sqlite3` with platform-specific standard state paths (`%LOCALAPPDATA%\ScriptsToolkit\` on Windows, `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/` on POSIX) and `SCRIPT_LOGGING_INVOCATION_DB` override.
2. **Fail-Open Execution:** Invocation recording failure must NEVER block the child program from executing. Target resolution errors remain actionable launch failures (exit code 127).
3. **No Write Locks in Reader:** `ReadOnlyHistoryReader` uses SQLite URI `mode=ro` and strictly refuses to create files or directories.
4. **Non-Destructive Migration & Rehearsal:** Completed automated rehearsal against all 257 live files in a disposable environment. 168 legacy wrappers upgraded, 10 unmanaged custom scripts preserved byte-for-byte, 79 obsolete third-party wrappers untouched, 0 collisions. Full rollback and argument fidelity verified.
5. **Setup Entry Point Integration:** `modules/setup.py`, `pyscripts/setup.py`, `bootstrap_latest.py`, and `scripts_setup/setup_utils.py` refactored to delegate wrapper generation to `launcher_generator.write_wrapper` and update `scripts_manifest.json`.

## Document Index
- `00_implementation-plan.md`: Master architectural overview and global constraints.
- `01_stage1-invocation-store-and-redaction.md`: Storage, redaction, and atomic counters.
- `02_stage2-readonly-reader-and-query-api.md`: Reader, pagination, and reconciliation.
- `03_stage3-launcher-engine-and-argv-fidelity.md`: Launcher runner, argv echo, and Windows fidelity.
- `04_stage4-manifest-generator-and-migration.md`: Scanner, manifest, wrappers, and migration.
- `05_stage5-validation-benchmarks-and-contract.md`: End-to-end suite, benchmarks, and CONTRACT.md.
- `checklist.md`: Feature-level progress tracking.
- `STATUS.md`: Compact operational ledger.
- `REHEARSAL_REPORT.md`: Comprehensive rehearsal, diff, rollback, and safety report.
