# Agent Sync Phase 2 — Sequential Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the full `start → work → handoff → resume` lifecycle for sequential
agent handoffs across Claude Code, Codex, and Gemini CLI. After this phase, a user
can `agent-sync start -t T001 -a claude`, work, then `agent-sync handoff -t T001 -a codex`,
and Codex picks up exactly where Claude left off with full context injected.

**Architecture:** Provider adapters wrap each CLI's launch and config conventions.
Hook handlers write to the DB so the stop handler can render a complete HANDOFF.md.
The `start`, `handoff`, and `resume` commands orchestrate the full lifecycle.
All three providers share the same hook dispatcher (Phase 1); only their launch
commands and instruction-file conventions differ.

**Tech Stack:** Python 3.11+, `sqlite3`, `subprocess`, `argparse`, `pathlib`,
`dataclasses`, `shutil`, `pytest`, `uv`

**Prerequisites:** Phase 1 complete (DB, state layer, worktrees, docs renderer,
hook dispatcher skeleton, `init` + `doctor` commands).

**Read first:** `agent_sync/docs/plans/OVERVIEW.md` for module layout and
`agent_sync/docs/plans/PLAN-1-FOUNDATION.md` for all existing interfaces.

---

## File Map

| File | Responsibility |
|---|---|
| `agent_sync/adapters/__init__.py` | Package marker |
| `agent_sync/adapters/base.py` | `AgentAdapter` ABC: `launch()`, `config_files()`, `hook_env()` |
| `agent_sync/adapters/claude.py` | `ClaudeAdapter`: uses `claude -p`, `${CLAUDE_PROJECT_DIR}` hooks |
| `agent_sync/adapters/codex.py` | `CodexAdapter`: uses `codex exec`, `.codex/` hooks |
| `agent_sync/adapters/gemini.py` | `GeminiAdapter`: uses `gemini -p`, `.gemini/` hooks |
| `agent_sync/adapters/local.py` | `LocalWorkerAdapter`: writes to `task_queue/queued/` |
| `agent_sync/hooks/handlers/session_start.py` | Full impl: resolve task/run from session, inject SESSION_BRIEF |
| `agent_sync/hooks/handlers/post_tool.py` | Full impl: record write paths into claims table, log artifact events |
| `agent_sync/hooks/handlers/stop.py` | Full impl: query events/claims, render full HANDOFF.md, end run |
| `agent_sync/commands/start.py` | `cmd_start()`: create/attach task, worktree, run, SESSION_BRIEF, launch agent |
| `agent_sync/commands/handoff_cmd.py` | `cmd_handoff()`: freeze run, write HANDOFF.md, release claims, create handoff record |
| `agent_sync/commands/resume.py` | `cmd_resume()`: reconstruct state, render SESSION_BRIEF, launch next agent |
| `agent_sync/cli.py` | Wire `start`, `handoff`, `resume` into main parser |
| `tests/test_agent_sync_adapters_test.py` | Adapter config, launch args, hook env |
| `tests/test_agent_sync_routing_test.py` | Agent selection, capability checks |
| `tests/test_agent_sync_integration_test.py` | Full start→handoff→resume round-trip (subprocess mocked) |

---

## Task 1: `AgentAdapter` ABC + `ClaudeAdapter`

**Files:**
- Create: `agent_sync/adapters/__init__.py`
- Create: `agent_sync/adapters/base.py`
- Create: `agent_sync/adapters/claude.py`
- Create: `tests/test_agent_sync_adapters_test.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_sync_adapters_test.py
import pytest
from pathlib import Path
from agent_sync.adapters.base import AgentAdapter
from agent_sync.adapters.claude import ClaudeAdapter


def test_claude_adapter_name() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    assert adapter.agent_name == "claude"


def test_claude_adapter_launch_args_non_interactive() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    args = adapter.launch_args(prompt="do the thing", task_id="T001")
    assert "claude" in args[0]
    assert "-p" in args or "--print" in args


def test_claude_adapter_hook_env_contains_project_dir() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    env = adapter.hook_env()
    assert "CLAUDE_PROJECT_DIR" in env
    assert env["CLAUDE_PROJECT_DIR"] == "/tmp/repo"


def test_claude_adapter_config_files() -> None:
    adapter = ClaudeAdapter(repo_root=Path("/tmp/repo"))
    files = adapter.config_files()
    assert any(".claude/settings.json" in str(f) for f in files)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/mcarls/projects/ai-orchestrator
uv run pytest tests/test_agent_sync_adapters_test.py -v --tb=short
```
Expected: FAIL with `ModuleNotFoundError: No module named 'agent_sync.adapters'`

- [ ] **Step 3: Write `agent_sync/adapters/__init__.py`**

```python
```

- [ ] **Step 4: Write `agent_sync/adapters/base.py`**

```python
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class AgentAdapter(abc.ABC):
    """Abstract base for provider-specific agent launchers."""

    repo_root: Path

    @property
    @abc.abstractmethod
    def agent_name(self) -> str:
        """Short provider identifier: 'claude', 'codex', 'gemini', 'local'."""

    @abc.abstractmethod
    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        """Return argv list to launch the agent non-interactively."""

    @abc.abstractmethod
    def hook_env(self) -> dict[str, str]:
        """Return env vars the shell wrappers need to locate the repo root."""

    @abc.abstractmethod
    def config_files(self) -> list[Path]:
        """Return paths to provider config files written by agent-sync init."""

    def instruction_file(self) -> Path | None:
        """Return the provider's instruction file (CLAUDE.md / AGENTS.md / GEMINI.md)."""
        return None
```

- [ ] **Step 5: Write `agent_sync/adapters/claude.py`**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_sync.adapters.base import AgentAdapter


