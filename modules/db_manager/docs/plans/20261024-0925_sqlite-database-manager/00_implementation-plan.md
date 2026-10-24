# SQLite Database Explorer and Safe Manager (`db_manager`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a robust, reusable, SQLite-first CLI utility (`db-manager` / `db_manager`) for structural inspection, browsing, search, online backup, exports, consistency checks, and conservative transactional editing.

**Architecture:** Layered standard-library Python architecture with clean boundaries: connection management with strict read-only/write authorizers, schema and database inspector, parameterized query/search engines with quoted identifier validation, streaming export engine with CSV formula escaping, live online SQLite backup engine with provenance manifest, and typed optimistic-concurrency transactional modification planner.

**Tech Stack:** Python 3.10+, standard library `sqlite3`, `argparse`, `pathlib.Path`, `hashlib`, `dataclasses`, and `pytest`.

**Spec:** `modules/db_manager/docs/02_sqlite_database_manager_handoff.md`

## Global Constraints

- Standalone module inside `modules/db_manager/` with entry point `db-manager = "db_manager.cli:main"`.
- Every user-facing CLI flag must have both a single-dash short form and double-dash long form (`-X` and `--long-name`), including `-V/--version`.
- Entry point addition is a MAJOR version change in this repository (`1.0.0`).
- Test temp roots must stay inside `modules/db_manager/.pytest_tmp_root/`.
- Test files must follow `*_test.py` naming convention.
- App modules (such as `script_logging`) own schemas and migrations; `db_manager` must not own or run app migrations.
- Read-only connections must never create files, write WAL/SHM artifacts when avoidable, attach external databases, load extensions, or execute mutating SQL.
- Mutating commands must default to dry-run preview (`-n/--dry-run`) and require explicit `-w/--write`.
- Modifying single rows requires single-row primary key targeting and optimistic concurrency checks (`WHERE pk = ? AND (col = ? OR ...)`), failing if rowcount != 1.
- CSV exports must escape spreadsheet formula injection characters (`=`, `+`, `-`, `@`, `\t`, `\r`).
- Online backups must use `sqlite3.Connection.backup` API and produce an audit manifest with SHA256 checksums and verification results.

## Review Focus

1. **Unchecked File Creation on Read-Only Open**: A non-existent file path passed to `info`, `tables`, `schema`, `browse`, `search`, `query`, or `check` must raise a clear `FileNotFoundError` or actionable CLI error without creating an empty database file or parent directory.
2. **SQL Injection through Table/Column Names**: Unsanitized identifiers in browse, search, or dynamic predicates must never allow SQL injection. Identifiers must be validated against schema and strictly double-quoted (`"col"` with internal `""` escaping).
3. **Multi-Row Unintended Update/Delete**: A poorly formed or non-unique primary-key predicate must not update or delete multiple rows. Concurrency check must assert `cursor.rowcount == 1` and rollback on zero or >1 rows.
4. **Formula Injection in CSV Exports**: Values beginning with `=`, `+`, `-`, `@`, tab, or return in CSV output must be escaped so spreadsheet software does not execute them as formulas.
5. **Backup/Restore Race and Stale WAL/SHM State**: Backing up while active writers run must use the official `Connection.backup` API, not raw file copies. Restoring over an existing database must check provenance, require explicit confirmation, create a target backup, and clean stale WAL/SHM files safely.

---

## Task Decomposition

### Task 1: Package Scaffolding, Standards Compliance & Connection Safety
- Setup `pyproject.toml`, `README.md`, `db_manager/__init__.py`.
- Implement `db_manager/connections.py` with read-only connection enforcing URI `file:{path}?mode=ro`, `PRAGMA query_only=ON`, busy timeout, disabled extension loading, and strict SQLite authorizer denying DDL, DML, ATTACH, DETACH, VACUUM, and unsafe PRAGMAs.
- Implement write connection helper with foreign key enforcement and extension blocking.
- Add tests in `tests/connections_test.py`.

### Task 2: Structural Inspection & Health Checking (P0)
- Implement `db_manager/inspector.py`:
  - `DatabaseInfo`: file size, format/version, page size/count, journal mode, WAL presence, schema/user version, object counts, app ID, FK mode, timestamps.
  - `TableInfo`: column details, primary keys, foreign keys, indexes, without-rowid detection, estimated vs exact row counts.
  - `TableSchema`: DDL from sqlite_master/sqlite_schema.
  - `check_database`: `PRAGMA quick_check`, optional `integrity_check`, and `foreign_key_check`.
- Add tests in `tests/inspector_test.py`.

### Task 3: Bounded Query, Parameterized Search, and Table Browsing (P0)
- Implement `db_manager/query.py`:
  - Identifier quoting and schema validation.
  - `execute_readonly_query`: bounded read-only query with authorizer and row factory.
  - `browse_table`: paginated rows with column projection, filtering, sorting, NULL display (`<NULL>`), and bounded BLOB hex previews.
  - `search_table`: parameterized text/JSON search with indexed equality/range options and scan warning labels.
- Add tests in `tests/query_test.py`.

### Task 4: Online Consistent Backup, Audit Manifest & Export Engine (P0)
- Implement `db_manager/backup.py`:
  - `backup_database`: online `sqlite3.Connection.backup` to new destination, SHA256 checksums, and JSON manifest.
  - `restore_database`: restore to new file or validated overwrite with pre-backup and integrity check.
- Implement `db_manager/export.py`:
  - `export_table`: JSON, JSONL, CSV with formula injection escaping, and SQL dump via `iterdump()`.
- Implement `db_manager/discover.py`:
  - Discover known toolkit database paths safely without file mutation or privacy leaks.
- Add tests in `tests/backup_test.py` and `tests/export_test.py`.

### Task 5: P0 CLI Implementation & Subcommands
- Implement `db_manager/cli.py` with P0 subcommands: `info`, `tables`, `schema`, `browse`, `search`, `query`, `export`, `check`, `backup`, `discover`.
- Ensure every flag has `-X` and `--long-name`, plus `-V/--version`.
- Add CLI smoke tests in `tests/cli_test.py`.

### Task 6: Conservative Transactional Editing & Compare Engine (P1)
- Implement `db_manager/changes.py`:
  - Database initialization (`init`) with dry-run schema execution.
  - Single-row edit (`edit`), insert (`insert`), and delete (`delete`) with optimistic concurrency checks, pre-write backup, foreign key checks, and atomic rollbacks.
  - Mutation SQL runner (`sql`) requiring explicit `-w/--write`.
  - Database schema and row comparison (`compare`).
- Add tests in `tests/changes_test.py` and `tests/compare_test.py`.

### Task 7: Recovery Diagnostics, TUI Presentation & Registry Integration (P2)
- Implement `db_manager/recovery.py`: recovery diagnostics, external SQLite CLI `.recover` invocation to new output with caveats.
- Implement `db_manager/tui.py`: clean terminal tables and formatted inspection displays.
- Integrate P1 & P2 commands into `db_manager/cli.py`.
- Register `db-manager` in `modules/scripts_help/scripts_help/registry/registry.py`.
- Run full test suite, lint, and formatting checks (`pytest`, `ruff check`, `ruff format`).
- Update documentation and freeze handoffs.
