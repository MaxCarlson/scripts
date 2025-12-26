# Building a Minimal Agent Orchestrator in 2025

A single Python process can coordinate multiple AI CLI tools with graceful fallback, backed by PostgreSQL for cross-device access and llama-swap for local model management. This guide provides working code for each component of a minimal viable orchestrator system.

**The core architecture is simpler than expected**: an asyncio event loop manages a task queue, spawns CLI subprocesses for agent work, and uses PostgreSQL LISTEN/NOTIFY for real-time TUI updates. The entire system runs on one machine with an RTX 5090, serving a lightweight orchestrator model permanently while hot-swapping worker models as needed.

## Unified CLI interface enables transparent provider switching

The three major AI CLI tools—Claude Code, Codex, and Gemini—all support JSON output and programmatic invocation. Building a unified wrapper that automatically falls back between providers when rate limits hit is straightforward:

```python
from enum import Enum
from dataclasses import dataclass
import subprocess
import json
import time

class CLIProvider(Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"

@dataclass
class CLIResponse:
    provider: CLIProvider
    text: str
    usage: dict
    success: bool
    error: str = None

class RateLimitError(Exception):
    def __init__(self, provider: CLIProvider, retry_after: float = 60.0):
        self.provider = provider
        self.retry_after = retry_after

class UnifiedCLI:
    def __init__(self, fallback_order: list[CLIProvider] = None):
        self.fallback_order = fallback_order or [
            CLIProvider.GEMINI,  # Free tier: 60 req/min, 1000 req/day
            CLIProvider.CLAUDE,
            CLIProvider.CODEX
        ]
        self._rate_limit_cooldown = {}
    
    def _is_rate_limited(self, provider: CLIProvider) -> bool:
        return time.time() < self._rate_limit_cooldown.get(provider, 0)
    
    def _set_rate_limit(self, provider: CLIProvider, duration: float = 60.0):
        self._rate_limit_cooldown[provider] = time.time() + duration
    
    def _run_claude(self, prompt: str, **kwargs) -> CLIResponse:
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if kwargs.get("cwd"):
            cmd.extend(["--cwd", kwargs["cwd"]])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode != 0 or "rate" in result.stderr.lower():
            raise RateLimitError(CLIProvider.CLAUDE)
        
        data = json.loads(result.stdout) if result.stdout else {}
        return CLIResponse(
            provider=CLIProvider.CLAUDE,
            text=self._extract_text(data, "claude"),
            usage=data.get("usage", {}),
            success=True
        )
    
    def _run_codex(self, prompt: str, **kwargs) -> CLIResponse:
        cmd = ["codex", "exec", "--json", prompt]
        if kwargs.get("full_auto"):
            cmd.insert(2, "--full-auto")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        events = [json.loads(l) for l in result.stdout.strip().split('\n') if l]
        
        # Extract final message from event stream
        text, usage = "", {}
        for event in events:
            if event.get("type") == "error" and "rate" in event.get("message", "").lower():
                raise RateLimitError(CLIProvider.CODEX)
            if event.get("type") == "item.completed":
                if event.get("item", {}).get("type") == "agent_message":
                    text = event["item"].get("text", "")
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
        
        return CLIResponse(provider=CLIProvider.CODEX, text=text, usage=usage, success=True)
    
    def _run_gemini(self, prompt: str, **kwargs) -> CLIResponse:
        cmd = ["gemini", "-p", prompt, "--output-format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        data = json.loads(result.stdout) if result.stdout else {}
        
        if data.get("error") and "rate" in data["error"].get("message", "").lower():
            raise RateLimitError(CLIProvider.GEMINI)
        
        return CLIResponse(
            provider=CLIProvider.GEMINI,
            text=data.get("response", ""),
            usage=data.get("stats", {}),
            success=True
        )
    
    def query(self, prompt: str, **kwargs) -> CLIResponse:
        """Query with automatic fallback on rate limits."""
        last_error = None
        runners = {
            CLIProvider.CLAUDE: self._run_claude,
            CLIProvider.CODEX: self._run_codex,
            CLIProvider.GEMINI: self._run_gemini
        }
        
        for provider in self.fallback_order:
            if self._is_rate_limited(provider):
                continue
            try:
                return runners[provider](prompt, **kwargs)
            except RateLimitError as e:
                self._set_rate_limit(e.provider, e.retry_after)
                last_error = e
        
        raise RuntimeError(f"All providers exhausted. Last error: {last_error}")
```

