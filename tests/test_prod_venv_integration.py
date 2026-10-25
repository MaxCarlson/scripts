"""Verification test proving launcher engine is usable directly from production virtual environment."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest


def test_production_venv_launcher_invocation(tmp_path: Path):
    """Verify representative invocation through production .venv without PYTHONPATH."""
    # Ensure production python can import script_logging.launcher
    import script_logging
    import script_logging.launcher
    assert script_logging.__file__ is not None
    assert script_logging.launcher.__file__ is not None

    db_file = tmp_path / "test_invocations.sqlite3"
    manifest_file = tmp_path / "manifest.json"
    target_file = tmp_path / "echo_target.py"

    target_code = (
        "import sys\n"
        "print('PROD_VENV_SUCCESS: ' + ' '.join(sys.argv[1:]))\n"
        "sys.exit(0)\n"
    )
    target_file.write_text(target_code, encoding="utf-8")

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "representative_cmd": {
                "program_id": "pyscript:echo_target.py",
                "kind": "python_file",
                "target": str(target_file),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    env = os.environ.copy()
    env["SCRIPT_LOGGING_INVOCATION_DB"] = str(db_file)
    # Remove PYTHONPATH from environment to strictly test .venv package resolution
    env.pop("PYTHONPATH", None)

    cmd = [
        sys.executable,
        "-m",
        "script_logging.launcher",
        "--manifest",
        str(manifest_file),
        "--command",
        "representative_cmd",
        "--",
        "hello_from_prod_venv",
        "arg2",
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
    assert res.returncode == 0
    assert "PROD_VENV_SUCCESS: hello_from_prod_venv arg2" in res.stdout

    # Verify SQLite DB recorded the invocation
    from script_logging.reader import open_invocation_reader
    reader = open_invocation_reader(db_file)
    page = reader.list_invocations(program_id="pyscript:echo_target.py")
    assert len(page.items) == 1
    assert page.items[0].status == "exited"
    assert page.items[0].exit_code == 0
    assert page.items[0].invoked_name == "representative_cmd"
