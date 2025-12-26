# Minimal Viable Agent Orchestrator - Implementation Plan

**Date**: 2025-12-24
**Priority**: MAXIMUM (Overrides all other research documents)
**Status**: Ready for Implementation

---

## Executive Summary

Transform the existing `knowledge_manager` module into a **minimal viable agent orchestrator** that:

1. **Preserves** the existing TUI for human interaction
2. **Adds** an agent manager module to assign and track AI work
3. **Integrates** available CLIs (Claude Code, OpenAI Codex, Gemini CLI)
4. **Uses** local 5090 models for orchestration decisions
5. **Upgrades** from SQLite to network-capable database
6. **Provides** live tracking of agent work
7. **Ensures** work is trackable for agent handoffs

**No over-engineering**. Build what's needed now, extend later.

---

## Core Principles

### What We're Building

**NOT Building**:
- ❌ 10 research documents
- ❌ Complex vector databases (yet)
- ❌ CrewAI integration (yet)
- ❌ Multi-model consensus systems (yet)

**Building NOW**:
- ✅ Agent manager module
- ✅ CLI wrapper interfaces (Claude Code, OpenAI Codex, Gemini)
- ✅ Task assignment system
- ✅ Permission management
- ✅ Network-enabled database
- ✅ Live progress tracking
- ✅ Agent work logging in task details

### Key Constraints

**Must Preserve**:
- Existing TUI (`km tui`) for human project/task management
- Existing CLI (`km project`, `km task`) for scripting
- Backward compatibility with existing databases
- Cross-platform support (Windows 11, WSL2, Termux)

**Must Add**:
- Agent manager (`km agent` commands)
- CLI orchestration layer
- Network database (PostgreSQL or keep SQLite with network sync)
- Live status tracking
- Agent workspace isolation

---

## System Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────┐
│                   User Interfaces                       │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────┐   │
│  │ TUI (km) │  │ CLI (km) │  │ Agent Manager (new) │   │
│  └────┬─────┘  └────┬─────┘  └──────────┬──────────┘   │
└───────┼─────────────┼───────────────────┼──────────────┘
        │             │                   │
        ▼             ▼                   ▼
┌─────────────────────────────────────────────────────────┐
│              Knowledge Manager Core                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Project Ops │  │  Task Ops    │  │  Agent Ops     │ │
│  │ (existing)  │  │  (existing)  │  │  (NEW)         │ │
│  └─────────────┘  └──────────────┘  └────────────────┘ │
└───────────────────────┬─────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              Database Layer                             │
│  ┌──────────────────────────────────────────────────┐   │
│  │ PostgreSQL (or SQLite + syncthing)               │   │
│  │ - Projects, Tasks, Subtasks                      │   │
│  │ - Agent Work Logs (NEW)                          │   │
│  │ - Agent Locks (NEW)                              │   │
│  │ - CLI Usage Tracking (NEW)                       │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              Agent Orchestration Layer (NEW)            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Orchestrator │  │ CLI Wrappers │  │  Workspace   │  │
│  │ (5090 Model) │  │ Claude/GPT/  │  │  Manager     │  │
│  │              │  │ Gemini       │  │              │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              CLI Tool Layer                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ Claude Code │  │ OpenAI Codex│  │ Gemini CLI      │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Directory Structure

```
modules/
├── knowledge_manager/
│   ├── db.py                    # Existing DB layer
│   ├── models.py                # Existing models (Project, Task)
│   ├── project_ops.py           # Existing
│   ├── task_ops.py              # Existing
│   ├── agent_ops.py             # NEW - Agent CRUD operations
│   ├── agent_models.py          # NEW - Agent, AgentWorkLog, AgentLock models
│   ├── tui/                     # Existing TUI
│   │   ├── app.py
│   │   └── screens/
│   │       ├── projects.py
│   │       ├── tasks.py
│   │       └── agents.py        # NEW - Live agent status screen
│   ├── cli.py                   # Existing CLI (extend with agent commands)
│   └── migrations/              # NEW - Database migrations
│       └── 001_add_agent_tables.sql
│
├── agent_manager/               # NEW MODULE
│   ├── __init__.py
│   ├── orchestrator.py          # Main orchestration logic
│   ├── cli_wrappers/            # CLI tool wrappers
│   │   ├── __init__.py
│   │   ├── base.py              # Base CLI wrapper interface
│   │   ├── claude_code.py       # Claude Code wrapper
│   │   ├── openai_codex.py      # OpenAI Codex wrapper
│   │   └── gemini_cli.py        # Gemini CLI wrapper
│   ├── workspace.py             # Workspace isolation manager
│   ├── permissions.py           # Permission management
│   ├── usage_tracker.py         # CLI usage tracking
│   └── models.py                # Agent manager models
│
└── [existing modules...]
```

---

## Phase 1: Database Extensions (Week 1)

### Goal
Add tables to track agents, work logs, locks, and CLI usage without breaking existing functionality.

### Database Schema Additions

#### 1. `agents` Table

