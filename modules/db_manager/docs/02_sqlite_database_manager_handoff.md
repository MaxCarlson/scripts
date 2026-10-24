# Handoff 2 — Reusable SQLite Database Explorer and Safe Manager

**Repository:** `MaxCarlson/scripts` (`~/src/scripts`)  
**Planning baseline:** `origin/main` at `6fa307f3bd84761f6fe21f3700dceb9889fe090b`, 2026-10-24  
**Proposed new module:** `modules/db_manager/` (published CLI name `db-manager`, subject to collision check)  
**Scope:** General SQLite inspection, browsing, search, export, consistency checks, backups, and carefully gated editing/recovery. **Do not own `script_logging` schemas or implement launcher and scripts-help UI functionality.**

## 1. Recommendation and tradeoff

A small reusable SQLite module is worthwhile: the repository already has multiple SQLite consumers (`script_logging`, Runmux, MangaDL, Compresser, scheduler and others), but no general purpose single CLI/TUI for inspecting databases. Build a **SQLite-first, read-only-first utility**, not a universal DB management framework. The Python standard-library `sqlite3` covers most needs; avoid PostgreSQL/MySQL/cloud connectors until real demand. Existing GUI tools such as DB Browser for SQLite are useful alternatives; this project is justified by terminal integration, safe scripted workflows and recoverable exports, not by replicating a full GUI.

**Architectural boundary:** app modules (especially `script_logging`) own their schemas, versioned migrations, business rules, and query APIs. `db_manager` understands generic SQLite structure and safety, but should not directly mutate application-owned data except under explicit user-controlled recovery/maintenance operations. Scripts-help consumes `script_logging` APIs, **not** raw SQL through `db_manager`.

## 2. Existing repository integration

Verified `modules/script_logging/script_logging/store.py` uses SQLite with `HistoryStore`, `EventRecord`, and `RunRecord`. The launcher handoff adds invocation storage, likely in an independent `invocations.sqlite3`. Other SQLite usage was observed in modules including `runmux`, `mangadl`, `compresser`, `agent_sync`, and `knowledge_manager`; inspect their current code/config before creating discovery rules. Never assume every file ending `.db` or `.sqlite3` belongs to this toolkit. This new module must be independently useful for arbitrary user-supplied SQLite databases and must not import each application.

Before editing read `MODULE_STANDARDS.md`, `docs/agent/PYTHON_REPO_STANDARDS.md`, `docs/agent/SCRIPTS_REPO_STANDARDS.md`, and relevant migration docs. Work on an isolated feature branch/worktree. Coordinate with cli_tui modernization to avoid simultaneous edits to `cli_tui` files.

## 3. Scope by phase

### P0 — Useful, safe read-only explorer

- `info`: database file size, SQLite format/version, page size/count, journal mode, WAL presence, schema/user version, table/view/index/trigger counts, app ID (when present), FK mode and file metadata; clearly distinguish reported data from assumptions.
- `tables`: list database objects with row estimates or **optional** exact counts; exact `COUNT(*)` can be expensive, so do not trigger on every screen refresh. Show primary keys, foreign keys, indexes, and columns.
- `schema`: show SQL DDL from `sqlite_master`/`sqlite_schema`, foreign keys, index definitions, constraints and types. Never assume `rowid` exists (consider WITHOUT ROWID and virtual tables).
- `browse`: bounded paginated rows, projection/column selection, per-column filter, sorting, null handling and detail view for wide text/JSON/BLOBs. BLOB preview bounded; hex metadata and size first, no arbitrary decoder execution.
- `search`: search selected table(s), fields and string values with properly parameterized predicates; include text/JSON search where applicable. Provide indexed equality/range operations and explicitly label slow full scans. Use quoted identifiers from validated schema **only**; values always use SQL parameters.
- `query`: optional bounded **read-only** SELECT/EXPLAIN interface for advanced use, off by default for unsafe expressions. Set `PRAGMA query_only=ON`, disable extension loading, require a strict SQLite authorizer or equivalent to deny ATTACH/DETACH, DDL, DML, vacuum, and unsafe PRAGMAs. SQLite's `mode=ro` URI protects the database file; guard against side effects or access to unrelated attached files as well.
- `export`: JSON, JSONL and CSV, plus a portable SQL dump for read-only use. Escape spreadsheet formula injection in CSV when opened by Excel; document the choice. Export to a **new file by default**, with explicit overwrite and bounded BLOB handling.
- `check`: read-only `PRAGMA quick_check` and optional `integrity_check`, foreign-key verification and structured diagnostics; indicate that a successful integrity check does not mean application-level correctness.
- `backup`: consistent online SQLite backup using the standard `sqlite3.Connection.backup` API, producing a **new destination**. Do not naively copy only the main file while WAL transactions are active. Record a manifest (source, timestamp, version, checksums of final backup, validation results) without sensitive data.
- `discover`: opt-in shortcuts to known local toolkit DB paths (not a recursive disk-wide crawl); users can supply any arbitrary DB file. Discovery must not reveal private filenames through logging, and must not initialize missing DBs.