@dataclass
class ClaudeAdapter(AgentAdapter):
    """Adapter for Anthropic Claude Code CLI."""

    @property
    def agent_name(self) -> str:
        return "claude"

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        binary = shutil.which("claude") or "claude"
        return [binary, "-p", prompt, "--bare"]

    def hook_env(self) -> dict[str, str]:
        return {"CLAUDE_PROJECT_DIR": str(self.repo_root)}

    def config_files(self) -> list[Path]:
        return [self.repo_root / ".claude" / "settings.json"]

    def instruction_file(self) -> Path | None:
        return self.repo_root / "CLAUDE.md"
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_agent_sync_adapters_test.py -v --tb=short
```
Expected: All 4 pass.

- [ ] **Step 7: Commit**

```bash
git add agent_sync/adapters/ tests/test_agent_sync_adapters_test.py
git commit -m "feat(agent_sync): add AgentAdapter ABC and ClaudeAdapter"
```

---

## Task 2: `CodexAdapter` + `GeminiAdapter`

**Files:**
- Create: `agent_sync/adapters/codex.py`
- Create: `agent_sync/adapters/gemini.py`
- Modify: `tests/test_agent_sync_adapters_test.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_agent_sync_adapters_test.py`:

```python
from agent_sync.adapters.codex import CodexAdapter
from agent_sync.adapters.gemini import GeminiAdapter


def test_codex_adapter_name() -> None:
    adapter = CodexAdapter(repo_root=Path("/tmp/repo"))
    assert adapter.agent_name == "codex"


def test_codex_adapter_hook_env_has_no_project_dir_var() -> None:
    # Codex resolves via git rev-parse in the shell wrapper, not env var
    adapter = CodexAdapter(repo_root=Path("/tmp/repo"))
    env = adapter.hook_env()
    assert "CLAUDE_PROJECT_DIR" not in env
    assert "AGENT_SYNC_REPO_ROOT" in env


def test_codex_config_files() -> None:
    adapter = CodexAdapter(repo_root=Path("/tmp/repo"))
    files = adapter.config_files()
    assert any(".codex/hooks.json" in str(f) for f in files)
    assert any(".codex/config.toml" in str(f) for f in files)


def test_gemini_adapter_name() -> None:
    adapter = GeminiAdapter(repo_root=Path("/tmp/repo"))
    assert adapter.agent_name == "gemini"


def test_gemini_adapter_launch_args() -> None:
    adapter = GeminiAdapter(repo_root=Path("/tmp/repo"))
    args = adapter.launch_args(prompt="do the thing", task_id="T001")
    assert "gemini" in args[0]
    assert "-p" in args or "--prompt" in args


def test_gemini_config_files() -> None:
    adapter = GeminiAdapter(repo_root=Path("/tmp/repo"))
    files = adapter.config_files()
    assert any(".gemini/settings.json" in str(f) for f in files)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_agent_sync_adapters_test.py::test_codex_adapter_name -v --tb=short
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `agent_sync/adapters/codex.py`**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_sync.adapters.base import AgentAdapter


@dataclass
class CodexAdapter(AgentAdapter):
    """Adapter for OpenAI Codex CLI."""

    @property
    def agent_name(self) -> str:
        return "codex"

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        binary = shutil.which("codex") or "codex"
        return [binary, "exec", prompt]

    def hook_env(self) -> dict[str, str]:
        # Codex shell wrappers call `git rev-parse --show-toplevel` to find root.
        # We also expose AGENT_SYNC_REPO_ROOT as a fallback for environments where
        # git is unavailable inside the hook subprocess.
        return {"AGENT_SYNC_REPO_ROOT": str(self.repo_root)}

    def config_files(self) -> list[Path]:
        return [
            self.repo_root / ".codex" / "hooks.json",
            self.repo_root / ".codex" / "config.toml",
            self.repo_root / ".codex" / "rules" / "agent_sync.rules",
        ]

    def instruction_file(self) -> Path | None:
        return self.repo_root / "AGENTS.md"
```

- [ ] **Step 4: Write `agent_sync/adapters/gemini.py`**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from agent_sync.adapters.base import AgentAdapter


@dataclass
class GeminiAdapter(AgentAdapter):
    """Adapter for Google Gemini CLI."""

    @property
    def agent_name(self) -> str:
        return "gemini"

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        binary = shutil.which("gemini") or "gemini"
        return [binary, "-p", prompt]

    def hook_env(self) -> dict[str, str]:
        return {"AGENT_SYNC_REPO_ROOT": str(self.repo_root)}

    def config_files(self) -> list[Path]:
        return [self.repo_root / ".gemini" / "settings.json"]

    def instruction_file(self) -> Path | None:
        return self.repo_root / "GEMINI.md"
```

- [ ] **Step 5: Run all adapter tests**

```bash
uv run pytest tests/test_agent_sync_adapters_test.py -v --tb=short
```
Expected: All 10 pass.

- [ ] **Step 6: Commit**

```bash
git add agent_sync/adapters/codex.py agent_sync/adapters/gemini.py \
    tests/test_agent_sync_adapters_test.py
git commit -m "feat(agent_sync): add CodexAdapter and GeminiAdapter"
```

---

## Task 3: `LocalWorkerAdapter`

**Files:**
- Create: `agent_sync/adapters/local.py`
- Modify: `tests/test_agent_sync_adapters_test.py`

The local adapter does not launch a CLI process. It writes a task JSON into
`task_queue/queued/` (the existing infrastructure). The caller polls `task_queue/`
for completion rather than waiting on a subprocess.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_agent_sync_adapters_test.py`:

```python
import json
from agent_sync.adapters.local import LocalWorkerAdapter


def test_local_adapter_name() -> None:
    adapter = LocalWorkerAdapter(repo_root=Path("/tmp/repo"))
    assert adapter.agent_name == "local"


def test_local_adapter_enqueue_creates_task_file(tmp_path: Path) -> None:
    adapter = LocalWorkerAdapter(repo_root=tmp_path)
    queued_dir = tmp_path / "task_queue" / "queued"
    queued_dir.mkdir(parents=True)

    task_file = adapter.enqueue(
        task_id="T001",
        prompt="run tests",
        metadata={"worktree": str(tmp_path / ".agent_sync" / "worktrees" / "T001")},
    )

    assert task_file.exists()
    data = json.loads(task_file.read_text(encoding="utf-8"))
    assert data["task_id"] == "T001"
    assert data["prompt"] == "run tests"
    assert data["agent"] == "local"


def test_local_adapter_launch_args_raises() -> None:
    adapter = LocalWorkerAdapter(repo_root=Path("/tmp/repo"))
    with pytest.raises(NotImplementedError):
        adapter.launch_args(prompt="x", task_id="T001")