```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,              -- UUID
    name TEXT NOT NULL,               -- Human-readable name
    cli_tool TEXT NOT NULL,           -- 'claude_code', 'openai_codex', 'gemini_cli', 'local_5090'
    status TEXT NOT NULL,             -- 'idle', 'working', 'error', 'disabled'
    current_task_id TEXT,             -- Foreign key to tasks(id)
    created_at TEXT NOT NULL,
    last_active_at TEXT,
    config_json TEXT,                 -- JSON config (model params, etc.)
    FOREIGN KEY (current_task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_agents_cli_tool ON agents(cli_tool);
```

#### 2. `agent_work_logs` Table

```sql
CREATE TABLE agent_work_logs (
    id TEXT PRIMARY KEY,              -- UUID
    agent_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    project_id TEXT,                  -- Denormalized for quick project queries
    status TEXT NOT NULL,             -- 'assigned', 'in_progress', 'completed', 'failed', 'paused'
    work_summary TEXT,                -- Brief summary of work done
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX idx_work_logs_agent ON agent_work_logs(agent_id);
CREATE INDEX idx_work_logs_task ON agent_work_logs(task_id);
CREATE INDEX idx_work_logs_project ON agent_work_logs(project_id);
CREATE INDEX idx_work_logs_status ON agent_work_logs(status);
```

#### 3. `agent_locks` Table

```sql
CREATE TABLE agent_locks (
    entity_id TEXT NOT NULL,          -- Project or Task UUID
    entity_type TEXT NOT NULL,        -- 'project' or 'task'
    agent_id TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    expires_at TEXT,                  -- Optional lock expiry
    PRIMARY KEY (entity_id, entity_type),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_locks_agent ON agent_locks(agent_id);
```

#### 4. `cli_usage_tracking` Table

```sql
CREATE TABLE cli_usage_tracking (
    id TEXT PRIMARY KEY,              -- UUID
    cli_tool TEXT NOT NULL,           -- 'claude_code', 'openai_codex', 'gemini_cli'
    usage_date TEXT NOT NULL,         -- Date (YYYY-MM-DD)
    request_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_usage_cli_date ON cli_usage_tracking(cli_tool, usage_date);
```

### Migration Strategy

**Option A: Keep SQLite (Simpler)**
1. Add migration system to `knowledge_manager/db.py`
2. Run migrations on first connection
3. Use Syncthing for cross-device sync

**Option B: Upgrade to PostgreSQL (Network-Native)**
1. Create PostgreSQL schema with all tables
2. Write SQLite → PostgreSQL migration script
3. Update `db.py` to use PostgreSQL adapter
4. Deploy PostgreSQL in Docker on main machine

**Recommendation**: Start with **Option A** (SQLite + migrations). Upgrade to PostgreSQL only if sync issues arise.

### Implementation Tasks

- [ ] Add migration system to `db.py` (detect version, apply migrations)
- [ ] Create `migrations/001_add_agent_tables.sql`
- [ ] Create Python models in `agent_models.py`:
  - `Agent` dataclass
  - `AgentWorkLog` dataclass
  - `AgentLock` dataclass
  - `CLIUsageTracking` dataclass
- [ ] Add CRUD operations in `agent_ops.py`:
  - `create_agent()`, `get_agent()`, `list_agents()`, `update_agent()`, `delete_agent()`
  - `create_work_log()`, `get_work_logs()`, `update_work_log()`
  - `acquire_lock()`, `release_lock()`, `check_lock()`
  - `track_cli_usage()`, `get_cli_usage_stats()`
- [ ] Write tests for all agent operations

---

## Phase 2: CLI Wrapper Layer (Week 2)

### Goal
Create unified interface for calling Claude Code, OpenAI Codex, and Gemini CLI.

### Base CLI Wrapper Interface

```python
# agent_manager/cli_wrappers/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from pathlib import Path

@dataclass
class CLIRequest:
    """Standardized request to any CLI tool"""
    task_id: str
    task_title: str
    task_details: Optional[str]
    project_context: Optional[str]
    workspace_path: Path
    allowed_paths: list[Path]
    timeout: int = 300  # seconds

@dataclass
class CLIResponse:
    """Standardized response from any CLI tool"""
    success: bool
    output: str
    error: Optional[str]
    tokens_used: int
    duration: float  # seconds
    exit_code: int

class BaseCLI(ABC):
    """Base class for all CLI tool wrappers"""

    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.usage_tracker = None  # Injected from orchestrator

    @abstractmethod
    def execute(self, request: CLIRequest) -> CLIResponse:
        """Execute a request and return standardized response"""
        pass

    @abstractmethod
    def check_availability(self) -> bool:
        """Check if this CLI tool is available and configured"""
        pass

    @abstractmethod
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Return current rate limit status (if detectable)"""
        pass

    def track_usage(self, request: CLIRequest, response: CLIResponse):
        """Record usage statistics"""
        if self.usage_tracker:
            self.usage_tracker.record(
                cli_tool=self.tool_name,
                tokens=response.tokens_used,
                success=response.success
            )
```

### Claude Code CLI Wrapper

