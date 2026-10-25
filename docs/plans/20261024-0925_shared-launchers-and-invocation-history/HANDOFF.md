# Plan Handoff: Shared Launchers and Invocation-History Infrastructure

**Plan Location:** `docs/plans/20261024-0925_shared-launchers-and-invocation-history/`
**Branch:** `shared-launchers-20261024-0925`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`
**Baseline:** `origin/main` at `1618996cd8573ebe25ed9810ab333e6456b7ddf0`
**Status:** All Stages 1–5 Complete; Production Migration Applied to `bin/`; Agent C Final Hardening & Integration Complete; 117 Tests Passing; Ready for PR Merge to `main`.

## Objective & Scope
Implement generated cross-platform native wrappers, central invocation recording, SQLite WAL persistence with atomic counter invariants, and a stable read-only consumer API in `modules/script_logging` and `scripts_setup`.
Excluded from this handoff: `scripts_help` TUI views and generic database browser (owned by separate agents/handoffs).

## Key Architectural Decisions & Verification
1. **Dedicated Invocation Storage:** Invocations and counters reside in `invocations.sqlite3` with platform-specific standard state paths (`%LOCALAPPDATA%\ScriptsToolkit\` on Windows, `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/` on POSIX) and `SCRIPT_LOGGING_INVOCATION_DB` override.
2. **Fail-Open Execution:** Invocation recording failure must NEVER block the child program from executing. Target resolution errors remain actionable launch failures (exit code 127).
3. **No Write Locks in Reader:** `ReadOnlyHistoryReader` uses SQLite URI `mode=ro` and strictly refuses to create files or directories.
4. **Symlink Safety in Backup & Rollback:** Symlinks are never dereferenced or written to. The 10 unmanaged custom symlinks are preserved byte-for-byte and tracked in `symlinks.json`.
5. **Setup Entry Point Integration:** `modules/setup.py`, `pyscripts/setup.py`, `bootstrap_latest.py`, and `scripts_setup/setup_utils.py` refactored to delegate wrapper generation to `launcher_generator.write_wrapper` and update `scripts_manifest.json`.
6. **Production Migration Applied:** 168 legacy managed wrappers upgraded, 1 missing wrapper created (`db-manager.cmd`), 10 unmanaged custom symlinks preserved, 79 obsolete third-party wrappers untouched. Automated backup at `.launcher_backup_20261024_220544`.
7. **Smoke-Tested In Production:** Tested `mangadl.cmd --help`, `termdash.cmd --help`, `append_clipboard.cmd --help`, and missing target exit code 127. Recorded invocations verified in `%LOCALAPPDATA%\ScriptsToolkit\invocations.sqlite3`.

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
