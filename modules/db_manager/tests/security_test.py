"""
Security, injection resistance, and data-integrity regression tests for db_manager.
"""

from pathlib import Path
import sqlite3
import pytest

from db_manager.connections import get_readonly_connection, get_write_connection
from db_manager.inspector import inspect_database, list_tables, get_schema
from db_manager.query import browse_table, search_table, execute_readonly_query, quote_identifier
from db_manager.export import export_table
from db_manager.changes import plan_and_apply_edit
from db_manager.backup import backup_database


def test_readonly_connection_blocks_mutating_pragmas(tmp_path: Path):
    """Mutating PRAGMAs must be denied by authorizer in read-only mode."""
    db_file = tmp_path / "test_pragma.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE t (id INT PRIMARY KEY);")
        conn.execute("PRAGMA user_version = 10;")

    with get_readonly_connection(db_file) as ro_conn:
        # Safe read pragmas succeed
        cur = ro_conn.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == 10

        cur = ro_conn.execute("PRAGMA page_size;")
        assert cur.fetchone()[0] > 0

        # Mutating pragmas must raise DatabaseError (denied by authorizer)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("PRAGMA user_version = 999;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("PRAGMA foreign_keys = OFF;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("PRAGMA synchronous = OFF;")

        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            ro_conn.execute("PRAGMA writable_schema = 1;")

    # Verify user_version was unchanged
    with get_readonly_connection(db_file) as ro_conn:
        assert ro_conn.execute("PRAGMA user_version;").fetchone()[0] == 10


def test_connection_rejects_directory_path(tmp_path: Path):
    """Opening a directory as a SQLite database must raise ValueError."""
    dir_path = tmp_path / "somedir"
    dir_path.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="Target path is not a file"):
        get_readonly_connection(dir_path)

    with pytest.raises(ValueError, match="Target path is not a file"):
        get_write_connection(dir_path)


def test_injection_resistant_identifiers_with_spaces_quotes_and_keywords(tmp_path: Path):
    """Table and column names with spaces, embedded double-quotes, and reserved words must be safely quoted."""
    db_file = tmp_path / "quoted_idents.db"
    odd_table = 'weird "table" (x-1)'
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            f"CREATE TABLE {quote_identifier(odd_table)} ("
            '"col with spaces" INTEGER PRIMARY KEY, '
            '"select" TEXT, '
            '"order" REAL'
            ");"
        )
        conn.execute(f"INSERT INTO {quote_identifier(odd_table)} VALUES (1, 'First Item', 10.5);")
        conn.execute(f"INSERT INTO {quote_identifier(odd_table)} VALUES (2, 'Second Item', 20.0);")

    with get_readonly_connection(db_file) as conn:
        # Table listing
        tables = list_tables(conn, exact_count=True)
        assert len(tables) == 1
        assert tables[0].name == odd_table
        assert tables[0].row_count == 2

        # Schema inspection
        schema = get_schema(conn, table_name=odd_table)
        assert len(schema) == 1
        col_names = [c.name for c in schema[0].columns]
        assert col_names == ["col with spaces", "select", "order"]

        # Bounded browsing with projection, filter, and sorting on reserved words
        browse_res = browse_table(
            conn,
            table=odd_table,
            columns=["col with spaces", "select"],
            filter_col="select",
            filter_val="First Item",
            sort_col="col with spaces",
            limit=5,
        )
        assert len(browse_res.rows) == 1
        assert browse_res.rows[0]["col with spaces"] == 1
        assert browse_res.rows[0]["select"] == "First Item"

        # Parameterized search across weirdly named table
        search_res = search_table(conn, table=odd_table, pattern="Second")
        assert len(search_res.matches) == 1
        assert search_res.matches[0]["col with spaces"] == 2

        # Export table to CSV
        csv_file = tmp_path / "odd_table.csv"
        export_table(conn, table=odd_table, output_path=csv_file, export_format="csv")
        csv_text = csv_file.read_text(encoding="utf-8")
        assert "col with spaces,select,order" in csv_text
        assert "First Item" in csv_text

    # Mutation test: edit row in weirdly named table with optimistic concurrency
    edit_plan = plan_and_apply_edit(
        db_file,
        table=odd_table,
        pk_values={"col with spaces": 1},
        new_values={"select": "Updated First"},
        dry_run=False,
    )
    assert not edit_plan.is_dry_run

    with get_readonly_connection(db_file) as conn:
        row = conn.execute(
            f'SELECT "select" FROM {quote_identifier(odd_table)} WHERE "col with spaces" = 1;'
        ).fetchone()
        assert row["select"] == "Updated First"


