# Agent Sync Phase 3 — Parallel Delegation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the parallel delegation layer: manifest-driven fan-out of child tasks
to isolated worktrees, file-level claim locking across concurrent agents, an
integration gate that merges completed child branches with validation, and the
`agent-sync review`, `agent-sync integrate`, and `agent-sync memory sync` commands.

**Architecture:** A primary agent creates a YAML manifest listing subtasks with
their scope, target agent, and acceptance commands. `agent-sync dispatch` reads
the manifest, fans out child runs into isolated git worktrees, and writes a
polling-friendly status table. The integration gate rebases each child branch onto
the target branch, runs acceptance commands, and performs a `--no-ff --no-commit`
merge — never auto-pushing. The memory sync command distills the run event log
and HANDOFF.md into `memory/notes/` for manual review.

**Tech Stack:** Python 3.11+, `sqlite3`, `subprocess`, `threading`, `argparse`,
`pathlib`, `dataclasses`, `yaml` (PyYAML), `pytest`, `uv`

**Prerequisites:** Phase 1 and Phase 2 complete.

**Read first:** `agent_sync/docs/plans/OVERVIEW.md` and
`agent_sync/docs/plans/PLAN-2-SEQUENTIAL.md` for existing interfaces.

---

## File Map

| File | Responsibility |
|---|---|
| `agent_sync/routing.py` | Task-to-agent scoring: capability matching, load balancing |
| `agent_sync/manifests/schema.py` | `DispatchManifest` dataclass, YAML loader/validator |
| `agent_sync/commands/dispatch_cmd.py` | `cmd_dispatch()`: fan-out child tasks from manifest |
| `agent_sync/commands/review.py` | `cmd_review()`: launch reviewer agent against task branch |
| `agent_sync/commands/integrate.py` | `cmd_integrate()`: rebase + guarded merge to target branch |
| `agent_sync/commands/memory_sync.py` | `cmd_memory_sync()`: distill events/HANDOFF into memory/notes/ |
| `agent_sync/cli.py` | Wire all new subcommands |
| `tests/test_agent_sync_routing_test.py` | Routing score, agent selection |
| `tests/test_agent_sync_dispatch_test.py` | Manifest loading, fan-out, claim collision |
| `tests/test_agent_sync_integration_test.py` | Integrate gate: rebase, validation, merge |

---

## Task 1: Task routing + agent scoring

**Files:**
- Create: `agent_sync/routing.py`
- Create: `tests/test_agent_sync_routing_test.py`

Routing is conservative: if the user specifies an agent in the manifest, use it.
If the manifest says `agent: auto`, score available agents by declared capabilities
and current load (runs with status='active').

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_routing_test.py
import sqlite3
from pathlib import Path

import pytest

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.routing import select_agent, AgentCapability


def _fresh_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    for name, binary in [("claude", "claude"), ("codex", "codex"), ("gemini", "gemini")]:
        conn.execute(
            "INSERT INTO agents (agent_name, binary_name) VALUES (?, ?)", (name, binary)
        )
    conn.commit()
    return conn


