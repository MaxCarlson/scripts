# Stage 5: End-to-End Validation, Overhead Benchmarks, Contract & Documentation

**Stage Goal:** Run complete end-to-end integration tests, measure startup and recording overhead, write `CONTRACT.md`, bump `script_logging` version to 0.2.0, and finalize repository documentation and verification evidence.

---

### Task 5.1: End-to-End Integration Suite

**Files:**
- Create: `tests/test_shared_launcher_e2e.py`

**Interfaces:**
- Consumes: `launcher_generator.py`, `script_logging.launcher`, `script_logging.reader`.
- Produces: Complete end-to-end validation proving wrapper execution records into isolated SQLite database and preserves exit codes.

- [ ] **Step 1: Write failing end-to-end integration test**

```python
# tests/test_shared_launcher_e2e.py
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from scripts_setup.launcher_generator import scan_repository_programs, generate_manifest, generate_windows_wrapper, generate_posix_wrapper
from script_logging.reader import open_invocation_reader

def test_full_wrapper_to_database_e2e_flow(tmp_path, monkeypatch):
    # Setup temporary isolated repo structure
    repo_root = tmp_path / "repo"
    bin_dir = repo_root / "bin"
    bin_dir.mkdir(parents=True)
    db_path = tmp_path / "state" / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(db_path))

    # Target echo script
    target_py = repo_root / "test_target.py"
    target_py.write_text(
        "import sys, json\n"
        "print('HEARTBEAT')\n"
        "sys.exit(0 if 'fail' not in sys.argv else 7)\n",
        encoding="utf-8"
    )

    manifest_data = {
        "schema_version": 1,
        "commands": {
            "my_echo": {
                "program_id": "pyscript:test_target.py",
                "kind": "python_file",
                "target": str(target_py),
            }
        }
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

    # Invoke wrapper directly via subprocess
    cmd = [str(wrapper_path), "arg1", "--flag=val"] if is_win else [str(wrapper_path), "arg1", "--flag=val"]
    res = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True, shell=is_win)
    assert res.returncode == 0
    assert "HEARTBEAT" in res.stdout

    # Verify reader sees invocation
    reader = open_invocation_reader(db_path)
    invocations = reader.list_invocations(program_id="pyscript:test_target.py")
    assert len(invocations.items) == 1
    record = invocations.items[0]
    assert record.status == "exited"
    assert record.exit_code == 0
    assert record.invoked_name == "my_echo"
    assert "arg1" in record.argv_json

    # Test failure path
    fail_cmd = [str(wrapper_path), "fail"]
    res_fail = subprocess.run(fail_cmd, cwd=str(repo_root), capture_output=True, text=True, shell=is_win)
    assert res_fail.returncode == 7

    stats = reader.get_program_statistics("pyscript:test_target.py")
    assert stats.total_starts == 2
    assert stats.success_count == 1
    assert stats.failure_count == 1
```

- [ ] **Step 2: Run test to verify it fails/passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_shared_launcher_e2e.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 3: Implement any boundary edge cases identified in e2e testing**

Ensure working directory, relative path resolution, and shell invocation flags behave correctly under Windows CMD and PowerShell.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest tests/test_shared_launcher_e2e.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 5.1**

```bash
git add tests/test_shared_launcher_e2e.py
git commit -m "test: add end-to-end wrapper-to-database integration verification"
```

---

### Task 5.2: Startup Overhead Benchmarks

**Files:**
- Create: `modules/script_logging/tests/benchmark_overhead.py`

**Interfaces:**
- Measures:
  - Cold startup latency (first invocation loading sqlite3, schema, writing start/finish).
  - Warm startup latency (subsequent invocations over 50 iterations, reporting p50 and p95).
  - Direct executable launch vs launcher wrapper launch comparison.

- [ ] **Step 1: Write benchmark script**

```python
# modules/script_logging/tests/benchmark_overhead.py
import time
import subprocess
import statistics
import sys
from pathlib import Path

def benchmark_overhead():
    # Measure baseline: python -c "pass"
    direct_times = []
    for _ in range(30):
        t0 = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        direct_times.append((time.perf_counter() - t0) * 1000)

    # Measure launcher overhead: python -m script_logging.launcher ...
    # ...
    print(f"Direct: p50={statistics.median(direct_times):.1f}ms")
```

- [ ] **Step 2: Run benchmark script and record measurements**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe modules/script_logging/tests/benchmark_overhead.py`
Expected: Outputs quantitative before/after p50/p95 latency and memory metrics.

- [ ] **Step 3: Add automated test asserting latency bounds**

Add a test in `modules/script_logging/tests/test_overhead.py` verifying that warm recording overhead adds less than 60ms to execution time.

- [ ] **Step 4: Commit Task 5.2**

```bash
git add modules/script_logging/tests/benchmark_overhead.py
git commit -m "perf(script_logging): add startup overhead benchmarks and latency regression checks"
```

---

### Task 5.3: CONTRACT.md, Standards & Version Bumps

**Files:**
- Create: `CONTRACT.md`
- Modify: `modules/script_logging/pyproject.toml`
- Modify: `modules/script_logging/script_logging/__init__.py`

**Interfaces:**
- Produces:
  - `CONTRACT.md` documenting:
    - Canonical program identity rules (`module:<name>`, `pyscript:<relpath>`, `shell:<relpath>`).
    - Lifecycle states (`started`, `exited`, `launch_failed`, `interrupted`, `unknown`).
    - Public reader API signatures, cursor pagination, and ordering semantics.
    - Privacy policy, default redacted patterns, and opt-out flags.
    - State paths per platform and environment variable overrides.
    - Representative synthetic JSON records.
  - Bump `script-logging` version to `0.2.0` in `pyproject.toml` and `__init__.py`.

- [ ] **Step 1: Draft `CONTRACT.md`**

Write `CONTRACT.md` with full specification of database schema, status lifecycle, public API contracts, and privacy guarantees.

- [ ] **Step 2: Bump version in `pyproject.toml` and `__init__.py`**

In `modules/script_logging/pyproject.toml`: `version = "0.2.0"`.
In `modules/script_logging/script_logging/__init__.py`: `__version__ = "0.2.0"`.

- [ ] **Step 3: Run repository linter and test suite**

Run:
```bash
ruff check modules/script_logging scripts_setup tests
C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging tests --basetemp=modules/script_logging/.pytest_tmp_root
```
Expected: All tests pass, Ruff clean.

- [ ] **Step 4: Commit Task 5.3**

```bash
git add CONTRACT.md modules/script_logging/pyproject.toml modules/script_logging/script_logging/__init__.py
git commit -m "docs: publish invocation infrastructure CONTRACT.md and bump script_logging to 0.2.0"
```
