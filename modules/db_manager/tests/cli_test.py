"""
Unit and CLI smoke tests for db-manager CLI.
"""

import argparse
import json
from pathlib import Path
import sqlite3
import pytest

from db_manager.cli import build_parser, main


def _setup_cli_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE items (id INT PRIMARY KEY, title TEXT, price REAL);")
        conn.execute("INSERT INTO items VALUES (1, 'Sample Item A', 19.99);")
        conn.execute("INSERT INTO items VALUES (2, 'Sample Item B', 29.99);")


def test_cli_all_flags_have_short_and_long_forms():
    """Verify repository standard: every optional argument has both -X and --long-name."""
    parser = build_parser()

    # Test top-level actions
    for action in parser._actions:
        if action.option_strings:
            shorts = [opt for opt in action.option_strings if opt.startswith("-") and not opt.startswith("--")]
            longs = [opt for opt in action.option_strings if opt.startswith("--")]
            assert len(shorts) >= 1, f"Missing short flag for {action.option_strings}"
            assert len(longs) >= 1, f"Missing long flag for {action.option_strings}"

    # Test subcommands
    subparsers_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for name, subparser in subparsers_action.choices.items():
        for action in subparser._actions:
            if action.option_strings:
                shorts = [opt for opt in action.option_strings if opt.startswith("-") and not opt.startswith("--")]
                longs = [opt for opt in action.option_strings if opt.startswith("--")]
                assert len(shorts) >= 1, f"Subcommand '{name}' missing short flag for {action.option_strings}"
                assert len(longs) >= 1, f"Subcommand '{name}' missing long flag for {action.option_strings}"


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "db-manager 1.0.0" in captured.out


def test_cli_info_and_tables(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_test.db"
    _setup_cli_db(db_file)

    # Info
    rc = main(["info", "-i", str(db_file), "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["table_count"] == 1
    assert data["file_size_bytes"] > 0

    # Tables with exact count
    rc = main(["tables", "-i", str(db_file), "-e", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    tables = json.loads(captured.out)
    assert len(tables) == 1
    assert tables[0]["name"] == "items"
    assert tables[0]["row_count"] == 2


def test_cli_schema_and_browse(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_test.db"
    _setup_cli_db(db_file)

    # Schema
    rc = main(["schema", "-i", str(db_file), "-T", "items", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    schemas = json.loads(captured.out)
    assert len(schemas) == 1
    assert schemas[0]["name"] == "items"

    # Browse
    rc = main(["browse", "-i", str(db_file), "-T", "items", "-l", "1", "-p", "1", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    browse_res = json.loads(captured.out)
    assert len(browse_res["rows"]) == 1
    assert browse_res["has_more"] is True


def test_cli_search_and_query(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_test.db"
    _setup_cli_db(db_file)

    # Search
    rc = main(["search", "-i", str(db_file), "-T", "items", "-P", "Item A", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    search_res = json.loads(captured.out)
    assert len(search_res["matches"]) == 1
    assert search_res["matches"][0]["title"] == "Sample Item A"

    # Query
    rc = main(["query", "-i", str(db_file), "-Q", "SELECT title FROM items WHERE id = 2", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    query_res = json.loads(captured.out)
    assert query_res["row_count"] == 1
    assert query_res["rows"][0]["title"] == "Sample Item B"


def test_cli_export_and_check(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_test.db"
    _setup_cli_db(db_file)
    out_csv = tmp_path / "exported.csv"

    # Export
    rc = main(["export", "-i", str(db_file), "-T", "items", "-F", "csv", "-O", str(out_csv)])
    assert rc == 0
    assert out_csv.exists()
    capsys.readouterr()

    # Check
    rc = main(["check", "-i", str(db_file), "-c", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    check_res = json.loads(captured.out)
    assert check_res["is_healthy"] is True


def test_cli_backup_dry_run_and_write(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_test.db"
    _setup_cli_db(db_file)
    bak_file = tmp_path / "backup.db"

    # Dry-run
    rc = main(["backup", "-i", str(db_file), "-O", str(bak_file), "-n"])
    assert rc == 0
    assert not bak_file.exists()
    capsys.readouterr()

    # Write
    rc = main(["backup", "-i", str(db_file), "-O", str(bak_file), "-w", "-j"])
    assert rc == 0
    assert bak_file.exists()
    captured = capsys.readouterr()
    manifest = json.loads(captured.out)
    assert manifest["integrity_check_passed"] is True


def test_cli_discover(capsys):
    rc = main(["discover", "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)


def test_cli_init_and_mutations(tmp_path: Path, capsys):
    db_file = tmp_path / "cli_mut.db"

    # Init
    rc = main(["init", "-i", str(db_file), "-s", "CREATE TABLE users (id INT PRIMARY KEY, name TEXT);", "-w", "-j"])
    assert rc == 0
    assert db_file.exists()
    capsys.readouterr()

    # Insert
    rc = main(["insert", "-i", str(db_file), "-T", "users", "-V", '{"id": 1, "name": "Alice"}', "-w", "-j"])
    assert rc == 0
    capsys.readouterr()

    # Edit
    rc = main(["edit", "-i", str(db_file), "-T", "users", "-K", "id=1", "-S", "name=Alicia", "-w", "-j"])
    assert rc == 0
    capsys.readouterr()

    # Delete
    rc = main(["delete", "-i", str(db_file), "-T", "users", "-K", "id=1", "-w", "-j"])
    assert rc == 0
    capsys.readouterr()


def test_cli_sql_and_compare_and_recover(tmp_path: Path, capsys):
    db1 = tmp_path / "db1.sqlite3"
    db2 = tmp_path / "db2.sqlite3"
    _setup_cli_db(db1)
    _setup_cli_db(db2)

    # SQL mutation
    rc = main(["sql", "-i", str(db1), "-Q", "UPDATE items SET price = 9.99 WHERE id = 1", "-w", "-j"])
    assert rc == 0
    capsys.readouterr()

    # Compare (should report differences)
    rc = main(["compare", "-1", str(db1), "-2", str(db2), "-j"])
    assert rc == 1  # non-zero return code when differences found
    captured = capsys.readouterr()
    cmp_res = json.loads(captured.out)
    assert not cmp_res["identical"]

    # Recover diagnostics
    rc = main(["recover", "-i", str(db1), "-j"])
    assert rc == 0
    captured = capsys.readouterr()
    diag = json.loads(captured.out)
    assert diag["header_valid"] is True