```python
# agent_manager/cli_wrappers/claude_code.py

import subprocess
import json
from pathlib import Path
from .base import BaseCLI, CLIRequest, CLIResponse

class ClaudeCodeCLI(BaseCLI):
    """Wrapper for Claude Code CLI"""

    def __init__(self):
        super().__init__("claude_code")
        self.executable = self._find_executable()

    def _find_executable(self) -> Optional[str]:
        """Locate claude executable"""
        # Try common locations
        try:
            result = subprocess.run(
                ["which", "claude"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    def check_availability(self) -> bool:
        """Check if Claude Code CLI is available"""
        if not self.executable:
            return False
        try:
            result = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False

    def execute(self, request: CLIRequest) -> CLIResponse:
        """Execute task using Claude Code CLI"""
        import time
        start_time = time.time()

        # Build prompt for Claude
        prompt = self._build_prompt(request)

        # Write prompt to temp file
        prompt_file = request.workspace_path / ".agent_prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        # Execute Claude Code CLI
        cmd = [
            self.executable,
            "chat",
            "--message", f"@{prompt_file}",
            "--cwd", str(request.workspace_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=request.timeout,
                cwd=request.workspace_path
            )

            duration = time.time() - start_time

            return CLIResponse(
                success=(result.returncode == 0),
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                tokens_used=self._estimate_tokens(result.stdout),
                duration=duration,
                exit_code=result.returncode
            )

        except subprocess.TimeoutExpired:
            return CLIResponse(
                success=False,
                output="",
                error=f"Timeout after {request.timeout}s",
                tokens_used=0,
                duration=request.timeout,
                exit_code=-1
            )
        except Exception as e:
            return CLIResponse(
                success=False,
                output="",
                error=str(e),
                tokens_used=0,
                duration=time.time() - start_time,
                exit_code=-1
            )

    def _build_prompt(self, request: CLIRequest) -> str:
        """Build prompt for Claude Code"""
        lines = []
        lines.append(f"# Task: {request.task_title}")
        lines.append(f"")
        if request.task_details:
            lines.append(f"## Details")
            lines.append(request.task_details)
            lines.append(f"")
        if request.project_context:
            lines.append(f"## Project Context")
            lines.append(request.project_context)
            lines.append(f"")
        lines.append(f"## Workspace")
        lines.append(f"You are working in: {request.workspace_path}")
        lines.append(f"You have access to: {', '.join(str(p) for p in request.allowed_paths)}")
        lines.append(f"")
        lines.append(f"## Instructions")
        lines.append(f"Complete the task above. Update the task details file with your progress.")
        lines.append(f"Mark the task as 'in-progress' when you start, 'done' when complete.")
        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate (4 chars per token)"""
        return len(text) // 4

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Claude Code CLI doesn't expose rate limits easily"""
        return {
            "available": True,
            "limit_known": False,
            "requests_remaining": None
        }
```

### OpenAI Codex & Gemini CLI Wrappers

Similar structure to Claude Code wrapper, adapted for:
- **OpenAI Codex**: Use `openai` Python SDK or CLI if available
- **Gemini CLI**: Use `gcloud` or custom Gemini CLI wrapper

### Implementation Tasks

- [ ] Create `BaseCLI` abstract base class
- [ ] Implement `ClaudeCodeCLI` wrapper with subprocess execution
- [ ] Implement `OpenAICodexCLI` wrapper (using SDK or CLI)
- [ ] Implement `GeminiCLI` wrapper
- [ ] Add CLI availability detection (check if tools are installed)
- [ ] Add error handling and retry logic
- [ ] Write tests for each CLI wrapper
- [ ] Document CLI tool installation requirements

---

## Phase 3: Agent Orchestrator (Week 3)

### Goal
Build the orchestration logic that assigns tasks to agents, manages workspaces, and tracks progress.

### Orchestrator Architecture

