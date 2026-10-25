<!-- version: 1.0.0 -->
# db-manager

Reusable SQLite database explorer, inspector, online backup utility, and safe transactional manager.

`db-manager` is a SQLite-first, read-only-first command line tool and Python library designed for terminal integration, safe scripted workflows, and recoverable operations across arbitrary SQLite databases.

---

## 1. Architectural Boundary & Separation of Ownership

`db-manager` is built as an independent, general-purpose utility:
- **Generic SQLite Structure**: Underneath, it understands SQLite metadata, B-tree tables, `WITHOUT ROWID` tables, views, triggers, indexes, WAL journals, and page structures.
- **Application Boundaries**: Application modules (such as `script_logging`, `runmux`, `mangadl`, `compresser`) own their schemas, versioned migrations, business logic, and query APIs. `db_manager` does **not** define, modify, or migrate application-specific schemas.
- **No Unintended Mutations**: `db_manager` never mutates application-owned databases during inspection, browsing, search, or discovery.
- **Consumer Interfaces**: User-facing tools such as `scripts-help` consume `script_logging` APIs for invocation metrics—they do not bypass application business rules with raw SQL queries through `db_manager`.

---

## 2. Installation & Environment Setup

### Direct Package Installation (Editable Development)

From the repository root:
```bash
# In the active repository virtual environment (.venv)
python -m pip install -e modules/db_manager
```
Or via `uv`:
```bash
uv pip install -e modules/db_manager
```

### Generated Entry Points & Launchers

1. **Console Script Entry Point**:
   `[project.scripts]` in `pyproject.toml` registers `db-manager = "db_manager.cli:main"`.
   When installed in the repository virtual environment, Python creates `.venv/Scripts/db-manager.exe` (Windows) or `.venv/bin/db-manager` (Linux/macOS/Termux).

2. **Root Launcher Wrapper (`bin/db-manager.cmd`)**:
   The toolkit provides a managed launcher shim in `bin/` that delegates to `script_logging.launcher`:
   ```cmd
   "%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command "db-manager" -- %*
   ```
   > **Note on Exit Code 127**: If `bin/db-manager.cmd` reports `Error: Target '.venv\Scripts\db-manager.exe' does not exist` (exit code 127), run `python -m pip install -e modules/db_manager` or `python setup.py` to compile the console script executable into the active virtual environment.

3. **Direct Module Invocation**:
   Even without entry points installed, `db_manager` can always be executed directly via Python:
   ```bash
   python -m db_manager.cli --help
   ```

---

## 3. Published Subcommands & Short/Long Flag Reference

Every user-facing optional flag strictly implements both a single-dash short form and a double-dash long form:

