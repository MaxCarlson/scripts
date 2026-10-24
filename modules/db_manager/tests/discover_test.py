"""
Unit tests for db_manager.discover.
"""

from pathlib import Path
import sqlite3

from db_manager.discover import discover_known_databases


def test_discover_known_databases(tmp_path: Path):
    # Setup synthetic repo structure
    module_dir = tmp_path / "modules" / "script_logging"
    module_dir.mkdir(parents=True)
    db_file = module_dir / "history.sqlite3"
    with sqlite3.connect(db_file) as conn:
        conn.execute("CREATE TABLE test (x INT);")

    # Another candidate that does NOT exist
    runmux_dir = tmp_path / "modules" / "runmux"

    discovered = discover_known_databases(repo_root=tmp_path)
    # Must only find existing candidate
    paths = [d.path for d in discovered]
    assert str(db_file.resolve()) in paths

    # Missing database must NOT have been created
    assert not runmux_dir.exists()
