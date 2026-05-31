# Agent Sync Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `agent_sync` module foundation: SQLite schema, state layer,
worktree manager, Markdown doc renderer, hook dispatcher skeleton, and a working
CLI with `init` and `doctor` commands. No provider adapters yet — those come in
Phase 2.

**Architecture:** SQLite WAL DB at `agent_sync/db/state.sqlite3` owns runtime
truth. State layer modules (`tasks`, `runs`, `claims`, `events`) are thin CRUD
wrappers over it. The hook dispatcher is a Python module invoked by thin shell
wrappers, normalizes provider JSON payloads, and calls event handlers. The CLI
is an argparse entrypoint with subcommands.

**Tech Stack:** Python 3.11+, `sqlite3` stdlib, `argparse`, `subprocess`,
`dataclasses`, `pathlib`, `pytest`, `uv`

**Read first:** `agent_sync/docs/plans/OVERVIEW.md` for module layout and
integration context.

---

## File Map

| File | Responsibility |
|---|---|
| `agent_sync/__init__.py` | Package version |
| `agent_sync/cli.py` | `argparse` entry point, subcommand registration |
| `agent_sync/db/__init__.py` | Package marker |
| `agent_sync/db/connection.py` | `get_connection()` — WAL, FK, busy_timeout |
| `agent_sync/db/schema.py` | DDL string constants + `initialize_schema()` |
| `agent_sync/state/__init__.py` | Package marker |
| `agent_sync/state/tasks.py` | `Task` dataclass + `create_task`, `get_task`, `update_task_status`, `list_tasks` |
| `agent_sync/state/runs.py` | `Run` dataclass + `start_run`, `end_run`, `heartbeat`, `get_active_run` |
| `agent_sync/state/claims.py` | `Claim` dataclass + `acquire_claims`, `release_claims`, `check_conflicts` |
| `agent_sync/state/handoffs.py` | `Handoff` dataclass + `create_handoff`, `accept_handoff` |
| `agent_sync/state/events.py` | `log_event()`, `record_artifact()` |
| `agent_sync/worktree.py` | `create_worktree()`, `remove_worktree()`, `list_worktrees()` |
| `agent_sync/docs_gen/__init__.py` | Package marker |
| `agent_sync/docs_gen/templates.py` | String template constants for SESSION_BRIEF, HANDOFF, AGENT_CONTRACT |
| `agent_sync/docs_gen/renderer.py` | `render_session_brief()`, `render_handoff()`, `render_agent_contract()` |
| `agent_sync/hooks/__init__.py` | Package marker |
| `agent_sync/hooks/normalize.py` | `HookEvent` dataclass, `normalize_payload()` |
| `agent_sync/hooks/dispatch.py` | `__main__` entry: parse args, normalize, route to handler |
| `agent_sync/hooks/handlers/__init__.py` | Package marker |
| `agent_sync/hooks/handlers/session_start.py` | Inject SESSION_BRIEF into hook output |
| `agent_sync/hooks/handlers/pre_tool.py` | Block forbidden commands, preflight claims |
| `agent_sync/hooks/handlers/post_tool.py` | Record artifacts, update claim paths |
| `agent_sync/hooks/handlers/stop.py` | Render HANDOFF.md, end run |
| `agent_sync/shell/claude-dispatch.sh` | Shell wrapper → `python -m agent_sync.hooks.dispatch` |
| `agent_sync/shell/codex-dispatch.sh` | Same, provider=codex |
| `agent_sync/shell/gemini-dispatch.sh` | Same, provider=gemini |
| `agent_sync/commands/__init__.py` | Package marker |
| `agent_sync/commands/init.py` | `cmd_init()` — bootstrap DB + provider configs |
| `agent_sync/commands/doctor.py` | `cmd_doctor()` — verify hooks, DB, worktrees |
| `tests/test_agent_sync_db_test.py` | DB connection, schema, migrations |
| `tests/test_agent_sync_state_test.py` | Task, Run, Handoff CRUD |
| `tests/test_agent_sync_claims_test.py` | Claim acquire/release/conflict |
| `tests/test_agent_sync_worktree_test.py` | Worktree create/remove/list |
| `tests/test_agent_sync_hooks_test.py` | Normalize payloads, handler outputs |

---

## Task 1: Package skeleton + DB connection

**Files:**
- Create: `agent_sync/__init__.py`
- Create: `agent_sync/db/__init__.py`
- Create: `agent_sync/db/connection.py`
- Create: `tests/test_agent_sync_db_test.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_sync_db_test.py
import sqlite3
import tempfile
from pathlib import Path
import pytest
from agent_sync.db.connection import get_connection


def test_get_connection_returns_connection(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_get_connection_enables_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    conn.close()


def test_get_connection_enforces_foreign_keys(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    conn = get_connection(db_path)
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    conn.close()


def test_get_connection_creates_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "state.sqlite3"
    conn = get_connection(db_path)
    assert db_path.exists()
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/mcarls/projects/ai-orchestrator
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_db_test.py -v
```
Expected: `ModuleNotFoundError: No module named 'agent_sync'`

- [ ] **Step 3: Create the package and connection module**

```python
# agent_sync/__init__.py
__version__ = "0.1.0"
```

```python
# agent_sync/db/__init__.py
```

```python
# agent_sync/db/connection.py
import sqlite3
from pathlib import Path


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return an SQLite connection with WAL mode, FK enforcement, and busy timeout.

    Args:
        db_path: Path to the SQLite database file. Parent directories are created
            if they do not exist.

    Returns:
        An open sqlite3.Connection configured for concurrent safe use.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_db_test.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add agent_sync/__init__.py agent_sync/db/__init__.py agent_sync/db/connection.py tests/test_agent_sync_db_test.py
git commit -m "feat(agent_sync): package skeleton + SQLite WAL connection"
```

---

## Task 2: Database schema

