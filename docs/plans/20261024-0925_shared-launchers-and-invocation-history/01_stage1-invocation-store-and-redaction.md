# Stage 1: Invocation Store, Redaction, Schema, and Core Persistence

**Stage Goal:** Build the database schema, models, privacy/redaction engine, platform path resolution, and `InvocationStore` with atomic start/finish lifecycle and counter maintenance in `modules/script_logging`.

---

### Task 1.1: Models, Schema, and Path Resolver

**Files:**
- Create: `modules/script_logging/script_logging/models.py`
- Create: `modules/script_logging/script_logging/invocation_store.py`
- Test: `modules/script_logging/tests/test_invocation_store.py`

**Interfaces:**
- Consumes: None (standard library `dataclasses`, `pathlib`, `uuid`, `datetime`, `sqlite3`).
- Produces:
  - `InvocationRecord`, `CommandPattern`, `ProgramStatistics`, `AliasStatistics`, `Page`, `ReconciliationReport` in `script_logging.models`.
  - `resolve_invocation_db_path(*, create: bool = False) -> Path` in `script_logging.invocation_store`.
  - `InvocationStore` class in `script_logging.invocation_store`.

- [ ] **Step 1: Write the failing test for models and path resolution**

```python
# modules/script_logging/tests/test_invocation_store.py
import os
from pathlib import Path
import pytest
from script_logging.invocation_store import resolve_invocation_db_path, InvocationStore
from script_logging.models import InvocationRecord

def test_resolve_invocation_db_path_env_override(monkeypatch, tmp_path):
    override = tmp_path / "custom" / "invocations.sqlite3"
    monkeypatch.setenv("SCRIPT_LOGGING_INVOCATION_DB", str(override))
    resolved = resolve_invocation_db_path(create=False)
    assert resolved == override
    assert not resolved.parent.exists()

    resolved_created = resolve_invocation_db_path(create=True)
    assert resolved_created == override
    assert resolved_created.parent.is_dir()

def test_resolve_invocation_db_path_platform_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIPT_LOGGING_INVOCATION_DB", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    path = resolve_invocation_db_path(create=True)
    assert "ScriptsToolkit" in str(path) or "scripts-toolkit" in str(path)
    assert path.name == "invocations.sqlite3"

def test_invocation_store_initializes_schema(tmp_path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    with store._connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"schema_meta", "invocations", "command_patterns", "program_usage", "alias_usage"}.issubset(tables)
        version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        assert version == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_store.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'script_logging.models'` or `cannot import name 'InvocationStore'`

- [ ] **Step 3: Implement `models.py` and `invocation_store.py` schema initialization**

Implement `models.py` with typed frozen dataclasses (`InvocationRecord`, `CommandPattern`, `ProgramStatistics`, `AliasStatistics`, `Page`, `ReconciliationReport`).
Implement `resolve_invocation_db_path` supporting `SCRIPT_LOGGING_INVOCATION_DB`, Windows `%LOCALAPPDATA%\ScriptsToolkit\invocations.sqlite3`, POSIX `${XDG_STATE_HOME:-~/.local/state}/scripts-toolkit/invocations.sqlite3`, and macOS `~/Library/Application Support/ScriptsToolkit/invocations.sqlite3`.
Implement `InvocationStore.__init__` with SQLite WAL mode, foreign keys, busy timeout (15000ms), and `CREATE TABLE IF NOT EXISTS` for `schema_meta`, `invocations`, `command_patterns`, `program_usage`, and `alias_usage`.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_store.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 1.1**

```bash
git add modules/script_logging/script_logging/models.py modules/script_logging/script_logging/invocation_store.py modules/script_logging/tests/test_invocation_store.py
git commit -m "feat(script_logging): add invocation models, schema initialization, and path resolver"
```

---

### Task 1.2: Redaction Policy and Sanitization

**Files:**
- Create: `modules/script_logging/script_logging/redaction.py`
- Test: `modules/script_logging/tests/test_redaction.py`

**Interfaces:**
- Consumes: None (standard library `re`, `json`, `hashlib`, `urllib.parse`).
- Produces:
  - `redact_argv(argv: tuple[str, ...], *, max_args: int = 256, max_cmd_len: int = 8192) -> tuple[tuple[str, ...], bool]`
  - `compute_pattern_id(program_id: str, redacted_argv: tuple[str, ...]) -> str`
  - `normalize_argv_json(redacted_argv: tuple[str, ...]) -> str`

- [ ] **Step 1: Write the failing test for redaction rules**