```python
# agent_manager/orchestrator.py

from pathlib import Path
from typing import Optional, List
import uuid
import logging
from datetime import datetime, timezone

from knowledge_manager import db, agent_ops, task_ops
from knowledge_manager.models import Task, TaskStatus
from knowledge_manager.agent_models import Agent, AgentWorkLog
from .cli_wrappers import ClaudeCodeCLI, OpenAICodexCLI, GeminiCLI, BaseCLI
from .workspace import WorkspaceManager
from .permissions import PermissionManager

logger = logging.getLogger(__name__)

class AgentOrchestrator:
    """Main orchestrator for assigning and managing agent work"""

    def __init__(self, base_data_dir: Optional[Path] = None):
        self.base_data_dir = base_data_dir
        self.db_path = db.get_default_db_path(base_data_dir)

        # Initialize CLI wrappers
        self.clis: Dict[str, BaseCLI] = {
            "claude_code": ClaudeCodeCLI(),
            "openai_codex": OpenAICodexCLI(),
            "gemini_cli": GeminiCLI()
        }

        # Managers
        self.workspace_manager = WorkspaceManager(base_data_dir)
        self.permission_manager = PermissionManager()

    def assign_task_to_agent(
        self,
        task_id: uuid.UUID,
        preferred_cli: Optional[str] = None,
        auto_start: bool = True
    ) -> Optional[Agent]:
        """Assign a task to an available agent"""

        conn = db.get_db_connection(self.db_path)

        try:
            # 1. Get task
            task = task_ops.get_task_by_id(conn, task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return None

            # 2. Check if task is already locked
            existing_lock = agent_ops.get_lock(conn, str(task_id), "task")
            if existing_lock:
                logger.warning(f"Task {task_id} is already locked by agent {existing_lock.agent_id}")
                return None

            # 3. Select CLI tool
            cli_tool = self._select_cli_tool(preferred_cli, task)
            if not cli_tool:
                logger.error("No available CLI tools")
                return None

            # 4. Create or get agent
            agent = self._get_or_create_agent(conn, cli_tool)

            # 5. Acquire lock
            lock_acquired = agent_ops.acquire_lock(
                conn,
                entity_id=str(task_id),
                entity_type="task",
                agent_id=str(agent.id)
            )

            if not lock_acquired:
                logger.error(f"Failed to acquire lock for task {task_id}")
                return None

            # 6. Create work log
            work_log = agent_ops.create_work_log(
                conn,
                agent_id=agent.id,
                task_id=task.id,
                project_id=task.project_id,
                status="assigned"
            )

            # 7. Update agent status
            agent.status = "working"
            agent.current_task_id = str(task_id)
            agent_ops.update_agent(conn, agent)

            # 8. Update task status
            task.status = TaskStatus.IN_PROGRESS
            task_ops.update_task(conn, task)

            conn.commit()

            # 9. Start work if auto_start
            if auto_start:
                self._execute_task_async(agent, task)

            return agent

        except Exception as e:
            conn.rollback()
            logger.error(f"Error assigning task: {e}", exc_info=True)
            return None
        finally:
            conn.close()

    def _select_cli_tool(
        self,
        preferred: Optional[str],
        task: Task
    ) -> Optional[str]:
        """Select best CLI tool for this task"""

        # If preferred CLI specified and available, use it
        if preferred and preferred in self.clis:
            if self.clis[preferred].check_availability():
                return preferred

        # Otherwise, pick first available
        for tool_name, cli in self.clis.items():
            if cli.check_availability():
                # TODO: Add usage-based selection (avoid rate-limited CLIs)
                return tool_name

        return None

    def _get_or_create_agent(
        self,
        conn,
        cli_tool: str
    ) -> Agent:
        """Get existing idle agent or create new one"""

        # Try to find idle agent with this CLI tool
        agents = agent_ops.list_agents(conn, cli_tool=cli_tool, status="idle")
        if agents:
            return agents[0]

        # Create new agent
        agent = Agent(
            id=uuid.uuid4(),
            name=f"{cli_tool}_agent_{uuid.uuid4().hex[:8]}",
            cli_tool=cli_tool,
            status="idle",
            created_at=datetime.now(timezone.utc)
        )

        return agent_ops.create_agent(conn, agent)

    def _execute_task_async(self, agent: Agent, task: Task):
        """Execute task in background (use threading or asyncio)"""
        import threading
        thread = threading.Thread(
            target=self._execute_task,
            args=(agent, task),
            daemon=True
        )
        thread.start()

    def _execute_task(self, agent: Agent, task: Task):
        """Execute task using agent's CLI tool"""

        conn = db.get_db_connection(self.db_path)

        try:
            # 1. Setup workspace
            workspace_path = self.workspace_manager.create_workspace(
                project_id=task.project_id,
                task_id=task.id
            )

            # 2. Get allowed paths from permissions
            allowed_paths = self.permission_manager.get_allowed_paths(
                task=task,
                workspace_path=workspace_path
            )

            # 3. Build CLI request
            from .cli_wrappers.base import CLIRequest
            request = CLIRequest(
                task_id=str(task.id),
                task_title=task.title,
                task_details=self._load_task_details(task),
                project_context=self._load_project_context(task),
                workspace_path=workspace_path,
                allowed_paths=allowed_paths,
                timeout=600  # 10 minutes
            )

            # 4. Execute CLI
            cli = self.clis[agent.cli_tool]
            logger.info(f"Agent {agent.name} executing task {task.id} using {agent.cli_tool}")

            response = cli.execute(request)

            # 5. Update work log
            work_log = agent_ops.get_work_log_by_task(conn, task.id, agent.id)
            if work_log:
                work_log.status = "completed" if response.success else "failed"
                work_log.work_summary = response.output[:500]  # First 500 chars
                work_log.completed_at = datetime.now(timezone.utc)
                agent_ops.update_work_log(conn, work_log)

            # 6. Update task
            if response.success:
                task.status = TaskStatus.DONE
            # Write agent output to task details
            self._append_to_task_details(task, response.output)
            task_ops.update_task(conn, task)

            # 7. Release lock
            agent_ops.release_lock(conn, str(task.id), "task")

            # 8. Update agent status
            agent.status = "idle"
            agent.current_task_id = None
            agent.last_active_at = datetime.now(timezone.utc)
            agent_ops.update_agent(conn, agent)

            # 9. Track usage
            cli.track_usage(request, response)

            conn.commit()

            logger.info(f"Agent {agent.name} completed task {task.id}: {response.success}")

        except Exception as e:
            conn.rollback()
            logger.error(f"Error executing task {task.id}: {e}", exc_info=True)

            # Update work log to failed
            try:
                work_log = agent_ops.get_work_log_by_task(conn, task.id, agent.id)
                if work_log:
                    work_log.status = "failed"
                    work_log.work_summary = f"Error: {str(e)}"
                    agent_ops.update_work_log(conn, work_log)
                    conn.commit()
            except:
                pass

        finally:
            conn.close()

    def _load_task_details(self, task: Task) -> Optional[str]:
        """Load task details markdown file"""
        if task.details_md_path and task.details_md_path.exists():
            return task.details_md_path.read_text(encoding="utf-8")
        return None

    def _load_project_context(self, task: Task) -> Optional[str]:
        """Load project context for task"""
        if not task.project_id:
            return None

        conn = db.get_db_connection(self.db_path)
        try:
            from knowledge_manager import project_ops
            result = project_ops.get_project_with_details(
                str(task.project_id),
                base_data_dir=self.base_data_dir
            )
            if result:
                _, description = result
                return description
        finally:
            conn.close()
        return None

    def _append_to_task_details(self, task: Task, content: str):
        """Append agent work to task details file"""
        from knowledge_manager import utils

        if not task.details_md_path:
            task.details_md_path = utils.generate_markdown_file_path(
                task.id,
                "task",
                self.base_data_dir
            )

        # Read existing content
        existing = ""
        if task.details_md_path.exists():
            existing = task.details_md_path.read_text(encoding="utf-8")

        # Append new content with timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        new_content = f"{existing}\n\n---\n**Agent Work Log** ({timestamp}):\n\n{content}\n"

        utils.write_markdown_file(task.details_md_path, new_content)
```