```

- [ ] **Step 2: Write `agent_sync/adapters/local.py`**

```python
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_sync.adapters.base import AgentAdapter


@dataclass
class LocalWorkerAdapter(AgentAdapter):
    """Delegates tasks to the existing task_queue/ filesystem infrastructure."""

    @property
    def agent_name(self) -> str:
        return "local"

    def launch_args(self, *, prompt: str, task_id: str) -> list[str]:
        raise NotImplementedError(
            "LocalWorkerAdapter uses enqueue(), not launch_args(). "
            "Use agent-sync dispatch for local worker delegation."
        )

    def hook_env(self) -> dict[str, str]:
        return {}

    def config_files(self) -> list[Path]:
        return []

    def enqueue(
        self,
        *,
        task_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Write a task JSON into task_queue/queued/ for local_worker_loop.sh."""
        queued_dir = self.repo_root / "task_queue" / "queued"
        queued_dir.mkdir(parents=True, exist_ok=True)

        ts = int(time.time() * 1000)
        task_file = queued_dir / f"{ts}-{task_id}.json"
        payload: dict[str, Any] = {
            "task_id": task_id,
            "agent": "local",
            "prompt": prompt,
            "metadata": metadata or {},
        }
        task_file.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return task_file
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_agent_sync_adapters_test.py -v --tb=short
```
Expected: All 13 pass.

- [ ] **Step 4: Commit**

```bash
git add agent_sync/adapters/local.py tests/test_agent_sync_adapters_test.py
git commit -m "feat(agent_sync): add LocalWorkerAdapter (task_queue delegate)"
```

---

## Task 4: Hook handlers — full PostToolUse and Stop implementations

**Files:**
- Modify: `agent_sync/hooks/handlers/post_tool.py`
- Modify: `agent_sync/hooks/handlers/stop.py`
- Modify: `agent_sync/hooks/handlers/session_start.py`
- Modify: `tests/test_agent_sync_hooks_test.py`

The Phase 1 stubs need to be replaced with DB-wired implementations.

### `session_start.py` — full implementation

When a hook fires `SessionStart`, we need to:
1. Resolve which run is active for this repo+agent from the DB.
2. If found, inject `SESSION_BRIEF.md` content as a `context` response so the
   agent sees it immediately on startup.
3. If no active run exists, respond with an empty JSON (no-op).

- [ ] **Step 1: Write failing tests for session_start**

Append to `tests/test_agent_sync_hooks_test.py`:

```python
import json
import sqlite3
from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.hooks.normalize import HookEvent
from agent_sync.hooks.handlers.session_start import handle_session_start
from agent_sync.state.tasks import create_task
from agent_sync.state.runs import start_run


def _fresh_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO agents (agent_name, binary_name) VALUES (?, ?)",
        ("claude", "claude"),
    )
    conn.commit()
    return conn


def test_session_start_no_active_run_returns_empty(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    event = HookEvent(
        provider="claude",
        event_type="SessionStart",
        session_id="sess-001",
        cwd=str(tmp_path),
        tool_name=None,
        tool_input=None,
        tool_response=None,
        stop_reason=None,
    )
    result = handle_session_start(event, conn=conn, repo_root=tmp_path)
    assert result == {}


def test_session_start_active_run_injects_brief(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    create_task(conn, task_id="T001", title="test task", description="desc")
    run = start_run(conn, task_id="T001", agent_name="claude", worktree_path=str(tmp_path))

    brief_path = tmp_path / "agent_sync" / "docs" / "SESSION_BRIEF.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text("# Session Brief\nTask T001\n", encoding="utf-8")

    event = HookEvent(
        provider="claude",
        event_type="SessionStart",
        session_id="sess-001",
        cwd=str(tmp_path),
        tool_name=None,
        tool_input=None,
        tool_response=None,
        stop_reason=None,
    )
    result = handle_session_start(event, conn=conn, repo_root=tmp_path)
    assert "context" in result
    assert "T001" in result["context"]
```

- [ ] **Step 2: Rewrite `agent_sync/hooks/handlers/session_start.py`**

```python
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent

logger = logging.getLogger(__name__)


def handle_session_start(
    event: HookEvent,
    *,
    conn: sqlite3.Connection,
    repo_root: Path,
) -> dict:
    """Inject SESSION_BRIEF.md content when an active run exists for this agent."""
    row = conn.execute(
        """
        SELECT r.run_id, r.task_id
        FROM runs r
        WHERE r.agent_name = ? AND r.status = 'active'
        ORDER BY r.started_at DESC
        LIMIT 1
        """,
        (event.provider,),
    ).fetchone()

    if not row:
        return {}

    brief_path = repo_root / "agent_sync" / "docs" / "SESSION_BRIEF.md"
    if not brief_path.exists():
        logger.warning("SESSION_BRIEF.md not found at %s", brief_path)
        return {}

    content = brief_path.read_text(encoding="utf-8")
    logger.info("Injecting SESSION_BRIEF for run %s", row["run_id"])
    return {"context": content}
```

- [ ] **Step 3: Write failing tests for post_tool**

Append to `tests/test_agent_sync_hooks_test.py`:

```python
from agent_sync.hooks.handlers.post_tool import handle_post_tool


def test_post_tool_records_write_event(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    create_task(conn, task_id="T001", title="test task", description="desc")
    run = start_run(conn, task_id="T001", agent_name="claude", worktree_path=str(tmp_path))

    event = HookEvent(
        provider="claude",
        event_type="PostToolUse",
        session_id="sess-001",
        cwd=str(tmp_path),
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "src" / "foo.py"), "content": "x = 1"},
        tool_response={"success": True},
        stop_reason=None,
    )
    result = handle_post_tool(event, conn=conn, repo_root=tmp_path)
    assert result == {}

    rows = conn.execute(
        "SELECT event_type, path FROM events WHERE run_id = ?",
        (run.run_id,),
    ).fetchall()
    assert any(r["event_type"] == "file_written" for r in rows)
```

- [ ] **Step 4: Rewrite `agent_sync/hooks/handlers/post_tool.py`**

```python
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from agent_sync.hooks.normalize import HookEvent

logger = logging.getLogger(__name__)

# Tool names that write files — track their output paths.
_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
# Tool names that may create/delete files.
_FS_TOOLS = frozenset({"Bash", "mcp__filesystem__write_file"})


def handle_post_tool(
    event: HookEvent,
    *,
    conn: sqlite3.Connection,
    repo_root: Path,
) -> dict:
    """Record file write events so stop handler can build a complete HANDOFF.md."""
    if event.tool_name not in _WRITE_TOOLS:
        return {}

    run_row = conn.execute(
        "SELECT run_id FROM runs WHERE agent_name = ? AND status = 'active' LIMIT 1",
        (event.provider,),
    ).fetchone()
    if not run_row:
        return {}

    run_id = run_row["run_id"]
    tool_input = event.tool_input or {}
    file_path = tool_input.get("file_path") or tool_input.get("path", "")

    if file_path:
        conn.execute(
            """
            INSERT INTO events (run_id, event_type, path, payload)
            VALUES (?, 'file_written', ?, '{}')
            """,
            (run_id, file_path),
        )
        conn.commit()
        logger.debug("Recorded file_written event: %s (run %s)", file_path, run_id)

    return {}
```

- [ ] **Step 5: Write failing test for stop handler**

Append to `tests/test_agent_sync_hooks_test.py`:

```python
from agent_sync.hooks.handlers.stop import handle_stop


def test_stop_handler_writes_handoff_and_ends_run(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    create_task(conn, task_id="T001", title="Implement auth", description="OAuth2 flow")
    run = start_run(conn, task_id="T001", agent_name="claude", worktree_path=str(tmp_path))

    # Simulate a file write event
    conn.execute(
        "INSERT INTO events (run_id, event_type, path, payload) VALUES (?, 'file_written', ?, '{}')",
        (run.run_id, str(tmp_path / "src" / "auth.py")),
    )
    conn.commit()

    docs_dir = tmp_path / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    event = HookEvent(
        provider="claude",
        event_type="Stop",
        session_id="sess-001",
        cwd=str(tmp_path),
        tool_name=None,
        tool_input=None,
        tool_response=None,
        stop_reason="end_turn",
    )
    result = handle_stop(event, conn=conn, repo_root=tmp_path)
    assert result == {}

    handoff_path = docs_dir / "HANDOFF.md"
    assert handoff_path.exists()
    content = handoff_path.read_text(encoding="utf-8")
    assert "T001" in content
    assert "auth.py" in content

    run_row = conn.execute(
        "SELECT status FROM runs WHERE run_id = ?", (run.run_id,)
    ).fetchone()
    assert run_row["status"] == "completed"
```

- [ ] **Step 6: Rewrite `agent_sync/hooks/handlers/stop.py`**

```python
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agent_sync.docs_gen.renderer import render_handoff
from agent_sync.hooks.normalize import HookEvent
from agent_sync.state.runs import end_run

logger = logging.getLogger(__name__)


def handle_stop(
    event: HookEvent,
    *,
    conn: sqlite3.Connection,
    repo_root: Path,
) -> dict:
    """Render HANDOFF.md from DB state and mark the run completed."""
    run_row = conn.execute(
        """
        SELECT r.run_id, r.task_id, r.agent_name, r.worktree_path
        FROM runs r
        WHERE r.agent_name = ? AND r.status = 'active'
        ORDER BY r.started_at DESC
        LIMIT 1
        """,
        (event.provider,),
    ).fetchone()

    if not run_row:
        logger.warning("Stop hook fired but no active run found for %s", event.provider)
        return {}

    run_id = run_row["run_id"]
    task_id = run_row["task_id"]

    task_row = conn.execute(
        "SELECT title, description, status FROM tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()

    file_events = conn.execute(
        """
        SELECT DISTINCT path FROM events
        WHERE run_id = ? AND event_type = 'file_written' AND path IS NOT NULL
        ORDER BY created_at
        """,
        (run_id,),
    ).fetchall()

    written_paths = [r["path"] for r in file_events]

    handoff_md = render_handoff(
        task_id=task_id,
        task_title=task_row["title"] if task_row else task_id,
        task_description=task_row["description"] if task_row else "",
        run_id=run_id,
        agent_name=event.provider,
        stop_reason=event.stop_reason or "end_turn",
        files_modified=written_paths,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )

    docs_dir = repo_root / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "HANDOFF.md").write_text(handoff_md, encoding="utf-8")
    logger.info("Wrote HANDOFF.md for run %s", run_id)

    end_run(conn, run_id=run_id, status="completed")
    return {}
```

- [ ] **Step 7: Update `render_handoff()` signature in `docs_gen/renderer.py`**

The Phase 1 `render_handoff()` took keyword args. Verify its signature and update
if needed to accept `files_modified: list[str]`:

```python
def render_handoff(
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    run_id: str,
    agent_name: str,
    stop_reason: str,
    files_modified: list[str],
    timestamp: str,
) -> str:
    files_section = "\n".join(f"- `{p}`" for p in files_modified) or "_none recorded_"
    return HANDOFF.format(
        task_id=task_id,
        task_title=task_title,
        task_description=task_description,
        run_id=run_id,
        agent_name=agent_name,
        stop_reason=stop_reason,
        files_modified=files_section,
        timestamp=timestamp,
    )
```

Ensure `HANDOFF` template in `docs_gen/templates.py` contains `{files_modified}`.
If it doesn't, add the section:

```python
HANDOFF = """\
# Handoff — {task_id}

**Task:** {task_title}
**Run:** {run_id}
**Agent:** {agent_name}
**Stopped:** {timestamp}
**Stop reason:** {stop_reason}

## Description

{task_description}

## Files Modified

{files_modified}

## Next Steps

_Fill in before handing off to the next agent._

---
_Generated by agent-sync. Edit freely._
"""
```

- [ ] **Step 8: Run all hook tests**

```bash
uv run pytest tests/test_agent_sync_hooks_test.py -v --tb=short
```
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add agent_sync/hooks/handlers/ agent_sync/docs_gen/ \
    tests/test_agent_sync_hooks_test.py
git commit -m "feat(agent_sync): wire DB into session_start, post_tool, stop handlers"
```

---

## Task 5: `agent-sync start` command

**Files:**
- Create: `agent_sync/commands/start.py`
- Modify: `agent_sync/cli.py`
- Modify: `tests/test_agent_sync_integration_test.py`

`agent-sync start -t <task-id> -a <agent>` is the primary entry point for
beginning a work session. It must:
1. Create or attach to an existing task in the DB.
2. Create a git worktree for the task+agent combination.
3. Start a `Run` record.
4. Acquire file claims for the task's declared scope (or none if not declared).
5. Render `SESSION_BRIEF.md` (or create a blank one if first run on this task).
6. Launch the agent non-interactively with a prompt that tells it to read
   `SESSION_BRIEF.md` and `AGENT_CONTRACT.md`.

- [ ] **Step 1: Write failing test**

```python
# tests/test_agent_sync_integration_test.py
import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.commands.start import cmd_start
from agent_sync.state.tasks import get_task
from agent_sync.state.runs import get_active_run


def _init_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    conn.execute(
        "INSERT INTO agents (agent_name, binary_name) VALUES (?, ?)",
        ("claude", "claude"),
    )
    conn.commit()
    return conn


def test_start_creates_task_and_run(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    with patch("agent_sync.commands.start.subprocess.run") as mock_run, \
         patch("agent_sync.commands.start.create_worktree") as mock_wt:
        mock_run.return_value = MagicMock(returncode=0)
        mock_wt.return_value = tmp_path / ".agent_sync" / "worktrees" / "T001--claude--start"

        cmd_start(
            task_id="T001",
            agent_name="claude",
            title="Build auth module",
            description="Implement OAuth2",
            repo_root=tmp_path,
            conn=conn,
        )

    task = get_task(conn, "T001")
    assert task is not None
    assert task.title == "Build auth module"

    run = get_active_run(conn, task_id="T001", agent_name="claude")
    assert run is not None
    assert run.status == "active"


def test_start_writes_session_brief(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    with patch("agent_sync.commands.start.subprocess.run"), \
         patch("agent_sync.commands.start.create_worktree") as mock_wt:
        mock_wt.return_value = tmp_path / ".agent_sync" / "worktrees" / "T001--claude--start"

        cmd_start(
            task_id="T001",
            agent_name="claude",
            title="Build auth module",
            description="Implement OAuth2",
            repo_root=tmp_path,
            conn=conn,
        )

    brief = (tmp_path / "agent_sync" / "docs" / "SESSION_BRIEF.md").read_text(encoding="utf-8")
    assert "T001" in brief
    assert "claude" in brief
```

- [ ] **Step 2: Write `agent_sync/commands/start.py`**

```python
from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

from agent_sync.adapters.claude import ClaudeAdapter
from agent_sync.adapters.codex import CodexAdapter
from agent_sync.adapters.gemini import GeminiAdapter
from agent_sync.adapters.base import AgentAdapter
from agent_sync.docs_gen.renderer import render_session_brief
from agent_sync.state.runs import get_active_run, start_run
from agent_sync.state.tasks import create_task, get_task
from agent_sync.worktree import create_worktree

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
}


def _get_adapter(agent_name: str, repo_root: Path) -> AgentAdapter:
    cls = _ADAPTERS.get(agent_name)
    if cls is None:
        raise ValueError(f"Unknown agent '{agent_name}'. Valid: {list(_ADAPTERS)}")
    return cls(repo_root=repo_root)


def cmd_start(
    *,
    task_id: str,
    agent_name: str,
    title: str,
    description: str,
    repo_root: Path,
    conn: sqlite3.Connection,
    launch: bool = True,
) -> None:
    """Create or attach a task and start a new agent run."""
    adapter = _get_adapter(agent_name, repo_root)

    # Idempotent: create task if it doesn't exist.
    existing = get_task(conn, task_id)
    if existing is None:
        create_task(conn, task_id=task_id, title=title, description=description)
        logger.info("Created task %s", task_id)
    else:
        logger.info("Attaching to existing task %s", task_id)

    # Create the git worktree.
    worktree_path = create_worktree(
        repo_root=repo_root,
        task_id=task_id,
        agent_name=agent_name,
    )
    logger.info("Worktree at %s", worktree_path)

    # Start the run record.
    run = start_run(
        conn,
        task_id=task_id,
        agent_name=agent_name,
        worktree_path=str(worktree_path),
    )
    logger.info("Started run %s", run.run_id)

    # Render SESSION_BRIEF.md.
    docs_dir = repo_root / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    brief_md = render_session_brief(
        task_id=task_id,
        task_title=title,
        task_description=description,
        run_id=run.run_id,
        agent_name=agent_name,
        worktree_path=str(worktree_path),
    )
    (docs_dir / "SESSION_BRIEF.md").write_text(brief_md, encoding="utf-8")
    logger.info("Wrote SESSION_BRIEF.md")

    if not launch:
        return

    # Launch the agent.
    prompt = (
        f"You are resuming task {task_id}. "
        f"Read agent_sync/docs/SESSION_BRIEF.md and agent_sync/docs/AGENT_CONTRACT.md "
        f"before doing anything else."
    )
    args = adapter.launch_args(prompt=prompt, task_id=task_id)
    logger.info("Launching %s: %s", agent_name, " ".join(args))
    subprocess.run(args, cwd=str(worktree_path), check=False)
```

- [ ] **Step 3: Wire `start` into `agent_sync/cli.py`**

In `cli.py`, find the stub for `start` and replace it:

```python
from agent_sync.commands.start import cmd_start

# In _build_parser(), add start subcommand:
p_start = sub.add_parser("start", help="Start or attach a task to an agent + worktree")
p_start.add_argument("-t", "--task-id", required=True, help="Task ID (e.g. T001)")
p_start.add_argument("-a", "--agent", required=True,
                     choices=["claude", "codex", "gemini", "local"],
                     help="Agent to assign this task to")
p_start.add_argument("--title", default="", help="Task title (used on first start only)")
p_start.add_argument("--description", "-d", default="", help="Task description")
p_start.add_argument("--no-launch", action="store_true",
                     help="Set up task/run/brief but don't launch the agent")

# In dispatch():
elif args.command == "start":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_start(
        task_id=args.task_id,
        agent_name=args.agent,
        title=args.title,
        description=args.description,
        repo_root=repo_root,
        conn=conn,
        launch=not args.no_launch,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agent_sync_integration_test.py -v --tb=short
```
Expected: Both pass.

- [ ] **Step 5: Commit**

```bash
git add agent_sync/commands/start.py agent_sync/cli.py \
    tests/test_agent_sync_integration_test.py
git commit -m "feat(agent_sync): implement agent-sync start command"
```

---

## Task 6: `agent-sync handoff` command

**Files:**
- Create: `agent_sync/commands/handoff_cmd.py`
- Modify: `agent_sync/cli.py`
- Modify: `tests/test_agent_sync_integration_test.py`

`agent-sync handoff -t T001 -a codex` freezes the current run, writes the final
HANDOFF.md, releases all claims, and records the handoff in the DB.

- [ ] **Step 1: Add failing test**

Append to `tests/test_agent_sync_integration_test.py`:

```python
from agent_sync.commands.handoff_cmd import cmd_handoff
from agent_sync.state.handoffs import get_pending_handoff


def test_handoff_freezes_run_and_writes_doc(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)
    from agent_sync.state.tasks import create_task
    from agent_sync.state.runs import start_run

    create_task(conn, task_id="T001", title="Auth module", description="OAuth2")
    run = start_run(conn, task_id="T001", agent_name="claude",
                    worktree_path=str(tmp_path))

    docs_dir = tmp_path / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    cmd_handoff(
        task_id="T001",
        to_agent="codex",
        repo_root=tmp_path,
        conn=conn,
    )

    # Run should be completed
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = ?", (run.run_id,)
    ).fetchone()
    assert row["status"] == "completed"

    # HANDOFF.md should exist
    assert (docs_dir / "HANDOFF.md").exists()

    # Handoff record in DB
    handoff = get_pending_handoff(conn, task_id="T001")
    assert handoff is not None
    assert handoff.to_agent == "codex"
```

- [ ] **Step 2: Add `get_pending_handoff()` to `agent_sync/state/handoffs.py`**

```python
def get_pending_handoff(conn: sqlite3.Connection, *, task_id: str) -> Handoff | None:
    """Return the most recent pending handoff for a task, or None."""
    row = conn.execute(
        """
        SELECT handoff_id, task_id, from_agent, to_agent, status,
               handoff_doc_path, created_at, accepted_at
        FROM handoffs
        WHERE task_id = ? AND status = 'proposed'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if not row:
        return None
    return Handoff(**dict(row))
```

- [ ] **Step 3: Write `agent_sync/commands/handoff_cmd.py`**

```python
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agent_sync.docs_gen.renderer import render_handoff
from agent_sync.state.handoffs import Handoff, create_handoff
from agent_sync.state.runs import end_run

logger = logging.getLogger(__name__)


def cmd_handoff(
    *,
    task_id: str,
    to_agent: str,
    repo_root: Path,
    conn: sqlite3.Connection,
    notes: str = "",
) -> None:
    """Freeze the active run, write HANDOFF.md, record handoff in DB."""
    run_row = conn.execute(
        """
        SELECT run_id, agent_name, worktree_path
        FROM runs
        WHERE task_id = ? AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()

    if not run_row:
        raise RuntimeError(f"No active run for task {task_id}. Nothing to hand off.")

    run_id = run_row["run_id"]
    from_agent = run_row["agent_name"]

    task_row = conn.execute(
        "SELECT title, description FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()

    file_events = conn.execute(
        """
        SELECT DISTINCT path FROM events
        WHERE run_id = ? AND event_type = 'file_written' AND path IS NOT NULL
        ORDER BY created_at
        """,
        (run_id,),
    ).fetchall()
    written_paths = [r["path"] for r in file_events]

    # Render and write HANDOFF.md.
    docs_dir = repo_root / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    handoff_path = docs_dir / "HANDOFF.md"
    handoff_md = render_handoff(
        task_id=task_id,
        task_title=task_row["title"] if task_row else task_id,
        task_description=task_row["description"] if task_row else "",
        run_id=run_id,
        agent_name=from_agent,
        stop_reason="handoff",
        files_modified=written_paths,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )
    handoff_path.write_text(handoff_md, encoding="utf-8")
    logger.info("Wrote HANDOFF.md for run %s → %s", run_id, to_agent)

    # End the run.
    end_run(conn, run_id=run_id, status="completed")

    # Record handoff.
    create_handoff(
        conn,
        task_id=task_id,
        from_agent=from_agent,
        to_agent=to_agent,
        handoff_doc_path=str(handoff_path),
    )
    logger.info("Handoff T%s: %s → %s", task_id, from_agent, to_agent)
```

- [ ] **Step 4: Wire `handoff` into `agent_sync/cli.py`**

```python
from agent_sync.commands.handoff_cmd import cmd_handoff

p_handoff = sub.add_parser("handoff", help="Freeze run, write HANDOFF.md, prepare next agent")
p_handoff.add_argument("-t", "--task-id", required=True, help="Task ID")
p_handoff.add_argument("-a", "--agent", required=True,
                       help="Agent to hand off TO (claude, codex, gemini, local)")
p_handoff.add_argument("--notes", default="", help="Optional free-text notes for the next agent")

# In dispatch():
elif args.command == "handoff":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_handoff(
        task_id=args.task_id,
        to_agent=args.agent,
        repo_root=repo_root,
        conn=conn,
        notes=args.notes,
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_agent_sync_integration_test.py -v --tb=short
```
Expected: All 3 integration tests pass.

- [ ] **Step 6: Commit**

```bash
git add agent_sync/commands/handoff_cmd.py agent_sync/state/handoffs.py \
    agent_sync/cli.py tests/test_agent_sync_integration_test.py
git commit -m "feat(agent_sync): implement agent-sync handoff command"
```

---

## Task 7: `agent-sync resume` command

**Files:**
- Create: `agent_sync/commands/resume.py`
- Modify: `agent_sync/cli.py`
- Modify: `tests/test_agent_sync_integration_test.py`

`agent-sync resume -t T001` finds the pending handoff for T001, renders a
fresh SESSION_BRIEF.md incorporating HANDOFF.md context, accepts the handoff
in the DB, and launches the receiving agent.

- [ ] **Step 1: Add failing test**

Append to `tests/test_agent_sync_integration_test.py`:

```python
from agent_sync.commands.resume import cmd_resume


def test_resume_accepts_handoff_and_launches(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    from agent_sync.state.tasks import create_task
    from agent_sync.state.runs import start_run
    from agent_sync.state.handoffs import create_handoff
    from agent_sync.state.runs import end_run

    create_task(conn, task_id="T001", title="Auth module", description="OAuth2")
    run = start_run(conn, task_id="T001", agent_name="claude",
                    worktree_path=str(tmp_path))
    end_run(conn, run_id=run.run_id, status="completed")

    docs_dir = tmp_path / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = docs_dir / "HANDOFF.md"
    handoff_path.write_text("# Handoff\nTask T001\n", encoding="utf-8")

    create_handoff(
        conn,
        task_id="T001",
        from_agent="claude",
        to_agent="codex",
        handoff_doc_path=str(handoff_path),
    )

    with patch("agent_sync.commands.resume.subprocess.run") as mock_run, \
         patch("agent_sync.commands.resume.create_worktree") as mock_wt:
        mock_run.return_value = MagicMock(returncode=0)
        mock_wt.return_value = tmp_path / ".agent_sync" / "worktrees" / "T001--codex--resume"

        cmd_resume(task_id="T001", repo_root=tmp_path, conn=conn)

    # Handoff accepted
    from agent_sync.state.handoffs import get_pending_handoff
    pending = get_pending_handoff(conn, task_id="T001")
    assert pending is None  # was accepted, no longer pending

    # New run started for codex
    new_run = get_active_run(conn, task_id="T001", agent_name="codex")
    assert new_run is not None

    # SESSION_BRIEF updated
    brief = (docs_dir / "SESSION_BRIEF.md").read_text(encoding="utf-8")
    assert "T001" in brief
```

- [ ] **Step 2: Add `get_active_run(agent_name)` to `agent_sync/state/runs.py`**

```python
def get_active_run(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent_name: str,
) -> Run | None:
    """Return the active run for a task+agent, or None."""
    row = conn.execute(
        """
        SELECT run_id, task_id, agent_name, worktree_path, status, started_at, ended_at
        FROM runs
        WHERE task_id = ? AND agent_name = ? AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (task_id, agent_name),
    ).fetchone()
    if not row:
        return None
    return Run(**dict(row))
```

- [ ] **Step 3: Update `accept_handoff()` in `agent_sync/state/handoffs.py`**

```python
def accept_handoff(conn: sqlite3.Connection, *, handoff_id: str) -> None:
    """Mark a proposed handoff as accepted."""
    conn.execute(
        "UPDATE handoffs SET status = 'accepted', accepted_at = datetime('now') WHERE handoff_id = ?",
        (handoff_id,),
    )
    conn.commit()
```

- [ ] **Step 4: Write `agent_sync/commands/resume.py`**

```python
from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

from agent_sync.adapters.claude import ClaudeAdapter
from agent_sync.adapters.codex import CodexAdapter
from agent_sync.adapters.gemini import GeminiAdapter
from agent_sync.adapters.base import AgentAdapter
from agent_sync.docs_gen.renderer import render_session_brief
from agent_sync.state.handoffs import accept_handoff, get_pending_handoff
from agent_sync.state.runs import start_run
from agent_sync.worktree import create_worktree

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
}


