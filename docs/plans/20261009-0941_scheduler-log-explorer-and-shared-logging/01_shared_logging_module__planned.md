# Stage 1: Shared Logging Module

## Boundary

Create a reusable module with generic event/run records and persistence. Do not yet change scheduler behavior or its TUI.

## Work

- Check the proposed `script_logging` import/distribution name against installed packages and repository naming conventions; settle a non-conflicting name before coding.
- Define typed generic records and an indexed SQLite store for append, query, clear, metadata retention, and output retention.
- Provide a standard-library `logging` bridge and readable text formatting without configuring the root logger as a side effect of import.
- Make writes transactional, safe under concurrent readers/writers, and explicit about time zones and serialization.
- Add package docs, tests, pyproject metadata, validation target, and root setup ordering so this library installs before consumers.
- Add at least one small sample/example demonstrating use without scheduler types.

## Verification

- Verify CRUD/query/time-range behavior, JSON metadata round trips, IDs, severity, retention/pruning, output expiration, and malformed input handling.
- Verify concurrent append integrity and standard logging integration.
- Run the new library suite, scheduler suite (to ensure package addition causes no regression), lint, module setup/install path, and `git diff --check`.
- Tests use isolated SQLite files in the owning module's `.pytest_tmp_root`; they do not alter user logs.

## Exit Criteria

The module API is generic, documented, installed by repository setup before scheduler, and independently testable. Scheduler remains unchanged until this stage is reviewed and complete.