### Implementation Tasks

- [ ] Create `AgentOrchestrator` class
- [ ] Implement task assignment logic with locking
- [ ] Implement CLI selection algorithm (prefer available, track usage)
- [ ] Implement async task execution (threading or asyncio)
- [ ] Create `WorkspaceManager` for isolated task workspaces
- [ ] Create `PermissionManager` for path access control
- [ ] Add logging for all orchestrator operations
- [ ] Write integration tests

---

## Phase 4: Workspace & Permission Management (Week 4)

### Workspace Manager

```python
# agent_manager/workspace.py

from pathlib import Path
import uuid
import shutil
import logging

logger = logging.getLogger(__name__)

class WorkspaceManager:
    """Manages isolated workspaces for agent tasks"""

    def __init__(self, base_data_dir: Optional[Path] = None):
        self.base_data_dir = base_data_dir or Path.home() / ".local" / "share" / "knowledge_manager_data"
        self.workspaces_dir = self.base_data_dir / "agent_workspaces"
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

    def create_workspace(
        self,
        project_id: Optional[uuid.UUID],
        task_id: uuid.UUID
    ) -> Path:
        """Create isolated workspace for task"""

        workspace_path = self.workspaces_dir / str(task_id)

        if workspace_path.exists():
            logger.warning(f"Workspace already exists: {workspace_path}")
            return workspace_path

        workspace_path.mkdir(parents=True)

        # Create README with context
        readme = workspace_path / "README.md"
        readme.write_text(
            f"# Agent Workspace\n\n"
            f"Task ID: {task_id}\n"
            f"Project ID: {project_id or 'None'}\n"
            f"Created: {datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8"
        )

        logger.info(f"Created workspace: {workspace_path}")
        return workspace_path

    def cleanup_workspace(self, task_id: uuid.UUID, keep_logs: bool = True):
        """Clean up workspace after task completion"""

        workspace_path = self.workspaces_dir / str(task_id)

        if not workspace_path.exists():
            return

        if keep_logs:
            # Archive instead of delete
            archive_dir = self.base_data_dir / "agent_workspace_archives"
            archive_dir.mkdir(parents=True, exist_ok=True)

            archive_path = archive_dir / f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.move(str(workspace_path), str(archive_path))
            logger.info(f"Archived workspace: {archive_path}")
        else:
            shutil.rmtree(workspace_path)
            logger.info(f"Deleted workspace: {workspace_path}")
```

### Permission Manager

```python
# agent_manager/permissions.py

from pathlib import Path
from typing import List
import logging

logger = logging.getLogger(__name__)

class PermissionManager:
    """Manages file system permissions for agents"""

    def __init__(self):
        self.default_allow_patterns = [
            "**/*.py",
            "**/*.md",
            "**/*.txt",
            "**/*.json",
            "**/*.yaml",
            "**/*.toml"
        ]

        self.default_deny_patterns = [
            "**/.git/**",
            "**/.env",
            "**/secrets/**",
            "**/*password*",
            "**/*secret*",
            "**/*.key"
        ]

    def get_allowed_paths(
        self,
        task: Task,
        workspace_path: Path
    ) -> List[Path]:
        """Get list of paths agent can access"""

        # By default, agent can access:
        # 1. Its own workspace
        # 2. Project-specific directories (if configured)

        allowed = [workspace_path]

        # TODO: Load project-specific permissions from config
        # For now, just allow workspace

        return allowed

    def check_permission(
        self,
        agent_id: uuid.UUID,
        path: Path,
        operation: str  # 'read', 'write', 'execute'
    ) -> bool:
        """Check if agent has permission for operation on path"""

        # TODO: Implement granular permission checks
        # For MVP, allow all operations within workspace

        return True
```

