# Stage 2: Read-Only Query API, Reader, and Reconciliation

**Stage Goal:** Implement `ReadOnlyHistoryReader` using SQLite URI read-only mode, cursor-paginated deterministic queries, counter reconciliation tooling, and synthetic test fixtures for consumer integration in `modules/script_logging`.

---

### Task 2.1: ReadOnlyHistoryReader

**Files:**
- Create: `modules/script_logging/script_logging/reader.py`
- Test: `modules/script_logging/tests/test_reader.py`

**Interfaces:**
- Consumes: `models.py`, `invocation_store.resolve_invocation_db_path`.
- Produces:
  - `ReadOnlyHistoryReader` class in `script_logging.reader`.
  - `open_invocation_reader(path: Path | None = None) -> ReadOnlyHistoryReader`.

- [x] **Step 1: Write failing tests for read-only invariants**

```python
# modules/script_logging/tests/test_reader.py
from pathlib import Path
import pytest
from script_logging.reader import open_invocation_reader, ReadOnlyHistoryReader

def test_reader_does_not_create_missing_db(tmp_path):
    missing_path = tmp_path / "nonexistent" / "invocations.sqlite3"
    with pytest.raises(FileNotFoundError):
        open_invocation_reader(missing_path)
    assert not missing_path.exists()
    assert not missing_path.parent.exists()

def test_reader_cannot_write(tmp_path):
    from script_logging.invocation_store import InvocationStore
    db_path = tmp_path / "invocations.sqlite3"
    InvocationStore(db_path)  # create and initialize

    reader = open_invocation_reader(db_path)
    # Attempting to execute an INSERT or UPDATE must fail with OperationalError: attempt to write a readonly database
    import sqlite3
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with reader._connect() as conn:
            conn.execute("INSERT INTO schema_meta VALUES ('test', 'fail')")
```

- [x] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_reader.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'script_logging.reader'`

- [x] **Step 3: Implement `ReadOnlyHistoryReader`**

In `script_logging/reader.py`:
- `open_invocation_reader(path: Path | None = None) -> ReadOnlyHistoryReader`:
  - If `path` is None, calls `resolve_invocation_db_path(create=False)`.
  - Checks `path.is_file()`. If not found, raises `FileNotFoundError(f"Invocation database not found at {path}")`.
- `ReadOnlyHistoryReader._connect()`:
  - Formats URI: `f"file:{path.as_posix()}?mode=ro"`.
  - `sqlite3.connect(uri=True, timeout=15)`.
  - Sets `PRAGMA busy_timeout = 15000;`.
  - Sets `row_factory = sqlite3.Row`.

- [x] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_reader.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [x] **Step 5: Commit Task 2.1**

```bash
git add modules/script_logging/script_logging/reader.py modules/script_logging/tests/test_reader.py
git commit -m "feat(script_logging): implement ReadOnlyHistoryReader with URI mode=ro"
```

---

### Task 2.2: Public Query API and Cursor Pagination

**Files:**
- Modify: `modules/script_logging/script_logging/reader.py`
- Modify: `modules/script_logging/script_logging/__init__.py`
- Test: `modules/script_logging/tests/test_queries.py`

**Interfaces:**
- Consumes: `models.py`, `reader.py`.
- Produces:
  - `list_invocations(...) -> Page[InvocationRecord]`
  - `list_unique_commands(...) -> Page[CommandPattern]`
  - `get_program_statistics(...) -> ProgramStatistics`
  - `get_command_statistics(...) -> CommandStatistics`
  - Exported through `script_logging/__init__.py`.

- [x] **Step 1: Write failing tests for queries and cursor pagination**

```python
# modules/script_logging/tests/test_queries.py
from datetime import datetime, timezone
from pathlib import Path
import pytest
from script_logging.invocation_store import InvocationStore
from script_logging.reader import open_invocation_reader