### P1 — Conservative, transactional editing

- `init`: create a **new empty SQLite DB**, or apply user-supplied schema SQL to a new DB after a dry-run plan. Do not initialize/migrate `script_logging` schema; its application owns that.
- `edit`: inspect a single row by stable primary-key predicate, show old/new values and generated parameterized UPDATE; require explicit `-w/--write` and an optional backup. Prefer optimistic concurrency (`WHERE primary_key AND prior-values-or-version`) and abort if exactly one row was not affected. Do not silently update an arbitrary multi-row selection.
- `insert`/`delete`: similarly explicit one-table operations with preview, confirmations for destructive operations, FK enforcement and transaction rollback on error. Multi-row updates/deletes initially out of scope unless separate batch plan with exact row count and explicit authorization.
- `sql -w/--write`: optional advanced arbitrary mutations, **separate from read-only `query`**, warning/confirmation and forced backup/snapshot unless consciously overridden; reject ATTACH and extension loading even in write mode. No user-defined SQL script gets silently elevated.
- `restore`: never restore over a live application DB by default. Restore into a new path, run integrity checks, then require the user to stop the owning application and separately confirm replacement. Verify backup provenance and avoid stale WAL/SHM reuse. Provide rollback to previous on-disk copy.
- `compare`: schema-only diff and optional keyed row comparison between independent DBs, bounded output.

### P2 — Optional interactive UI and focused recovery

Use reusable **`cli_tui` generic list/detail/table/document components** once available. A Python-side CLI with JSON output remains authoritative for automation and Termux compatibility. For recovery, offer inspection of latest valid backups, integrity diagnostics, and restore-to-new-file; optionally invoke the external SQLite CLI `.recover` into a **new** output with clear caveats. Deleted rows cannot generally be reconstructed from an ordinary SQLite DB without backups or surviving journal/WAL data; do not promise forensic recovery or automatic repair of corrupted files. If no viable backup exists, provide a diagnostic/export report rather than modifying source bytes.

## 4. CLI shape (provisional; conform to repo rules)

Use argparse subcommands and **both a single-dash short and double-dash long name for every user-facing optional flag**, including `-V/--version`. Preserve reserved repository conventions: `-i/--input-file` for a DB input path; `-f/--force` for force; `-c/--config` for configuration; `-t/--threads` only if needed. Use `-T/--table`, `-C/--column`, `-K/--primary-key`, `-Q/--sql-query`, `-P/--pattern`, `-l/--limit`, `-s/--sort`, `-o/--output-dir` (only when semantically a directory), `-n/--dry-run`, `-w/--write`, `-v/--verbose`, `-q/--quiet`. Use `--` only as argv separator, not a flag. Any CLI command that can modify source data must be dry-run/preview-only unless explicitly written. Suggested usage:

```text
db-manager info -i PATH
db-manager tables -i PATH
db-manager schema -i PATH -T TABLE
db-manager browse -i PATH -T TABLE -l 100
db-manager search -i PATH -T TABLE -C COLUMN -P PATTERN
db-manager query -i PATH -Q 'SELECT ...' -l 100
db-manager check -i PATH
db-manager backup -i PATH -o BACKUP_DIR -n
db-manager backup -i PATH -o BACKUP_DIR -w
db-manager restore -i BACKUP -o NEW_DIR -w
db-manager edit -i PATH -T TABLE -K PRIMARY_KEY -n
db-manager edit -i PATH -T TABLE -K PRIMARY_KEY -w
```

Examples are **contract sketches**: settle actual short-letter collisions and single-file-vs-directory semantics in parser design, and produce accurate documentation. Do not implement invalid/no-op flags simply to meet syntax conventions. For freeform SQL, bounded JSON output, and tables containing quoted identifiers, write real parsing/quoting tests rather than string interpolation.