Claude Code has an official Python SDK (`pip install claude-agent-sdk`) that enables deeper integration with hooks and MCP servers. Codex provides `codex exec --json` for programmatic use, with TypeScript SDK available but Python bindings still requested. Gemini CLI's free tier offers **60 requests per minute and 1,000 requests per day**—generous enough to serve as primary provider for development.

## RTX 5090 can run orchestrator and worker models simultaneously

The **32GB VRAM** budget supports running a lightweight orchestrator model permanently (~5GB) while hot-swapping larger worker models (~25GB available). The RTX 5090's Blackwell architecture provides **1,792 GB/s memory bandwidth**, roughly 78% more than the 4090.

**Recommended orchestrator model**: Qwen3-8B at Q4_K_M quantization consumes approximately 5GB VRAM with 8K context. It excels at tool calling with Hermes-style function invocation and supports thinking/non-thinking modes via `/think` and `/no_think` commands.

**Recommended worker models** that fit in the remaining ~25GB:
- Qwen2.5-Coder-32B (Q4_K_M): ~19-20GB for code generation
- QwQ-32B (Q4_K_M): ~19-20GB for complex reasoning
- Qwen3-32B (Q4_K_M): ~21GB for general tasks

**llama.cpp outperforms Ollama** for this use case. Benchmarks show roughly 30% faster inference, and it integrates better with llama-swap for model management. However, note that RTX 5090 has reported driver issues on native Windows—**use WSL2 for stability** until drivers mature.

```yaml
# llama-swap config.yaml for orchestrator + hot-swapped workers
healthCheckTimeout: 120
startPort: 10001

macros:
  "llama-base": |
    llama-server --port ${PORT}
    --n-gpu-layers 99
    --flash-attn
    --cont-batching

models:
  "orchestrator":
    cmd: |
      ${llama-base}
      --model /models/Qwen3-8B-Q4_K_M.gguf
      --ctx-size 8192
    aliases: ["gpt-4o-mini", "router"]
    ttl: 0  # Never unload

  "coder":
    cmd: |
      ${llama-base}
      --model /models/Qwen2.5-Coder-32B-Q4_K_M.gguf
      --ctx-size 16384
    ttl: 300  # Unload after 5 mins idle

  "reasoning":
    cmd: |
      ${llama-base}
      --model /models/QwQ-32B-Q4_K_M.gguf
      --ctx-size 32768
    ttl: 300

groups:
  "permanent":
    persistent: true
    swap: false
    members: ["orchestrator"]
    
  "workers":
    swap: true
    exclusive: false
    members: ["coder", "reasoning"]

hooks:
  on_startup:
    preload: ["orchestrator"]
```

Install llama-swap via Docker (`ghcr.io/mostlygeek/llama-swap:cuda`), Homebrew, or WinGet. It automatically routes requests based on the `model` field in API calls, starting and stopping model servers as needed.

## PostgreSQL replaces SQLite for cross-device coordination

PostgreSQL's **LISTEN/NOTIFY** mechanism is the decisive advantage over MySQL—it enables real-time TUI updates without polling. Migration from SQLite is a single command:

```bash
docker run --rm dimitri/pgloader:latest \
  pgloader sqlite:///path/to/tasks.db \
  postgresql://user:password@localhost:5432/agent_tasks
```