def test_query_pagination_and_deterministic_order(tmp_path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    for i in range(15):
        inv_id = store.start_invocation(
            program_id="module:mangadl",
            invoked_name="mangadl",
            argv=("mangadl", "run", f"--step={i}"),
            cwd=Path("/work"),
            origin="launcher",
        )
        store.finish_invocation(inv_id, exit_code=0 if i % 2 == 0 else 1, status="exited")

    reader = open_invocation_reader(db_path)
    page1 = reader.list_invocations(limit=5)
    assert len(page1.items) == 5
    assert page1.next_cursor is not None

    page2 = reader.list_invocations(limit=5, cursor=page1.next_cursor)
    assert len(page2.items) == 5
    # Ensure no overlap between page 1 and page 2
    ids1 = {r.invocation_id for r in page1.items}
    ids2 = {r.invocation_id for r in page2.items}
    assert ids1.isdisjoint(ids2)

    # Program statistics
    stats = reader.get_program_statistics("module:mangadl")
    assert stats.total_starts == 15
    assert stats.success_count == 8
    assert stats.failure_count == 7
```

- [x] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_queries.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `AttributeError: 'ReadOnlyHistoryReader' object has no attribute 'list_invocations'`

- [x] **Step 3: Implement query methods and cursor serialization**

In `reader.py`:
- Deterministic order: `ORDER BY started_epoch_ms DESC, invocation_id DESC`.
- Cursor format: Base64-encoded `f"{epoch_ms}:{inv_id}"`. When cursor is provided, query adds `WHERE (started_epoch_ms < :cursor_epoch) OR (started_epoch_ms = :cursor_epoch AND invocation_id < :cursor_id)`.
- Implement `list_invocations`: supports filters for `program_id`, `invoked_name`, `status`, `since`, `before`.
- Implement `list_unique_commands`: returns `Page[CommandPattern]` ordered by `last_seen_utc DESC` or invocation count.
- Implement `get_program_statistics`: aggregates totals, success/failure counts, first/last seen.
- Implement `get_command_statistics`: queries pattern-level statistics.
- Export public helper wrappers in `script_logging/__init__.py`.

- [x] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_queries.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [x] **Step 5: Commit Task 2.2**

```bash
git add modules/script_logging/script_logging/reader.py modules/script_logging/script_logging/__init__.py modules/script_logging/tests/test_queries.py
git commit -m "feat(script_logging): implement cursor pagination and statistics query API"
```

---

### Task 2.3: Reconciliation Tooling

**Files:**
- Create: `modules/script_logging/script_logging/reconciliation.py`
- Test: `modules/script_logging/tests/test_reconciliation.py`

**Interfaces:**
- Consumes: `invocation_store.py`, `models.py`.
- Produces:
  - `reconcile_invocation_summaries(path: Path | None = None, *, dry_run: bool = True) -> ReconciliationReport`.

- [x] **Step 1: Write failing test for counter reconciliation**

```python
# modules/script_logging/tests/test_reconciliation.py
from pathlib import Path
import pytest
from script_logging.invocation_store import InvocationStore
from script_logging.reconciliation import reconcile_invocation_summaries

def test_reconciliation_detects_and_fixes_drift(tmp_path):
    db_path = tmp_path / "invocations.sqlite3"
    store = InvocationStore(db_path)
    inv_id = store.start_invocation(
        program_id="module:mangadl",
        invoked_name="mangadl",
        argv=("mangadl", "run"),
        cwd=Path("/tmp"),
        origin="launcher",
    )
    store.finish_invocation(inv_id, exit_code=0, status="exited")

    # Artificially tamper with program_usage counter
    with store._connect() as conn:
        conn.execute("UPDATE program_usage SET success_count = 999 WHERE program_id = 'module:mangadl'")

    # Dry-run detects mismatch without changing
    report_dry = reconcile_invocation_summaries(db_path, dry_run=True)
    assert report_dry.mismatches_found > 0
    assert report_dry.corrections_applied == 0

    # Apply fixes
    report_apply = reconcile_invocation_summaries(db_path, dry_run=False)
    assert report_apply.corrections_applied > 0

    # Verify counter is restored to actual truth (1)
    with store._connect() as conn:
        count = conn.execute("SELECT success_count FROM program_usage WHERE program_id = 'module:mangadl'").fetchone()[0]
        assert count == 1
```

- [x] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_reconciliation.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError: No module named 'script_logging.reconciliation'`

- [x] **Step 3: Implement `reconciliation.py`**

In `reconciliation.py`:
- Scan `invocations` table: recompute aggregate totals for `command_patterns`, `program_usage`, `alias_usage`.
- Compare against current rows in each summary table.
- Record any discrepancy in `ReconciliationReport`.
- If `dry_run=False`, execute `UPDATE` / `INSERT` in a single transaction to restore consistency.

- [x] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_reconciliation.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [x] **Step 5: Commit Task 2.3**

```bash
git add modules/script_logging/script_logging/reconciliation.py modules/script_logging/tests/test_reconciliation.py
git commit -m "feat(script_logging): implement summary counter reconciliation tooling"
```

---

### Task 2.4: Synthetic Fixture for Consumer Integration

**Files:**
- Create: `modules/script_logging/tests/fixtures/synthetic_history.py`
- Create: `modules/script_logging/tests/test_consumer_contract.py`

**Interfaces:**
- Consumes: `invocation_store.py`, `reader.py`.
- Produces:
  - `generate_synthetic_database(path: Path) -> dict[str, Any]`: Reproducible synthetic test database fixture.

- [x] **Step 1: Write consumer contract test using synthetic fixture**

```python
# modules/script_logging/tests/test_consumer_contract.py
from pathlib import Path
import pytest
from script_logging.tests.fixtures.synthetic_history import generate_synthetic_database
from script_logging.reader import open_invocation_reader

def test_consumer_query_contract_against_synthetic_data(tmp_path):
    db_path = tmp_path / "synthetic.sqlite3"
    expected = generate_synthetic_database(db_path)

    reader = open_invocation_reader(db_path)
    # Check that programs list matches
    for prog_id, prog_meta in expected["programs"].items():
        stats = reader.get_program_statistics(prog_id)
        assert stats.total_starts == prog_meta["total_starts"]
        assert stats.success_count == prog_meta["success_count"]
        assert stats.failure_count == prog_meta["failure_count"]

    # Verify query for unique patterns
    patterns_page = reader.list_unique_commands(limit=50)
    assert len(patterns_page.items) == expected["pattern_count"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_consumer_contract.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement `synthetic_history.py`**

Implement deterministic fixture population with predictable distributions across multiple programs (`module:mangadl`, `module:compresser`, `pyscript:pyscripts/run_history_process.py`), including varied exit codes, durations, origins, and redacted argument patterns.

- [x] **Step 4: Run test to verify it passes**

Run: `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m pytest modules/script_logging/tests/test_consumer_contract.py --basetemp=modules/script_logging/.pytest_tmp_root`
Expected: PASS

- [x] **Step 5: Commit Task 2.4**

```bash
git add modules/script_logging/tests/fixtures/synthetic_history.py modules/script_logging/tests/test_consumer_contract.py
git commit -m "test(script_logging): add synthetic history fixture and consumer contract verification"
```