| Subcommand | Primary Short/Long Flags | Purpose |
|---|---|---|
| `info` | `-i, --input-file`<br>`-j, --json` | Database file size, page size, page count, WAL status, user/schema versions, and object counts. |
| `tables` | `-i, --input-file`<br>`-e, --exact-count`<br>`-j, --json` | List tables, views, column counts, primary keys, foreign keys, and optional exact row counts. |
| `schema` | `-i, --input-file`<br>`-T, --table`<br>`-j, --json` | Display SQL DDL from `sqlite_master`, columns, foreign keys, and index definitions. |
| `browse` | `-i, --input-file`<br>`-T, --table`<br>`-l, --limit`<br>`-p, --page`<br>`-c, --columns`<br>`-C, --column`<br>`-F, --filter`<br>`-O, --operator`<br>`-s, --sort`<br>`-d, --desc`<br>`-j, --json` | Bounded paginated viewing of rows, column projections, per-column filters, and ASC/DESC sorting. |
| `search` | `-i, --input-file`<br>`-T, --table`<br>`-P, --pattern`<br>`-C, --column`<br>`-l, --limit`<br>`-j, --json` | Parameterized text/pattern search. Warns explicitly on unindexed full-table scans. |
| `query` | `-i, --input-file`<br>`-Q, --sql-query`<br>`-l, --limit`<br>`-t, --timeout`<br>`-j, --json` | Bounded read-only `SELECT` / `EXPLAIN` query execution with progress handler and timeout enforcement. |
| `export` | `-i, --input-file`<br>`-O, --output-file`<br>`-T, --table`<br>`-F, --format`<br>`-l, --limit`<br>`-f, --force`<br>`-j, --json` | Export tables or entire database to CSV, JSON, JSONL, or portable SQL dump with formula escaping. |
| `check` | `-i, --input-file`<br>`-c, --integrity-check`<br>`-k, --foreign-keys`<br>`-j, --json` | Run `PRAGMA quick_check`, optional `PRAGMA integrity_check`, and `PRAGMA foreign_key_check`. |
| `backup` | `-i, --input-file`<br>`-O, --output-file`<br>`-n, --dry-run`<br>`-w, --write`<br>`-f, --force`<br>`-j, --json` | Consistent online hot backup via `Connection.backup` API with cryptographic audit manifest. |
| `restore` | `-i, --input-file`<br>`-O, --output-file`<br>`-n, --dry-run`<br>`-w, --write`<br>`-f, --force`<br>`-j, --json` | Safe restore to new file or pre-backed-up target under continuous `BEGIN EXCLUSIVE` lock. |
| `discover` | `-j, --json` | Opt-in shortcuts discovering known local toolkit database paths without disk-wide crawling. |
| `init` | `-i, --input-file`<br>`-S, --schema-file`<br>`-s, --schema-sql`<br>`-n, --dry-run`<br>`-w, --write`<br>`-f, --force`<br>`-j, --json` | Create new database or apply DDL via pre-init backup, temporary isolated DB, and atomic copy. |
| `edit` | `-i, --input-file`<br>`-T, --table`<br>`-K, --primary-key`<br>`-S, --set`<br>`-n, --dry-run`<br>`-w, --write`<br>`-B, --skip-backup`<br>`-j, --json` | Single-row update targeting primary key with optimistic concurrency snapshot check and rollback. |
| `insert` | `-i, --input-file`<br>`-T, --table`<br>`-V, --values`<br>`-n, --dry-run`<br>`-w, --write`<br>`-B, --skip-backup`<br>`-j, --json` | Single-row insert with foreign key enforcement and transaction rollback on error. |
| `delete` | `-i, --input-file`<br>`-T, --table`<br>`-K, --primary-key`<br>`-n, --dry-run`<br>`-w, --write`<br>`-B, --skip-backup`<br>`-j, --json` | Single-row deletion targeting primary key with optimistic concurrency snapshot check. |
| `sql` | `-i, --input-file`<br>`-Q, --sql-query`<br>`-n, --dry-run`<br>`-w, --write`<br>`-B, --skip-backup`<br>`-j, --json` | Advanced arbitrary mutation execution requiring explicit `-w/--write`; blocks ATTACH/DETACH. |
| `compare` | `-1, --db1`<br>`-2, --db2`<br>`-l, --limit`<br>`-F, --full`<br>`-j, --json` | Compare schema DDL, table structures, and deterministic row samples or full content diffs. |
| `recover` | `-i, --input-file`<br>`-O, --output-file`<br>`-f, --force`<br>`-j, --json` | Header validation, discovery of nearby `.bak` snapshots, and external `sqlite3 .recover` execution. |

Global options available on every subcommand:
- `-V, --version`: Show program version and exit.
- `-v, --verbose`: Enable detailed debug output.
- `-q, --quiet`: Suppress non-essential informational messages.
- `-h, --help`: Show detailed argument help.

---

## 4. Machine-Readable JSON Output

Every subcommand supports `-j/--json`. When specified, `db-manager` suppresses human-oriented ASCII borders and prints structured, parseable JSON directly to standard output:

```bash
# Get database info in JSON
db-manager info -i /path/to/db.sqlite3 -j

# Get tables in JSON
db-manager tables -i /path/to/db.sqlite3 -e -j

# Execute query in JSON
db-manager query -i /path/to/db.sqlite3 -Q "SELECT id, name FROM users" -j
```

---

## 5. Security & Safety Model

1. **Strict Read-Only Guarantee**:
   - Connections open using SQLite URI `mode=ro` and `PRAGMA query_only = ON;`.
   - Never creates non-existent database files or directories when opening in read-only mode.
   - Authorizer callback denies `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, `ALTER`, `ATTACH`, `DETACH`, `VACUUM`, and mutating `PRAGMA`s (e.g. `user_version = ...`, `synchronous = ...`, `foreign_keys = OFF`).
   - Runaway queries (such as infinite recursive CTEs or accidental Cartesian joins) are intercepted via a VM step progress handler and terminated cleanly with a `TimeoutError`.

2. **Conservative Mutation Protocol**:
   - All mutating commands default to dry-run mode (`-n/--dry-run`). The user must explicitly pass `-w/--write`.
   - Before applying any mutation, `db_manager` automatically generates a pre-write backup (`.pre-<operation>-<timestamp>.bak`) unless explicitly bypassed with `-B/--skip-backup`.
   - Single-row `edit` and `delete` operations enforce strict optimistic concurrency:
     ```sql
     WHERE ("id" = ?) AND ("name" IS ? AND "status" IS ?)
     ```
     This check combines the primary-key predicate with a NULL-safe snapshot check of all originally observed columns, preventing accidental cross-row collisions or race conditions. If the query does not affect exactly one row, the transaction immediately rolls back and raises an error.

3. **CSV Formula Injection Prevention**:
   - In accordance with spreadsheet security standards, any text field in a CSV export starting with `=`, `+`, `-`, `@`, `\t`, or `\r` is automatically neutralized by prepending a single quote (`'`).