```python
# modules/script_logging/tests/test_redaction.py
import pytest
from script_logging.redaction import redact_argv, compute_pattern_id

def test_redact_sensitive_flags_equals_and_spaced():
    argv = (
        "mytool",
        "--token=ghp_secret123",
        "--password", "supersecret",
        "--api-key", "key987",
        "-p", "8080",  # Legitimate port option must NOT be redacted
        "--path", "/usr/bin",
        "https://user:pass@example.com/api?token=abc&page=2"
    )
    redacted, is_redacted = redact_argv(argv)
    assert is_redacted is True
    assert "--token=[REDACTED]" in redacted
    assert "supersecret" not in redacted
    assert "key987" not in redacted
    assert "-p" in redacted and "8080" in redacted
    assert "--path" in redacted and "/usr/bin" in redacted
    # URL userinfo and sensitive query param redacted
    assert "https://user:[REDACTED]@example.com/api?token=[REDACTED]&page=2" in redacted

def test_redact_truncation():
    huge_argv = tuple(["arg"] * 300)
    redacted, is_redacted = redact_argv(huge_argv, max_args=100)
    assert is_redacted is True
    assert len(redacted) == 101
    assert redacted[-1] == "[TRUNCATED:count=200]"

def test_pattern_id_deterministic():
    p1 = compute_pattern_id("module:mangadl", ("mangadl", "dl", "--quality", "high"))
    p2 = compute_pattern_id("module:mangadl", ("mangadl", "dl", "--quality", "high"))
    p3 = compute_pattern_id("module:compresser", ("compresser", "dl", "--quality", "high"))
    assert p1 == p2
    assert p1 != p3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_redaction.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'script_logging.redaction'`

- [ ] **Step 3: Implement `redaction.py`**

Implement regex and URL parsing for credentials, tokens, sensitive query parameters (`token`, `secret`, `key`, `auth`, `password`), flag-value pair tracking, length/count truncation with explicit `[TRUNCATED:...]` markers, and SHA-256 pattern hashing.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_redaction.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 1.2**

```bash
git add modules/script_logging/script_logging/redaction.py modules/script_logging/tests/test_redaction.py
git commit -m "feat(script_logging): implement sensitive argument redaction and pattern hashing"
```

---

### Task 1.3: Start & Finish Lifecycle with Atomic Counter Invariants

**Files:**
- Modify: `modules/script_logging/script_logging/invocation_store.py`
- Test: `modules/script_logging/tests/test_invocation_store.py`

**Interfaces:**
- Consumes: `models.py`, `redaction.py`.
- Produces:
  - `InvocationStore.start_invocation(...) -> str`
  - `InvocationStore.finish_invocation(...) -> None`
  - `InvocationStore.get_invocation(invocation_id: str) -> InvocationRecord | None`

- [ ] **Step 1: Write the failing test for start/finish and counter invariants**