def test_csv_formula_injection_prevention_extended(tmp_path: Path):
    """CSV export must escape all dangerous spreadsheet formula trigger characters."""
    import csv

    db_file = tmp_path / "formula_db.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE payloads (id INT PRIMARY KEY, attack TEXT);")
        payloads = [
            (1, "=1+2"),
            (2, "+SUM(A1:A10)"),
            (3, "-100"),
            (4, "@HYPERLINK('http://evil.com')"),
            (5, "\tTAB_INJECT"),
            (6, "\rCR_INJECT"),
            (7, "Normal Safe String"),
        ]
        conn.executemany("INSERT INTO payloads VALUES (?, ?);", payloads)

    out_csv = tmp_path / "escaped.csv"
    with get_readonly_connection(db_file) as conn:
        export_table(conn, table="payloads", output_path=out_csv, export_format="csv")

    with open(out_csv, "r", newline="", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    # Verify each formula line was prepended with single quote
    rows = {int(r[0]): r[1] for r in reader[1:]}
    assert rows[1] == "'=1+2"
    assert rows[2] == "'+SUM(A1:A10)"
    assert rows[3] == "'-100"
    assert rows[4] == "'@HYPERLINK('http://evil.com')"
    assert rows[5] == "'\tTAB_INJECT"
    assert rows[6] == "'\rCR_INJECT"
    assert rows[7] == "Normal Safe String"


def test_synthetic_script_logging_fixture_inspection_and_backup(tmp_path: Path):
    """
    Demonstrate safe read-only inspection, browsing, search, and online hot backup
    against a disposable synthetic script_logging-shaped SQLite database fixture
    without importing or depending on script_logging.
    """
    db_file = tmp_path / "history.sqlite3"
    with sqlite3.connect(db_file) as conn:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                exit_code INTEGER
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            """
        )
        conn.execute("CREATE INDEX idx_events_run_id ON events(run_id);")
        conn.execute(
            """
            CREATE TABLE invocations (
                invocation_id TEXT PRIMARY KEY,
                run_id TEXT,
                wrapper TEXT,
                duration_ms REAL
            );
            """
        )

        # Insert realistic runmux / script_logging mock telemetry
        conn.execute(
            "INSERT INTO runs VALUES ('20261024-001', 'runmux run -t 4', '2026-10-24T12:00:00Z', '2026-10-24T12:05:00Z', 0);"
        )
        conn.execute(
            "INSERT INTO runs VALUES ('20261024-002', 'ytaedl --proxy', '2026-10-24T12:10:00Z', '2026-10-24T12:12:00Z', 1);"
        )

        for i in range(1, 6):
            conn.execute(
                "INSERT INTO events (run_id, timestamp, level, message) VALUES (?, ?, ?, ?);",
                (
                    "20261024-001",
                    f"2026-10-24T12:0{i}:00Z",
                    "INFO",
                    f"Process worker {i} spawned successfully",
                ),
            )
        conn.execute(
            "INSERT INTO events (run_id, timestamp, level, message) VALUES ('20261024-002', '2026-10-24T12:11:00Z', 'ERROR', 'Connection timed out');"
        )

        conn.execute("INSERT INTO invocations VALUES ('inv-01', '20261024-001', 'bin/runmux.cmd', 300000.0);")
        conn.execute("INSERT INTO invocations VALUES ('inv-02', '20261024-002', 'bin/ytaedl.cmd', 120000.0);")

    # 1. Metadata inspection
    info = inspect_database(db_file)
    assert info.table_count == 3
    assert info.index_count >= 1
    assert info.wal_file_present or info.journal_mode == "wal"

    with get_readonly_connection(db_file) as ro_conn:
        # 2. Table listing with exact row counts
        tables = list_tables(ro_conn, exact_count=True)
        counts = {t.name: t.row_count for t in tables}
        assert counts["runs"] == 2
        assert counts["events"] == 6
        assert counts["invocations"] == 2

        # 3. Bounded browsing
        events_page = browse_table(ro_conn, table="events", limit=3, offset=0, sort_col="event_id")
        assert len(events_page.rows) == 3
        assert events_page.has_more is True

        # 4. Filtered search
        err_search = search_table(ro_conn, table="events", pattern="Connection timed out", columns=["message"])
        assert len(err_search.matches) == 1
        assert err_search.matches[0]["run_id"] == "20261024-002"

        # 5. Read-only query execution
        q_res = execute_readonly_query(
            ro_conn,
            sql="SELECT r.run_id, r.command, count(e.event_id) as event_count "
            "FROM runs r LEFT JOIN events e ON r.run_id = e.run_id "
            "GROUP BY r.run_id ORDER BY r.run_id ASC",
        )
        assert q_res.row_count == 2
        assert q_res.rows[0]["event_count"] == 5
        assert q_res.rows[1]["event_count"] == 1

    # 6. Online hot backup produces valid destination and manifest
    backup_dst = tmp_path / "history_backup.sqlite3"
    manifest = backup_database(db_file, backup_dst)
    assert backup_dst.exists()
    assert manifest.integrity_check_passed is True

    # 7. Verify source database remained completely untouched
    with get_readonly_connection(db_file) as ro_conn:
        final_runs = ro_conn.execute("SELECT count(*) FROM runs;").fetchone()[0]
        assert final_runs == 2