## 5. Safety design

**Read-only connection:** open with SQLite URI `mode=ro`, `PRAGMA query_only=ON`, `busy_timeout`, `row_factory`, limits where available, disabled extension loading, and a restrictive authorizer for user SQL. The read-only path must not create parent directories or a DB. Reading a live WAL DB may involve SQLite's legitimate WAL/SHM interaction; report errors cleanly without fallback to writable mode. Allow caller-specified snapshot/backups when live DB access is impossible.

**Trusted paths:** accept explicit user-selected paths, not arbitrary remote URLs. Resolve symlinks carefully; use path ownership/permissions checks before any write or restore. Do not follow untrusted symlinks to arbitrary destructive targets. Restrict output truncation, search time/rows, BLOB size and string lengths; support cancellation. Avoid dynamic loading of SQLite extensions and arbitrary shell commands.

**Modification flow:** gather plan → show affected database/table/key/columns, predicted row count, integrity/backup status and risks → acquire bounded transaction → confirm expected row identity/version → apply one atomic change → audit result → verify updated state. Treat DB writes as potentially irreversible and require explicit user authorization. No application migrations through the generic editor. Default backup-before-write; if disabled, require a separate conspicuous acknowledgement.

**Exports:** exports can contain credentials, historical URLs and local paths. Default to local private output files with safe permissions, never remote sync or repository paths. Do not automatically surface raw secret-bearing values in the TUI preview; allow masked views and explicit reveal mode.

## 6. API and layering

Target a straightforward split:

```text
modules/db_manager/
  pyproject.toml
  README.md
  db_manager/
    __init__.py
    cli.py
    connections.py       # read-only vs write connection policy
    inspector.py         # schema, tables, columns, indexes, statistics
    query.py             # bounded query/search, identifier validation
    export.py            # JSON/CSV/JSONL/dump
    backup.py            # SQLite backup, validation, restore-to-new
    changes.py           # typed edit plans and transactional apply
    tui.py               # optional adapter, no business logic
  tests/
    db_manager_test.py
```

Public result classes should be stable, serializable, and testable without curses. DB path resolution for the **invocation DB** remains in `script_logging`; `db_manager` may consume that path only to provide a convenience shortcut such as `db-manager discover`, not to redefine it. Avoid sqlite adapters for unrelated database engines until a second backend warrants a formal interface.

## 7. Acceptance tests

1. `tmp_path` synthetic databases: empty DB, WAL live writer, JSON, BLOB, NULL, compound PK, WITHOUT ROWID, views, triggers, virtual tables, names requiring quoting, Unicode names and values.
2. Read-only query cannot mutate, attach unrelated DBs, load extensions, or invoke file-writing side effects; file and parent directories unchanged after browse/search/query.
3. Parameterized search resists injection in values and identifiers; bounded rows/cancellation work; stable sort/page behavior; no accidental full-database reads by default.
4. Safe online backup while synthetic writer is active; restore-to-new-path verified with integrity check and representative data comparison; no production DB touched.
5. Edit/insert/delete are dry-run by default and require explicit write; reject zero/multiple key match, stale-row concurrency and FK violations; rollback leaves source untouched.
6. Invalid/corrupt/locked/encrypted/not-a-SQLite DBs produce actionable errors; `.recover` absent is reported honestly. Never claim deleted rows can be restored without evidence.
7. Cross-platform Windows/WSL2/Termux/macOS path and permissions tests where platforms available. CLI flags all have short+long forms, `-V/--version`, valid packaging/registry/README version, `*_test.py` naming, no outside-test writes.
8. `ruff check`, pytest, synthetic CLI smoke tests, documentation examples and actual measured performance for large tables; state precisely which platforms were tested.

## 8. Deliverables and interface freeze

Create `db_manager` as a **new module**, with entry point governed by repo MAJOR-on-entrypoint-change convention (new module initial release per standards), package README version comment, docs, registry entry, full source and tests. Include CLI/TUI screenshots only if generated from validated functionality. Deliver a safety model and operation matrix (read-only vs write/restore), a `db-manager --help` transcript, restoration procedure, example DB fixtures, and validation evidence. Coordinate with scripts-help agent only on optional generic table widget API. **Do not put invocation-summary reconciliation or app-specific schema migrations in this module**; those remain with `script_logging`.