**Files:**
- Create: `agent_sync/db/schema.py`
- Modify: `tests/test_agent_sync_db_test.py` (add schema tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_agent_sync_db_test.py`:

```python
from agent_sync.db.schema import initialize_schema


def test_initialize_schema_creates_tables(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_meta", "agents", "tasks", "task_dependencies",
        "runs", "claims", "handoffs", "events", "artifacts", "memory_links",
    }
    assert expected.issubset(tables)
    conn.close()


def test_initialize_schema_is_idempotent(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    initialize_schema(conn)  # should not raise
    conn.close()


def test_schema_meta_has_version(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    version = conn.execute("SELECT schema_version FROM schema_meta").fetchone()
    assert version is not None
    assert version[0] == 1
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_db_test.py -v -k "schema"
```
Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 3: Implement schema.py**

```python
# agent_sync/db/schema.py
"""SQLite schema DDL for the agent_sync coordination database.

All tables use STRICT mode (requires SQLite 3.37+). The schema tracks agents,
tasks, runs, file-level claims, handoffs, events, and run artifacts.
"""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER NOT NULL PRIMARY KEY,
    applied_at     TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS agents (
    agent_name        TEXT    NOT NULL PRIMARY KEY,
    provider          TEXT    NOT NULL,
    adapter_name      TEXT    NOT NULL,
    cli_command       TEXT    NOT NULL,
    default_profile   TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    capabilities_json TEXT    NOT NULL,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS tasks (
    task_id        TEXT    NOT NULL PRIMARY KEY,
    parent_task_id TEXT    REFERENCES tasks(task_id) ON DELETE SET NULL,
    title          TEXT    NOT NULL,
    kind           TEXT    NOT NULL,
    priority       INTEGER NOT NULL,
    status         TEXT    NOT NULL,
    target_branch  TEXT    NOT NULL,
    manifest_path  TEXT    NOT NULL,
    summary_md     TEXT    NOT NULL,
    acceptance_md  TEXT,
    routing_json   TEXT    NOT NULL,
    scoring_json   TEXT    NOT NULL,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL,
    started_at     TEXT,
    completed_at   TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id             TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id  TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id)
) STRICT;

CREATE TABLE IF NOT EXISTS runs (
    run_id                  TEXT    NOT NULL PRIMARY KEY,
    task_id                 TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    parent_run_id           TEXT    REFERENCES runs(run_id) ON DELETE SET NULL,
    agent_name              TEXT    NOT NULL REFERENCES agents(agent_name),
    mode                    TEXT    NOT NULL,
    status                  TEXT    NOT NULL,
    repo_root               TEXT    NOT NULL,
    cwd                     TEXT    NOT NULL,
    branch_name             TEXT    NOT NULL,
    worktree_path           TEXT    NOT NULL,
    vendor_session_id       TEXT,
    vendor_transcript_path  TEXT,
    permission_mode         TEXT,
    model_name              TEXT,
    heartbeat_at            TEXT    NOT NULL,
    started_at              TEXT    NOT NULL,
    ended_at                TEXT,
    stop_reason             TEXT,
    summary_md              TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_runs_task_status
    ON runs(task_id, status);

CREATE TABLE IF NOT EXISTS claims (
    claim_id         TEXT    NOT NULL PRIMARY KEY,
    run_id           TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id          TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    repo_root        TEXT    NOT NULL,
    path             TEXT    NOT NULL,
    path_kind        TEXT    NOT NULL,
    access_mode      TEXT    NOT NULL,
    lease_expires_at TEXT    NOT NULL,
    released_at      TEXT,
    created_at       TEXT    NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_claims_lookup
    ON claims(repo_root, path, released_at, lease_expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_exact_write_claim
    ON claims(repo_root, path)
    WHERE access_mode = 'write' AND released_at IS NULL;

CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id      TEXT NOT NULL PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    from_run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    to_agent_name   TEXT NOT NULL REFERENCES agents(agent_name),
    handoff_md_path TEXT NOT NULL,
    status          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    accepted_at     TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS events (
    event_id     INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id      TEXT    REFERENCES tasks(task_id) ON DELETE CASCADE,
    level        TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    payload_json TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_events_run_created
    ON events(run_id, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id    TEXT    NOT NULL PRIMARY KEY,
    run_id         TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id        TEXT    REFERENCES tasks(task_id) ON DELETE SET NULL,
    artifact_type  TEXT    NOT NULL,
    relative_path  TEXT    NOT NULL,
    sha256         TEXT    NOT NULL,
    byte_count     INTEGER NOT NULL,
    metadata_json  TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS memory_links (
    memory_link_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT    NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    run_id         TEXT    REFERENCES runs(run_id) ON DELETE SET NULL,
    backend        TEXT    NOT NULL,
    memory_ref     TEXT    NOT NULL,
    role           TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
) STRICT;
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes. Safe to call multiple times (idempotent).

    Args:
        conn: An open SQLite connection from get_connection().
    """
    conn.executescript(_DDL)
    conn.execute(
        "INSERT OR IGNORE INTO schema_meta (schema_version, applied_at) VALUES (?, datetime('now'))",
        (SCHEMA_VERSION,),
    )
    conn.commit()
```

- [ ] **Step 4: Run tests**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_db_test.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add agent_sync/db/schema.py tests/test_agent_sync_db_test.py
git commit -m "feat(agent_sync): SQLite schema with STRICT tables and claim indexes"
```

---

## Task 3: State layer — Tasks and Runs

**Files:**
- Create: `agent_sync/state/__init__.py`
- Create: `agent_sync/state/tasks.py`
- Create: `agent_sync/state/runs.py`
- Create: `tests/test_agent_sync_state_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_state_test.py
import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.state.tasks import Task, create_task, get_task, update_task_status, list_tasks
from agent_sync.state.runs import Run, start_run, end_run, heartbeat, get_active_run


@pytest.fixture()
def conn(tmp_path: Path):
    c = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(c)
    # Seed an agent row required by runs FK
    c.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)",
        ("claude", "claude", "ClaudeAdapter", "claude", None, 1,
         '["code","review"]', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    c.commit()
    yield c
    c.close()


# --- Task tests ---

def test_create_and_get_task(conn) -> None:
    task = create_task(
        conn,
        title="Fix auth bug",
        kind="bugfix",
        priority=4,
        target_branch="main",
        summary_md="Fix refresh token race.",
    )
    assert task.task_id.startswith("TASK-")
    fetched = get_task(conn, task.task_id)
    assert fetched is not None
    assert fetched.title == "Fix auth bug"
    assert fetched.status == "ready"


def test_update_task_status(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    update_task_status(conn, task.task_id, "running")
    updated = get_task(conn, task.task_id)
    assert updated.status == "running"


def test_list_tasks_filters_by_status(conn) -> None:
    create_task(conn, title="A", kind="feature", priority=3,
                target_branch="main", summary_md="s")
    create_task(conn, title="B", kind="bugfix", priority=4,
                target_branch="main", summary_md="s")
    ready = list_tasks(conn, status="ready")
    assert len(ready) == 2
    update_task_status(conn, ready[0].task_id, "running")
    assert len(list_tasks(conn, status="ready")) == 1


def test_get_task_returns_none_for_missing(conn) -> None:
    assert get_task(conn, "TASK-NONEXISTENT") is None


# --- Run tests ---

def test_start_and_end_run(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(
        conn,
        task_id=task.task_id,
        agent_name="claude",
        mode="primary",
        repo_root=Path("/repo"),
        cwd=Path("/repo"),
        branch_name="ags/T/claude/fix",
        worktree_path=Path("/repo/.agent_sync/worktrees/T--claude"),
    )
    assert run.run_id.startswith("RUN-")
    assert run.status == "active"

    end_run(conn, run.run_id, status="completed", stop_reason="task done")
    updated = get_active_run(conn, task.task_id)
    assert updated is None


def test_heartbeat_updates_timestamp(conn) -> None:
    task = create_task(conn, title="T", kind="feature", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(conn, task_id=task.task_id, agent_name="claude",
                    mode="primary", repo_root=Path("/r"), cwd=Path("/r"),
                    branch_name="b", worktree_path=Path("/w"))
    old_ts = conn.execute(
        "SELECT heartbeat_at FROM runs WHERE run_id=?", (run.run_id,)
    ).fetchone()[0]
    heartbeat(conn, run.run_id)
    new_ts = conn.execute(
        "SELECT heartbeat_at FROM runs WHERE run_id=?", (run.run_id,)
    ).fetchone()[0]
    assert new_ts >= old_ts
```

- [ ] **Step 2: Run to verify failure**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_state_test.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement tasks.py**

```python
# agent_sync/state/tasks.py
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _task_id() -> str:
    return f"TASK-{datetime.now(timezone.utc).strftime('%Y-%m%d')}-{uuid.uuid4().hex[:6].upper()}"


@dataclass
class Task:
    task_id: str
    title: str
    kind: str
    priority: int
    status: str
    target_branch: str
    manifest_path: str
    summary_md: str
    routing_json: str
    scoring_json: str
    created_at: str
    updated_at: str
    parent_task_id: Optional[str] = None
    acceptance_md: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


def create_task(
    conn: sqlite3.Connection,
    *,
    title: str,
    kind: str,
    priority: int,
    target_branch: str,
    summary_md: str,
    parent_task_id: Optional[str] = None,
    acceptance_md: Optional[str] = None,
    routing: Optional[dict] = None,
    scoring: Optional[dict] = None,
    manifest_path: str = "",
) -> Task:
    """Insert a new task with status='ready' and return it."""
    now = _now()
    task = Task(
        task_id=_task_id(),
        title=title,
        kind=kind,
        priority=priority,
        status="ready",
        target_branch=target_branch,
        manifest_path=manifest_path,
        summary_md=summary_md,
        routing_json=json.dumps(routing or {}),
        scoring_json=json.dumps(scoring or {}),
        created_at=now,
        updated_at=now,
        parent_task_id=parent_task_id,
        acceptance_md=acceptance_md,
    )
    conn.execute(
        """
        INSERT INTO tasks
          (task_id, parent_task_id, title, kind, priority, status,
           target_branch, manifest_path, summary_md, acceptance_md,
           routing_json, scoring_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (task.task_id, task.parent_task_id, task.title, task.kind,
         task.priority, task.status, task.target_branch, task.manifest_path,
         task.summary_md, task.acceptance_md, task.routing_json,
         task.scoring_json, task.created_at, task.updated_at),
    )
    conn.commit()
    return task


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[Task]:
    """Return a Task by ID, or None if not found."""
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        return None
    return Task(**dict(row))


def update_task_status(conn: sqlite3.Connection, task_id: str, status: str) -> None:
    """Update task status and updated_at timestamp."""
    conn.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
        (status, _now(), task_id),
    )
    conn.commit()


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[Task]:
    """Return tasks, optionally filtered by status and/or kind."""
    clauses, params = [], []
    if status:
        clauses.append("status=?")
        params.append(status)
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM tasks {where} ORDER BY priority DESC, created_at", params
    ).fetchall()
    return [Task(**dict(r)) for r in rows]
```

- [ ] **Step 4: Implement runs.py**

```python
# agent_sync/state/runs.py
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run_id() -> str:
    return f"RUN-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}-{uuid.uuid4().hex[:6]}"


@dataclass
class Run:
    run_id: str
    task_id: str
    agent_name: str
    mode: str
    status: str
    repo_root: str
    cwd: str
    branch_name: str
    worktree_path: str
    heartbeat_at: str
    started_at: str
    parent_run_id: Optional[str] = None
    vendor_session_id: Optional[str] = None
    vendor_transcript_path: Optional[str] = None
    permission_mode: Optional[str] = None
    model_name: Optional[str] = None
    ended_at: Optional[str] = None
    stop_reason: Optional[str] = None
    summary_md: Optional[str] = None


def start_run(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent_name: str,
    mode: str,
    repo_root: Path,
    cwd: Path,
    branch_name: str,
    worktree_path: Path,
    parent_run_id: Optional[str] = None,
    model_name: Optional[str] = None,
    permission_mode: Optional[str] = None,
) -> Run:
    """Insert a new run with status='active' and return it."""
    now = _now()
    run = Run(
        run_id=_run_id(),
        task_id=task_id,
        agent_name=agent_name,
        mode=mode,
        status="active",
        repo_root=str(repo_root),
        cwd=str(cwd),
        branch_name=branch_name,
        worktree_path=str(worktree_path),
        heartbeat_at=now,
        started_at=now,
        parent_run_id=parent_run_id,
        model_name=model_name,
        permission_mode=permission_mode,
    )
    conn.execute(
        """
        INSERT INTO runs
          (run_id, task_id, parent_run_id, agent_name, mode, status,
           repo_root, cwd, branch_name, worktree_path,
           model_name, permission_mode,
           heartbeat_at, started_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (run.run_id, run.task_id, run.parent_run_id, run.agent_name, run.mode,
         run.status, run.repo_root, run.cwd, run.branch_name, run.worktree_path,
         run.model_name, run.permission_mode, run.heartbeat_at, run.started_at),
    )
    conn.commit()
    return run


def end_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    stop_reason: Optional[str] = None,
    summary_md: Optional[str] = None,
) -> None:
    """Mark a run as ended with the given status."""
    conn.execute(
        "UPDATE runs SET status=?, ended_at=?, stop_reason=?, summary_md=? WHERE run_id=?",
        (status, _now(), stop_reason, summary_md, run_id),
    )
    conn.commit()


def heartbeat(conn: sqlite3.Connection, run_id: str) -> None:
    """Refresh the heartbeat timestamp for a run."""
    conn.execute(
        "UPDATE runs SET heartbeat_at=? WHERE run_id=?",
        (_now(), run_id),
    )
    conn.commit()


def get_active_run(conn: sqlite3.Connection, task_id: str) -> Optional[Run]:
    """Return the active run for a task, or None."""
    row = conn.execute(
        "SELECT * FROM runs WHERE task_id=? AND status='active' LIMIT 1",
        (task_id,),
    ).fetchone()
    return Run(**dict(row)) if row else None
```

- [ ] **Step 5: Create state __init__.py**

```python
# agent_sync/state/__init__.py
```

- [ ] **Step 6: Run tests**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_state_test.py -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add agent_sync/state/ tests/test_agent_sync_state_test.py
git commit -m "feat(agent_sync): Task and Run state layer with CRUD"
```

---

## Task 4: State layer — Claims, Handoffs, Events

**Files:**
- Create: `agent_sync/state/claims.py`
- Create: `agent_sync/state/handoffs.py`
- Create: `agent_sync/state/events.py`
- Create: `tests/test_agent_sync_claims_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_claims_test.py
from pathlib import Path
import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.state.tasks import create_task
from agent_sync.state.runs import start_run
from agent_sync.state.claims import (
    acquire_claims, release_claims, check_conflicts, ClaimConflictError
)


@pytest.fixture()
def setup(tmp_path):
    conn = get_connection(tmp_path / "state.sqlite3")
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)",
        ("claude", "claude", "ClaudeAdapter", "claude", None, 1,
         '[]', "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    task = create_task(conn, title="T", kind="bugfix", priority=3,
                       target_branch="main", summary_md="s")
    run = start_run(conn, task_id=task.task_id, agent_name="claude",
                    mode="primary", repo_root=Path("/repo"), cwd=Path("/repo"),
                    branch_name="b", worktree_path=Path("/w"))
    return conn, task, run


def test_acquire_and_release_claims(setup) -> None:
    conn, task, run = setup
    paths = [Path("src/auth/token.py"), Path("tests/auth/")]
    claim_ids = acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                                repo_root=Path("/repo"), paths=paths,
                                access_mode="write")
    assert len(claim_ids) == 2

    release_claims(conn, run.run_id)
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/token.py")])
    assert conflicts == []


def test_write_claim_conflict_raises(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/")],
                   access_mode="write")
    # Same file under claimed dir should conflict
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/token.py")])
    assert len(conflicts) == 1


def test_parent_dir_claim_conflicts_with_child_file(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/token.py")],
                   access_mode="write")
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/")])
    assert len(conflicts) == 1


def test_read_claim_does_not_conflict_with_write(setup) -> None:
    conn, task, run = setup
    acquire_claims(conn, run_id=run.run_id, task_id=task.task_id,
                   repo_root=Path("/repo"), paths=[Path("src/auth/")],
                   access_mode="read")
    # Another read-only claim on same path should not conflict
    conflicts = check_conflicts(conn, repo_root=Path("/repo"),
                                paths=[Path("src/auth/")],
                                access_mode="read")
    assert conflicts == []
```

- [ ] **Step 2: Run to verify failure**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_claims_test.py -v
```

- [ ] **Step 3: Implement claims.py**

```python
# agent_sync/state/claims.py
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath
from typing import Optional


LEASE_MINUTES = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _expires() -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=LEASE_MINUTES)
    return exp.isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise(path: Path) -> str:
    """Return a repo-relative POSIX string without leading slash."""
    return str(PurePosixPath(path)).lstrip("/")


class ClaimConflictError(Exception):
    pass


@dataclass
class Claim:
    claim_id: str
    run_id: str
    task_id: str
    repo_root: str
    path: str
    path_kind: str
    access_mode: str
    lease_expires_at: str
    created_at: str
    released_at: Optional[str] = None


def check_conflicts(
    conn: sqlite3.Connection,
    *,
    repo_root: Path,
    paths: list[Path],
    access_mode: str = "write",
) -> list[dict]:
    """Return active conflicting write claims for the given paths.

    Only write-access conflicts are checked. Two read claims on the same path
    do not conflict with each other.
    """
    if access_mode != "write":
        return []
    root = str(repo_root)
    now = _now()
    conflicts = []
    for path in paths:
        candidate = _normalise(path)
        rows = conn.execute(
            """
            SELECT claim_id, run_id, path
            FROM claims
            WHERE repo_root = ?
              AND access_mode = 'write'
              AND released_at IS NULL
              AND lease_expires_at > ?
              AND (
                    path = ?
                 OR path LIKE ? || '/%'
                 OR ? LIKE path || '/%'
              )
            LIMIT 1
            """,
            (root, now, candidate, candidate, candidate),
        ).fetchall()
        conflicts.extend(dict(r) for r in rows)
    return conflicts


def acquire_claims(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    task_id: str,
    repo_root: Path,
    paths: list[Path],
    access_mode: str = "write",
) -> list[str]:
    """Acquire file-level leases inside a BEGIN IMMEDIATE transaction.

    Raises ClaimConflictError if a write conflict exists for any path.
    Returns list of claim IDs on success.
    """
    if access_mode == "write":
        conflicts = check_conflicts(conn, repo_root=repo_root, paths=paths)
        if conflicts:
            raise ClaimConflictError(
                f"Write conflict on paths: {[c['path'] for c in conflicts]}"
            )

    root = str(repo_root)
    now = _now()
    expires = _expires()
    claim_ids = []

    conn.execute("BEGIN IMMEDIATE")
    try:
        for path in paths:
            normalised = _normalise(path)
            kind = "dir" if str(path).endswith("/") else "file"
            cid = f"CLM-{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO claims
                  (claim_id, run_id, task_id, repo_root, path, path_kind,
                   access_mode, lease_expires_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (cid, run_id, task_id, root, normalised, kind,
                 access_mode, expires, now),
            )
            claim_ids.append(cid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return claim_ids


def release_claims(conn: sqlite3.Connection, run_id: str) -> None:
    """Release all active claims for the given run."""
    conn.execute(
        "UPDATE claims SET released_at=? WHERE run_id=? AND released_at IS NULL",
        (_now(), run_id),
    )
    conn.commit()
```

- [ ] **Step 4: Implement handoffs.py and events.py**

```python
# agent_sync/state/handoffs.py
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Handoff:
    handoff_id: str
    task_id: str
    from_run_id: str
    to_agent_name: str
    handoff_md_path: str
    status: str
    created_at: str
    accepted_at: Optional[str] = None


def create_handoff(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    from_run_id: str,
    to_agent_name: str,
    handoff_md_path: str,
) -> Handoff:
    """Create a handoff record with status='proposed'."""
    h = Handoff(
        handoff_id=f"HO-{uuid.uuid4().hex[:10]}",
        task_id=task_id,
        from_run_id=from_run_id,
        to_agent_name=to_agent_name,
        handoff_md_path=handoff_md_path,
        status="proposed",
        created_at=_now(),
    )
    conn.execute(
        """
        INSERT INTO handoffs
          (handoff_id, task_id, from_run_id, to_agent_name,
           handoff_md_path, status, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (h.handoff_id, h.task_id, h.from_run_id, h.to_agent_name,
         h.handoff_md_path, h.status, h.created_at),
    )
    conn.commit()
    return h


def accept_handoff(conn: sqlite3.Connection, handoff_id: str) -> None:
    """Mark a handoff as accepted."""
    conn.execute(
        "UPDATE handoffs SET status='accepted', accepted_at=? WHERE handoff_id=?",
        (_now(), handoff_id),
    )
    conn.commit()
```

```python
# agent_sync/state/events.py
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log_event(
    conn: sqlite3.Connection,
    *,
    provider: str,
    event_type: str,
    payload: dict,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    level: str = "info",
) -> int:
    """Append an event to the events table. Returns the new event_id."""
    cursor = conn.execute(
        """
        INSERT INTO events
          (run_id, task_id, level, event_type, provider, payload_json, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (run_id, task_id, level, event_type, provider,
         json.dumps(payload), _now()),
    )
    conn.commit()
    return cursor.lastrowid


def record_artifact(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    artifact_type: str,
    relative_path: str,
    data: bytes,
    task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Record an artifact reference in the DB. Returns artifact_id."""
    sha256 = hashlib.sha256(data).hexdigest()
    aid = f"ART-{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO artifacts
          (artifact_id, run_id, task_id, artifact_type, relative_path,
           sha256, byte_count, metadata_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (aid, run_id, task_id, artifact_type, relative_path,
         sha256, len(data), json.dumps(metadata or {}), _now()),
    )
    conn.commit()
    return aid
```

- [ ] **Step 5: Run all state tests**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_claims_test.py tests/test_agent_sync_state_test.py -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add agent_sync/state/claims.py agent_sync/state/handoffs.py agent_sync/state/events.py tests/test_agent_sync_claims_test.py
git commit -m "feat(agent_sync): claims, handoffs, and event log state layer"
```

---

## Task 5: Worktree manager

**Files:**
- Create: `agent_sync/worktree.py`
- Create: `tests/test_agent_sync_worktree_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_worktree_test.py
import subprocess
from pathlib import Path
import pytest

from agent_sync.worktree import (
    create_worktree, remove_worktree, list_worktrees,
    worktree_branch_name, worktree_dir_name,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"],
                   check=True, capture_output=True)
    (path / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"],
                   check=True, capture_output=True)


def test_branch_name_format() -> None:
    name = worktree_branch_name("TASK-20260101-abc123", "claude", "auth-fix")
    assert name == "ags/TASK-20260101-abc123/claude/auth-fix"


def test_dir_name_format() -> None:
    name = worktree_dir_name("TASK-20260101-abc123", "claude", "auth-fix")
    assert name == "TASK-20260101-abc123--claude--auth-fix"


def test_create_and_remove_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wt_path, branch = create_worktree(
        repo_root=repo,
        task_id="TASK-20260101-abc123",
        agent="claude",
        slug="auth-fix",
        base_branch="main",
    )
    assert wt_path.exists()
    assert branch == "ags/TASK-20260101-abc123/claude/auth-fix"

    remove_worktree(repo_root=repo, worktree_path=wt_path)
    assert not wt_path.exists()


def test_list_worktrees(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wt_path, _ = create_worktree(repo, "TASK-001", "claude", "fix", "main")
    trees = list_worktrees(repo)
    # At minimum the new worktree should be listed
    paths = [t["worktree"] for t in trees]
    assert str(wt_path) in paths
    remove_worktree(repo, wt_path)
```

- [ ] **Step 2: Run to verify failure**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_worktree_test.py -v
```

- [ ] **Step 3: Implement worktree.py**

```python
# agent_sync/worktree.py
"""Git worktree lifecycle management for agent_sync.

All worktrees follow the naming convention:
  directory:  .agent_sync/worktrees/<task-id>--<agent>--<slug>
  branch:     ags/<task-id>/<agent>/<slug>

Use module-managed worktrees for all agents (including Claude Code, even though
Claude has its own -w flag) for cross-vendor consistency.
"""
import subprocess
from pathlib import Path


def worktree_branch_name(task_id: str, agent: str, slug: str) -> str:
    """Return the branch name for a task worktree."""
    return f"ags/{task_id}/{agent}/{slug}"


def worktree_dir_name(task_id: str, agent: str, slug: str) -> str:
    """Return the directory basename for a task worktree."""
    return f"{task_id}--{agent}--{slug}"


def _wt_root(repo_root: Path) -> Path:
    return repo_root / ".agent_sync" / "worktrees"


def create_worktree(
    repo_root: Path,
    task_id: str,
    agent: str,
    slug: str,
    base_branch: str,
) -> tuple[Path, str]:
    """Create a new Git worktree and branch for a task.

    Args:
        repo_root: Absolute path to the repository root.
        task_id: Task identifier (e.g. TASK-20260101-abc123).
        agent: Agent name (e.g. claude, codex, gemini).
        slug: Short slug describing the work (e.g. auth-fix).
        base_branch: Branch to base the new worktree branch on.

    Returns:
        Tuple of (worktree_path, branch_name).
    """
    branch = worktree_branch_name(task_id, agent, slug)
    wt_dir = _wt_root(repo_root) / worktree_dir_name(task_id, agent, slug)
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(wt_dir), base_branch],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    return wt_dir, branch


def remove_worktree(repo_root: Path, worktree_path: Path) -> None:
    """Remove a worktree and prune stale references."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )


def list_worktrees(repo_root: Path) -> list[dict]:
    """Return a list of dicts describing each worktree.

    Each dict has keys: worktree, HEAD, branch.
    """
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    trees = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                trees.append(current)
            current = {"worktree": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
    if current:
        trees.append(current)
    return trees
```

- [ ] **Step 4: Run tests**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_worktree_test.py -v
```
Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add agent_sync/worktree.py tests/test_agent_sync_worktree_test.py
git commit -m "feat(agent_sync): git worktree lifecycle manager"
```

---

## Task 6: Markdown doc renderer

**Files:**
- Create: `agent_sync/docs_gen/__init__.py`
- Create: `agent_sync/docs_gen/templates.py`
- Create: `agent_sync/docs_gen/renderer.py`

- [ ] **Step 1: Write inline tests (no separate test file — these are pure string functions)**

The tests live inside the functions via assertions in step 4.

- [ ] **Step 2: Implement templates.py**

```python
# agent_sync/docs_gen/templates.py
"""String templates for agent_sync generated Markdown documents."""

SESSION_BRIEF = """\
---
schema: agent_sync/session_brief/v1
task_id: {task_id}
run_id: {run_id}
agent: {agent_name}
branch: {branch_name}
worktree: {worktree_path}
generated_at: {generated_at}
---

# Session Brief — {task_id}

## What You Are Doing

{summary_md}

## Current Status

- Task status: **{task_status}**
- This run: **{run_id}** ({agent_name}, {mode})
- Branch: `{branch_name}`
- Worktree: `{worktree_path}`

## Claimed Files

{claims_section}

## Acceptance Commands

{acceptance_md}

## Open Issues / Handoff Context

{handoff_context}

---
*Generated by agent_sync. Treat repo state as authoritative over any prior session memory.*
"""

HANDOFF = """\
---
schema: agent_sync/handoff/v1
task_id: {task_id}
from_run_id: {from_run_id}
from_agent: {from_agent}
to_agent: {to_agent}
status: ready_for_resume
created_at: {created_at}
target_branch: {target_branch}
work_branch: {work_branch}
worktree_path: {worktree_path}
---

# Handoff — {task_id}

## Objective

{summary_md}

## What Changed

{changed_files_section}

## Validation State

{validation_section}

## Blocking Issues

{blocking_issues}

## Open Questions

{open_questions}

## Next Steps

{next_steps}

## Integration Notes

{integration_notes}

---
*To continue: `agent-sync resume -t {task_id}` or read this file and proceed from repo state.*
"""

AGENT_CONTRACT = """\
# Agent Contract

This repository uses `agent_sync` for deterministic multi-agent coordination.

## Always Read First

- `agent_sync/docs/SESSION_BRIEF.md`
- `agent_sync/docs/HANDOFF.md`
- `agent_sync/docs/AGENT_CONTRACT.md`

## Rules

- Use repo state, not prior chat memory, as the source of truth.
- Do not write mutable orchestration state into `.claude/`, `.codex/`, or `.gemini/`.
- When stopping, ensure HANDOFF.md is complete enough for another agent to continue.
- Confirm your assigned task_id and claimed files from SESSION_BRIEF.md before editing.
- If parallel work is needed, create child task manifests (`agent-sync dispatch`).
- Do not commit directly to the target branch; work on your task branch only.
- `agent-sync integrate` is the only path to merge your branch.
- If blocked, write the block reason and exact next step into HANDOFF.md before stopping.

## Forbidden Commands (handled by hooks + provider rules)

- `git push` (use `agent-sync integrate`)
- `git commit` on target branch
- `gh pr create` / `gh pr merge`
- `rm -rf`, `sudo`
- Writes to `.env`, `*.key`, `*.pem`, credential files
- DB migrations against non-local environments
"""

AGENTS_MD_SECTION = """\

## agent_sync coordination

Read these files before making changes:

- `agent_sync/docs/SESSION_BRIEF.md`
- `agent_sync/docs/HANDOFF.md`
- `agent_sync/docs/AGENT_CONTRACT.md`

Treat `agent_sync/db/state.sqlite3` and `agent_sync/docs/` as the current source
of truth. Do not invent project state from chat history when the repo disagrees.
"""

CLAUDE_MD_SECTION = """\

## agent_sync coordination

This repository uses `agent_sync` for deterministic coordination.

Always read:

- `agent_sync/docs/SESSION_BRIEF.md`
- `agent_sync/docs/HANDOFF.md`
- `agent_sync/docs/AGENT_CONTRACT.md`

Use repo-local state, not prior chat memory, as the source of truth.
Do not store mutable handoff state in `.claude/`.
When stopping, ensure HANDOFF.md is complete enough for another agent to continue.
"""

GEMINI_MD_SECTION = CLAUDE_MD_SECTION.replace(".claude/", ".gemini/")
```

- [ ] **Step 3: Implement renderer.py**

```python
# agent_sync/docs_gen/renderer.py
"""Render agent_sync Markdown documents from DB state."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .templates import SESSION_BRIEF, HANDOFF, AGENT_CONTRACT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def render_session_brief(
    conn: sqlite3.Connection,
    task_id: str,
    run_id: str,
) -> str:
    """Render SESSION_BRIEF.md content for the given task and run."""
    task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not task or not run:
        raise ValueError(f"task_id={task_id} or run_id={run_id} not found")

    active_claims = conn.execute(
        "SELECT path, access_mode FROM claims WHERE run_id=? AND released_at IS NULL",
        (run_id,),
    ).fetchall()
    if active_claims:
        claims_section = "\n".join(
            f"- `{r['path']}` ({r['access_mode']})" for r in active_claims
        )
    else:
        claims_section = "_No file claims active yet._"

    last_handoff = conn.execute(
        """
        SELECT handoff_md_path FROM handoffs
        WHERE task_id=? AND status IN ('proposed','accepted')
        ORDER BY created_at DESC LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    handoff_context = (
        f"See `{last_handoff['handoff_md_path']}`" if last_handoff
        else "_No prior handoff. This is the first run._"
    )

    return SESSION_BRIEF.format(
        task_id=task_id,
        run_id=run_id,
        agent_name=run["agent_name"],
        branch_name=run["branch_name"],
        worktree_path=run["worktree_path"],
        generated_at=_now(),
        summary_md=task["summary_md"],
        task_status=task["status"],
        mode=run["mode"],
        claims_section=claims_section,
        acceptance_md=task["acceptance_md"] or "_None specified._",
        handoff_context=handoff_context,
    )


def render_handoff(
    conn: sqlite3.Connection,
    task_id: str,
    from_run_id: str,
    to_agent: str,
    *,
    changed_files: Optional[list[str]] = None,
    validation_output: Optional[str] = None,
    blocking_issues: Optional[list[str]] = None,
    open_questions: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
    integration_notes: Optional[str] = None,
) -> str:
    """Render HANDOFF.md content for a stop/handoff event."""
    task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    run = conn.execute("SELECT * FROM runs WHERE run_id=?", (from_run_id,)).fetchone()
    if not task or not run:
        raise ValueError(f"task_id or run_id not found")

    changed_section = (
        "\n".join(f"- `{f}`" for f in changed_files)
        if changed_files else "_No file changes recorded._"
    )
    validation_section = validation_output or "_Validation not run or not recorded._"
    blocking_section = (
        "\n".join(f"- {i}" for i in blocking_issues)
        if blocking_issues else "_None._"
    )
    questions_section = (
        "\n".join(f"- {q}" for q in open_questions)
        if open_questions else "_None._"
    )
    steps_section = (
        "\n".join(f"- {s}" for s in next_steps)
        if next_steps else "_None specified._"
    )

    return HANDOFF.format(
        task_id=task_id,
        from_run_id=from_run_id,
        from_agent=run["agent_name"],
        to_agent=to_agent,
        created_at=_now(),
        target_branch=task["target_branch"],
        work_branch=run["branch_name"],
        worktree_path=run["worktree_path"],
        summary_md=task["summary_md"],
        changed_files_section=changed_section,
        validation_section=validation_section,
        blocking_issues=blocking_section,
        open_questions=questions_section,
        next_steps=steps_section,
        integration_notes=integration_notes or "_None._",
    )


def render_agent_contract() -> str:
    """Return the static AGENT_CONTRACT.md content."""
    return AGENT_CONTRACT
```

- [ ] **Step 4: Smoke-test the renderer manually**

```bash
cd /home/mcarls/projects/ai-orchestrator
python -c "
from pathlib import Path
from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.state.tasks import create_task
from agent_sync.state.runs import start_run
from agent_sync.docs_gen.renderer import render_session_brief, render_handoff

conn = get_connection(Path('/tmp/ags_test.sqlite3'))
initialize_schema(conn)
conn.execute(\"INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?)\",
    ('claude','claude','ClaudeAdapter','claude',None,1,'[]','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z'))
conn.commit()
task = create_task(conn, title='Fix auth', kind='bugfix', priority=4, target_branch='main', summary_md='Fix token race.')
run = start_run(conn, task_id=task.task_id, agent_name='claude', mode='primary',
    repo_root=Path('/repo'), cwd=Path('/repo'), branch_name='ags/T/claude/fix',
    worktree_path=Path('/repo/.agent_sync/worktrees/T--claude--fix'))
brief = render_session_brief(conn, task.task_id, run.run_id)
print(brief[:300])
"
```
Expected: Markdown snippet printed without errors.

- [ ] **Step 5: Create `agent_sync/docs_gen/__init__.py`**

```python
# agent_sync/docs_gen/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add agent_sync/docs_gen/ 
git commit -m "feat(agent_sync): Markdown doc renderer for SESSION_BRIEF and HANDOFF"
```

---

## Task 7: Hook dispatcher + normalize

**Files:**
- Create: `agent_sync/hooks/__init__.py`
- Create: `agent_sync/hooks/normalize.py`
- Create: `agent_sync/hooks/dispatch.py`
- Create: `agent_sync/hooks/handlers/__init__.py`
- Create: `agent_sync/hooks/handlers/session_start.py`
- Create: `agent_sync/hooks/handlers/pre_tool.py`
- Create: `agent_sync/hooks/handlers/post_tool.py`
- Create: `agent_sync/hooks/handlers/stop.py`
- Create: `agent_sync/shell/claude-dispatch.sh`
- Create: `agent_sync/shell/codex-dispatch.sh`
- Create: `agent_sync/shell/gemini-dispatch.sh`
- Create: `tests/test_agent_sync_hooks_test.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_hooks_test.py
import json
from agent_sync.hooks.normalize import normalize_payload, HookEvent


CLAUDE_SESSION_START = {
    "session_id": "abc123",
    "cwd": "/repo",
    "transcript_path": "/home/.claude/projects/.../transcript.jsonl",
}

CLAUDE_PRE_TOOL = {
    "session_id": "abc123",
    "cwd": "/repo",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /"},
}

CLAUDE_POST_TOOL = {
    "session_id": "abc123",
    "cwd": "/repo",
    "tool_name": "Write",
    "tool_input": {"file_path": "/repo/src/auth/token.py"},
    "tool_response": {"success": True},
}

CLAUDE_STOP = {
    "session_id": "abc123",
    "cwd": "/repo",
    "stop_reason": "end_turn",
}


def test_normalize_session_start() -> None:
    event = normalize_payload("claude", "SessionStart", CLAUDE_SESSION_START)
    assert event.provider == "claude"
    assert event.event == "SessionStart"
    assert event.vendor_session_id == "abc123"
    assert event.cwd == "/repo"
    assert event.tool is None


def test_normalize_pre_tool() -> None:
    event = normalize_payload("claude", "PreToolUse", CLAUDE_PRE_TOOL)
    assert event.event == "PreToolUse"
    assert event.tool is not None
    assert event.tool["name"] == "Bash"
    assert event.tool["input"]["command"] == "rm -rf /"


def test_normalize_post_tool() -> None:
    event = normalize_payload("claude", "PostToolUse", CLAUDE_POST_TOOL)
    assert event.tool["name"] == "Write"
    assert event.tool["response"]["success"] is True


def test_normalize_stop() -> None:
    event = normalize_payload("claude", "Stop", CLAUDE_STOP)
    assert event.stop_reason == "end_turn"


def test_normalize_codex_maps_same_fields() -> None:
    # Codex uses same JSON structure as Claude for these events
    event = normalize_payload("codex", "PreToolUse", CLAUDE_PRE_TOOL)
    assert event.provider == "codex"
    assert event.tool["name"] == "Bash"
```

- [ ] **Step 2: Run to verify failure**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_hooks_test.py -v
```

- [ ] **Step 3: Implement normalize.py**

```python
# agent_sync/hooks/normalize.py
"""Normalize provider-specific hook JSON payloads into a common HookEvent."""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class HookEvent:
    provider: str           # claude | codex | gemini | local
    event: str              # SessionStart | PreToolUse | PostToolUse | Stop
    repo_root: str
    cwd: str
    vendor_session_id: Optional[str] = None
    permission_mode: Optional[str] = None
    tool: Optional[dict] = None
    stop_reason: Optional[str] = None
    raw: dict = field(default_factory=dict)
    ts: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def normalize_payload(provider: str, event: str, payload: dict) -> HookEvent:
    """Convert a raw provider hook payload into a HookEvent.

    All three providers (Claude, Codex, Gemini) use the same JSON structure
    for these four events. Only documented fields are consumed; unknown fields
    are stored in raw but not relied upon.

    Args:
        provider: One of 'claude', 'codex', 'gemini'.
        event: Hook event name.
        payload: Raw JSON dict from stdin.

    Returns:
        Normalised HookEvent.
    """
    cwd = payload.get("cwd", "")
    # repo_root defaults to cwd; adapters may override
    repo_root = payload.get("repo_root", cwd)

    tool = None
    if event in ("PreToolUse", "PostToolUse"):
        tool_name = payload.get("tool_name") or payload.get("tool", {}).get("name")
        tool_input = payload.get("tool_input") or payload.get("tool", {}).get("input", {})
        tool_response = payload.get("tool_response") or payload.get("tool", {}).get("response")
        tool = {"name": tool_name, "input": tool_input, "response": tool_response}

    return HookEvent(
        provider=provider,
        event=event,
        repo_root=repo_root,
        cwd=cwd,
        vendor_session_id=payload.get("session_id"),
        permission_mode=payload.get("permission_mode"),
        tool=tool,
        stop_reason=payload.get("stop_reason"),
        raw=payload,
    )
```

- [ ] **Step 4: Implement dispatch.py and handler stubs**

```python
# agent_sync/hooks/__init__.py
```

```python
# agent_sync/hooks/handlers/__init__.py
```

```python
# agent_sync/hooks/handlers/session_start.py
"""SessionStart hook handler — inject SESSION_BRIEF.md context."""
import json
import sys
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Return a hook output dict that injects the session brief.

    The returned dict is printed as JSON to stdout so the provider
    injects it as additional context at session start.
    """
    brief_path = Path(event.repo_root) / "agent_sync" / "docs" / "SESSION_BRIEF.md"
    if brief_path.exists():
        brief = brief_path.read_text(encoding="utf-8")
        return {
            "type": "inject",
            "content": f"[agent_sync session brief]\n{brief}",
        }
    return {}
```

```python
# agent_sync/hooks/handlers/pre_tool.py
"""PreToolUse hook handler — block forbidden commands."""
import re
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent

# Commands that must not run outside agent-sync integrate
_BLOCKED = [
    re.compile(r"git\s+push"),
    re.compile(r"gh\s+pr\s+(create|merge)"),
    re.compile(r"git\s+commit.*--amend"),
    re.compile(r"\brm\s+-rf\s+/"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bnpm\s+publish\b"),
    re.compile(r"\bpip\s+publish\b"),
]


def handle(event: HookEvent, db_path: Path) -> dict:
    """Block forbidden commands; allow everything else."""
    if event.tool is None:
        return {}
    tool_name = event.tool.get("name", "")
    if tool_name not in ("Bash", "shell"):
        return {}
    command = event.tool.get("input", {}).get("command", "")
    for pattern in _BLOCKED:
        if pattern.search(command):
            return {
                "type": "block",
                "reason": (
                    f"agent_sync policy: command blocked by PreToolUse guard.\n"
                    f"Matched pattern: {pattern.pattern}\n"
                    f"Use `agent-sync integrate` for merge/push operations."
                ),
            }
    return {}
```

```python
# agent_sync/hooks/handlers/post_tool.py
"""PostToolUse hook handler — record changed files."""
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Record file write events for artifact tracking (stub — extended in Phase 2)."""
    # In Phase 2 this will update the DB with changed file paths.
    return {}
```

```python
# agent_sync/hooks/handlers/stop.py
"""Stop hook handler — emit HANDOFF.md and end run."""
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent


def handle(event: HookEvent, db_path: Path) -> dict:
    """Emit HANDOFF.md candidate on session stop (stub — extended in Phase 2)."""
    handoff_path = Path(event.repo_root) / "agent_sync" / "docs" / "HANDOFF.md"
    if not handoff_path.exists():
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(
            f"# Handoff\n\nSession stopped by {event.provider}.\n"
            f"Repo root: {event.repo_root}\n"
            f"Session ID: {event.vendor_session_id}\n"
            f"\nExtended handoff generation wired in Phase 2.\n",
            encoding="utf-8",
        )
    return {}
```

```python
# agent_sync/hooks/dispatch.py
"""Hook dispatcher — CLI entry point for shell wrappers.

Usage:
    python -m agent_sync.hooks.dispatch --provider claude --event SessionStart \
        --repo-root /path/to/repo

Reads JSON payload from stdin, normalizes it, calls the appropriate handler,
and prints a JSON response to stdout (used by providers that consume hook output).
"""
import argparse
import json
import sys
from pathlib import Path

from .normalize import normalize_payload
from .handlers import session_start, pre_tool, post_tool, stop


_HANDLERS = {
    "SessionStart": session_start.handle,
    "PreToolUse": pre_tool.handle,
    "PostToolUse": post_tool.handle,
    "Stop": stop.handle,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="agent_sync hook dispatcher",
        prog="python -m agent_sync.hooks.dispatch",
    )
    parser.add_argument("-P", "--provider", required=True,
                        choices=["claude", "codex", "gemini", "local"])
    parser.add_argument("-e", "--event", required=True)
    parser.add_argument("-r", "--repo-root", required=True)
    args = parser.parse_args(argv)

    raw = json.loads(sys.stdin.read() or "{}")
    raw["repo_root"] = args.repo_root

    event = normalize_payload(args.provider, args.event, raw)

    db_path = Path(args.repo_root) / "agent_sync" / "db" / "state.sqlite3"
    handler = _HANDLERS.get(args.event)
    if handler is None:
        # Unknown event — pass through silently
        print("{}", flush=True)
        return 0

    result = handler(event, db_path)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Create shell dispatch wrappers**

```bash
mkdir -p /home/mcarls/projects/ai-orchestrator/agent_sync/shell
```

```bash
# agent_sync/shell/claude-dispatch.sh
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
exec python -m agent_sync.hooks.dispatch \
    --provider claude \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
```

```bash
# agent_sync/shell/codex-dispatch.sh
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec python -m agent_sync.hooks.dispatch \
    --provider codex \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
```

```bash
# agent_sync/shell/gemini-dispatch.sh
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec python -m agent_sync.hooks.dispatch \
    --provider gemini \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
```

Write these files and make them executable:

```bash
cat > /home/mcarls/projects/ai-orchestrator/agent_sync/shell/claude-dispatch.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
exec python -m agent_sync.hooks.dispatch \
    --provider claude \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
EOF

cat > /home/mcarls/projects/ai-orchestrator/agent_sync/shell/codex-dispatch.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec python -m agent_sync.hooks.dispatch \
    --provider codex \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
EOF

cat > /home/mcarls/projects/ai-orchestrator/agent_sync/shell/gemini-dispatch.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
EVENT_NAME="${1:?missing event name}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
exec python -m agent_sync.hooks.dispatch \
    --provider gemini \
    --event "${EVENT_NAME}" \
    --repo-root "${REPO_ROOT}"
EOF

chmod +x agent_sync/shell/*.sh
```

- [ ] **Step 6: Run hook tests**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest tests/test_agent_sync_hooks_test.py -v
```
Expected: all PASSED

- [ ] **Step 7: Smoke test the dispatcher**

```bash
echo '{"session_id":"abc","cwd":"/tmp","tool_name":"Bash","tool_input":{"command":"git push"}}' | \
  PYTHONPATH=. python -m agent_sync.hooks.dispatch \
    --provider claude --event PreToolUse --repo-root /tmp
```
Expected: `{"type": "block", "reason": "agent_sync policy: ..."}` printed to stdout.

- [ ] **Step 8: Commit**

```bash
git add agent_sync/hooks/ agent_sync/shell/
git commit -m "feat(agent_sync): hook dispatcher + normalize + handler stubs"
```

---

## Task 8: CLI skeleton + init + doctor commands

**Files:**
- Create: `agent_sync/commands/__init__.py`
- Create: `agent_sync/commands/init.py`
- Create: `agent_sync/commands/doctor.py`
- Create: `agent_sync/cli.py`

- [ ] **Step 1: Implement commands/init.py**

```python
# agent_sync/commands/init.py
"""agent-sync init — bootstrap DB, provider configs, and shell wrappers."""
import json
import shutil
from pathlib import Path

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.docs_gen.renderer import render_agent_contract
from agent_sync.docs_gen.templates import (
    AGENTS_MD_SECTION, CLAUDE_MD_SECTION, GEMINI_MD_SECTION
)


_CLAUDE_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["SessionStart"], "timeout": 30}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["PreToolUse"], "timeout": 30}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["PostToolUse"], "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["Stop"], "timeout": 30}]}],
    }
}

_CODEX_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" SessionStart',
            "timeout": 30, "statusMessage": "agent_sync session brief"}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" PreToolUse',
            "timeout": 30, "statusMessage": "agent_sync policy"}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" PostToolUse',
            "timeout": 30, "statusMessage": "agent_sync artifact capture"}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" Stop',
            "timeout": 30, "statusMessage": "agent_sync handoff"}]}],
    }
}

_GEMINI_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" SessionStart',
            "timeout": 30}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" PreToolUse',
            "timeout": 30}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" PostToolUse',
            "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" Stop',
            "timeout": 30}]}],
    }
}

_CODEX_CONFIG_TOML = """\
[profile.default]
model = "codex-default"

[mcp]
# Add MCP servers here if needed
"""

_CODEX_RULES = """\
# agent_sync guarded command policy
# These prefixes are blocked unless running through agent-sync integrate
deny git push
deny git commit --amend
deny gh pr create
deny gh pr merge
deny rm -rf /
deny sudo
"""

_GITIGNORE_ADDITIONS = [
    ".agent_sync/worktrees/",
    "agent_sync/db/state.sqlite3",
]


def cmd_init(repo_root: Path, *, dry_run: bool = False, apply: bool = True) -> None:
    """Bootstrap agent_sync DB, provider configs, and static docs.

    Args:
        repo_root: Repository root directory.
        dry_run: If True, print planned changes but do not write anything.
        apply: If False, only report what would be done (same as dry_run).
    """
    if dry_run or not apply:
        _print_plan(repo_root)
        return
    _do_init(repo_root)


def _print_plan(repo_root: Path) -> None:
    print("agent-sync init — planned changes (dry run):")
    print(f"  create  {repo_root}/agent_sync/db/state.sqlite3")
    print(f"  create  {repo_root}/agent_sync/docs/AGENT_CONTRACT.md")
    print(f"  update  {repo_root}/.claude/settings.json  (merge hooks)")
    print(f"  create  {repo_root}/.codex/hooks.json")
    print(f"  create  {repo_root}/.codex/config.toml")
    print(f"  create  {repo_root}/.codex/rules/agent_sync.rules")
    print(f"  create  {repo_root}/.gemini/settings.json")
    print(f"  update  {repo_root}/AGENTS.md  (append agent_sync section)")
    print(f"  update  {repo_root}/CLAUDE.md   (append agent_sync section)")
    print(f"  create  {repo_root}/GEMINI.md")
    print(f"  update  {repo_root}/.gitignore  (append worktree + db paths)")


def _do_init(repo_root: Path) -> None:
    # 1. DB
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    conn.close()
    print(f"[init] DB initialized at {db_path}")

    # 2. AGENT_CONTRACT.md
    contract_path = repo_root / "agent_sync" / "docs" / "AGENT_CONTRACT.md"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(render_agent_contract(), encoding="utf-8")
    print(f"[init] Wrote {contract_path}")

    # 3. Claude hooks — merge into .claude/settings.json
    claude_settings = repo_root / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if claude_settings.exists():
        existing = json.loads(claude_settings.read_text(encoding="utf-8"))
    existing.setdefault("hooks", {}).update(_CLAUDE_HOOKS["hooks"])
    claude_settings.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"[init] Updated {claude_settings}")

    # 4. Codex config
    codex_dir = repo_root / ".codex"
    codex_dir.mkdir(exist_ok=True)
    (codex_dir / "hooks.json").write_text(
        json.dumps(_CODEX_HOOKS, indent=2), encoding="utf-8"
    )
    (codex_dir / "config.toml").write_text(_CODEX_CONFIG_TOML, encoding="utf-8")
    rules_dir = codex_dir / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "agent_sync.rules").write_text(_CODEX_RULES, encoding="utf-8")
    print(f"[init] Wrote Codex config to {codex_dir}")

    # 5. Gemini hooks
    gemini_dir = repo_root / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    existing_gemini = {}
    gemini_settings = gemini_dir / "settings.json"
    if gemini_settings.exists():
        existing_gemini = json.loads(gemini_settings.read_text(encoding="utf-8"))
    existing_gemini.setdefault("hooks", {}).update(_GEMINI_HOOKS["hooks"])
    gemini_settings.write_text(
        json.dumps(existing_gemini, indent=2), encoding="utf-8"
    )
    print(f"[init] Updated {gemini_settings}")

    # 6. Instruction file sections
    _append_section(repo_root / "AGENTS.md", AGENTS_MD_SECTION, "## agent_sync")
    _append_section(repo_root / "CLAUDE.md", CLAUDE_MD_SECTION, "## agent_sync")
    gemini_md = repo_root / "GEMINI.md"
    if not gemini_md.exists():
        gemini_md.write_text(f"# Gemini CLI project instructions\n{GEMINI_MD_SECTION}", encoding="utf-8")
        print(f"[init] Created {gemini_md}")

    # 7. .gitignore additions
    gitignore = repo_root / ".gitignore"
    existing_ignore = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    additions = [p for p in _GITIGNORE_ADDITIONS if p not in existing_ignore]
    if additions:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n# agent_sync\n" + "\n".join(additions) + "\n")
        print(f"[init] Updated {gitignore}")

    print("[init] Done. Run `agent-sync doctor` to verify.")


def _append_section(path: Path, section: str, marker: str) -> None:
    """Append section to a Markdown file if the marker is not already present."""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if marker in content:
            return
        path.write_text(content + "\n" + section, encoding="utf-8")
    else:
        path.write_text(section, encoding="utf-8")
    print(f"[init] Updated {path}")
```

- [ ] **Step 2: Implement commands/doctor.py**

```python
# agent_sync/commands/doctor.py
"""agent-sync doctor — verify hooks, DB, worktrees, provider installations."""
import json
import shutil
import subprocess
from pathlib import Path

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    print(f"  {icon}  {label}" + (f": {detail}" if detail else ""))
    return ok


def cmd_doctor(repo_root: Path, *, verbose: bool = False) -> int:
    """Print a health report. Returns 0 if all checks pass, 1 otherwise."""
    print("agent-sync doctor")
    failures = 0

    # DB
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    db_ok = db_path.exists()
    if not _check("DB exists", db_ok, str(db_path)):
        failures += 1
        print("    → Run `agent-sync init` to create it.")
    else:
        try:
            conn = get_connection(db_path)
            conn.execute("SELECT schema_version FROM schema_meta").fetchone()
            conn.close()
            _check("DB schema valid", True)
        except Exception as exc:
            _check("DB schema valid", False, str(exc))
            failures += 1

    # Provider binaries
    for binary in ("claude", "codex", "gemini"):
        found = shutil.which(binary) is not None
        if not _check(f"{binary} binary found", found):
            failures += 1

    # Claude settings.json
    claude_settings = repo_root / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
            has_hooks = "Stop" in data.get("hooks", {})
            _check("Claude hooks configured", has_hooks)
            if not has_hooks:
                failures += 1
        except Exception as exc:
            _check("Claude settings.json parseable", False, str(exc))
            failures += 1
    else:
        _check("Claude settings.json exists", False)
        failures += 1

    # Codex hooks
    codex_hooks = repo_root / ".codex" / "hooks.json"
    _check("Codex hooks.json exists", codex_hooks.exists())
    if not codex_hooks.exists():
        failures += 1

    # Gemini settings
    gemini_settings = repo_root / ".gemini" / "settings.json"
    _check("Gemini settings.json exists", gemini_settings.exists())
    if not gemini_settings.exists():
        failures += 1

    # Shell wrappers
    for wrapper in ("claude-dispatch.sh", "codex-dispatch.sh", "gemini-dispatch.sh"):
        p = repo_root / "agent_sync" / "shell" / wrapper
        ok = p.exists() and p.stat().st_mode & 0o111
        _check(f"Shell wrapper {wrapper} executable", ok)
        if not ok:
            failures += 1

    # AGENT_CONTRACT.md
    contract = repo_root / "agent_sync" / "docs" / "AGENT_CONTRACT.md"
    _check("AGENT_CONTRACT.md exists", contract.exists())
    if not contract.exists():
        failures += 1

    # .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        _check(".gitignore excludes worktrees", ".agent_sync/worktrees/" in content)
    else:
        _check(".gitignore exists", False)

    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    return 0 if failures == 0 else 1
```

- [ ] **Step 3: Implement cli.py and commands/__init__.py**

```python
# agent_sync/commands/__init__.py
```

```python
# agent_sync/cli.py
"""agent-sync CLI entry point."""
import argparse
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    """Walk up from cwd looking for .git directory."""
    here = Path.cwd()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return here


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-sync",
        description="Deterministic multi-agent coordination for git repositories",
    )
    parser.add_argument(
        "-r", "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from cwd)",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Print planned changes without executing",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # init
    p_init = sub.add_parser("init", help="Bootstrap DB, provider configs, and docs")
    p_init.add_argument("-A", "--apply", action="store_true", default=True,
                        help="Apply changes (default: True)")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Verify hooks, DB, and provider setup")
    p_doctor.add_argument("-v", "--verbose", action="store_true")

    # start (stub — implemented in Phase 2)
    p_start = sub.add_parser("start", help="Start or attach a task to an agent")
    p_start.add_argument("-t", "--task", required=True, help="Task ID")
    p_start.add_argument("-a", "--agent", required=True, help="Agent name")
    p_start.add_argument("-s", "--slug", default="work", help="Branch slug")
    p_start.add_argument("-i", "--interactive", action="store_true", default=True)

    # handoff (stub)
    p_handoff = sub.add_parser("handoff", help="Freeze run and prepare next agent")
    p_handoff.add_argument("-t", "--task", required=True)
    p_handoff.add_argument("-a", "--agent", required=True, help="Target agent")

    # resume (stub)
    p_resume = sub.add_parser("resume", help="Reconstruct state and relaunch agent")
    p_resume.add_argument("-t", "--task", required=True)

    args = parser.parse_args(argv)
    repo_root = args.repo_root or _find_repo_root()

    if args.command == "init":
        from agent_sync.commands.init import cmd_init
        cmd_init(repo_root, dry_run=args.dry_run)
        return 0

    if args.command == "doctor":
        from agent_sync.commands.doctor import cmd_doctor
        return cmd_doctor(repo_root, verbose=args.verbose)

    if args.command in ("start", "handoff", "resume", "dispatch", "review",
                        "integrate", "memory"):
        print(f"[agent-sync] '{args.command}' implemented in Phase 2/3. "
              f"See agent_sync/docs/plans/PLAN-2-SEQUENTIAL.md")
        return 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Test CLI smoke**

```bash
PYTHONPATH=. python -m agent_sync.cli --help
PYTHONPATH=. python -m agent_sync.cli init --dry-run -r /home/mcarls/projects/ai-orchestrator
PYTHONPATH=. python -m agent_sync.cli doctor -r /home/mcarls/projects/ai-orchestrator
```
Expected: help text and dry-run output printed, doctor listing checks.

- [ ] **Step 5: Run all Phase 1 tests together**

```bash
env -u PYTHONHOME -u PYTHONSTARTUP PYTHONPATH=. pytest \
  tests/test_agent_sync_db_test.py \
  tests/test_agent_sync_state_test.py \
  tests/test_agent_sync_claims_test.py \
  tests/test_agent_sync_worktree_test.py \
  tests/test_agent_sync_hooks_test.py \
  -v
```
Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add agent_sync/commands/ agent_sync/cli.py
git commit -m "feat(agent_sync): CLI skeleton with init and doctor commands"
```

---

## Phase 1 Complete

**What is now working:**
- SQLite DB with full schema, WAL mode, FK enforcement, busy timeout
- Task, Run, Claim, Handoff, Event state layer with CRUD
- File-level write claim conflict detection (overlap predicate)
- Git worktree create / remove / list
- SESSION_BRIEF and HANDOFF Markdown renderers
- Hook dispatcher invoked by shell wrappers, with PreToolUse command blocking
- `agent-sync init` — writes provider configs for Claude, Codex, Gemini
- `agent-sync doctor` — verifies the full setup

**Proceed to:** `agent_sync/docs/plans/PLAN-2-SEQUENTIAL.md`
