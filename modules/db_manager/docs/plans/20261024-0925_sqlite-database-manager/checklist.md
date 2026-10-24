# Implementation Checklist: SQLite Database Explorer and Safe Manager

## Stage 1: P0 Read-Only Explorer & Core Infrastructure
- [x] Task 1: Package scaffolding, standards compliance & connection safety
  - [x] `modules/db_manager/pyproject.toml`
  - [x] `modules/db_manager/README.md`
  - [x] `modules/db_manager/db_manager/__init__.py`
  - [x] `modules/db_manager/db_manager/connections.py`
  - [x] `modules/db_manager/tests/connections_test.py`
- [x] Task 2: Structural inspection & health checking
  - [x] `modules/db_manager/db_manager/inspector.py`
  - [x] `modules/db_manager/tests/inspector_test.py`
- [x] Task 3: Bounded query, parameterized search, and table browsing
  - [x] `modules/db_manager/db_manager/query.py`
  - [x] `modules/db_manager/tests/query_test.py`
- [x] Task 4: Online consistent backup, audit manifest & export engine
  - [x] `modules/db_manager/db_manager/backup.py`
  - [x] `modules/db_manager/db_manager/export.py`
  - [x] `modules/db_manager/db_manager/discover.py`
  - [x] `modules/db_manager/tests/backup_test.py`
  - [x] `modules/db_manager/tests/export_test.py`
  - [x] `modules/db_manager/tests/discover_test.py`
- [x] Task 5: P0 CLI implementation & subcommands
  - [x] `modules/db_manager/db_manager/cli.py` (P0 subcommands)
  - [x] `modules/db_manager/tests/cli_test.py`
  - [x] Verify Stage 1 tests pass offline

## Stage 2: P1 Conservative Transactional Editing & Compare
- [x] Task 6: Conservative transactional editing & compare engine
  - [x] Write connection helpers in `connections.py`
  - [x] `modules/db_manager/db_manager/changes.py` (`init`, `edit`, `insert`, `delete`, `sql`, `compare`)
  - [x] P1 CLI subcommand integration in `cli.py`
  - [x] `modules/db_manager/tests/changes_test.py`
  - [x] Verify Stage 2 tests pass offline

## Stage 3: P2 Recovery, TUI Presentation & Registry Integration
- [x] Task 7: Recovery diagnostics, TUI adapter & registry integration
  - [x] `modules/db_manager/db_manager/recovery.py`
  - [x] `modules/db_manager/db_manager/tui.py`
  - [x] P2 CLI subcommand integration (`recover`)
  - [x] Registry update in `modules/scripts_help/scripts_help/registry/registry.py`
  - [x] `modules/db_manager/tests/recovery_test.py`
  - [x] Full suite test & lint verification (`pytest`, `ruff check`, `ruff format` — 44 tests passing)
  - [x] Pre-commit gates verified: NULL-safe optimistic concurrency, restore WAL exclusivity & rollback, dry-run defaults, bounded read-only query safeguards
  - [x] Update documentation, freeze handoffs, and prepare stage report
