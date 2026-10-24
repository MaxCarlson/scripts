import json
import pytest
from script_logging.launcher import launch_target, main
from script_logging.reader import open_invocation_reader


def test_launcher_executes_target_and_records_invocation(tmp_path, monkeypatch):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    # Create dummy target python script
    target_py = tmp_path / "echo_target.py"
    target_py.write_text(
        "import sys\nprint('TARGET_OUTPUT: ' + ' '.join(sys.argv[1:]))\nsys.exit(42)\n",
        encoding="utf-8",
    )

    # Create synthetic manifest
    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "mycmd": {
                "program_id": "pyscript:echo_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Execute via launcher
    code = launch_target(manifest_file, "mycmd", ["foo", "bar"], origin="launcher")
    assert code == 42

    # Verify DB recorded completed run
    reader = open_invocation_reader(db_path)
    page = reader.list_invocations(program_id="pyscript:echo_target.py")
    assert len(page.items) == 1
    assert page.items[0].status == "exited"
    assert page.items[0].exit_code == 42
    assert page.items[0].invoked_name == "mycmd"
    assert page.items[0].origin == "launcher"


def test_launcher_recursion_guard_detects_self_reference(tmp_path, capsys):
    manifest_file = tmp_path / "manifest.json"
    dummy_wrapper = tmp_path / "mycmd.cmd"
    dummy_wrapper.write_text("dummy", encoding="utf-8")

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "mycmd": {
                "program_id": "module:mycmd",
                "kind": "console_script",
                "target": str(dummy_wrapper),  # Target points directly to wrapper!
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    code = launch_target(manifest_file, "mycmd", [], current_wrapper=dummy_wrapper)
    assert code == 127
    captured = capsys.readouterr()
    assert (
        "Recursive launcher execution detected" in captured.err
        or "Target is the wrapper itself" in captured.err
    )


def test_launcher_recursion_guard_detects_launcher_proxy(tmp_path, capsys):
    manifest_file = tmp_path / "manifest.json"
    proxy_script = tmp_path / "other_proxy.cmd"
    proxy_script.write_text(
        "@echo off\npython -m script_logging.launcher --manifest m.json --command other -- %*\n",
        encoding="utf-8",
    )

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "mycmd": {
                "program_id": "module:mycmd",
                "kind": "console_script",
                "target": str(proxy_script),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    code = launch_target(manifest_file, "mycmd", [])
    assert code == 127
    captured = capsys.readouterr()
    assert "Recursive launcher execution detected" in captured.err


def test_launcher_target_missing_file_error(tmp_path, capsys):
    manifest_file = tmp_path / "manifest.json"
    missing_target = tmp_path / "does_not_exist.exe"

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "mycmd": {
                "program_id": "module:mycmd",
                "kind": "console_script",
                "target": str(missing_target),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    code = launch_target(manifest_file, "mycmd", [])
    assert code == 127
    captured = capsys.readouterr()
    assert "does not exist" in captured.err.lower()
    assert "setup.py" in captured.err.lower() or "build" in captured.err.lower()


def test_launcher_missing_command_in_manifest(tmp_path, capsys):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps({"schema_version": 1, "commands": {}}), encoding="utf-8")

    code = launch_target(manifest_file, "unknown_cmd", [])
    assert code == 127
    captured = capsys.readouterr()
    assert "not found in manifest" in captured.err.lower()


def test_launcher_missing_manifest_file(tmp_path, capsys):
    missing_manifest = tmp_path / "no_manifest.json"
    code = launch_target(missing_manifest, "any_cmd", [])
    assert code == 127
    captured = capsys.readouterr()
    assert "manifest" in captured.err.lower()


def test_launcher_fail_open_on_corrupt_database(tmp_path, monkeypatch):
    # Corrupt DB: a directory instead of a sqlite file
    corrupt_db = tmp_path / "corrupt_db_dir"
    corrupt_db.mkdir()
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(corrupt_db))

    target_py = tmp_path / "success_target.py"
    target_py.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "mycmd": {
                "program_id": "pyscript:success_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Target must STILL execute and return 7 despite database failure
    code = launch_target(manifest_file, "mycmd", [])
    assert code == 7


def test_launcher_main_cli_entry_point(tmp_path, monkeypatch):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    target_py = tmp_path / "cli_target.py"
    target_py.write_text(
        "import sys\nassert sys.argv[1:] == ['alpha', 'beta', '--opt=val']\nsys.exit(0)\n",
        encoding="utf-8",
    )

    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "testcli": {
                "program_id": "pyscript:cli_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    cli_args = [
        "--manifest",
        str(manifest_file),
        "--command",
        "testcli",
        "--origin",
        "custom_origin",
        "--",
        "alpha",
        "beta",
        "--opt=val",
    ]
    exit_code = main(cli_args)
    assert exit_code == 0

    reader = open_invocation_reader(db_path)
    page = reader.list_invocations(program_id="pyscript:cli_target.py")
    assert len(page.items) == 1
    assert page.items[0].origin == "custom_origin"
    assert page.items[0].exit_code == 0


def test_launcher_main_cli_without_double_dash(tmp_path, monkeypatch):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    target_py = tmp_path / "cli_target2.py"
    target_py.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "testcli2": {
                "program_id": "pyscript:cli_target2.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    cli_args = [
        "--manifest",
        str(manifest_file),
        "--command",
        "testcli2",
        "pos1",
        "pos2",
    ]
    exit_code = main(cli_args)
    assert exit_code == 0

    reader = open_invocation_reader(db_path)
    page = reader.list_invocations(program_id="pyscript:cli_target2.py")
    assert len(page.items) == 1
    assert page.items[0].exit_code == 0


def test_launcher_fail_open_when_store_throws(tmp_path, monkeypatch):
    target_py = tmp_path / "target.py"
    target_py.write_text("import sys\nsys.exit(13)\n", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "cmd": {
                "program_id": "pyscript:target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    class BrokenStore:
        def start_invocation(self, *args, **kwargs):
            raise RuntimeError("Database exploded")

        def finish_invocation(self, *args, **kwargs):
            raise RuntimeError("Database exploded again")

    code = launch_target(manifest_file, "cmd", [], store=BrokenStore())
    assert code == 13


@pytest.mark.parametrize("exit_val", [0, 1, 42, 100])
def test_launcher_child_exit_code_fidelity(tmp_path, monkeypatch, exit_val):
    target_py = tmp_path / "exit_target.py"
    target_py.write_text(f"import sys\nsys.exit({exit_val})\n", encoding="utf-8")

    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "cmd": {
                "program_id": "pyscript:exit_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    code = launch_target(manifest_file, "cmd", [])
    assert code == exit_val