4. **Online WAL Hot Backups**:
   - Backups use SQLite's native `Connection.backup` API, streaming database pages while preserving consistency even with active WAL writers.
   - The backup audit manifest explicitly records both the raw source file checksum and the logical WAL-consistent snapshot checksum.

5. **Safe Restoration**:
   - Restores maintain exclusive database ownership via `PRAGMA locking_mode = EXCLUSIVE;` and `BEGIN EXCLUSIVE;`.
   - Never deletes or unlinks live `-wal` or `-shm` files manually; SQLite manages its own transaction logs atomically.
   - If restoration fails, pre-existing database files are preserved intact.

---

## 6. Safe Backup & Restore Walkthrough

```bash
# 1. Preview online backup (dry run)
db-manager backup -i /data/app.sqlite3 -O /backups/app-20261025.bak -n

# 2. Execute online hot backup
db-manager backup -i /data/app.sqlite3 -O /backups/app-20261025.bak -w

# 3. Check integrity of backup snapshot
db-manager check -i /backups/app-20261025.bak -c

# 4. Restore backup into a new location
db-manager restore -i /backups/app-20261025.bak -O /data/restored_app.sqlite3 -w
```

---

## 7. Platform & Permission Considerations

- **Windows File Locks**: On Windows, open SQLite connections retain file locks. If a target database is held by a live application with uncommitted transactions, `restore` and `init -f` will wait up to the configured `busy_timeout` (default 5-10s) before raising a locked error.
- **Unprivileged Symlinks**: `db_manager` uses `Path.resolve()` to safely resolve paths across Linux, WSL2, macOS, and Windows. Note that creating symlinks on Windows requires administrative privileges or Developer Mode.
- **Read-Only Media**: When inspecting databases on read-only filesystems or CD/DVD images, SQLite WAL mode may fail if temporary files cannot be created in the database directory. In such cases, use `query` or `backup` to stream data to a writable destination.

---

## 8. Synthetic `script_logging` Telemetry Inspection Example

To inspect an application database (such as `script_logging` or `runmux`) in a completely non-destructive, read-only manner:

```bash
# Inspect metadata and table counts
db-manager info -i modules/script_logging/history.sqlite3

# View schema definition of events table
db-manager schema -i modules/script_logging/history.sqlite3 -T events

# Browse latest run events with pagination
db-manager browse -i modules/script_logging/history.sqlite3 -T events -l 25 -s timestamp -d

# Search for errors across all columns
db-manager search -i modules/script_logging/history.sqlite3 -T events -P "ERROR"

# Execute a safe aggregation query
db-manager query -i modules/script_logging/history.sqlite3 \
  -Q "SELECT level, count(*) as count FROM events GROUP BY level"
```

---

## 9. Python API Usage

```python
from pathlib import Path
from db_manager.connections import get_readonly_connection, get_write_connection
from db_manager.inspector import inspect_database, list_tables, get_schema
from db_manager.query import browse_table, search_table, execute_readonly_query
from db_manager.backup import backup_database
from db_manager.export import export_table

db_path = Path("my_database.sqlite3")

# Inspect database
info = inspect_database(db_path)
print(f"Page size: {info.page_size}, Tables: {info.table_count}, WAL: {info.wal_file_present}")

# Read-only query execution
with get_readonly_connection(db_path) as conn:
    tables = list_tables(conn)
    result = browse_table(conn, table=tables[0].name, limit=25)
    print(f"Fetched {len(result.rows)} rows from {tables[0].name}")

# Consistent online hot backup with cryptographic manifest
manifest = backup_database(db_path, Path("backup.sqlite3"), force=True)
print(f"Backup completed with SHA256 {manifest.destination_sha256}")
```