For more control, create a pgloader load file that handles type mappings (SQLite's AUTOINCREMENT becomes SERIAL, INTEGER booleans become proper BOOLEAN, datetime text becomes TIMESTAMP).

**Windows PostgreSQL setup** requires editing two configuration files after installation:

```ini
# postgresql.conf - listen on all interfaces
listen_addresses = '*'

# pg_hba.conf - allow LAN connections
host    all    all    192.168.1.0/24    scram-sha-256
```

Open Windows Firewall port 5432 and restart the PostgreSQL service. Android devices connect via Termux: `pkg install postgresql` provides the `psql` client.

The notification system requires a trigger that broadcasts task changes:

```sql
CREATE OR REPLACE FUNCTION notify_task_change()
RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('task_updates', json_build_object(
    'operation', TG_OP,
    'id', COALESCE(NEW.id, OLD.id),
    'status', NEW.status
  )::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER task_change_trigger
AFTER INSERT OR UPDATE OR DELETE ON tasks
FOR EACH ROW EXECUTE FUNCTION notify_task_change();
```

Python's asyncpg library handles notifications efficiently:

```python
import asyncio
import asyncpg
import json

async def listen_for_updates(callback):
    conn = await asyncpg.connect(
        host='192.168.1.100', database='agent_tasks',
        user='agent_user', password='password'
    )
    
    async def handler(conn, pid, channel, payload):
        await callback(json.loads(payload))
    
    await conn.add_listener('task_updates', handler)
    
    while True:
        await asyncio.sleep(1)  # Keep connection alive
```

For connection pooling in multi-agent scenarios, asyncpg's pool with `min_size=2, max_size=10` handles concurrent access well for home deployments.

## File-system sandboxing prevents path traversal attacks

Agents should be restricted to specific directories. The key insight is using `pathlib.resolve()` to canonicalize paths, then checking if the resolved path's parents include the sandbox root:

```python
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import os

@dataclass
class AgentSandbox:
    root_dir: Path
    agent_id: str
    
    def __post_init__(self):
        self.root_dir = self.root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)
    
    def resolve_path(self, relative_path: str) -> Optional[Path]:
        """Safely resolve path within sandbox, blocking traversal."""
        clean_path = os.path.normpath('/' + relative_path).lstrip('/')
        full_path = (self.root_dir / clean_path).resolve()
        
        # Critical check: verify path is within sandbox
        if self.root_dir not in full_path.parents and full_path != self.root_dir:
            return None
        return full_path
    
    def read_file(self, path: str) -> Optional[str]:
        safe_path = self.resolve_path(path)
        if safe_path and safe_path.is_file():
            return safe_path.read_text()
        return None
    
    def write_file(self, path: str, content: str) -> bool:
        safe_path = self.resolve_path(path)
        if safe_path:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            safe_path.write_text(content)
            return True
        return False
```

For hierarchical scoping where child agents inherit restricted permissions from parents, use a `Permission` flag enum and ensure children can never exceed parent permissions:

```python
from enum import Flag, auto

class Permission(Flag):
    NONE = 0
    READ = auto()
    WRITE = auto()
    EXECUTE = auto()
    CREATE_CHILD = auto()
    ALL = READ | WRITE | EXECUTE | CREATE_CHILD

@dataclass
class AgentScope:
    agent_id: str
    allowed_paths: set[str]
    permissions: Permission
    parent_scope: Optional['AgentScope'] = None
    
    def create_child_scope(self, child_id: str, paths: set[str], 
                           permissions: Permission) -> 'AgentScope':
        if not (self.permissions & Permission.CREATE_CHILD):
            raise PermissionError("Cannot create child agents")
        
        # Child permissions are intersection with parent
        return AgentScope(
            agent_id=child_id,
            allowed_paths=paths & self.allowed_paths,
            permissions=permissions & self.permissions,
            parent_scope=self
        )
```

## Task locking prevents concurrent work on the same task

Database-level locking is essential when multiple agents might claim the same task. The pattern uses an UPDATE statement that only succeeds if the task is unlocked or its lock has expired:

```python
from contextlib import contextmanager
from datetime import datetime, timedelta
import sqlite3
import socket
import threading

class TaskLock:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_locks (
                    task_id TEXT PRIMARY KEY,
                    locked_by TEXT,
                    expires_at TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)
    
    @contextmanager
    def acquire(self, task_id: str, timeout_seconds: int = 300):
        worker_id = f"{socket.gethostname()}_{threading.get_ident()}"
        now = datetime.utcnow()
        expires = now + timedelta(seconds=timeout_seconds)
        
        with self.lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            try:
                cursor = conn.execute("""
                    UPDATE task_locks 
                    SET locked_by = ?, expires_at = ?, status = 'running'
                    WHERE task_id = ? AND (locked_by IS NULL OR expires_at < ?)
                """, (worker_id, expires.isoformat(), task_id, now.isoformat()))
                
                if cursor.rowcount == 0:
                    raise LockError(f"Task {task_id} already locked")
                
                conn.commit()
                yield task_id
                
                conn.execute("""
                    UPDATE task_locks SET status = 'completed', locked_by = NULL
                    WHERE task_id = ?
                """, (task_id,))
                conn.commit()
            except Exception:
                conn.execute("""
                    UPDATE task_locks SET status = 'failed', locked_by = NULL
                    WHERE task_id = ? AND locked_by = ?
                """, (task_id, worker_id))
                conn.commit()
                raise
            finally:
                conn.close()
```

For PostgreSQL, use advisory locks (`SELECT pg_advisory_lock(task_id_hash)`) which are automatically released when the connection closes—providing crash safety without explicit cleanup.

## Agent handoff requires structured checkpoint serialization

When one agent stops and another must continue, the handoff packet should contain everything needed to resume:

```python
from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional
import json
from datetime import datetime

@dataclass
class AgentState:
    agent_id: str
    task_id: str
    status: str  # "in_progress", "blocked", "completed"
    progress: float  # 0.0 to 1.0
    checkpoint_data: dict[str, Any]  # Task-specific state
    conversation_history: List[dict]  # Messages for context
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)
    
    @classmethod
    def from_json(cls, data: str) -> 'AgentState':
        return cls(**json.loads(data))

@dataclass
class HandoffPacket:
    source_agent: str
    target_agent: str
    state: AgentState
    reason: str  # "specialization", "timeout", "escalation"
    context_summary: str  # LLM-generated summary of work done
    pending_actions: List[dict]  # What remains to be done
```

Store checkpoints as JSON files with task ID and timestamp in the filename. This enables easy debugging and manual recovery. The orchestrator can list checkpoints with `storage_path.glob(f"{task_id}_*.json")` and load the most recent.

## Single-process orchestrator coordinates everything

The minimal orchestrator uses asyncio to manage a task queue, spawn CLI subprocesses, and notify the TUI of status changes:

```python
import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from enum import Enum
import subprocess
import json

class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Task:
    task_id: str
    agent_type: str
    payload: dict
    status: TaskStatus = TaskStatus.QUEUED
    result: Optional[dict] = None

class MinimalOrchestrator:
    def __init__(self):
        self.task_queue: asyncio.Queue[Task] = asyncio.Queue()
        self.tasks: Dict[str, Task] = {}
        self.status_callbacks: list[Callable] = []
        self._running = False
    
    async def submit_task(self, task: Task) -> str:
        self.tasks[task.task_id] = task
        await self.task_queue.put(task)
        self._notify_status(task)
        return task.task_id
    
    async def start(self, num_workers: int = 3):
        self._running = True
        workers = [
            asyncio.create_task(self._worker(f"worker_{i}"))
            for i in range(num_workers)
        ]
        await asyncio.gather(*workers)
    
    async def _worker(self, worker_id: str):
        while self._running:
            try:
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)
                task.status = TaskStatus.RUNNING
                self._notify_status(task)
                
                result = await self._run_agent_cli(task)
                
                task.status = TaskStatus.COMPLETED if result.get("success") else TaskStatus.FAILED
                task.result = result
                self._notify_status(task)
                
            except asyncio.TimeoutError:
                continue
    
    async def _run_agent_cli(self, task: Task) -> dict:
        # Route to appropriate CLI based on agent_type
        cli_map = {
            "code_agent": ["claude", "-p"],
            "reasoning_agent": ["gemini", "-p"],
            "local_agent": ["curl", "-X", "POST", "http://localhost:8080/v1/chat/completions", "-d"]
        }
        
        base_cmd = cli_map.get(task.agent_type, ["claude", "-p"])
        prompt = json.dumps(task.payload)
        
        proc = await asyncio.create_subprocess_exec(
            *base_cmd, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            return {"success": True, "output": stdout.decode()}
        return {"success": False, "error": stderr.decode()}
    
    def _notify_status(self, task: Task):
        for callback in self.status_callbacks:
            callback(task)
    
    def on_status_change(self, callback: Callable):
        self.status_callbacks.append(callback)
```

Wire the PostgreSQL LISTEN/NOTIFY to the TUI by running the notification listener as a background asyncio task that calls your refresh function when updates arrive.

## Practical quick-start sequence

1. **Install CLIs**: `npm install -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli`
2. **Start local orchestrator model**: `llama-server --model Qwen3-8B-Q4_K_M.gguf --n-gpu-layers 99 --ctx-size 8192 --flash-attn --port 8080`
3. **Install PostgreSQL** on Windows via official installer, edit configs for LAN access
4. **Migrate data**: `pgloader sqlite:///tasks.db postgresql://user:pass@localhost/agent_tasks`
5. **Add notification trigger** to tasks table
6. **Run orchestrator** with the minimal Python code above

The system can be extended incrementally: add permission escalation workflows, implement more sophisticated routing logic, or integrate additional CLI tools. The single-process design keeps complexity low while the PostgreSQL backbone enables multi-device access and real-time synchronization.