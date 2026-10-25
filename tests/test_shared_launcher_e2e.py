"""End-to-end integration test verifying wrapper to SQLite database execution flow."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from scripts_setup.launcher_generator import generate_windows_wrapper, generate_posix_wrapper
from script_logging.reader import open_invocation_reader


def test_full_wrapper_to_database_e2e_flow(tmp_path: Path):
    """Verify complete flow: wrapper execution records into isolated SQLite database and preserves exit codes."""
    repo_root = tmp_path / "repo"
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    db_path = state_dir / "invocations.sqlite3"

    # Setup mock venv interpreter
    venv_dir = repo_root / ".venv"
    venv_scripts = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    venv_scripts.mkdir(parents=True)
    real_python = Path(sys.executable)
    venv_python = venv_scripts / ("python.exe" if os.name == "nt" else "python")
    try:
        venv_python.symlink_to(real_python)
    except OSError:
        import shutil
        shutil.copy2(real_python, venv_python)

    # Provide pyvenv.cfg so python recognizes venv
    real_cfg = real_python.parents[1] / "pyvenv.cfg"
    if real_cfg.is_file():
        import shutil
        shutil.copy2(real_cfg, venv_dir / "pyvenv.cfg")
    else:
        (venv_dir / "pyvenv.cfg").write_text(
            f"home = {sys.base_prefix}\ninclude-system-site-packages = false\nversion = 3.12.10\n",
            encoding="utf-8",
        )

    # Target echo script
    target_py = repo_root / "test_target.py"
    target_py.write_text(
        "import sys\n"
        "print('HEARTBEAT_E2E: ' + ' '.join(sys.argv[1:]))\n"
        "sys.exit(0 if 'fail' not in sys.argv else 7)\n",
        encoding="utf-8",
    )

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "my_echo": {
                "program_id": "pyscript:test_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file = repo_root / "scripts_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Generate wrapper in bin
    is_win = os.name == "nt"
    wrapper_path = bin_dir / ("my_echo.cmd" if is_win else "my_echo")
    content = generate_windows_wrapper("my_echo") if is_win else generate_posix_wrapper("my_echo")
    wrapper_path.write_text(content, encoding="utf-8")
    if not is_win:
        wrapper_path.chmod(0o755)

    env = os.environ.copy()
    env["SCRIPT_LOGGING_INVOCATION_DB"] = str(db_path)
    # Ensure PYTHONPATH includes repo modules so launcher resolves in test subshell
    worktree = Path(__file__).parents[1]
    paths = [
        str(worktree / "modules" / "script_logging"),
        str(worktree / "scripts_setup"),
        str(worktree),
    ]
    env["PYTHONPATH"] = os.pathsep.join(paths + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else []))

    # 1. Invoke wrapper directly via subprocess (success run)
    cmd = f'cmd.exe /c ""{wrapper_path}" arg1 --flag=val"' if is_win else [str(wrapper_path), "arg1", "--flag=val"]
    res = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    assert res.returncode == 0
    assert "HEARTBEAT_E2E: arg1 --flag=val" in res.stdout

    # Verify reader sees invocation
    reader = open_invocation_reader(db_path)
    invocations = reader.list_invocations(program_id="pyscript:test_target.py")
    assert len(invocations.items) == 1
    record = invocations.items[0]
    assert record.status == "exited"
    assert record.exit_code == 0
    assert record.invoked_name == "my_echo"
    assert "arg1" in record.redacted_argv

    # 2. Test failure path (exit code 7)
    fail_cmd = f'cmd.exe /c ""{wrapper_path}" fail"' if is_win else [str(wrapper_path), "fail"]
    res_fail = subprocess.run(fail_cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
    assert res_fail.returncode == 7

    stats = reader.get_program_statistics("pyscript:test_target.py")
    assert stats.total_starts == 2
    assert stats.success_count == 1
    assert stats.failure_count == 1

    all_runs = reader.list_invocations(program_id="pyscript:test_target.py")
    assert len(all_runs.items) == 2
    assert all_runs.items[0].exit_code == 7