### Implementation Tasks

- [ ] Implement `WorkspaceManager` with create/cleanup methods
- [ ] Implement `PermissionManager` with path access control
- [ ] Add configuration file support for project-specific permissions
- [ ] Add workspace archival (keep logs after task completion)
- [ ] Write tests for workspace isolation
- [ ] Document permission configuration format

---

## Phase 5: CLI Commands & TUI Integration (Week 5)

### New CLI Commands

Add to `knowledge_manager/cli.py`:

```python
# Agent management commands

def handle_agent_list(args):
    """List all agents and their status"""
    conn = db.get_db_connection(utils.get_db_path(args.data_dir))
    try:
        agents = agent_ops.list_agents(conn)
        if not agents:
            print("No agents found.")
            return

        print(f"\n--- Agents ({len(agents)}) ---")
        for agent in agents:
            print(f"ID: {agent.id}")
            print(f"Name: {agent.name}")
            print(f"CLI Tool: {agent.cli_tool}")
            print(f"Status: {agent.status}")
            if agent.current_task_id:
                print(f"Current Task: {agent.current_task_id}")
            print(f"Last Active: {agent.last_active_at or 'Never'}")
            print("---")
    finally:
        conn.close()

def handle_agent_assign(args):
    """Assign task to agent"""
    from agent_manager.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(base_data_dir=args.data_dir)

    agent = orchestrator.assign_task_to_agent(
        task_id=uuid.UUID(args.task_id),
        preferred_cli=args.cli_tool,
        auto_start=not args.no_start
    )

    if agent:
        print(f"Task {args.task_id} assigned to agent {agent.name}")
    else:
        print(f"Failed to assign task {args.task_id}", file=sys.stderr)
        sys.exit(1)

def handle_agent_status(args):
    """Show live status of all agents"""
    conn = db.get_db_connection(utils.get_db_path(args.data_dir))
    try:
        agents = agent_ops.list_agents(conn)

        print("\n=== Agent Status Dashboard ===\n")

        for agent in agents:
            status_icon = {
                "idle": "⚪",
                "working": "🟢",
                "error": "🔴",
                "disabled": "⚫"
            }.get(agent.status, "❓")

            print(f"{status_icon} {agent.name} ({agent.cli_tool})")
            if agent.current_task_id:
                task = task_ops.get_task_by_id(conn, uuid.UUID(agent.current_task_id))
                if task:
                    print(f"   Working on: {task.title}")

        # Show recent work logs
        print("\n=== Recent Work Logs ===\n")
        work_logs = agent_ops.list_work_logs(conn, limit=10)
        for log in work_logs:
            print(f"{log.started_at}: {log.status} - {log.work_summary or 'No summary'}")

    finally:
        conn.close()

# Add to argument parser
agent_parser = subparsers.add_parser("agent", help="Manage agents")
agent_subparsers = agent_parser.add_subparsers(dest="agent_action", required=True)

# agent list
agent_list_parser = agent_subparsers.add_parser("list", help="List all agents")
agent_list_parser.set_defaults(func=handle_agent_list)

# agent assign
agent_assign_parser = agent_subparsers.add_parser("assign", help="Assign task to agent")
agent_assign_parser.add_argument("-t", "--task-id", required=True, help="Task ID to assign")
agent_assign_parser.add_argument("-c", "--cli-tool", help="Preferred CLI tool")
agent_assign_parser.add_argument("-n", "--no-start", action="store_true", help="Don't auto-start task")
agent_assign_parser.set_defaults(func=handle_agent_assign)

# agent status
agent_status_parser = agent_subparsers.add_parser("status", help="Show agent status dashboard")
agent_status_parser.set_defaults(func=handle_agent_status)
```

### TUI Agent Screen

Add to `knowledge_manager/tui/screens/agents.py`:

