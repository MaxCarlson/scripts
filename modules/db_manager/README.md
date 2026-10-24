<!-- version: 1.0.0 -->
# db-manager

Reusable SQLite database explorer, inspector, online backup utility, and safe transactional manager.

`db-manager` is a SQLite-first, read-only-first command line tool and Python library designed for terminal integration, safe scripted workflows, and recoverable operations across arbitrary SQLite databases.

## Features

- **Read-Only Safety**: Enforces `mode=ro`, `PRAGMA query_only = ON;`, busy timeout, disabled extensions, and a strict SQLite authorizer preventing unauthorized mutations, ATTACH, DETACH, or VACUUM. Non-existent files are never accidentally created.
- **Deep Structural Inspection**: Detailed format/version, page size, WAL presence, schema and user version, object counts, table definitions, primary keys, foreign keys, indexes, and WITHOUT ROWID detection.
- **Bounded Browsing & Search**: Paginated row viewing, column projection, sorting, NULL indicator (`<NULL>`), bounded hex preview for BLOBs, and parameterized search across tables and columns. Identifiers are strictly validated and quoted.
- **Online Hot Backups**: Consistent backups using `sqlite3.Connection.backup` that handle active WAL transactions safely and generate an audit manifest with SHA256 checksums.
- **Formula-Safe Exports**: Export tables or query results to JSON, JSONL, CSV, and portable SQL dump. CSV exporter automatically escapes dangerous spreadsheet formula prefixes (`=`, `+`, `-`, `@`, `\t`, `\r`).
- **Conservative Transactional Editing**:
  - All mutating commands require explicit `-w/--write` (defaulting to dry-run preview `-n/--dry-run`).
  - Single-row edit/delete targeting primary keys with optimistic concurrency checks (`WHERE pk = ? AND (col = ? OR ...)`), failing immediately if row count != 1.
  - Automatic pre-write backup before modifying files.
  - Full transaction rollback on errors.
- **Safe Recovery**: Corruption diagnosis, backup verification, and non-destructive data extraction.

## CLI Usage

Every flag provides both a short single-dash form and a long double-dash form:

```bash
# Inspection & Health Check
db-manager info -i /path/to/db.sqlite3
db-manager tables -i /path/to/db.sqlite3 [-e/--exact-count]
db-manager schema -i /path/to/db.sqlite3 [-T/--table my_table]
db-manager check -i /path/to/db.sqlite3 [-c/--integrity-check]

# Browse, Search & Query
db-manager browse -i /path/to/db.sqlite3 -T my_table -l 50 [-p/--page 1] [-s/--sort id]
db-manager search -i /path/to/db.sqlite3 -T my_table -P "search_text" [-C/--column name]
db-manager query -i /path/to/db.sqlite3 -Q "SELECT id, name FROM my_table WHERE status = 'active'" -l 100

# Exports
db-manager export -i /path/to/db.sqlite3 -T my_table -F csv -O output.csv [-f/--force]
db-manager export -i /path/to/db.sqlite3 -T my_table -F json -O output.json
db-manager export -i /path/to/db.sqlite3 -F sql -O dump.sql

# Online Consistent Backup & Restore
db-manager backup -i /path/to/db.sqlite3 -O /backups/db.bak -n   # Preview / dry run
db-manager backup -i /path/to/db.sqlite3 -O /backups/db.bak -w   # Execute backup
db-manager restore -i /backups/db.bak -O /path/to/restored.db -w

# Conservative Transactional Editing
db-manager init -i /path/to/new.db [-S/--schema-file schema.sql] -n
db-manager init -i /path/to/new.db [-S/--schema-file schema.sql] -w
db-manager edit -i /path/to/db.sqlite3 -T users -K id=42 --set status=inactive -n
db-manager edit -i /path/to/db.sqlite3 -T users -K id=42 --set status=inactive -w
db-manager insert -i /path/to/db.sqlite3 -T users --values '{"id": 43, "name": "Alice"}' -w
db-manager delete -i /path/to/db.sqlite3 -T users -K id=43 -w
db-manager sql -i /path/to/db.sqlite3 -Q "UPDATE users SET status = 'active' WHERE id = 1" -w

# Compare
db-manager compare -1 /path/to/db1.sqlite3 -2 /path/to/db2.sqlite3

# Discovery
db-manager discover
```

## Python Library API

```python
from pathlib import Path
from db_manager.connections import get_readonly_connection, get_write_connection
from db_manager.inspector import inspect_database, list_tables, get_schema
from db_manager.query import browse_table, search_table, execute_readonly_query
from db_manager.backup import backup_database
from db_manager.export import export_table

db_path = Path("my_database.db")

# Inspect
info = inspect_database(db_path)
print(f"Format: {info.format}, Page size: {info.page_size}, Tables: {info.table_count}")

# Read-only query
with get_readonly_connection(db_path) as conn:
    tables = list_tables(conn)
    result = browse_table(conn, table=tables[0].name, limit=25)
    print(f"Fetched {len(result.rows)} rows")

# Online backup with audit manifest
manifest = backup_database(db_path, Path("backup.db"), force=True)
print(f"Backup completed with SHA256 {manifest.destination_sha256}")
```
