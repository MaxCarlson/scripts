"""Integration test validating db-manager packaging, executable discovery, and launcher execution in an isolated environment."""
from __future__ import annotations

import json
import os
from pathlib import Path

from script_logging.invocation_store import InvocationStore
from script_logging.reader import open_invocation_reader
from script_logging.launcher import launch_target
from scripts_setup.launcher_generator import (
    generate_windows_wrapper,
    scan_repository_programs,
)


def test_db_manager_packaging_and_discovery(tmp_path: Path):
    """Verify scan_repository_programs correctly discovers db-manager from modules/db_manager/pyproject.toml."""
    repo = tmp_path / "repo"
    db_mod = repo / "modules" / "db_manager"
    db_mod.mkdir(parents=True)
    
    pyproject_content = """[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "db-manager"
version = "1.0.0"
description = "SQLite database explorer and transactional manager."
requires-python = ">=3.10"

[project.scripts]
db-manager = "db_manager.cli:main"
"""
    (db_mod / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    
    commands = scan_repository_programs(repo)
    assert "db-manager" in commands
    cmd = commands["db-manager"]
    assert cmd.name == "db-manager"
    assert cmd.program_id == "module:db-manager"
    assert cmd.kind == "console_script"
    assert cmd.entry_point == "db_manager.cli:main"
    if os.name == "nt":
        assert cmd.target_windows == ".venv/Scripts/db-manager.exe"
    else:
        assert cmd.target_posix == ".venv/bin/db-manager"


def test_db_manager_uninstalled_actionable_error_and_no_recursion(tmp_path: Path, monkeypatch, capsys):
    """Verify that when db-manager.exe is missing, launcher fails actionably with code 127 without recursion."""
    repo = tmp_path / "repo"
    manifest_file = repo / "scripts_manifest.json"
    bin_dir = repo / "bin"
    bin_dir.mkdir(parents=True)
    
    # Missing target
    missing_target = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("db-manager.exe" if os.name == "nt" else "db-manager")
    
    manifest_data = {
        "schema_version": 1,
        "repository_id": "MaxCarlson/scripts",
        "commands": {
            "db-manager": {
                "name": "db-manager",
                "program_id": "module:db-manager",
                "kind": "console_script",
                "target": str(missing_target),
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    wrapper_path = bin_dir / ("db-manager.cmd" if os.name == "nt" else "db-manager")
    wrapper_path.write_text(generate_windows_wrapper("db-manager"), encoding="utf-8")
    
    db_file = tmp_path / "test.sqlite3"
    store = InvocationStore(db_file)
    
    code = launch_target(
        manifest_path=manifest_file,
        command_name="db-manager",
        args=["--help"],
        current_wrapper=wrapper_path,
        origin="launcher",
        store=store,
    )
    
    assert code == 127
    err = capsys.readouterr().err
    assert "Error: Target" in err
    assert "does not exist. Please run 'python setup.py' or bootstrap" in err


def test_db_manager_installed_execution_and_invocation_recording(tmp_path: Path):
    """Verify that when db-manager executable is installed, the wrapper executes successfully and records history."""
    repo = tmp_path / "repo"
    manifest_file = repo / "scripts_manifest.json"
    bin_dir = repo / "bin"
    bin_dir.mkdir(parents=True)
    venv_scripts = repo / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv_scripts.mkdir(parents=True)
    
    # Create mock executable that simulates `db-manager --help`
    target_py = venv_scripts / "mock_db_manager.py"
    target_py.write_text(
        "import sys\n"
        "if '--help' in sys.argv:\n"
        "    print('Usage: db-manager [OPTIONS] COMMAND [ARGS]...')\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    
    manifest_data = {
        "schema_version": 1,
        "repository_id": "MaxCarlson/scripts",
        "commands": {
            "db-manager": {
                "name": "db-manager",
                "program_id": "module:db-manager",
                "kind": "python_file",
                "target": str(target_py),
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    wrapper_path = bin_dir / ("db-manager.cmd" if os.name == "nt" else "db-manager")
    wrapper_path.write_text(generate_windows_wrapper("db-manager"), encoding="utf-8")
    
    db_file = tmp_path / "test_history.sqlite3"
    store = InvocationStore(db_file)
    
    code = launch_target(
        manifest_path=manifest_file,
        command_name="db-manager",
        args=["--help"],
        current_wrapper=wrapper_path,
        origin="launcher",
        store=store,
    )
    
    assert code == 0
    
    # Verify invocation recorded in SQLite
    reader = open_invocation_reader(db_file)
    page = reader.list_invocations(program_id="module:db-manager")
    assert len(page.items) == 1
    rec = page.items[0]
    assert rec.program_id == "module:db-manager"
    assert rec.invoked_name == "db-manager"
    assert rec.status == "exited"
    assert rec.exit_code == 0
    assert rec.redacted_argv == ("--help",)
    
    # Verify statistics
    stats = reader.get_program_statistics("module:db-manager")
    assert stats.total_starts == 1
    assert stats.success_count == 1
    assert stats.failure_count == 0