```python
# New screen for live agent monitoring

from textual.screen import Screen
from textual.widgets import DataTable, Static
from textual.reactive import reactive
from textual import work
import asyncio

class AgentsScreen(Screen):
    """Live agent status dashboard"""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "back", "Back")
    ]

    def compose(self):
        yield Static("Agent Status Dashboard", id="header")
        yield DataTable(id="agent_table")
        yield Static("", id="work_log")

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("Agent", "CLI Tool", "Status", "Current Task")
        self.refresh_data()
        self.set_interval(5.0, self.refresh_data)  # Auto-refresh every 5s

    @work(exclusive=True)
    async def refresh_data(self):
        """Refresh agent data from database"""
        from knowledge_manager import db, agent_ops, task_ops, utils

        conn = db.get_db_connection(utils.get_db_path(self.app.base_data_dir))
        try:
            agents = agent_ops.list_agents(conn)

            table = self.query_one(DataTable)
            table.clear()

            for agent in agents:
                current_task = ""
                if agent.current_task_id:
                    task = task_ops.get_task_by_id(conn, agent.current_task_id)
                    if task:
                        current_task = task.title

                status_icon = {
                    "idle": "⚪",
                    "working": "🟢",
                    "error": "🔴"
                }.get(agent.status, "❓")

                table.add_row(
                    agent.name,
                    agent.cli_tool,
                    f"{status_icon} {agent.status}",
                    current_task
                )

            # Update work log
            work_logs = agent_ops.list_work_logs(conn, limit=5)
            log_text = "\n".join([
                f"{log.started_at}: {log.status} - {log.work_summary or 'No summary'}"
                for log in work_logs
            ])
            self.query_one("#work_log", Static).update(log_text)

        finally:
            conn.close()

    async def action_refresh(self):
        """Manual refresh"""
        await self.refresh_data()

    async def action_back(self):
        """Go back to previous screen"""
        await self.app.pop_screen()
```

### Implementation Tasks

- [ ] Add `agent` command group to CLI
- [ ] Implement `agent list`, `agent assign`, `agent status` commands
- [ ] Create `AgentsScreen` TUI screen with live updates
- [ ] Add navigation to agents screen from main TUI menu
- [ ] Test CLI commands
- [ ] Test TUI agent monitoring

---

## Phase 6: Network Database (Week 6)

### Option A: SQLite + Syncthing (Simpler)

**Pros**:
- No complex setup
- Existing codebase works as-is
- Syncthing handles file sync across devices

**Cons**:
- Potential sync conflicts
- Not true concurrent access
- Network latency on sync

**Setup**:
1. Install Syncthing on all devices
2. Share knowledge_manager_data directory
3. Add lock files to prevent concurrent writes

### Option B: PostgreSQL (Network-Native)

**Pros**:
- True concurrent access
- Better for multi-device scenarios
- ACID guarantees

**Cons**:
- More complex setup
- Requires PostgreSQL server
- Migration from SQLite needed

**Setup**:
1. Deploy PostgreSQL in Docker
2. Create migration script (SQLite → PostgreSQL)
3. Update `db.py` to support PostgreSQL
4. Deploy on main machine, access over LAN/VPN

### Recommendation

**Start with Option A** (SQLite + Syncthing). Only migrate to PostgreSQL if:
- Concurrent agent access causes conflicts
- Multiple devices need simultaneous write access
- Performance degrades

### Implementation Tasks

**For Option A (SQLite + Syncthing)**:
- [ ] Document Syncthing setup procedure
- [ ] Add lock file mechanism for write operations
- [ ] Test sync behavior across devices
- [ ] Handle merge conflicts gracefully

**For Option B (PostgreSQL) - Future**:
- [ ] Create Docker compose for PostgreSQL
- [ ] Write SQLite → PostgreSQL migration script
- [ ] Add PostgreSQL adapter to `db.py`
- [ ] Test network access from multiple devices

---

## Phase 7: Testing & Documentation (Week 7)

### Testing Strategy

**Unit Tests**:
- [ ] Agent CRUD operations
- [ ] CLI wrapper interfaces
- [ ] Workspace management
- [ ] Permission checks
- [ ] Lock acquisition/release

**Integration Tests**:
- [ ] End-to-end task assignment
- [ ] CLI execution with mock responses
- [ ] Database migrations
- [ ] TUI screen rendering

**Manual Tests**:
- [ ] Assign real task to Claude Code CLI
- [ ] Monitor agent progress in TUI
- [ ] Verify task details updated by agent
- [ ] Test cross-device sync (if using Syncthing)

### Documentation

**User Documentation**:
- [ ] Getting started guide
- [ ] CLI command reference
- [ ] TUI usage guide
- [ ] Agent configuration guide
- [ ] Troubleshooting common issues

**Developer Documentation**:
- [ ] Architecture overview
- [ ] Database schema reference
- [ ] Adding new CLI wrappers
- [ ] Extending orchestrator logic
- [ ] Contributing guidelines

---

## Success Criteria

The minimal viable agent orchestrator is complete when:

✅ **Core Functionality**:
- [ ] Humans can create projects/tasks via TUI (existing feature preserved)
- [ ] Tasks can be assigned to agents via CLI: `km agent assign -t <task-id>`
- [ ] Agents execute tasks using Claude Code/OpenAI/Gemini CLIs
- [ ] Task status updates automatically (TODO → IN_PROGRESS → DONE)
- [ ] Agent work logged in task details markdown files

✅ **Observability**:
- [ ] `km agent status` shows live agent status
- [ ] TUI agents screen shows real-time progress
- [ ] Work logs stored in database and displayed

✅ **Isolation & Safety**:
- [ ] Tasks locked during agent execution (no concurrent work on same task)
- [ ] Agents work in isolated workspaces
- [ ] Permissions prevent access outside allowed paths

✅ **Cross-Device**:
- [ ] Database accessible from multiple devices (via Syncthing or PostgreSQL)
- [ ] TUI on Device A shows work done by agent on Device B

