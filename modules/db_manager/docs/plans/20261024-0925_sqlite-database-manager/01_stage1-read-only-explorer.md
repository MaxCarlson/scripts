# Stage 1: P0 Read-Only Explorer & Core Infrastructure

**Parent Plan:** [00_implementation-plan.md](00_implementation-plan.md)  
**Status:** In Progress  

## Scope

Establish the core `db_manager` module, safe connection abstraction, structural inspection, parameterized querying, bounded browsing, search, streaming exports, online backups, and read-only CLI commands:
- `info`: detailed database metadata, format, sizes, WAL status, object counts.
- `tables`: tables/views/virtual-tables list with columns, PKs, FKs, indexes, and row estimates.
- `schema`: complete DDL from `sqlite_master`/`sqlite_schema`.
- `browse`: paginated rows with column filtering, sorting, projection, NULL formatting, and bounded BLOB hex previews.
- `search`: parameterized search across tables/columns.
- `query`: bounded read-only SELECT/EXPLAIN with strict authorizer.
- `export`: JSON, JSONL, CSV (with spreadsheet formula escaping), and SQL dump.
- `check`: `PRAGMA quick_check`, optional `integrity_check`, and `foreign_key_check`.
- `backup`: online `sqlite3.Connection.backup` with audit manifest.
- `discover`: opt-in inspection of known toolkit database paths.

## Deliverables

1. `pyproject.toml` and package configuration for `db_manager`.
2. `db_manager/connections.py`: Read-only connection enforcing URI `file:{path}?mode=ro`, `PRAGMA query_only = ON;`, busy timeout, disabled extension loading, and authorizer callback denying write/schema mutations.
3. `db_manager/inspector.py`: Inspection data classes and helpers for database metadata, tables, columns, indexes, foreign keys, and integrity checks.
4. `db_manager/query.py`: Safe identifier quoting, read-only query execution, paginated browsing, and search.
5. `db_manager/export.py`: Streaming format exporters with formula escaping and BLOB hex limits.
6. `db_manager/backup.py`: Online backup using SQLite backup API, manifest generation, and restore-to-new-path validation.
7. `db_manager/discover.py`: Discovery of known repository database paths without disk mutation or private path leaks.
8. `db_manager/cli.py`: CLI dispatcher for P0 subcommands complying with short/long flag rules and `-V/--version`.
9. `tests/connections_test.py`, `tests/inspector_test.py`, `tests/query_test.py`, `tests/backup_test.py`, `tests/export_test.py`, `tests/cli_test.py`.

## Verification Criteria

- All tests run and pass using `pytest -v modules/db_manager/tests`.
- Read-only connections fail cleanly on non-existent files without creating new files or directories.
- SQLite authorizer blocks `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `ATTACH`, `DETACH`, and `VACUUM` in read-only mode.
- Formulas like `=CMD('calc')` or `@SUM(1,2)` in CSV export are prefixed with `'` to prevent injection.
- Online backup succeeds even with concurrent synthetic writers.
- All CLI flags provide `-X` and `--long-name`.
