# Status: Shared Launchers and Invocation-History Infrastructure

**Plan:** `docs/plans/20261024-0925_shared-launchers-and-invocation-history/`
**Branch:** `shared-launchers-20261024-0925`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925`
**Current Stage:** Stage 4 Production Migration & Stage 5 Complete (Ready for Final Delivery)

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
- **2026-10-24**: Stage 3 implemented and verified:
  - Task 3.1: Implemented centralized launcher engine `script_logging.launcher` with CLI options (`--manifest`, `--command`, `--wrapper`, `--origin`, `--`), self-reference recursion guards, proxy detection, actionable missing target errors, fail-open SQLite persistence, and genuine child process exit code return. All 14 tests in `test_launcher.py` pass. Commit `b9013c7a`.
  - Task 3.2: Implemented diagnostic echo harness `argv_echo_target.py` and comprehensive cross-platform argument fidelity suite `test_argv_fidelity.py` (30 tests) verifying spaces, empty arguments (`""`), quotes, metacharacters, unicode (`日本語`, `🚀`), backslashes, flags, dashes, exit codes, stdio streaming, and CMD/pwsh Windows batch wrapper edge cases. Documented batch escaping nuances in `CONTRACT.md`.
  - Total 76 tests passing cleanly in `modules/script_logging`.
- **2026-10-24**: Stage 4 Preparation & Dry-Run Report completed:
  - Implemented `scripts_setup/launcher_generator.py`: repository inventory scanner (`scan_repository_programs`), collision analyzer (`detect_collisions`), wrapper recognizer (`is_managed_wrapper`), template generators, atomic manifest writer (`scripts_manifest.json`), backup/migration/rollback engine, and CLI.
  - Implemented unit tests: `tests/test_launcher_generator.py` and `tests/test_migration.py`.
- **2026-10-24**: Stage 4 Rehearsal & Setup Integration verified:
  - Automated rehearsal in disposable native Windows workspace (`tests/test_migration_rehearsal.py`): verified content-signature recognition, 100% byte-for-byte preservation of unmanaged custom wrappers and obsolete wrappers, automated backup completeness, idempotent regeneration, interrupted recovery, full rollback restoring pre-migration hashes, and CMD/pwsh argument fidelity with Unicode and exit codes.
  - Integrated 4 setup entry points (`modules/setup.py`, `pyscripts/setup.py`, `bootstrap_latest.py`, `scripts_setup/setup_utils.py`) to delegate wrapper creation to `launcher_generator` (`write_wrapper`), preserving CLI compatibility (`tests/test_setup_integration.py`).
  - Authored comprehensive `REHEARSAL_REPORT.md`.
- **2026-10-24**: Stage 5 Validation, Overhead Benchmarks & Reconcile:
  - Verified symlink-safe rollback without dereferencing or modifying target shell scripts. Regression tested all 10 unmanaged launchers.
  - Verified representative invocation through production virtual environment without `PYTHONPATH` (`tests/test_prod_venv_integration.py`).
  - Added wrapper-to-database end-to-end integration test (`tests/test_shared_launcher_e2e.py`).
  - Measured startup overhead (`modules/script_logging/tests/benchmark_overhead.py`): Direct baseline p50=108.68ms; warm launcher execution p50=292.81ms; net logging overhead p50=184.13ms. Added latency bound test (`modules/script_logging/tests/test_overhead.py`).
  - Reconciled with latest `origin/main` (`1618996c`, including new `db_manager` module). Clean rebase with 0 conflicts.
  - Total 101 tests passing across test suite.
- **2026-10-24**: Production Migration Executed:
  - Applied migration to `C:\Users\mcarls\src\scripts\bin` with automated snapshot backup to `.launcher_backup_20261024_220544`.
  - 168 legacy managed wrappers upgraded to unified managed template.
  - 1 new wrapper created for `db-manager` (discovered from merged `origin/main`).
  - 10 unmanaged custom symlinks preserved 100% byte-for-byte.
  - 79 obsolete third-party wrappers untouched.
  - Smoke-tested live commands under both CMD and PowerShell (`mangadl --help`, `termdash --help`, `append_clipboard --help`, missing target exit 127). Verified invocations recorded to SQLite WAL at `%LOCALAPPDATA%\ScriptsToolkit\invocations.sqlite3`.

## Next Action
Deliver the final migration summary, benchmark metrics, integration SHA, and verification status to the user.