✅ **Documentation**:
- [ ] README with setup instructions
- [ ] CLI command reference
- [ ] Agent configuration guide

---

## What's NOT in MVP (Future Enhancements)

**Defer to Later**:
- ❌ Vector database (Qdrant) - use markdown files for now
- ❌ CrewAI framework - direct orchestration for MVP
- ❌ Local 5090 models - use CLIs only for MVP
- ❌ Multi-model consensus - single agent per task
- ❌ Auto-task decomposition - human creates subtasks
- ❌ Cost optimization algorithms - simple round-robin CLI selection
- ❌ Advanced memory summarization - keep full logs for now

**Add These Later** (after MVP validated):
- Phase 8: Vector database for semantic task search
- Phase 9: Local LLM for orchestration decisions
- Phase 10: Multi-agent collaboration on single task
- Phase 11: Auto-task decomposition
- Phase 12: Cost tracking and budget management

---

## Implementation Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Database Extensions | New tables, migrations, Python models |
| 2 | CLI Wrappers | Claude Code, OpenAI, Gemini wrappers |
| 3 | Orchestrator | Task assignment, execution, logging |
| 4 | Workspace & Permissions | Isolated workspaces, access control |
| 5 | CLI & TUI | Agent commands, live monitoring screen |
| 6 | Network Database | Syncthing setup or PostgreSQL migration |
| 7 | Testing & Docs | Tests, user docs, developer docs |

**Total**: 7 weeks to MVP

**Faster Path** (if needed):
- Skip network database (Week 6) initially
- Run everything on single machine first
- Add cross-device support later

---

## Next Steps (Start Immediately)

### This Week
1. **Review this plan** with user - confirm approach
2. **Setup development environment**:
   - Ensure Claude Code CLI installed and working
   - Check OpenAI Codex CLI availability
   - Test Gemini CLI (if available)
3. **Create database migrations** (Phase 1):
   - Add migration system to `db.py`
   - Create `001_add_agent_tables.sql`
4. **Start CLI wrappers** (Phase 2):
   - Implement `BaseCLI` interface
   - Begin Claude Code wrapper

### Questions for User

Before proceeding, clarify:
1. **CLI Availability**: Which CLIs do you actually have installed?
   - Claude Code: Installed? (`claude --version`)
   - OpenAI Codex: Have access? How to invoke?
   - Gemini CLI: Available? Or use API?
2. **Network Requirement**: Do you need cross-device access immediately, or can it wait?
3. **Testing Resources**: Do you have test API credits for development?
4. **Timeline**: Is 7 weeks acceptable, or need faster MVP?

---

## Appendices

### A. Database Migration System

```python
# knowledge_manager/db.py - Add migration system

def get_db_version(conn: sqlite3.Connection) -> int:
    """Get current database schema version"""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        # schema_version table doesn't exist
        return 0

def apply_migration(conn: sqlite3.Connection, version: int, sql: str):
    """Apply a single migration"""
    cursor = conn.cursor()

    # Create schema_version table if needed
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

    # Check if already applied
    cursor.execute("SELECT version FROM schema_version WHERE version = ?", (version,))
    if cursor.fetchone():
        return  # Already applied

    # Apply migration
    cursor.executescript(sql)

    # Record migration
    cursor.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (version, datetime.now(timezone.utc).isoformat())
    )

    conn.commit()

def run_all_migrations(conn: sqlite3.Connection):
    """Run all pending migrations"""
    current_version = get_db_version(conn)

    migrations_dir = Path(__file__).parent / "migrations"
    if not migrations_dir.exists():
        return

    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration_file in migration_files:
        # Extract version from filename: 001_add_agent_tables.sql
        version = int(migration_file.stem.split("_")[0])

        if version > current_version:
            print(f"Applying migration {version}: {migration_file.name}")
            sql = migration_file.read_text(encoding="utf-8")
            apply_migration(conn, version, sql)
```

### B. Configuration File Format

```yaml
# ~/.config/knowledge_manager/agent_config.yaml

agent_manager:
  # CLI tool preferences
  cli_tools:
    claude_code:
      enabled: true
      executable: /usr/local/bin/claude
      max_concurrent: 2

    openai_codex:
      enabled: true
      api_key: ${OPENAI_API_KEY}
      model: gpt-4
      max_concurrent: 1

    gemini_cli:
      enabled: false

  # Workspace settings
  workspaces:
    base_dir: ~/.local/share/knowledge_manager_data/agent_workspaces
    cleanup_after_days: 30
    archive_on_completion: true

  # Permission settings
  permissions:
    default_allow_patterns:
      - "**/*.py"
      - "**/*.md"
      - "**/*.txt"
    default_deny_patterns:
      - "**/.env"
      - "**/secrets/**"

  # Orchestration settings
  orchestrator:
    default_cli: claude_code
    task_timeout: 600  # seconds
    auto_start: true
    max_retries: 2
```

---

## End of Plan

This plan is ready for implementation. Start with Phase 1 (Database Extensions) and proceed sequentially.