```python
# in modules/script_logging/tests/test_invocation_store.py
from datetime import datetime, timezone
from pathlib import Path

def test_start_and_finish_invocation_lifecycle(tmp_path):
    store = InvocationStore(tmp_path / "invocations.sqlite3")
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "chapter", "1"),
        cwd=Path("/work"),
        origin="launcher",
    )
    assert inv_id is not None

    record = store.get_invocation(inv_id)
    assert record.status == "started"
    assert record.exit_code is None

    # Check pattern and usage counters incremented on start
    with store._connect() as conn:
        usage = conn.execute("SELECT total_starts, success_count FROM program_usage WHERE program_id='module:mangadl'").fetchone()
        assert usage["total_starts"] == 1
        assert usage["success_count"] == 0

    # Finish invocation successfully
    store.finish_invocation(inv_id, exit_code=0, status="exited")
    record_finished = store.get_invocation(inv_id)
    assert record_finished.status == "exited"
    assert record_finished.exit_code == 0
    assert record_finished.duration_ms is not None

    # Check counter incremented exactly once
    with store._connect() as conn:
        usage = conn.execute("SELECT total_starts, success_count, failure_count FROM program_usage WHERE program_id='module:mangadl'").fetchone()
        assert usage["total_starts"] == 1
        assert usage["success_count"] == 1
        assert usage["failure_count"] == 0

    # Duplicate finish must be idempotent
    store.finish_invocation(inv_id, exit_code=0, status="exited")
    with store._connect() as conn:
        usage = conn.execute("SELECT total_starts, success_count FROM program_usage WHERE program_id='module:mangadl'").fetchone()
        assert usage["success_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_store.py -k test_start_and_finish_invocation_lifecycle --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `AttributeError: 'InvocationStore' object has no attribute 'start_invocation'`

- [ ] **Step 3: Implement `start_invocation` and `finish_invocation`**

In `invocation_store.py`:
- `start_invocation`:
  - Redacts `argv` using `redact_argv`.
  - Calculates pattern ID and normalizes JSON.
  - Inserts row into `invocations` with `status="started"`.
  - Inside the same transaction, UPSERT into `command_patterns` (incrementing `invocation_count` by 1).
  - Inside the same transaction, UPSERT into `program_usage` and `alias_usage` (incrementing `total_starts` by 1).
- `finish_invocation`:
  - Finds existing row in `invocations`. If already in terminal status (`exited`, `launch_failed`, `interrupted`), return early (idempotent).
  - Computes `duration_ms` from `started_epoch_ms` and finished time.
  - Updates `invocations` row (`finished_at_utc`, `duration_ms`, `exit_code`, `status`).
  - Inside the same transaction, updates summary counts (`success_count` if `exit_code == 0 and status == "exited"`, else `failure_count` or `unknown_count`) in `command_patterns`, `program_usage`, and `alias_usage`.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_store.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 1.3**

```bash
git add modules/script_logging/script_logging/invocation_store.py modules/script_logging/tests/test_invocation_store.py
git commit -m "feat(script_logging): implement start/finish invocation lifecycle and counter maintenance"
```

---

### Task 1.4: Concurrency, Busy Timeout, and Fail-Open Safety

**Files:**
- Modify: `modules/script_logging/script_logging/invocation_store.py`
- Create: `modules/script_logging/tests/test_invocation_concurrency.py`

**Interfaces:**
- Consumes: `InvocationStore`.
- Produces: Robust WAL concurrency and fail-open exception wrappers.

- [ ] **Step 1: Write concurrency and fail-open tests**

```python
# modules/script_logging/tests/test_invocation_concurrency.py
import concurrent.futures
from pathlib import Path
import pytest
from script_logging.invocation_store import InvocationStore

def _run_worker(db_path: Path, worker_id: int, runs: int):
    store = InvocationStore(db_path)
    for i in range(runs):
        inv_id = store.start_invocation(
            program_id=f"module:worker_{worker_id % 3}",
            invoked_name=f"worker_{worker_id % 3}",
            argv=(f"worker_{worker_id % 3}", "--run", str(i)),
            cwd=Path("/tmp"),
            origin="test",
        )
        store.finish_invocation(inv_id, exit_code=0, status="exited")

def test_multiprocess_multithread_concurrency(tmp_path):
    db_path = tmp_path / "concurrent.sqlite3"
    # Seed db
    InvocationStore(db_path)

    workers = 8
    runs_per_worker = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_run_worker, db_path, wid, runs_per_worker) for wid in range(workers)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    store = InvocationStore(db_path)
    with store._connect() as conn:
        total_invocations = conn.execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
        assert total_invocations == workers * runs_per_worker

def test_fail_open_on_readonly_storage(tmp_path, monkeypatch):
    db_path = tmp_path / "broken.sqlite3"
    store = InvocationStore(db_path)
    # Monkeypatch _connect to simulate OperationalError
    def _failing_connect():
        import sqlite3
        raise sqlite3.OperationalError("disk I/O error or locked")
    monkeypatch.setattr(store, "_connect", _failing_connect)

    # Must fail open (return fallback id or None, not raise exception)
    inv_id = store.start_invocation(
        program_id="module:test",
        invoked_name="test",
        argv=("test",),
        cwd=Path("/tmp"),
        origin="launcher",
        fail_open=True,
    )
    assert inv_id.startswith("fallback-")
    # Finish must also not raise
    store.finish_invocation(inv_id, exit_code=0, status="exited", fail_open=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_concurrency.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL

- [ ] **Step 3: Implement concurrency tuning and fail-open wrappers**

In `invocation_store.py`:
- Ensure `PRAGMA journal_mode = WAL;` and `PRAGMA busy_timeout = 15000;` on all connections.
- Support `fail_open: bool = True` on `start_invocation` and `finish_invocation`: catches `sqlite3.Error`, generates ephemeral fallback UUID, and optionally writes bounded diagnostic warning to stderr only if `os.environ.get("SCRIPT_LOGGING_DEBUG") == "1"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_invocation_concurrency.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [ ] **Step 5: Commit Task 1.4**

```bash
git add modules/script_logging/script_logging/invocation_store.py modules/script_logging/tests/test_invocation_concurrency.py
git commit -m "feat(script_logging): add WAL concurrency protection and fail-open safety"
```