def cmd_resume(
    *,
    task_id: str,
    repo_root: Path,
    conn: sqlite3.Connection,
    launch: bool = True,
) -> None:
    """Accept the pending handoff for a task and start the receiving agent."""
    handoff = get_pending_handoff(conn, task_id=task_id)
    if handoff is None:
        raise RuntimeError(
            f"No pending handoff found for task {task_id}. "
            "Run 'agent-sync handoff' first or check 'agent-sync doctor'."
        )

    to_agent = handoff.to_agent
    adapter_cls = _ADAPTERS.get(to_agent)
    if adapter_cls is None:
        raise ValueError(f"Unknown agent '{to_agent}' in handoff record.")
    adapter = adapter_cls(repo_root=repo_root)

    task_row = conn.execute(
        "SELECT title, description FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    title = task_row["title"] if task_row else task_id
    description = task_row["description"] if task_row else ""

    # Load prior handoff context for injection into the brief.
    handoff_context = ""
    if handoff.handoff_doc_path:
        hp = Path(handoff.handoff_doc_path)
        if hp.exists():
            handoff_context = hp.read_text(encoding="utf-8")

    # Create worktree for the receiving agent.
    worktree_path = create_worktree(
        repo_root=repo_root,
        task_id=task_id,
        agent_name=to_agent,
    )

    # Start the new run.
    run = start_run(
        conn,
        task_id=task_id,
        agent_name=to_agent,
        worktree_path=str(worktree_path),
    )

    # Accept the handoff now that the run is started.
    accept_handoff(conn, handoff_id=handoff.handoff_id)

    # Render SESSION_BRIEF incorporating HANDOFF context.
    docs_dir = repo_root / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    brief_md = render_session_brief(
        task_id=task_id,
        task_title=title,
        task_description=description,
        run_id=run.run_id,
        agent_name=to_agent,
        worktree_path=str(worktree_path),
        prior_handoff=handoff_context,
    )
    (docs_dir / "SESSION_BRIEF.md").write_text(brief_md, encoding="utf-8")
    logger.info("Wrote SESSION_BRIEF.md for %s", to_agent)

    if not launch:
        return

    prompt = (
        f"You are continuing task {task_id} from a previous agent. "
        f"Read agent_sync/docs/SESSION_BRIEF.md for full context before doing anything."
    )
    args = adapter.launch_args(prompt=prompt, task_id=task_id)
    logger.info("Launching %s: %s", to_agent, " ".join(args))
    subprocess.run(args, cwd=str(worktree_path), check=False)
```

- [ ] **Step 5: Update `render_session_brief()` to accept `prior_handoff`**

In `agent_sync/docs_gen/renderer.py`, update the signature:

```python
def render_session_brief(
    *,
    task_id: str,
    task_title: str,
    task_description: str,
    run_id: str,
    agent_name: str,
    worktree_path: str,
    prior_handoff: str = "",
) -> str:
    handoff_section = ""
    if prior_handoff:
        handoff_section = f"\n## Prior Agent Handoff\n\n{prior_handoff}\n"
    return SESSION_BRIEF.format(
        task_id=task_id,
        task_title=task_title,
        task_description=task_description,
        run_id=run_id,
        agent_name=agent_name,
        worktree_path=worktree_path,
        handoff_section=handoff_section,
    )
```

Ensure `SESSION_BRIEF` template includes `{handoff_section}`.

- [ ] **Step 6: Wire `resume` into `agent_sync/cli.py`**

```python
from agent_sync.commands.resume import cmd_resume

p_resume = sub.add_parser("resume", help="Accept pending handoff and launch receiving agent")
p_resume.add_argument("-t", "--task-id", required=True, help="Task ID")
p_resume.add_argument("--no-launch", action="store_true",
                      help="Accept handoff and write brief without launching agent")

# In dispatch():
elif args.command == "resume":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_resume(
        task_id=args.task_id,
        repo_root=repo_root,
        conn=conn,
        launch=not args.no_launch,
    )
```

- [ ] **Step 7: Run all integration tests**

```bash
uv run pytest tests/test_agent_sync_integration_test.py -v --tb=short
```
Expected: All 4 tests pass.

- [ ] **Step 8: Run the full Phase 2 test suite**

```bash
uv run pytest tests/test_agent_sync_adapters_test.py \
              tests/test_agent_sync_hooks_test.py \
              tests/test_agent_sync_integration_test.py \
              tests/test_agent_sync_db_test.py \
              tests/test_agent_sync_state_test.py \
              tests/test_agent_sync_claims_test.py \
              -v --tb=short
```
Expected: All pass.

- [ ] **Step 9: Commit**

```bash
git add agent_sync/commands/resume.py agent_sync/state/ \
    agent_sync/docs_gen/ agent_sync/cli.py \
    tests/test_agent_sync_integration_test.py
git commit -m "feat(agent_sync): implement agent-sync resume command"
```

---

## Task 8: End-to-end smoke test

This task validates the whole Phase 2 flow without a live agent binary.

- [ ] **Step 1: Write the full round-trip test**

Append to `tests/test_agent_sync_integration_test.py`:

```python
def test_full_handoff_round_trip(tmp_path: Path) -> None:
    """start(claude) → handoff(→codex) → resume(codex) produces consistent DB state."""
    conn = _init_db(tmp_path)

    # Register codex agent
    conn.execute(
        "INSERT OR IGNORE INTO agents (agent_name, binary_name) VALUES (?, ?)",
        ("codex", "codex"),
    )
    conn.commit()

    docs_dir = tmp_path / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    with patch("agent_sync.commands.start.subprocess.run"), \
         patch("agent_sync.commands.start.create_worktree") as mock_wt1:
        mock_wt1.return_value = tmp_path / ".agent_sync" / "w1"
        cmd_start(
            task_id="T001",
            agent_name="claude",
            title="Build parser",
            description="Parse TOML config",
            repo_root=tmp_path,
            conn=conn,
            launch=False,
        )

    cmd_handoff(task_id="T001", to_agent="codex", repo_root=tmp_path, conn=conn)

    with patch("agent_sync.commands.resume.subprocess.run"), \
         patch("agent_sync.commands.resume.create_worktree") as mock_wt2:
        mock_wt2.return_value = tmp_path / ".agent_sync" / "w2"
        cmd_resume(task_id="T001", repo_root=tmp_path, conn=conn, launch=False)

    # Claude run completed, codex run active
    claude_run = conn.execute(
        "SELECT status FROM runs WHERE task_id='T001' AND agent_name='claude'"
    ).fetchone()
    codex_run = conn.execute(
        "SELECT status FROM runs WHERE task_id='T001' AND agent_name='codex'"
    ).fetchone()
    assert claude_run["status"] == "completed"
    assert codex_run["status"] == "active"

    # No pending handoffs remain
    from agent_sync.state.handoffs import get_pending_handoff
    assert get_pending_handoff(conn, task_id="T001") is None

    # SESSION_BRIEF updated for codex
    brief = (docs_dir / "SESSION_BRIEF.md").read_text(encoding="utf-8")
    assert "codex" in brief
    assert "T001" in brief
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/test_agent_sync_integration_test.py::test_full_handoff_round_trip -v --tb=short
```
Expected: PASS.

- [ ] **Step 3: Run full suite**

```bash
uv run pytest tests/ -k "agent_sync" -v --tb=short
```
Expected: All agent_sync tests pass.

- [ ] **Step 4: Type check**

```bash
uv run mypy agent_sync/ --strict --ignore-missing-imports
```
Fix any errors before committing.

- [ ] **Step 5: Lint**

```bash
uv run ruff check --fix agent_sync/
uv run black agent_sync/
```

- [ ] **Step 6: Final commit**

```bash
git add -p  # Stage only agent_sync/ and tests/ changes
git commit -m "feat(agent_sync): Phase 2 complete — sequential handoff round-trip verified"
```

---

## Phase 2 Definition of Done

- [ ] `ClaudeAdapter`, `CodexAdapter`, `GeminiAdapter`, `LocalWorkerAdapter` all exist with correct `launch_args`, `hook_env`, `config_files`
- [ ] `session_start` handler injects SESSION_BRIEF when active run exists
- [ ] `post_tool` handler records `file_written` events for Write/Edit/MultiEdit tools
- [ ] `stop` handler renders HANDOFF.md from DB state and calls `end_run`
- [ ] `agent-sync start -t T001 -a claude` creates task + worktree + run + SESSION_BRIEF.md
- [ ] `agent-sync handoff -t T001 -a codex` freezes run + writes HANDOFF.md + records handoff
- [ ] `agent-sync resume -t T001` accepts handoff + starts new run + renders new SESSION_BRIEF + launches agent
- [ ] Full round-trip test passes without live agent binaries

Proceed to: `agent_sync/docs/plans/PLAN-3-PARALLEL.md`
