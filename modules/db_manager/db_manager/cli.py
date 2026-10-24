"""
cli.py — Command-line interface for db-manager.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys
from typing import Sequence

from db_manager import __version__
from db_manager.backup import backup_database, restore_database
from db_manager.changes import (
    compare_databases,
    execute_mutation_sql,
    init_database,
    parse_key_value_spec,
    plan_and_apply_delete,
    plan_and_apply_edit,
    plan_and_apply_insert,
)
from db_manager.connections import get_readonly_connection
from db_manager.discover import discover_known_databases
from db_manager.export import export_database_dump, export_table
from db_manager.inspector import (
    check_database,
    get_schema,
    inspect_database,
    list_tables,
)
from db_manager.query import (
    browse_table,
    execute_readonly_query,
    format_value_for_display,
    search_table,
)
from db_manager.recovery import (
    diagnose_database_recovery,
    execute_external_recover,
)
from db_manager.tui import format_key_values, format_table

logger = logging.getLogger("db_manager")


def build_parser() -> argparse.ArgumentParser:
    """Builds the top-level argument parser conforming to repository standards."""
    parser = argparse.ArgumentParser(
        prog="db-manager",
        description="Reusable SQLite Database Explorer, Inspector, Online Backup and Safe Manager.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"db-manager {__version__}",
        help="Show program version and exit.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output / debug logging.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-essential informational messages.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True, help="Subcommand to execute")

    # 1. info
    p_info = subparsers.add_parser("info", help="Inspect database metadata, page sizes, WAL status, and object counts.")
    p_info.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_info.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 2. tables
    p_tables = subparsers.add_parser("tables", help="List database tables, views, columns, keys, and row counts.")
    p_tables.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_tables.add_argument("-e", "--exact-count", action="store_true", help="Perform exact COUNT(*) on each table.")
    p_tables.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 3. schema
    p_schema = subparsers.add_parser("schema", help="Show SQL DDL and structural definitions.")
    p_schema.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_schema.add_argument("-T", "--table", default=None, help="Specific table to inspect schema for.")
    p_schema.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 4. browse
    p_browse = subparsers.add_parser("browse", help="Bounded paginated browsing of table rows.")
    p_browse.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_browse.add_argument("-T", "--table", required=True, help="Table name to browse.")
    p_browse.add_argument("-l", "--limit", type=int, default=50, help="Row limit per page (default: 50).")
    p_browse.add_argument("-p", "--page", type=int, default=1, help="Page number (1-based, default: 1).")
    p_browse.add_argument("-c", "--columns", default=None, help="Comma-separated column projection.")
    p_browse.add_argument("-C", "--column", default=None, help="Filter column name.")
    p_browse.add_argument("-F", "--filter", default=None, help="Filter value.")
    p_browse.add_argument("-O", "--operator", default="=", help="Filter operator (=, !=, <, >, LIKE, default: =).")
    p_browse.add_argument("-s", "--sort", default=None, help="Sort column name.")
    p_browse.add_argument("-d", "--desc", action="store_true", help="Sort descending.")
    p_browse.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 5. search
    p_search = subparsers.add_parser("search", help="Parameterized search across table columns.")
    p_search.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_search.add_argument("-T", "--table", required=True, help="Table name to search.")
    p_search.add_argument("-P", "--pattern", required=True, help="Search string/pattern.")
    p_search.add_argument("-C", "--column", default=None, help="Specific column to search (default: all columns).")
    p_search.add_argument("-l", "--limit", type=int, default=50, help="Maximum matching rows to return.")
    p_search.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 6. query
    p_query = subparsers.add_parser("query", help="Bounded read-only SELECT / EXPLAIN query execution.")
    p_query.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_query.add_argument("-Q", "--sql-query", required=True, help="Read-only SQL query to execute.")
    p_query.add_argument("-l", "--limit", type=int, default=100, help="Row limit (default: 100).")
    p_query.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 7. export
    p_export = subparsers.add_parser("export", help="Export table or database to CSV, JSON, JSONL, or SQL dump.")
    p_export.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_export.add_argument("-T", "--table", default=None, help="Table name to export (omit for full SQL dump).")
    p_export.add_argument("-O", "--output-file", required=True, help="Output destination file.")
    p_export.add_argument(
        "-F", "--format", default="json", choices=["json", "jsonl", "csv", "sql"], help="Export format."
    )
    p_export.add_argument("-l", "--limit", type=int, default=None, help="Optional row limit.")
    p_export.add_argument("-f", "--force", action="store_true", help="Force overwrite existing destination.")
    p_export.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON summary.")

    # 8. check
    p_check = subparsers.add_parser("check", help="Run SQLite quick_check, integrity_check, and foreign_key_check.")
    p_check.add_argument("-i", "--input-file", required=True, help="Path to SQLite database file.")
    p_check.add_argument("-c", "--integrity-check", action="store_true", help="Perform deep PRAGMA integrity_check.")
    p_check.add_argument("-k", "--foreign-keys", action="store_true", default=True, help="Check foreign keys.")
    p_check.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 9. backup
    p_backup = subparsers.add_parser("backup", help="Perform consistent online hot backup using SQLite backup API.")
    p_backup.add_argument("-i", "--input-file", required=True, help="Source SQLite database path.")
    p_backup.add_argument("-O", "--output-file", required=True, help="Destination backup file path.")
    p_backup.add_argument(
        "-n", "--dry-run", action="store_true", default=False, help="Preview backup plan without copying."
    )
    p_backup.add_argument(
        "-w", "--write", action="store_true", default=False, help="Confirm execution of online backup."
    )
    p_backup.add_argument("-f", "--force", action="store_true", default=False, help="Overwrite destination if present.")
    p_backup.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON manifest.")

    # 10. restore
    p_restore = subparsers.add_parser("restore", help="Safely restore database from backup to target.")
    p_restore.add_argument("-i", "--input-file", required=True, help="Source backup file path.")
    p_restore.add_argument("-O", "--output-file", required=True, help="Destination target database path.")
    p_restore.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview restore plan.")
    p_restore.add_argument("-w", "--write", action="store_true", default=False, help="Execute restore.")
    p_restore.add_argument(
        "-f", "--force", action="store_true", default=False, help="Overwrite target with target backup."
    )
    p_restore.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON report.")

    # 11. discover
    p_discover = subparsers.add_parser("discover", help="Discover known toolkit SQLite databases without disk crawl.")
    p_discover.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 12. init
    p_init = subparsers.add_parser("init", help="Create new SQLite database or apply user-supplied schema SQL.")
    p_init.add_argument("-i", "--input-file", required=True, help="Target database path to initialize.")
    p_init.add_argument("-S", "--schema-file", default=None, help="SQL schema file to execute upon initialization.")
    p_init.add_argument("-s", "--schema-sql", default=None, help="Raw SQL string to execute upon initialization.")
    p_init.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview initialization plan.")
    p_init.add_argument(
        "-w", "--write", action="store_true", default=False, help="Confirm execution of database initialization."
    )
    p_init.add_argument("-f", "--force", action="store_true", default=False, help="Force overwrite existing database.")
    p_init.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 13. edit
    p_edit = subparsers.add_parser("edit", help="Single-row edit with optimistic concurrency check.")
    p_edit.add_argument("-i", "--input-file", required=True, help="Target database path.")
    p_edit.add_argument("-T", "--table", required=True, help="Table name to edit.")
    p_edit.add_argument("-K", "--primary-key", required=True, help="Primary key spec (col=val or JSON).")
    p_edit.add_argument("-S", "--set", dest="set_values", required=True, help="New column values (col=newval or JSON).")
    p_edit.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview edit plan.")
    p_edit.add_argument("-w", "--write", action="store_true", default=False, help="Confirm execution of edit.")
    p_edit.add_argument(
        "-B", "--skip-backup", action="store_true", default=False, help="Skip automatic pre-write backup."
    )
    p_edit.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 14. insert
    p_insert = subparsers.add_parser("insert", help="Single-row insert with foreign key enforcement.")
    p_insert.add_argument("-i", "--input-file", required=True, help="Target database path.")
    p_insert.add_argument("-T", "--table", required=True, help="Table name to insert into.")
    p_insert.add_argument("-V", "--values", required=True, help="Row values (col=val or JSON).")
    p_insert.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview insert plan.")
    p_insert.add_argument("-w", "--write", action="store_true", default=False, help="Confirm execution of insert.")
    p_insert.add_argument(
        "-B", "--skip-backup", action="store_true", default=False, help="Skip automatic pre-write backup."
    )
    p_insert.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 15. delete
    p_delete = subparsers.add_parser("delete", help="Single-row delete with optimistic concurrency check.")
    p_delete.add_argument("-i", "--input-file", required=True, help="Target database path.")
    p_delete.add_argument("-T", "--table", required=True, help="Table name to delete from.")
    p_delete.add_argument("-K", "--primary-key", required=True, help="Primary key spec (col=val or JSON).")
    p_delete.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview delete plan.")
    p_delete.add_argument("-w", "--write", action="store_true", default=False, help="Confirm execution of delete.")
    p_delete.add_argument(
        "-B", "--skip-backup", action="store_true", default=False, help="Skip automatic pre-write backup."
    )
    p_delete.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 16. sql
    p_sql = subparsers.add_parser(
        "sql", help="Arbitrary mutation SQL execution requiring explicit write authorization."
    )
    p_sql.add_argument("-i", "--input-file", required=True, help="Target database path.")
    p_sql.add_argument("-Q", "--sql-query", required=True, help="Mutation SQL string to execute.")
    p_sql.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview mutation plan.")
    p_sql.add_argument("-w", "--write", action="store_true", default=False, help="Confirm execution of SQL mutation.")
    p_sql.add_argument(
        "-B", "--skip-backup", action="store_true", default=False, help="Skip automatic pre-write backup."
    )
    p_sql.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 17. compare
    p_compare = subparsers.add_parser("compare", help="Compare schemas and row counts between two SQLite databases.")
    p_compare.add_argument("-1", "--db1", required=True, help="First database file.")
    p_compare.add_argument("-2", "--db2", required=True, help="Second database file.")
    p_compare.add_argument("-l", "--limit", type=int, default=50, help="Row comparison sample limit (default: 50).")
    p_compare.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")

    # 18. recover
    p_recover = subparsers.add_parser("recover", help="Non-destructive recovery diagnostics and .recover invocation.")
    p_recover.add_argument("-i", "--input-file", required=True, help="Damaged SQLite database file.")
    p_recover.add_argument(
        "-O", "--output-file", default=None, help="Destination output database for external recovery."
    )
    p_recover.add_argument("-f", "--force", action="store_true", help="Force overwrite recovery output file.")
    p_recover.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON report.")

    return parser


def handle_info(args: argparse.Namespace) -> int:
    info = inspect_database(args.input_file)
    if args.json:
        print(json.dumps(asdict(info), indent=2))
        return 0

    pairs = [
        ("Database Path", info.path),
        ("File Size", f"{info.file_size_bytes:,} bytes"),
        ("SQLite Version", info.sqlite_version),
        ("Page Size", f"{info.page_size} bytes"),
        ("Page Count", f"{info.page_count:,}"),
        ("Calculated DB Size", f"{info.calculated_db_size:,} bytes"),
        ("Journal Mode", info.journal_mode),
        ("WAL File Present", "Yes" if info.wal_file_present else "No"),
        ("SHM File Present", "Yes" if info.shm_file_present else "No"),
        ("Schema Version", info.schema_version),
        ("User Version", info.user_version),
        ("Application ID", info.application_id),
        ("Foreign Keys Enabled", "Yes" if info.foreign_keys_enabled else "No"),
        ("Tables", info.table_count),
        ("Views", info.view_count),
        ("Indexes", info.index_count),
        ("Triggers", info.trigger_count),
        ("Last Modified", info.mtime_iso),
    ]
    print(format_key_values(pairs, title=f"Database Info: {Path(args.input_file).name}"))
    return 0


def handle_tables(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    with get_readonly_connection(path) as conn:
        tables = list_tables(conn, exact_count=args.exact_count)

    if args.json:
        data = [asdict(t) for t in tables]
        print(json.dumps(data, indent=2))
        return 0

    headers = ["Name", "Type", "Cols", "PKs", "FKs", "Idxs", "Rows"]
    rows = []
    for t in tables:
        row_count_str = (
            str(t.row_count) if t.row_count is not None else ("(exact omitted)" if not args.exact_count else "0")
        )
        pk_str = ", ".join(t.primary_keys) if t.primary_keys else "(none)"
        rows.append(
            [
                t.name,
                t.type,
                str(t.column_count),
                pk_str,
                str(t.foreign_key_count),
                str(t.index_count),
                row_count_str,
            ]
        )

    print(format_table(headers, rows, title=f"Tables & Views: {path.name}"))
    return 0


def handle_schema(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    with get_readonly_connection(path) as conn:
        schemas = get_schema(conn, table_name=args.table)

    if args.json:
        data = [asdict(s) for s in schemas]
        print(json.dumps(data, indent=2))
        return 0

    if not schemas:
        print(f"No schema found for target '{args.table or 'database'}'")
        return 0

    for s in schemas:
        print(f"\n--- {s.type.upper()}: {s.name} ---")
        if s.sql:
            print(f"{s.sql.strip()};")

        # Columns table
        col_headers = ["CID", "Name", "Type", "NotNull", "Default", "PK"]
        col_rows = [
            [str(c.cid), c.name, c.type, "YES" if c.notnull else "NO", str(c.default_value), str(c.pk)]
            for c in s.columns
        ]
        print(format_table(col_headers, col_rows))

        # Indexes
        if s.indexes:
            idx_headers = ["Index Name", "Unique", "Columns"]
            idx_rows = [[i.name, "YES" if i.unique else "NO", ", ".join(i.columns)] for i in s.indexes]
            print(format_table(idx_headers, idx_rows, title=f"Indexes on {s.name}"))

        # Foreign keys
        if s.foreign_keys:
            fk_headers = ["ID", "Parent Table", "From Col", "To Col", "On Update", "On Delete"]
            fk_rows = [
                [str(f.id), f.table, f.from_col, str(f.to_col), f.on_update, f.on_delete] for f in s.foreign_keys
            ]
            print(format_table(fk_headers, fk_rows, title=f"Foreign Keys on {s.name}"))

    return 0


def handle_browse(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    offset = max(0, (args.page - 1) * args.limit)
    proj_cols = [c.strip() for c in args.columns.split(",")] if args.columns else None

    with get_readonly_connection(path) as conn:
        res = browse_table(
            conn=conn,
            table=args.table,
            columns=proj_cols,
            filter_col=args.column,
            filter_val=args.filter,
            filter_op=args.operator,
            sort_col=args.sort,
            sort_desc=args.desc,
            limit=args.limit,
            offset=offset,
        )

    if args.json:
        print(json.dumps(asdict(res), indent=2, ensure_ascii=False))
        return 0

    headers = res.columns
    rows = [[format_value_for_display(row.get(col)) for col in headers] for row in res.rows]
    title = f"Browse {res.table} (Page {args.page}, Rows {len(rows)}{'+ more' if res.has_more else ''})"
    print(format_table(headers, rows, title=title))
    return 0


def handle_search(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    target_cols = [args.column] if args.column else None

    with get_readonly_connection(path) as conn:
        res = search_table(
            conn=conn,
            table=args.table,
            pattern=args.pattern,
            columns=target_cols,
            limit=args.limit,
        )

    if args.json:
        print(json.dumps(asdict(res), indent=2, ensure_ascii=False))
        return 0

    if res.warning:
        print(f"[{res.warning}]")

    headers = res.searched_columns
    rows = [[format_value_for_display(m.get(col)) for col in headers] for m in res.matches]
    title = f"Search '{args.pattern}' in {res.table} ({len(rows)} matches)"
    print(format_table(headers, rows, title=title))
    return 0


def handle_query(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    with get_readonly_connection(path) as conn:
        res = execute_readonly_query(conn=conn, sql=args.sql_query, limit=args.limit)

    if args.json:
        print(json.dumps(asdict(res), indent=2, ensure_ascii=False))
        return 0

    headers = res.columns
    rows = [[format_value_for_display(r.get(c)) for c in headers] for r in res.rows]
    title = f"Query: {args.sql_query[:40]}... ({res.row_count} rows in {res.execution_time_ms:.1f}ms)"
    print(format_table(headers, rows, title=title))
    return 0


def handle_export(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    with get_readonly_connection(path) as conn:
        if args.table:
            count = export_table(
                conn=conn,
                table=args.table,
                output_path=args.output_file,
                export_format=args.format,
                force=args.force,
                limit=args.limit,
            )
            msg = f"Exported {count} rows from table '{args.table}' to '{args.output_file}' ({args.format})"
        else:
            if args.format != "sql":
                raise ValueError(
                    "Whole-database export only supports format=sql (SQL dump). Specify -T/--table for table export."
                )
            count = export_database_dump(conn=conn, output_path=args.output_file, force=args.force)
            msg = f"Exported {count} lines of SQL dump to '{args.output_file}'"

    if args.json:
        print(json.dumps({"status": "success", "message": msg, "destination": args.output_file, "items": count}))
    else:
        print(msg)
    return 0


def handle_check(args: argparse.Namespace) -> int:
    path = Path(args.input_file).resolve()
    with get_readonly_connection(path) as conn:
        report = check_database(
            conn=conn,
            check_integrity=args.integrity_check,
            check_foreign_keys=args.foreign_keys,
        )

    if args.json:
        print(json.dumps(asdict(report), indent=2))
        return 0 if report.is_healthy else 1

    status_str = "HEALTHY" if report.is_healthy else "ISSUES DETECTED"
    pairs = [
        ("Status", status_str),
        ("Quick Check", ", ".join(report.quick_check)),
        (
            "Integrity Check",
            ", ".join(report.integrity_check) if report.integrity_check else "(skipped, use -c/--integrity-check)",
        ),
        ("Foreign Key Violations", len(report.foreign_key_violations)),
    ]
    print(format_key_values(pairs, title=f"Health Check: {path.name}"))

    if report.foreign_key_violations:
        print("\nForeign Key Violations:")
        headers = ["Table", "RowID", "Parent Table", "FK Index"]
        rows = [
            [str(v["table"]), str(v["rowid"]), str(v["parent_table"]), str(v["fk_index"])]
            for v in report.foreign_key_violations
        ]
        print(format_table(headers, rows))

    print(f"\nNote: {report.notes}")
    return 0 if report.is_healthy else 1


def handle_backup(args: argparse.Namespace) -> int:
    src = Path(args.input_file).resolve()
    dst = Path(args.output_file).resolve()

    if not args.write:
        # Dry-run preview
        plan = {
            "mode": "dry-run (preview only)",
            "source": str(src),
            "destination": str(dst),
            "source_exists": src.exists(),
            "destination_exists": dst.exists(),
            "action": "Will perform consistent online SQLite backup using Connection.backup API.",
            "note": "Pass -w/--write to execute backup.",
        }
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            pairs = list(plan.items())
            print(format_key_values(pairs, title="Backup Plan (Dry-run)"))
        return 0

    manifest = backup_database(src, dst, force=args.force, write_manifest=True)
    if args.json:
        print(json.dumps(manifest.to_dict(), indent=2))
    else:
        pairs = [
            ("Status", "SUCCESS"),
            ("Source", manifest.source_path),
            ("Destination", manifest.destination_path),
            ("Destination SHA256", manifest.destination_sha256),
            ("Backup Size", f"{manifest.destination_size_bytes:,} bytes"),
            ("Integrity Verified", "YES" if manifest.integrity_check_passed else "NO"),
        ]
        print(format_key_values(pairs, title="Online Backup Completed"))
    return 0


def handle_restore(args: argparse.Namespace) -> int:
    bak = Path(args.input_file).resolve()
    tgt = Path(args.output_file).resolve()

    if not args.write:
        plan = {
            "mode": "dry-run (preview only)",
            "backup_source": str(bak),
            "target_destination": str(tgt),
            "backup_exists": bak.exists(),
            "target_exists": tgt.exists(),
            "action": "Will restore backup to target, create pre-restore backup if target exists, and clean stale WAL/SHM.",
            "note": "Pass -w/--write to execute restore.",
        }
        if args.json:
            print(json.dumps(plan, indent=2))
        else:
            print(format_key_values(list(plan.items()), title="Restore Plan (Dry-run)"))
        return 0

    report = restore_database(bak, tgt, force=args.force, create_backup_of_target=True)
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        pairs = [
            ("Status", "SUCCESS"),
            ("Backup File", report.backup_path),
            ("Restored Target", report.target_path),
            ("Target Pre-backup", str(report.pre_restore_backup_path)),
            ("Integrity Verified", "YES" if report.integrity_check_passed else "NO"),
            ("Stale WAL/SHM Cleaned", "YES" if report.stale_wal_shm_cleaned else "NO"),
        ]
        print(format_key_values(pairs, title="Database Restore Completed"))
    return 0


def handle_discover(args: argparse.Namespace) -> int:
    dbs = discover_known_databases()
    if args.json:
        print(json.dumps([d.to_dict() for d in dbs], indent=2))
        return 0

    if not dbs:
        print("No known toolkit SQLite databases found in standard locations.")
        return 0

    headers = ["Name", "Module", "Size", "Accessible", "Path"]
    rows = [[d.name, d.module, f"{d.size_bytes:,} B", "YES" if d.is_accessible else "NO", d.path] for d in dbs]
    print(format_table(headers, rows, title="Discovered Toolkit Databases"))
    return 0


def handle_init(args: argparse.Namespace) -> int:
    schema_sql = args.schema_sql
    if args.schema_file:
        schema_path = Path(args.schema_file).resolve()
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        schema_sql = schema_path.read_text(encoding="utf-8")

    plan = init_database(
        db_path=args.input_file,
        schema_sql=schema_sql,
        dry_run=not args.write,
        force=args.force,
    )

    if args.json:
        print(json.dumps(asdict(plan), indent=2))
        return 0

    pairs = [
        ("Mode", "DRY-RUN (Pass -w/--write to execute)" if plan.is_dry_run else "SUCCESS"),
        ("Target Database", plan.target_path),
        ("Statements to Run", len(plan.statements)),
    ]
    print(format_key_values(pairs, title="Database Initialization"))
    if plan.statements:
        print("\nStatements:")
        for idx, stmt in enumerate(plan.statements, 1):
            print(f"  [{idx}] {stmt};")
    return 0


def handle_edit(args: argparse.Namespace) -> int:
    pk_dict = parse_key_value_spec(args.primary_key)
    set_dict = parse_key_value_spec(args.set_values)

    plan = plan_and_apply_edit(
        db_path=args.input_file,
        table=args.table,
        pk_values=pk_dict,
        new_values=set_dict,
        dry_run=not args.write,
        skip_backup=args.skip_backup,
    )

    if args.json:
        print(json.dumps(asdict(plan), indent=2))
        return 0

    pairs = [
        ("Mode", "DRY-RUN (Pass -w/--write to apply)" if plan.is_dry_run else "APPLIED SUCCESSFULLY"),
        ("Table", plan.table),
        ("Primary Key", json.dumps(plan.pk_values)),
        ("Backup Created", plan.backup_path or "(none / dry-run)"),
    ]
    print(format_key_values(pairs, title="Row Edit Plan"))
    print("\nValue Changes:")
    headers = ["Column", "Old Value", "New Value"]
    rows = []
    for col, new_val in plan.new_values.items():
        old_val = plan.old_values.get(col)
        rows.append([col, str(old_val), str(new_val)])
    print(format_table(headers, rows))
    return 0


def handle_insert(args: argparse.Namespace) -> int:
    val_dict = parse_key_value_spec(args.values)
    plan = plan_and_apply_insert(
        db_path=args.input_file,
        table=args.table,
        values=val_dict,
        dry_run=not args.write,
        skip_backup=args.skip_backup,
    )

    if args.json:
        print(json.dumps(asdict(plan), indent=2))
        return 0

    pairs = [
        ("Mode", "DRY-RUN (Pass -w/--write to apply)" if plan.is_dry_run else "INSERTED SUCCESSFULLY"),
        ("Table", plan.table),
        ("Backup Created", plan.backup_path or "(none / dry-run)"),
        ("Values", json.dumps(plan.values)),
    ]
    print(format_key_values(pairs, title="Row Insert Plan"))
    return 0


def handle_delete(args: argparse.Namespace) -> int:
    pk_dict = parse_key_value_spec(args.primary_key)
    plan = plan_and_apply_delete(
        db_path=args.input_file,
        table=args.table,
        pk_values=pk_dict,
        dry_run=not args.write,
        skip_backup=args.skip_backup,
    )

    if args.json:
        print(json.dumps(asdict(plan), indent=2))
        return 0

    pairs = [
        ("Mode", "DRY-RUN (Pass -w/--write to apply)" if plan.is_dry_run else "DELETED SUCCESSFULLY"),
        ("Table", plan.table),
        ("Primary Key", json.dumps(plan.pk_values)),
        ("Backup Created", plan.backup_path or "(none / dry-run)"),
    ]
    print(format_key_values(pairs, title="Row Delete Plan"))
    print("\nRow to be deleted:")
    print(format_key_values(list(plan.deleted_row.items())))
    return 0


def handle_sql(args: argparse.Namespace) -> int:
    res = execute_mutation_sql(
        db_path=args.input_file,
        sql=args.sql_query,
        dry_run=not args.write,
        skip_backup=args.skip_backup,
    )

    if args.json:
        print(json.dumps(asdict(res), indent=2))
        return 0

    pairs = [
        ("Mode", "DRY-RUN (Pass -w/--write to execute)" if res.is_dry_run else "EXECUTED SUCCESSFULLY"),
        ("SQL Query", res.sql),
        ("Affected Rows", str(res.affected_rows)),
        ("Backup Created", res.backup_path or "(none / dry-run)"),
    ]
    print(format_key_values(pairs, title="SQL Mutation"))
    return 0


def handle_compare(args: argparse.Namespace) -> int:
    cmp = compare_databases(args.db1, args.db2, row_limit=args.limit)
    if args.json:
        print(json.dumps(cmp.to_dict(), indent=2))
        return 0 if cmp.identical else 1

    status_str = "IDENTICAL" if cmp.identical else "DIFFERENCES FOUND"
    pairs = [
        ("Status", status_str),
        ("Database 1", cmp.db1_path),
        ("Database 2", cmp.db2_path),
        ("Differences Count", len(cmp.schema_differences)),
    ]
    print(format_key_values(pairs, title="Database Comparison"))

    if cmp.schema_differences:
        print("\nDifferences:")
        for d in cmp.schema_differences:
            print(f"  * {d}")

    return 0 if cmp.identical else 1


def handle_recover(args: argparse.Namespace) -> int:
    diag = diagnose_database_recovery(args.input_file)

    if args.output_file:
        # User requested recovery extraction
        out_path = Path(args.output_file).resolve()
        success = execute_external_recover(args.input_file, out_path, force=args.force)
        msg = f"Recovery executed to '{out_path}'. Succeeded: {success}"
        if args.json:
            print(json.dumps({"status": "success", "message": msg, "output_path": str(out_path)}))
        else:
            print(msg)
        return 0 if success else 1

    if args.json:
        print(json.dumps(diag.to_dict(), indent=2))
        return 0

    pairs = [
        ("Target Database", diag.database_path),
        ("File Size", f"{diag.file_size_bytes:,} bytes"),
        ("Header Valid", "YES" if diag.header_valid else "NO"),
        ("Integrity Output", "; ".join(diag.integrity_output)),
        ("Nearby Backups Found", len(diag.nearby_backups)),
        ("SQLite CLI Available", "YES" if diag.sqlite3_cli_available else "NO"),
        ("SQLite .recover Supported", "YES" if diag.sqlite3_recover_supported else "NO"),
    ]
    print(format_key_values(pairs, title="Database Recovery Diagnostics"))

    if diag.nearby_backups:
        print("\nNearby Backups:")
        headers = ["Backup Path", "Valid SQLite", "Size (B)", "Manifest"]
        rows = [
            [b.path, "YES" if b.is_valid_sqlite else "NO", str(b.size_bytes), b.manifest_path or "(none)"]
            for b in diag.nearby_backups
        ]
        print(format_table(headers, rows))

    print(f"\nNotice: {diag.notes}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the db-manager CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else (logging.WARNING if args.quiet else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    dispatchers = {
        "info": handle_info,
        "tables": handle_tables,
        "schema": handle_schema,
        "browse": handle_browse,
        "search": handle_search,
        "query": handle_query,
        "export": handle_export,
        "check": handle_check,
        "backup": handle_backup,
        "restore": handle_restore,
        "discover": handle_discover,
        "init": handle_init,
        "edit": handle_edit,
        "insert": handle_insert,
        "delete": handle_delete,
        "sql": handle_sql,
        "compare": handle_compare,
        "recover": handle_recover,
    }

    handler = dispatchers.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except Exception as exc:
        if args.verbose:
            logger.exception("Operation failed: %s", exc)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
