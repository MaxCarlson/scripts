# db_manager Documentation

`db_manager` is a reusable, safe SQLite database explorer, inspector, backup utility, and transactional manager for the `scripts` automation toolkit and arbitrary user databases.

## Scope & Architectural Boundary

- **Core focus**: SQLite-first, read-only-first exploration, parameterized query/search, structural inspection, online backups, exports, consistency checks, and conservative transactional editing.
- **Application boundaries**: Application modules (such as `script_logging`, `runmux`, `mangadl`, `compresser`) own their schemas, versioned migrations, business logic, and query APIs. `db_manager` does **not** own application-specific schemas or manage application migrations.
- **Integration**: `scripts_help` consumes `script_logging` APIs, not raw SQL through `db_manager`. `db_manager` provides optional discovery shortcuts to known local toolkit databases without importing application packages or altering disk state.

## Safety Architecture

1. **Read-Only Enforcement**:
   - SQLite URI `file:{path}?mode=ro`.
   - `PRAGMA query_only = ON;`.
   - Busy timeout configured to avoid deadlocks.
   - Disabled extension loading.
   - Strict SQLite authorizer (`set_authorizer`) denying `ATTACH`, `DETACH`, DDL (`CREATE`, `DROP`, `ALTER`), DML (`INSERT`, `UPDATE`, `DELETE`), `VACUUM`, and unsafe `PRAGMA`s.
   - Non-existent files are never created on read-only calls.

2. **Conservative Transactional Editing**:
   - All mutations require explicit `-w/--write`; dry-run preview is the default (`-n/--dry-run`).
   - Row modifications require single-row primary-key resolution and optimistic concurrency checks (`WHERE pk = ? AND (col = ? OR ...)`).
   - Aborts if affected rowcount != 1.
   - Automatic pre-write backup before applying mutations.
   - Strict transaction rollbacks on errors.
   - ATTACH and extension loading remain blocked even in write mode.

3. **Backup & Restore**:
   - Online backup using `sqlite3.Connection.backup` API, preserving consistency across active WAL transactions.
   - Backups record an audit manifest (timestamps, sizes, SHA256 checksums, SQLite version, integrity checks).
   - Restore creates a new destination file by default and runs integrity checks. Overwriting live application DBs requires explicit user confirmation and pre-backup.

4. **Safe Exports**:
   - Formats: JSON, JSONL, CSV, and portable SQL dump.
   - CSV formula injection protection: fields starting with `=`, `+`, `-`, `@`, `\t`, or `\r` are safely escaped.
   - BLOB handling: bounded hex representation and byte sizes, avoiding uncontrolled binary dumping.

## Documentation Index

- [Original Handoff Specification](02_sqlite_database_manager_handoff.md)
- [Module Project Handoff](HANDOFF.md)
- [Plan Index](plans/HANDOFF.md)
- [Active Plan: 20261024-0925_sqlite-database-manager](plans/20261024-0925_sqlite-database-manager/00_implementation-plan.md)