def test_select_agent_explicit_returns_that_agent(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    result = select_agent(
        conn=conn,
        preferred="codex",
        capabilities_required=frozenset(),
    )
    assert result == "codex"


def test_select_agent_auto_prefers_least_loaded(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    # Simulate claude having an active run
    conn.execute(
        """
        INSERT INTO tasks (task_id, title, description, status)
        VALUES ('T-LOAD', 'Load test', '', 'in_progress')
        """
    )
    conn.execute(
        """
        INSERT INTO runs (run_id, task_id, agent_name, worktree_path, status)
        VALUES ('R-LOAD', 'T-LOAD', 'claude', '/tmp/x', 'active')
        """
    )
    conn.commit()
    result = select_agent(
        conn=conn,
        preferred="auto",
        capabilities_required=frozenset(),
    )
    # codex or gemini — not claude (which is busy)
    assert result != "claude"


def test_select_agent_unknown_explicit_raises(tmp_path: Path) -> None:
    conn = _fresh_db(tmp_path)
    with pytest.raises(ValueError, match="Unknown agent"):
        select_agent(conn=conn, preferred="gpt5", capabilities_required=frozenset())
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_agent_sync_routing_test.py -v --tb=short
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `agent_sync/routing.py`**

```python
from __future__ import annotations

import sqlite3
from enum import Enum
from typing import FrozenSet


class AgentCapability(str, Enum):
    CODE_WRITE = "code_write"
    CODE_REVIEW = "code_review"
    TEST_GENERATE = "test_generate"
    DOC_WRITE = "doc_write"
    LOCAL_ONLY = "local_only"


# Static capability declarations per agent.
_AGENT_CAPABILITIES: dict[str, frozenset[AgentCapability]] = {
    "claude": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.CODE_REVIEW,
        AgentCapability.TEST_GENERATE,
        AgentCapability.DOC_WRITE,
    }),
    "codex": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.TEST_GENERATE,
    }),
    "gemini": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.CODE_REVIEW,
        AgentCapability.DOC_WRITE,
    }),
    "local": frozenset({
        AgentCapability.CODE_WRITE,
        AgentCapability.TEST_GENERATE,
        AgentCapability.LOCAL_ONLY,
    }),
}


def select_agent(
    *,
    conn: sqlite3.Connection,
    preferred: str,
    capabilities_required: FrozenSet[AgentCapability],
) -> str:
    """Return the best agent name for a task.

    If preferred is not 'auto', validate it exists and has required capabilities.
    If preferred is 'auto', pick the least-loaded agent that satisfies requirements.
    """
    known = {
        r["agent_name"]
        for r in conn.execute("SELECT agent_name FROM agents").fetchall()
    }

    if preferred != "auto":
        if preferred not in known:
            raise ValueError(
                f"Unknown agent '{preferred}'. Registered: {sorted(known)}"
            )
        agent_caps = _AGENT_CAPABILITIES.get(preferred, frozenset())
        missing = capabilities_required - agent_caps
        if missing:
            raise ValueError(
                f"Agent '{preferred}' lacks required capabilities: "
                f"{[c.value for c in missing]}"
            )
        return preferred

    # Auto: count active runs per agent, prefer least loaded.
    load: dict[str, int] = {name: 0 for name in known}
    for row in conn.execute(
        "SELECT agent_name, COUNT(*) AS n FROM runs WHERE status = 'active' GROUP BY agent_name"
    ).fetchall():
        load[row["agent_name"]] = row["n"]

    candidates = [
        name
        for name in known
        if capabilities_required <= _AGENT_CAPABILITIES.get(name, frozenset())
    ]
    if not candidates:
        raise ValueError(
            f"No registered agent satisfies capabilities: "
            f"{[c.value for c in capabilities_required]}"
        )

    return min(candidates, key=lambda n: (load.get(n, 0), n))
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agent_sync_routing_test.py -v --tb=short
```
Expected: All 3 pass.

- [ ] **Step 5: Commit**

```bash
git add agent_sync/routing.py tests/test_agent_sync_routing_test.py
git commit -m "feat(agent_sync): add agent routing/scoring module"
```

---

## Task 2: Dispatch manifest schema + loader

**Files:**
- Create: `agent_sync/manifests/__init__.py`
- Create: `agent_sync/manifests/schema.py`
- Create: `tests/test_agent_sync_dispatch_test.py`

A manifest is a YAML file the primary agent writes to `agent_sync/manifests/`.
Each subtask in the manifest specifies its ID, scope (file paths/globs), target
agent, and an acceptance command to run before integration.

Example manifest:

```yaml
# agent_sync/manifests/refactor-auth.yaml
task_id: T002
title: "Refactor auth module"
description: "Split monolithic auth.py into sub-modules"
target_branch: main
subtasks:
  - id: T002-1
    title: "Extract token handling"
    description: "Move token logic to auth/tokens.py"
    agent: codex
    scope:
      - src/auth.py
      - src/auth/tokens.py
    acceptance: "uv run pytest tests/test_auth_test.py -v --tb=short"
  - id: T002-2
    title: "Code review"
    description: "Review T002-1 branch for correctness and style"
    agent: gemini
    depends_on: [T002-1]
    readonly: true
    acceptance: null
```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_sync_dispatch_test.py
import textwrap
from pathlib import Path

import pytest

from agent_sync.manifests.schema import DispatchManifest, SubtaskSpec, load_manifest


SAMPLE_MANIFEST = textwrap.dedent("""\
    task_id: T002
    title: "Refactor auth"
    description: "Split auth.py"
    target_branch: main
    subtasks:
      - id: T002-1
        title: "Extract tokens"
        description: "Move token logic"
        agent: codex
        scope:
          - src/auth.py
        acceptance: "pytest tests/ -v"
      - id: T002-2
        title: "Review"
        description: "Review T002-1"
        agent: gemini
        depends_on: [T002-1]
        readonly: true
        acceptance: null
""")


def test_load_manifest_parses_structure(tmp_path: Path) -> None:
    mf = tmp_path / "refactor.yaml"
    mf.write_text(SAMPLE_MANIFEST, encoding="utf-8")

    manifest = load_manifest(mf)
    assert manifest.task_id == "T002"
    assert len(manifest.subtasks) == 2
    assert manifest.subtasks[0].agent == "codex"
    assert manifest.subtasks[1].readonly is True
    assert manifest.subtasks[1].depends_on == ["T002-1"]


def test_load_manifest_missing_required_field_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("title: Missing task_id\nsubtasks: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="task_id"):
        load_manifest(bad)


def test_subtask_without_scope_is_valid(tmp_path: Path) -> None:
    mf = tmp_path / "m.yaml"
    mf.write_text(
        "task_id: T003\ntitle: T\ndescription: D\ntarget_branch: main\n"
        "subtasks:\n  - id: T003-1\n    title: T\n    description: D\n"
        "    agent: claude\n    acceptance: null\n",
        encoding="utf-8",
    )
    manifest = load_manifest(mf)
    assert manifest.subtasks[0].scope == []
```

- [ ] **Step 2: Add `pyyaml` to pyproject.toml**

```toml
# In [project] dependencies or [tool.uv] dependencies:
dependencies = [
    "pyyaml>=6.0",
]
```

Run: `uv sync`

- [ ] **Step 3: Write `agent_sync/manifests/__init__.py`**

```python
```

- [ ] **Step 4: Write `agent_sync/manifests/schema.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SubtaskSpec:
    id: str
    title: str
    description: str
    agent: str
    scope: list[str] = field(default_factory=list)
    acceptance: str | None = None
    depends_on: list[str] = field(default_factory=list)
    readonly: bool = False


@dataclass
class DispatchManifest:
    task_id: str
    title: str
    description: str
    target_branch: str
    subtasks: list[SubtaskSpec]


def load_manifest(path: Path) -> DispatchManifest:
    """Load and validate a dispatch manifest YAML file."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    for required_key in ("task_id", "title", "description", "subtasks"):
        if required_key not in raw:
            raise ValueError(
                f"Manifest {path} missing required field '{required_key}'"
            )

    subtasks: list[SubtaskSpec] = []
    for item in raw.get("subtasks", []):
        for st_key in ("id", "title", "description", "agent"):
            if st_key not in item:
                raise ValueError(
                    f"Subtask in {path} missing required field '{st_key}'"
                )
        subtasks.append(
            SubtaskSpec(
                id=item["id"],
                title=item["title"],
                description=item["description"],
                agent=item["agent"],
                scope=item.get("scope") or [],
                acceptance=item.get("acceptance"),
                depends_on=item.get("depends_on") or [],
                readonly=bool(item.get("readonly", False)),
            )
        )

    return DispatchManifest(
        task_id=raw["task_id"],
        title=raw["title"],
        description=raw["description"],
        target_branch=raw.get("target_branch", "main"),
        subtasks=subtasks,
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_agent_sync_dispatch_test.py -v --tb=short
```
Expected: All 3 pass.

- [ ] **Step 6: Commit**

```bash
git add agent_sync/manifests/ tests/test_agent_sync_dispatch_test.py pyproject.toml
git commit -m "feat(agent_sync): add DispatchManifest schema and YAML loader"
```

---

## Task 3: `agent-sync dispatch` command — fan-out

**Files:**
- Create: `agent_sync/commands/dispatch_cmd.py`
- Modify: `agent_sync/cli.py`
- Modify: `tests/test_agent_sync_dispatch_test.py`

`agent-sync dispatch -m manifests/refactor-auth.yaml` fans out child tasks:
1. Validate all scope paths against existing claims (fail fast on collision).
2. For each subtask (respecting `depends_on` ordering), create worktrees, acquire
   claims, start runs, and launch agents.
3. Non-readonly subtasks run concurrently in separate worktrees unless they have
   `depends_on` ordering constraints.
4. Write a `TASKS/<task-id>/STATUS.md` table that can be polled for progress.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_agent_sync_dispatch_test.py`:

```python
import sqlite3
from unittest.mock import MagicMock, patch

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.commands.dispatch_cmd import cmd_dispatch
from agent_sync.manifests.schema import load_manifest


def _init_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    for name, binary in [("codex", "codex"), ("gemini", "gemini")]:
        conn.execute(
            "INSERT INTO agents (agent_name, binary_name) VALUES (?, ?)", (name, binary)
        )
    conn.commit()
    return conn


def test_dispatch_creates_subtask_runs(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    mf_path = tmp_path / "agent_sync" / "manifests" / "t002.yaml"
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(SAMPLE_MANIFEST, encoding="utf-8")

    with patch("agent_sync.commands.dispatch_cmd.subprocess.Popen") as mock_popen, \
         patch("agent_sync.commands.dispatch_cmd.create_worktree") as mock_wt:
        mock_popen.return_value = MagicMock(pid=1234)
        mock_wt.side_effect = lambda **kw: tmp_path / ".agent_sync" / kw["task_id"]

        cmd_dispatch(
            manifest_path=mf_path,
            repo_root=tmp_path,
            conn=conn,
            wait=False,
        )

    # Both subtasks should have runs
    runs = conn.execute("SELECT task_id, agent_name, status FROM runs").fetchall()
    task_ids = {r["task_id"] for r in runs}
    assert "T002-1" in task_ids


def test_dispatch_claim_collision_raises(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    # Pre-acquire a claim on src/auth.py
    conn.execute(
        "INSERT INTO tasks (task_id, title, description, status) VALUES ('TPRE', 'Pre', '', 'in_progress')"
    )
    conn.execute(
        "INSERT INTO runs (run_id, task_id, agent_name, worktree_path, status) VALUES ('RPRE', 'TPRE', 'codex', '/tmp', 'active')"
    )
    conn.execute(
        "INSERT INTO claims (claim_id, run_id, path, access_mode) VALUES ('CPRE', 'RPRE', 'src/auth.py', 'write')"
    )
    conn.commit()

    mf_path = tmp_path / "agent_sync" / "manifests" / "t002.yaml"
    mf_path.parent.mkdir(parents=True, exist_ok=True)
    mf_path.write_text(SAMPLE_MANIFEST, encoding="utf-8")

    from agent_sync.state.claims import ClaimConflictError
    with pytest.raises(ClaimConflictError):
        cmd_dispatch(
            manifest_path=mf_path,
            repo_root=tmp_path,
            conn=conn,
            wait=False,
        )
```

- [ ] **Step 2: Write `agent_sync/commands/dispatch_cmd.py`**

```python
from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

from agent_sync.adapters.base import AgentAdapter
from agent_sync.adapters.claude import ClaudeAdapter
from agent_sync.adapters.codex import CodexAdapter
from agent_sync.adapters.gemini import GeminiAdapter
from agent_sync.adapters.local import LocalWorkerAdapter
from agent_sync.docs_gen.renderer import render_session_brief
from agent_sync.manifests.schema import DispatchManifest, SubtaskSpec, load_manifest
from agent_sync.routing import select_agent
from agent_sync.state.claims import acquire_claims
from agent_sync.state.runs import start_run
from agent_sync.state.tasks import create_task, get_task
from agent_sync.worktree import create_worktree

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "local": LocalWorkerAdapter,
}


def _launch_subtask(
    *,
    subtask: SubtaskSpec,
    manifest: DispatchManifest,
    repo_root: Path,
    conn: sqlite3.Connection,
) -> subprocess.Popen | None:
    agent_name = select_agent(
        conn=conn,
        preferred=subtask.agent,
        capabilities_required=frozenset(),
    )

    task = get_task(conn, subtask.id)
    if task is None:
        create_task(
            conn,
            task_id=subtask.id,
            title=subtask.title,
            description=subtask.description,
        )

    worktree_path = create_worktree(
        repo_root=repo_root,
        task_id=subtask.id,
        agent_name=agent_name,
    )

    run = start_run(
        conn,
        task_id=subtask.id,
        agent_name=agent_name,
        worktree_path=str(worktree_path),
    )

    # Acquire file claims (write unless readonly).
    if subtask.scope:
        access_mode = "read" if subtask.readonly else "write"
        acquire_claims(
            conn,
            run_id=run.run_id,
            paths=subtask.scope,
            access_mode=access_mode,
        )

    # Write SESSION_BRIEF into the worktree docs dir.
    docs_dir = repo_root / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    brief_md = render_session_brief(
        task_id=subtask.id,
        task_title=subtask.title,
        task_description=subtask.description,
        run_id=run.run_id,
        agent_name=agent_name,
        worktree_path=str(worktree_path),
    )
    (docs_dir / f"SESSION_BRIEF_{subtask.id}.md").write_text(brief_md, encoding="utf-8")

    if isinstance(_ADAPTERS.get(agent_name), type) and agent_name == "local":
        local_adapter = LocalWorkerAdapter(repo_root=repo_root)
        local_adapter.enqueue(
            task_id=subtask.id,
            prompt=subtask.description,
            metadata={"worktree": str(worktree_path)},
        )
        return None

    adapter = _ADAPTERS[agent_name](repo_root=repo_root)
    prompt = (
        f"You are working on subtask {subtask.id}: {subtask.title}. "
        f"Read agent_sync/docs/SESSION_BRIEF_{subtask.id}.md for context. "
        f"Scope: {subtask.scope or 'unrestricted'}. "
        f"Acceptance command: {subtask.acceptance or 'none'}."
    )
    args = adapter.launch_args(prompt=prompt, task_id=subtask.id)
    logger.info("Dispatching subtask %s to %s", subtask.id, agent_name)
    return subprocess.Popen(args, cwd=str(worktree_path))


def cmd_dispatch(
    *,
    manifest_path: Path,
    repo_root: Path,
    conn: sqlite3.Connection,
    wait: bool = True,
) -> None:
    """Fan out subtasks from a manifest into parallel agent runs."""
    manifest = load_manifest(manifest_path)

    # Pre-validate all scopes against existing claims before launching anything.
    # This prevents partial fan-out where some tasks start and some fail.
    from agent_sync.state.claims import check_conflicts
    for subtask in manifest.subtasks:
        if subtask.scope and not subtask.readonly:
            check_conflicts(conn, paths=subtask.scope, access_mode="write")

    # Topological dispatch: tasks with no depends_on first, then dependents.
    dispatched: set[str] = set()
    processes: list[subprocess.Popen] = []

    # Simple two-pass: independent tasks, then dependents.
    independent = [st for st in manifest.subtasks if not st.depends_on]
    dependent = [st for st in manifest.subtasks if st.depends_on]

    for subtask in independent:
        proc = _launch_subtask(
            subtask=subtask,
            manifest=manifest,
            repo_root=repo_root,
            conn=conn,
        )
        if proc:
            processes.append(proc)
        dispatched.add(subtask.id)

    for subtask in dependent:
        missing = [d for d in subtask.depends_on if d not in dispatched]
        if missing:
            logger.warning(
                "Subtask %s depends on %s which were not dispatched — skipping.",
                subtask.id, missing,
            )
            continue
        proc = _launch_subtask(
            subtask=subtask,
            manifest=manifest,
            repo_root=repo_root,
            conn=conn,
        )
        if proc:
            processes.append(proc)
        dispatched.add(subtask.id)

    if wait:
        for proc in processes:
            proc.wait()
        logger.info("All dispatched subtasks completed.")
    else:
        logger.info("Dispatched %d subtask(s). Not waiting for completion.", len(dispatched))
```

- [ ] **Step 3: Wire `dispatch` into `agent_sync/cli.py`**

```python
from agent_sync.commands.dispatch_cmd import cmd_dispatch

p_dispatch = sub.add_parser("dispatch", help="Fan out child tasks from a manifest")
p_dispatch.add_argument("-m", "--manifest", required=True,
                        help="Path to dispatch manifest YAML")
p_dispatch.add_argument("--no-wait", action="store_true",
                        help="Return immediately after launching without waiting")

# In dispatch():
elif args.command == "dispatch":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_dispatch(
        manifest_path=Path(args.manifest),
        repo_root=repo_root,
        conn=conn,
        wait=not args.no_wait,
    )
```

- [ ] **Step 4: Run dispatch tests**

```bash
uv run pytest tests/test_agent_sync_dispatch_test.py -v --tb=short
```
Expected: All 5 tests pass (3 from Task 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add agent_sync/commands/dispatch_cmd.py agent_sync/cli.py \
    tests/test_agent_sync_dispatch_test.py
git commit -m "feat(agent_sync): implement agent-sync dispatch (parallel fan-out)"
```

---

## Task 4: `agent-sync review` command

**Files:**
- Create: `agent_sync/commands/review.py`
- Modify: `agent_sync/cli.py`

`agent-sync review -t T002-1 -a gemini` launches a reviewer agent against the
task's worktree branch in readonly mode. The reviewer gets a brief explaining its
role and the acceptance criteria.

- [ ] **Step 1: Write failing test**

```python
# In tests/test_agent_sync_dispatch_test.py — append:

from agent_sync.commands.review import cmd_review
from agent_sync.state.tasks import create_task
from agent_sync.state.runs import start_run, end_run


def test_review_launches_readonly_agent(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)
    conn.execute(
        "INSERT OR IGNORE INTO agents (agent_name, binary_name) VALUES ('gemini', 'gemini')"
    )
    conn.commit()

    create_task(conn, task_id="T002-1", title="Extract tokens", description="OAuth logic")
    run = start_run(conn, task_id="T002-1", agent_name="codex",
                    worktree_path=str(tmp_path))
    end_run(conn, run_id=run.run_id, status="completed")

    with patch("agent_sync.commands.review.subprocess.run") as mock_run, \
         patch("agent_sync.commands.review.create_worktree") as mock_wt:
        mock_run.return_value = MagicMock(returncode=0)
        mock_wt.return_value = tmp_path / ".agent_sync" / "review-T002-1"

        cmd_review(
            task_id="T002-1",
            reviewer_agent="gemini",
            acceptance_cmd=None,
            repo_root=tmp_path,
            conn=conn,
        )

    # A review run should exist
    rows = conn.execute(
        "SELECT agent_name, status FROM runs WHERE task_id = 'T002-1' AND agent_name = 'gemini'"
    ).fetchall()
    assert len(rows) == 1
```

- [ ] **Step 2: Write `agent_sync/commands/review.py`**

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
from agent_sync.state.runs import start_run
from agent_sync.worktree import create_worktree

logger = logging.getLogger(__name__)

_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
}


def cmd_review(
    *,
    task_id: str,
    reviewer_agent: str,
    acceptance_cmd: str | None,
    repo_root: Path,
    conn: sqlite3.Connection,
) -> None:
    """Launch a reviewer agent against a task's branch in readonly mode."""
    adapter_cls = _ADAPTERS.get(reviewer_agent)
    if adapter_cls is None:
        raise ValueError(f"Unknown reviewer agent '{reviewer_agent}'")
    adapter = adapter_cls(repo_root=repo_root)

    task_row = conn.execute(
        "SELECT title, description FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    title = task_row["title"] if task_row else task_id

    worktree_path = create_worktree(
        repo_root=repo_root,
        task_id=task_id,
        agent_name=reviewer_agent,
    )

    run = start_run(
        conn,
        task_id=task_id,
        agent_name=reviewer_agent,
        worktree_path=str(worktree_path),
    )

    acceptance_line = (
        f"After reviewing, run: `{acceptance_cmd}` and report the result."
        if acceptance_cmd
        else "No acceptance command specified. Report findings only."
    )
    prompt = (
        f"You are reviewing task {task_id}: {title}. "
        f"You are in READONLY mode — do not modify any files. "
        f"Review the code in this worktree for correctness, security, and style. "
        f"{acceptance_line}"
    )
    args = adapter.launch_args(prompt=prompt, task_id=task_id)
    logger.info("Launching reviewer %s for task %s", reviewer_agent, task_id)
    subprocess.run(args, cwd=str(worktree_path), check=False)
```

- [ ] **Step 3: Wire `review` into `agent_sync/cli.py`**

```python
from agent_sync.commands.review import cmd_review

p_review = sub.add_parser("review", help="Launch reviewer agent against task branch")
p_review.add_argument("-t", "--task-id", required=True, help="Task ID to review")
p_review.add_argument("-a", "--agent", required=True,
                      choices=["claude", "codex", "gemini"],
                      help="Reviewer agent")
p_review.add_argument("--acceptance", default=None,
                      help="Acceptance command for the reviewer to run")

# In dispatch():
elif args.command == "review":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_review(
        task_id=args.task_id,
        reviewer_agent=args.agent,
        acceptance_cmd=args.acceptance,
        repo_root=repo_root,
        conn=conn,
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agent_sync_dispatch_test.py -v --tb=short
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add agent_sync/commands/review.py agent_sync/cli.py \
    tests/test_agent_sync_dispatch_test.py
git commit -m "feat(agent_sync): implement agent-sync review command"
```

---

## Task 5: `agent-sync integrate` — integration gate

**Files:**
- Create: `agent_sync/commands/integrate.py`
- Modify: `agent_sync/cli.py`
- Modify: `tests/test_agent_sync_integration_test.py`

The integration gate is the only place merges happen. It:
1. Verifies no active runs exist for the task (all agents have stopped).
2. Rebases the task worktree branch onto the target branch.
3. Runs the acceptance command (if any) in the worktree.
4. If acceptance passes: `git merge --no-ff --no-commit` into the target branch,
   then validates again, then creates the merge commit.
5. Removes the task worktrees and releases all claims.
6. Never calls `git push` — that is the user's explicit action.

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_sync_integration_test.py`:

```python
from agent_sync.commands.integrate import cmd_integrate, IntegrationError


def test_integrate_fails_if_active_run_exists(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    from agent_sync.state.tasks import create_task
    from agent_sync.state.runs import start_run

    create_task(conn, task_id="T005", title="Open task", description="")
    start_run(conn, task_id="T005", agent_name="claude",
              worktree_path=str(tmp_path))

    with pytest.raises(IntegrationError, match="active run"):
        cmd_integrate(
            task_id="T005",
            target_branch="main",
            acceptance_cmd=None,
            repo_root=tmp_path,
            conn=conn,
            dry_run=True,
        )


def test_integrate_dry_run_does_not_merge(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    from agent_sync.state.tasks import create_task
    from agent_sync.state.runs import start_run, end_run

    create_task(conn, task_id="T006", title="Done task", description="")
    run = start_run(conn, task_id="T006", agent_name="claude",
                    worktree_path=str(tmp_path))
    end_run(conn, run_id=run.run_id, status="completed")

    with patch("agent_sync.commands.integrate.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        cmd_integrate(
            task_id="T006",
            target_branch="main",
            acceptance_cmd="echo ok",
            repo_root=tmp_path,
            conn=conn,
            dry_run=True,
        )
        # No git merge should have been called in dry-run
        merge_calls = [
            c for c in mock_run.call_args_list
            if "merge" in str(c)
        ]
        assert len(merge_calls) == 0
```

- [ ] **Step 2: Write `agent_sync/commands/integrate.py`**

```python
from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class IntegrationError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
        encoding="utf-8",
    )


def cmd_integrate(
    *,
    task_id: str,
    target_branch: str,
    acceptance_cmd: str | None,
    repo_root: Path,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> None:
    """Rebase, validate, and merge a completed task branch into target_branch."""
    # 1. Verify no active runs.
    active = conn.execute(
        "SELECT run_id FROM runs WHERE task_id = ? AND status = 'active'",
        (task_id,),
    ).fetchone()
    if active:
        raise IntegrationError(
            f"Task {task_id} has an active run ({active['run_id']}). "
            "Stop all agents before integrating."
        )

    # 2. Find the task worktree.
    run_row = conn.execute(
        """
        SELECT worktree_path
        FROM runs
        WHERE task_id = ? AND status = 'completed'
        ORDER BY ended_at DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()

    if not run_row:
        raise IntegrationError(f"No completed run found for task {task_id}.")

    worktree_path = Path(run_row["worktree_path"])
    if not worktree_path.exists():
        raise IntegrationError(
            f"Worktree path {worktree_path} no longer exists. "
            "It may have been removed already."
        )

    # 3. Get the branch name for this worktree.
    result = _run(["git", "branch", "--show-current"], cwd=worktree_path)
    task_branch = result.stdout.strip()
    if not task_branch:
        raise IntegrationError(f"Could not determine branch in {worktree_path}.")

    logger.info("Integrating branch '%s' → '%s'", task_branch, target_branch)

    if dry_run:
        logger.info("[dry-run] Would rebase %s onto %s", task_branch, target_branch)
        if acceptance_cmd:
            logger.info("[dry-run] Would run acceptance: %s", acceptance_cmd)
        logger.info("[dry-run] Would merge --no-ff into %s", target_branch)
        return

    # 4. Rebase onto target.
    logger.info("Rebasing onto %s...", target_branch)
    _run(["git", "rebase", target_branch], cwd=worktree_path)

    # 5. Run acceptance command.
    if acceptance_cmd:
        logger.info("Running acceptance: %s", acceptance_cmd)
        result = _run(
            ["sh", "-c", acceptance_cmd],
            cwd=worktree_path,
            check=False,
        )
        if result.returncode != 0:
            raise IntegrationError(
                f"Acceptance command failed (exit {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        logger.info("Acceptance passed.")

    # 6. Merge into target branch in the main repo.
    logger.info("Merging %s → %s (--no-ff --no-commit)", task_branch, target_branch)
    _run(["git", "checkout", target_branch], cwd=repo_root)
    _run(["git", "merge", "--no-ff", "--no-commit", task_branch], cwd=repo_root)

    # 7. Re-run acceptance against the merged (uncommitted) state.
    if acceptance_cmd:
        result = _run(
            ["sh", "-c", acceptance_cmd],
            cwd=repo_root,
            check=False,
        )
        if result.returncode != 0:
            _run(["git", "merge", "--abort"], cwd=repo_root)
            raise IntegrationError(
                f"Post-merge acceptance failed. Merge aborted.\n"
                f"{result.stdout}\n{result.stderr}"
            )

    # 8. Create the merge commit.
    task_row = conn.execute(
        "SELECT title FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    title = task_row["title"] if task_row else task_id
    commit_msg = f"Merge task {task_id}: {title}\n\nIntegrated via agent-sync integrate."
    _run(["git", "commit", "-m", commit_msg], cwd=repo_root)
    logger.info("Merge commit created on %s.", target_branch)

    # 9. Release all claims for this task.
    run_ids = [
        r["run_id"]
        for r in conn.execute(
            "SELECT run_id FROM runs WHERE task_id = ?", (task_id,)
        ).fetchall()
    ]
    for rid in run_ids:
        conn.execute(
            "UPDATE claims SET released_at = datetime('now') WHERE run_id = ? AND released_at IS NULL",
            (rid,),
        )
    conn.commit()
    logger.info("Released claims for %d run(s).", len(run_ids))

    # 10. Remove worktrees.
    from agent_sync.worktree import remove_worktree
    remove_worktree(repo_root=repo_root, worktree_path=worktree_path)
    logger.info("Removed worktree %s.", worktree_path)
```

- [ ] **Step 3: Wire `integrate` into `agent_sync/cli.py`**

```python
from agent_sync.commands.integrate import cmd_integrate

p_integrate = sub.add_parser("integrate", help="Rebase + guarded merge to target branch")
p_integrate.add_argument("-t", "--task-id", required=True, help="Task ID to integrate")
p_integrate.add_argument("--target", "-b", default="main",
                         help="Target branch (default: main)")
p_integrate.add_argument("--acceptance", "-c", default=None,
                         help="Acceptance command that must pass before merge")
p_integrate.add_argument("-n", "--dry-run", action="store_true",
                         help="Show what would happen without making changes")

# In dispatch():
elif args.command == "integrate":
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    cmd_integrate(
        task_id=args.task_id,
        target_branch=args.target,
        acceptance_cmd=args.acceptance,
        repo_root=repo_root,
        conn=conn,
        dry_run=args.dry_run,
    )
```

- [ ] **Step 4: Run integration tests**

```bash
uv run pytest tests/test_agent_sync_integration_test.py -v --tb=short
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add agent_sync/commands/integrate.py agent_sync/cli.py \
    tests/test_agent_sync_integration_test.py
git commit -m "feat(agent_sync): implement agent-sync integrate (guarded merge gate)"
```

---

## Task 6: `agent-sync memory sync` command

**Files:**
- Create: `agent_sync/commands/memory_sync.py`
- Modify: `agent_sync/cli.py`

`agent-sync memory sync -t T001` distills the run event log and HANDOFF.md into
a candidate markdown file in `memory/review/` for human review. It never writes
directly to `memory_items`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent_sync_integration_test.py`:

```python
from agent_sync.commands.memory_sync import cmd_memory_sync


def test_memory_sync_writes_candidate_file(tmp_path: Path) -> None:
    conn = _init_db(tmp_path)

    from agent_sync.state.tasks import create_task
    from agent_sync.state.runs import start_run, end_run

    create_task(conn, task_id="T010", title="Config parser", description="Parse TOML")
    run = start_run(conn, task_id="T010", agent_name="claude",
                    worktree_path=str(tmp_path))

    conn.execute(
        "INSERT INTO events (run_id, event_type, path, payload) VALUES (?, 'file_written', ?, '{}')",
        (run.run_id, "src/config.py"),
    )
    conn.commit()
    end_run(conn, run_id=run.run_id, status="completed")

    docs_dir = tmp_path / "agent_sync" / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "HANDOFF.md").write_text("# Handoff T010\nParsed TOML config.\n",
                                          encoding="utf-8")

    review_dir = tmp_path / "memory" / "review"
    cmd_memory_sync(task_id="T010", repo_root=tmp_path, conn=conn,
                    review_dir=review_dir)

    candidates = list(review_dir.glob("*.candidate.md"))
    assert len(candidates) == 1
    content = candidates[0].read_text(encoding="utf-8")
    assert "T010" in content
    assert "Config parser" in content
    assert "src/config.py" in content
```

- [ ] **Step 2: Write `agent_sync/commands/memory_sync.py`**

```python
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def cmd_memory_sync(
    *,
    task_id: str,
    repo_root: Path,
    conn: sqlite3.Connection,
    review_dir: Path | None = None,
) -> Path:
    """Distill run events and HANDOFF.md into a memory/review/ candidate file."""
    if review_dir is None:
        review_dir = repo_root / "memory" / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    task_row = conn.execute(
        "SELECT title, description, status FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    if not task_row:
        raise ValueError(f"Task {task_id} not found in DB.")

    runs = conn.execute(
        "SELECT run_id, agent_name, started_at, ended_at, status FROM runs WHERE task_id = ? ORDER BY started_at",
        (task_id,),
    ).fetchall()

    file_events = conn.execute(
        """
        SELECT DISTINCT e.path
        FROM events e
        JOIN runs r ON e.run_id = r.run_id
        WHERE r.task_id = ? AND e.event_type = 'file_written' AND e.path IS NOT NULL
        ORDER BY e.created_at
        """,
        (task_id,),
    ).fetchall()
    written_paths = [r["path"] for r in file_events]

    handoff_path = repo_root / "agent_sync" / "docs" / "HANDOFF.md"
    handoff_content = ""
    if handoff_path.exists():
        handoff_content = handoff_path.read_text(encoding="utf-8")

    runs_summary = "\n".join(
        f"- {r['agent_name']}: {r['status']} ({r['started_at']} → {r['ended_at'] or 'running'})"
        for r in runs
    )
    files_summary = "\n".join(f"- `{p}`" for p in written_paths) or "_none recorded_"

    slug = task_id.lower().replace(" ", "-")
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    candidate_path = review_dir / f"{date_str}-{slug}.candidate.md"

    content = f"""---
kind: session_summary
task_id: {task_id}
generated_at: {datetime.now(tz=timezone.utc).isoformat()}
---

# Session Summary — {task_id}: {task_row['title']}

## Task

{task_row['description']}

## Agent Runs

{runs_summary}

## Files Modified

{files_summary}

## Final Handoff Notes

{handoff_content or "_No HANDOFF.md found._"}

---
_Candidate file — review and promote with `memory/promote_candidate.py` before use._
"""

    candidate_path.write_text(content, encoding="utf-8")
    logger.info("Wrote candidate file: %s", candidate_path)
    return candidate_path
```

- [ ] **Step 3: Wire `memory sync` into `agent_sync/cli.py`**

```python
from agent_sync.commands.memory_sync import cmd_memory_sync

p_memory = sub.add_parser("memory", help="Memory sync utilities")
p_memory_sub = p_memory.add_subparsers(dest="memory_command")
p_mem_sync = p_memory_sub.add_parser("sync", help="Distill run state into memory/review/")
p_mem_sync.add_argument("-t", "--task-id", required=True, help="Task ID")

# In dispatch():
elif args.command == "memory":
    if args.memory_command == "sync":
        db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
        conn = get_connection(db_path)
        cmd_memory_sync(task_id=args.task_id, repo_root=repo_root, conn=conn)
    else:
        print("Usage: agent-sync memory sync -t <task-id>")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agent_sync_integration_test.py::test_memory_sync_writes_candidate_file -v --tb=short
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_sync/commands/memory_sync.py agent_sync/cli.py \
    tests/test_agent_sync_integration_test.py
git commit -m "feat(agent_sync): implement agent-sync memory sync command"
```

---

## Task 7: Full suite + pyproject.toml + package installation

**Files:**
- Create or modify: `agent_sync/pyproject.toml` (or root `pyproject.toml`)

- [ ] **Step 1: Verify `agent_sync` is importable as a module**

```bash
uv run python -c "import agent_sync; print(agent_sync.__version__)"
```

If the import fails, check that `agent_sync/__init__.py` exists with `__version__`.

- [ ] **Step 2: Add CLI entry point in pyproject.toml**

In the project's `pyproject.toml` (root level), add the `agent-sync` console script:

```toml
[project.scripts]
agent-sync = "agent_sync.cli:main"
```

Then install in editable mode:

```bash
uv pip install -e .
```

- [ ] **Step 3: Verify CLI works**

```bash
agent-sync --help
agent-sync init --help
agent-sync start --help
agent-sync handoff --help
agent-sync resume --help
agent-sync dispatch --help
agent-sync review --help
agent-sync integrate --help
agent-sync doctor --help
agent-sync memory sync --help
```
Expected: All subcommands show help without errors.

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest tests/ -k "agent_sync" -v --tb=short
```
Expected: All pass.

- [ ] **Step 5: Type check**

```bash
uv run mypy agent_sync/ --strict --ignore-missing-imports
```
Fix any errors.

- [ ] **Step 6: Lint and format**

```bash
uv run ruff check --fix agent_sync/
uv run black agent_sync/
```

- [ ] **Step 7: Bump version in pyproject.toml**

```toml
[project]
version = "0.3.0"  # Phase 3 complete
```

- [ ] **Step 8: Final commit**

```bash
git add pyproject.toml agent_sync/
git commit -m "feat(agent_sync): Phase 3 complete — parallel dispatch, review, integrate, memory sync"
```

---

## Phase 3 Definition of Done

- [ ] `select_agent()` correctly scores and selects the least-loaded capable agent
- [ ] `load_manifest()` validates YAML and produces `DispatchManifest` with subtask specs
- [ ] `agent-sync dispatch -m <manifest>` fans out subtasks with claim conflict pre-check
- [ ] Claim collision on overlapping write scopes raises `ClaimConflictError` before any agent launches
- [ ] `agent-sync review -t <id> -a <agent>` launches reviewer in readonly mode
- [ ] `agent-sync integrate -t <id>` blocks on active runs, rebases, runs acceptance, merges `--no-ff`
- [ ] `agent-sync integrate --dry-run` reports what would happen without modifying git state
- [ ] `agent-sync memory sync -t <id>` writes a `.candidate.md` to `memory/review/` — never to `memory_items` directly
- [ ] `agent-sync --help` and all subcommand `--help` output is correct
- [ ] All agent_sync tests pass: `uv run pytest tests/ -k "agent_sync" -v --tb=short`
- [ ] `uv run mypy agent_sync/ --strict --ignore-missing-imports` is clean

---

## End-to-End Parallel Workflow Example

```bash
# 1. Initialize the module
agent-sync init

# 2. Write a manifest for a parallel refactor
cat > agent_sync/manifests/refactor-auth.yaml << 'EOF'
task_id: T002
title: "Refactor auth module"
description: "Split monolithic auth.py into sub-modules"
target_branch: main
subtasks:
  - id: T002-1
    title: "Extract token handling"
    description: "Move token logic to auth/tokens.py"
    agent: codex
    scope:
      - src/auth.py
      - src/auth/tokens.py
    acceptance: "uv run pytest tests/test_auth_test.py -v --tb=short"
  - id: T002-2
    title: "Code review"
    description: "Review T002-1 branch for correctness and style"
    agent: gemini
    depends_on: [T002-1]
    readonly: true
    acceptance: null
EOF

# 3. Fan out child tasks (codex and gemini run in parallel on isolated worktrees)
agent-sync dispatch -m agent_sync/manifests/refactor-auth.yaml

# 4. (After agents finish) Run the integration gate
agent-sync integrate -t T002-1 \
  --target main \
  --acceptance "uv run pytest tests/ -v --tb=short"

# 5. (Optional) Distill to memory for later review
agent-sync memory sync -t T002-1
```
