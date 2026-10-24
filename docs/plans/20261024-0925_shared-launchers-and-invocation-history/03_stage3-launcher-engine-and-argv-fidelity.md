# Stage 3: Launcher Execution Engine & Diagnostic Argv-Echo

**Stage Goal:** Implement the centralized launcher engine (`script_logging.launcher`) with strict recursion prevention, stream preservation, fail-open logging, and verify cross-platform argument fidelity against a diagnostic argv-echo harness across PowerShell 7 and CMD.

---

### Task 3.1: Launcher Execution Engine

**Files:**
- Create: `modules/script_logging/script_logging/launcher.py`
- Test: `modules/script_logging/tests/test_launcher.py`

**Interfaces:**
- Consumes: `invocation_store.py`, `models.py`.
- Produces:
  - `main(argv: list[str] | None = None) -> int`: Main CLI entry point for wrappers.
  - `launch_target(manifest_path: Path, command_name: str, args: list[str], *, origin: str = "launcher") -> int`.

- [ ] **Step 1: Write failing tests for launcher execution and recursion guard**

```python
# modules/script_logging/tests/test_launcher.py
import json
import sys
from pathlib import Path
import pytest
from script_logging.launcher import launch_target

def test_launcher_executes_target_and_records_invocation(tmp_path, monkeypatch):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    # Create dummy target python script
    target_py = tmp_path / "echo_target.py"
    target_py.write_text("import sys\nprint('TARGET_OUTPUT: ' + ' '.join(sys.argv[1:]))\nsys.exit(42)\n", encoding="utf-8")

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
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Execute via launcher
    code = launch_target(manifest_file, "mycmd", ["foo", "bar"], origin="launcher")
    assert code == 42

    # Verify DB recorded completed run
    from script_logging.reader import open_invocation_reader
    reader = open_invocation_reader(db_path)
    page = reader.list_invocations(program_id="pyscript:echo_target.py")
    assert len(page.items) == 1
    assert page.items[0].status == "exited"
    assert page.items[0].exit_code == 42

def test_launcher_recursion_guard_detects_self_reference(tmp_path, monkeypatch, capsys):
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
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Must reject recursion with actionable message and exit code 127
    code = launch_target(manifest_file, "mycmd", [], current_wrapper=dummy_wrapper)
    assert code == 127
    captured = capsys.readouterr()
    assert "Recursive launcher execution detected" in captured.err or "Target is the wrapper itself" in captured.err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_launcher.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'script_logging.launcher'`

- [ ] **Step 3: Implement `launcher.py`**

In `script_logging/launcher.py`:
- Parse CLI arguments: `--manifest <path>`, `--command <name>`, `--wrapper <path>`, `--origin <origin>`, followed by `--`, followed by target arguments.
- Load manifest JSON. If command missing: log actionable error to stderr, exit 127.
- Resolve target path:
  - Normalize target path relative to repo root if relative.
  - If target equals `current_wrapper` or points to another wrapper/proxy: raise/abort with exit code 127.
  - If target file does not exist: log actionable error (e.g. "Run python setup.py to build missing console scripts"), exit 127.
- Call `store.start_invocation` (with `fail_open=True`).
- Execute child process via `subprocess.Popen` / `subprocess.run`:
  - `console_script`: execute binary directly.
  - `python_file`: execute repo `.venv` python with `[target, *args]`.
  - Stdio: `stdin=None`, `stdout=None`, `stderr=None` to inherit parent streams directly.
  - Forward SIGINT / Ctrl+C.
- Call `store.finish_invocation` (with `fail_open=True`).
- Return child process exit code.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_launcher.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 3.1**

```bash
git add modules/script_logging/script_logging/launcher.py modules/script_logging/tests/test_launcher.py
git commit -m "feat(script_logging): implement launcher engine with recursion guard and fail-open execution"
```

---

### Task 3.2: Diagnostic Argv-Echo Harness & Windows Argv Fidelity

**Files:**
- Create: `modules/script_logging/tests/argv_echo_target.py`
- Create: `modules/script_logging/tests/test_argv_fidelity.py`

**Interfaces:**
- Consumes: `launcher.py`.
- Produces:
  - `argv_echo_target.py`: standalone script writing `sys.argv[1:]` as a JSON array to stdout.
  - Rigorous argv fidelity test suite covering PowerShell 7, CMD, spaces, quotes, empty strings, metacharacters, and Unicode.

- [ ] **Step 1: Write diagnostic echo target and fidelity test cases**

```python
# modules/script_logging/tests/argv_echo_target.py
import json
import sys

if __name__ == "__main__":
    json.dump(sys.argv[1:], sys.stdout)
    sys.stdout.write("\n")
    sys.exit(0)
```

```python
# modules/script_logging/tests/test_argv_fidelity.py
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from script_logging.launcher import launch_target

TEST_ARGV_CASES = [
    ["hello", "world"],
    ["with spaces", "second arg"],
    ["", "empty_string_first"],
    ["empty_string_middle", "", "tail"],
    ['quotes "inside" arg', "plain"],
    ["metachars: & | < > ^ % ! ( )"],
    ["unicode: 日本語 🚀 ñ ü"],
    ["literal backslashes: C:\\Program Files\\Toolkit\\"],
    ["--flag=value", "--other", "val"],
    ["--", "positional_after_dash_dash"],
]

@pytest.mark.parametrize("args", TEST_ARGV_CASES)
def test_direct_launcher_argv_fidelity(tmp_path, monkeypatch, args):
    db_path = tmp_path / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    target_py = Path(__file__).parent / "argv_echo_target.py"
    manifest_file = tmp_path / "manifest.json"
    manifest_data = {
        "schema_version": 1,
        "commands": {
            "echo": {
                "program_id": "pyscript:argv_echo_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Run in subprocess capturing output
    cmd = [sys.executable, "-m", "script_logging.launcher", "--manifest", str(manifest_file), "--command", "echo", "--", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    received = json.loads(res.stdout)
    assert received == args

@pytest.mark.skipif(os.name != "nt", reason="Windows batch wrapper fidelity test requires Windows")
def test_windows_cmd_wrapper_argv_fidelity(tmp_path):
    # Test through a generated .cmd wrapper on Windows
    pass
```

- [ ] **Step 2: Run test to verify it fails/passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_argv_fidelity.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS for direct launcher cases; ensure thorough validation for generated `.cmd` wrapper.

- [ ] **Step 3: Implement Windows `.cmd` wrapper testing and batch edge-case handling**

In `test_argv_fidelity.py`:
- Create a test `.cmd` wrapper:
  ```cmd
  @echo off
  "%_VENV_PY%" -m script_logging.launcher --manifest "%_MANIFEST%" --command echo -- %*
  ```
- Test invoking the `.cmd` wrapper from both `cmd.exe /c` and `pwsh -Command` / `powershell -Command`.
- Verify which metacharacters or quotes require specific handling, and document exact behavior in `CONTRACT.md`.

- [ ] **Step 4: Run test to verify all argv fidelity tests pass**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_argv_fidelity.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 3.2**

```bash
git add modules/script_logging/tests/argv_echo_target.py modules/script_logging/tests/test_argv_fidelity.py
git commit -m "test(script_logging): add diagnostic argv echo target and cross-platform fidelity tests"
```
