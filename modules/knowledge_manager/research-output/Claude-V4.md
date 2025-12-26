# Multi-Agent Orchestrator System: Master Specification

This specification provides implementation-ready configurations, commands, and code patterns for building a multi-agent orchestrator that coordinates AI coding CLIs (Claude Code, Codex, Gemini) with PostgreSQL task queuing, local LLM routing, and cross-platform device access.

---

## 1. Database infrastructure: PostgreSQL on Docker/WSL2

### Docker Compose configuration

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    container_name: orchestrator-db
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-orchestrator}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-secretpassword}
      POSTGRES_DB: ${POSTGRES_DB:-orchestrator}
      PGDATA: /var/lib/postgresql/data/pgdata
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro
    command: >
      postgres
      -c listen_addresses='*'
      -c max_connections=100
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - orchestrator-net

  orchestrator:
    build:
      context: ./app
      dockerfile: Dockerfile
    container_name: orchestrator-app
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-orchestrator}:${POSTGRES_PASSWORD:-secretpassword}@db:5432/${POSTGRES_DB:-orchestrator}
      PYTHONUNBUFFERED: 1
    volumes:
      - ./app:/code
      - ./workspaces:/workspaces
    depends_on:
      db:
        condition: service_healthy
        restart: true
    networks:
      - orchestrator-net

volumes:
  postgres_data:
    driver: local

networks:
  orchestrator-net:
    driver: bridge
```

### WSL2 port forwarding to LAN (PowerShell as Admin)

```powershell
$wsl_ip = (wsl hostname -I).Trim().Split()[0]

# Forward PostgreSQL
netsh interface portproxy add v4tov4 listenport=5432 listenaddress=0.0.0.0 connectport=5432 connectaddress=$wsl_ip

# Firewall rule
New-NetFireWallRule -DisplayName 'PostgreSQL-5432' -Direction Inbound -LocalPort 5432 -Action Allow -Protocol TCP

# View rules
netsh interface portproxy show v4tov4
```

### WSL2 mirrored networking (.wslconfig)

```ini
# C:\Users\<username>\.wslconfig
[wsl2]
networkingMode=mirrored
memory=8GB
processors=4

[experimental]
hostAddressLoopback=true
dnsTunneling=true
```

### pg_hba.conf for remote access

```conf
# TYPE  DATABASE    USER        ADDRESS             METHOD
local   all         all                             peer
host    all         all         127.0.0.1/32        scram-sha-256
host    all         all         172.0.0.0/8         scram-sha-256
host    all         all         192.168.0.0/16      scram-sha-256
```

---

## 2. Cross-device access via SSH tunneling

### Termux PostgreSQL client setup

```bash
pkg update && pkg upgrade -y
pkg install postgresql openssh python

# .pgpass for passwordless connection
echo "192.168.1.100:5432:orchestrator:orchestrator:secretpassword" > ~/.pgpass
chmod 600 ~/.pgpass

# Test connection
psql -h 192.168.1.100 -U orchestrator -d orchestrator
```

### SSH tunnel with autossh

```bash
# Install
pkg install autossh

# Persistent tunnel to WSL2 PostgreSQL
autossh -M 0 -N \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -L 5432:localhost:5432 \
  user@192.168.1.100
```

### SSH config (~/.ssh/config)

```ssh-config
Host wsl2-orchestrator
    HostName 192.168.1.100
    User your-username
    LocalForward 5432 localhost:5432
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

---

## 3. Database migration: SQLite to PostgreSQL

### pgloader command

```bash
pgloader sqlite:///path/to/orchestrator.db \
  postgresql://orchestrator:password@localhost:5432/orchestrator
```

### pgloader script (migrate.load)

```lisp
LOAD DATABASE
    FROM sqlite:///home/user/orchestrator.db
    INTO postgresql://orchestrator:password@localhost:5432/orchestrator

WITH include drop, create tables, create indexes, reset sequences

CAST
    type datetime to timestamptz using sqlite-timestamp-to-timestamp,
    type integer to bigint when (= "id" column-name),
    type blob to bytea

EXCLUDING TABLE NAMES MATCHING 'sqlite_sequence'

AFTER LOAD DO $$ ANALYZE; $$;
```

### Type mappings reference

| SQLite | PostgreSQL |
|--------|------------|
| INTEGER | bigint |
| REAL | double precision |
| TEXT | text |
| BLOB | bytea |
| DATETIME | timestamptz |
| BOOLEAN | boolean |

---

## 4. Real-time updates with LISTEN/NOTIFY

### PostgreSQL trigger function

```sql
CREATE OR REPLACE FUNCTION notify_task_changes()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('task_updates', json_build_object(
        'operation', TG_OP,
        'table', TG_TABLE_NAME,
        'id', COALESCE(NEW.id, OLD.id),
        'data', CASE WHEN TG_OP = 'DELETE' THEN row_to_json(OLD) ELSE row_to_json(NEW) END,
        'timestamp', NOW()
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tasks_notify
    AFTER INSERT OR UPDATE OR DELETE ON tasks
    FOR EACH ROW EXECUTE FUNCTION notify_task_changes();
```

### asyncpg listener pattern

```python
import asyncio
import asyncpg
import json

class NotificationManager:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = None
        self.handlers = {}

    async def connect(self):
        self.conn = await asyncpg.connect(self.dsn)

    async def subscribe(self, channel: str, handler):
        self.handlers[channel] = handler
        await self.conn.add_listener(channel, self._callback)

    def _callback(self, conn, pid, channel, payload):
        data = json.loads(payload)
        if channel in self.handlers:
            asyncio.create_task(self.handlers[channel](data))

    async def listen_forever(self):
        while True:
            await asyncio.sleep(1)

# Usage
async def on_task_update(data):
    print(f"Task {data['id']}: {data['operation']}")

manager = NotificationManager("postgresql://orchestrator:pass@localhost/orchestrator")
await manager.connect()
await manager.subscribe('task_updates', on_task_update)
await manager.listen_forever()
```

---

## 5. CLI tool integration patterns

### Claude Code CLI

| Flag | Purpose |
|------|---------|
| `-p, --print` | Non-interactive mode |
| `--output-format json` | JSON output |
| `--continue` | Continue last session |
| `--resume <id>` | Resume specific session |
| `--permission-mode acceptEdits` | Auto-accept file changes |
| `--max-budget-usd 5.0` | Cost limit |

```python
import subprocess
import json

def invoke_claude(prompt: str, cwd: str = None) -> dict:
    result = subprocess.run(
        ['claude', '-p', prompt, '--output-format', 'json'],
        capture_output=True, text=True, timeout=300, cwd=cwd
    )
    return json.loads(result.stdout)

# JSON response structure
# {"type":"result","subtype":"success","total_cost_usd":0.003,
#  "result":"Response...","session_id":"abc123"}
```

### OpenAI Codex CLI

| Flag | Purpose |
|------|---------|
| `--json` | JSON Lines output |
| `-s, --sandbox` | `read-only`, `workspace-write`, `danger-full-access` |
| `--full-auto` | Auto-approve workspace writes |
| `--cd /path` | Working directory |
| `--output-schema file.json` | Structured output |

```python
def invoke_codex(prompt: str, cwd: str = None) -> list[dict]:
    result = subprocess.run(
        ['codex', 'exec', '--json', '--sandbox', 'read-only', prompt],
        capture_output=True, text=True, timeout=600, cwd=cwd
    )
    return [json.loads(line) for line in result.stdout.strip().split('\n') if line]

# Event types: thread.started, turn.started, item.completed, turn.completed
```

### Gemini CLI

| Flag | Purpose |
|------|---------|
| `-p, --prompt` | Non-interactive mode |
| `--output-format json` | JSON output |
| `--yolo` | Auto-approve all |
| `-m gemini-2.5-pro` | Model selection |

**Rate limits (free tier)**: 60 requests/minute, 1000 requests/day

```python
def invoke_gemini(prompt: str, cwd: str = None) -> dict:
    result = subprocess.run(
        ['gemini', '-p', prompt, '--output-format', 'json'],
        capture_output=True, text=True, timeout=300, cwd=cwd
    )
    return json.loads(result.stdout)
```

### Generic wrapper with error handling

```python
class CLIInvocationError(Exception):
    def __init__(self, cli: str, code: int, stderr: str):
        self.cli, self.code, self.stderr = cli, code, stderr

def invoke_cli(cmd: list[str], cwd: str = None, timeout: int = 300) -> dict:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
        if result.returncode != 0:
            if "rate limit" in result.stderr.lower():
                raise CLIInvocationError(cmd[0], 429, "Rate limited")
            raise CLIInvocationError(cmd[0], result.returncode, result.stderr)
        
        output = result.stdout.strip()
        if '\n' in output:
            return [json.loads(line) for line in output.split('\n') if line]
        return json.loads(output)
    except subprocess.TimeoutExpired:
        raise CLIInvocationError(cmd[0], -1, "Timeout")
```

---

## 6. Local LLM router with llama.cpp

### Model recommendations for RTX 5090 (6GB allocation)

| Model | Q4_K_M Size | VRAM (8K ctx) | Tool Calling | Recommendation |
|-------|-------------|---------------|--------------|----------------|
| **Qwen3-4B** | 2.50 GB | ~3.8 GB | ✅ Native | Best for 6GB strict |
| **Qwen3-8B** | 5.03 GB | ~6.2 GB | ✅ Native | Maximum capability |
| **Phi-4-mini** | ~2.5 GB | ~3.8 GB | ✅ Yes | Fastest routing |

### Download models

```bash
huggingface-cli download Qwen/Qwen3-4B-GGUF Q4_K_M.gguf --local-dir ./models
huggingface-cli download Qwen/Qwen3-8B-GGUF qwen3-8b-q4_k_m.gguf --local-dir ./models
```

### Start llama.cpp server with tool calling

```bash
./llama-server \
  -m ./models/qwen3-8b-q4_k_m.gguf \
  --jinja \
  --port 8080 \
  --host 0.0.0.0 \
  -ngl 99 \
  -c 8192 \
  -fa \
  --temp 0.6
```

### Routing prompt template

```
You are a task router. Classify requests and select the best CLI tool.

Categories:
- CODE_GENERATION: claude_cli, codex_cli
- WEB_SEARCH: gemini_cli (has Google search)
- FILE_OPERATIONS: claude_cli, codex_cli
- ANALYSIS: claude_cli

Respond with JSON only:
{"category": "...", "tool": "...", "confidence": "high|medium|low", "parameters": {...}}

/no_think
```

### Python router client

```python
import openai

client = openai.OpenAI(base_url="http://localhost:8080/v1", api_key="no-key")

ROUTER_PROMPT = """You are a task router. Classify into:
- CODE_GENERATION -> claude_cli or codex_cli
- WEB_SEARCH -> gemini_cli
- FILE_OPERATIONS -> claude_cli
Respond JSON only: {"category":"...","tool":"...","confidence":"..."} /no_think"""

def route_task(user_request: str) -> dict:
    response = client.chat.completions.create(
        model="qwen3-8b",
        messages=[
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": user_request}
        ],
        response_format={"type": "json_object"},
        temperature=0.3
    )
    return json.loads(response.choices[0].message.content)
```

---

## 7. Task queue with PostgreSQL advisory locks

### Schema

```sql
CREATE TABLE tasks (
    id BIGSERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    priority INT DEFAULT 0,
    worker_id VARCHAR(100),
    attempts INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_tasks_pending ON tasks(status, priority DESC, created_at)
    WHERE status = 'pending';
```

### Atomic task claiming with advisory lock

```sql
WITH claimed AS (
    SELECT id FROM tasks
    WHERE status = 'pending'
      AND pg_try_advisory_xact_lock('tasks'::regclass::int, id)
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE tasks
SET status = 'processing',
    claimed_at = NOW(),
    worker_id = $1,
    attempts = attempts + 1
FROM claimed
WHERE tasks.id = claimed.id
RETURNING tasks.*;
```

### Python asyncpg task worker

```python
import asyncpg
import asyncio

async def claim_task(pool: asyncpg.Pool, worker_id: str) -> dict | None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                WITH claimed AS (
                    SELECT id FROM tasks
                    WHERE status = 'pending'
                      AND pg_try_advisory_xact_lock('tasks'::regclass::int, id)
                    ORDER BY priority DESC, created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE tasks
                SET status = 'processing', claimed_at = NOW(), worker_id = $1
                FROM claimed WHERE tasks.id = claimed.id
                RETURNING tasks.*
            """, worker_id)
            return dict(row) if row else None

async def worker_loop(pool: asyncpg.Pool, worker_id: str):
    while True:
        task = await claim_task(pool, worker_id)
        if task:
            await process_task(task)
        else:
            await asyncio.sleep(1)
```

### asyncio worker pool with rate limiting

```python
import asyncio

class WorkerPool:
    def __init__(self, pool: asyncpg.Pool, num_workers: int = 5, max_concurrent: int = 3):
        self.pool = pool
        self.num_workers = num_workers
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.shutdown_event = asyncio.Event()

    async def worker(self, worker_id: str):
        while not self.shutdown_event.is_set():
            async with self.semaphore:
                task = await claim_task(self.pool, worker_id)
                if task:
                    await self.process(task)
                else:
                    await asyncio.sleep(1)

    async def process(self, task: dict):
        routing = route_task(task['payload']['prompt'])
        cli_map = {'claude_cli': invoke_claude, 'codex_cli': invoke_codex, 'gemini_cli': invoke_gemini}
        result = cli_map[routing['tool']](task['payload']['prompt'], task['payload'].get('cwd'))
        # Update task with result...

    async def run(self):
        workers = [asyncio.create_task(self.worker(f"worker-{i}")) for i in range(self.num_workers)]
        await asyncio.gather(*workers, return_exceptions=True)

    def shutdown(self):
        self.shutdown_event.set()
```

---

## 8. Agent state serialization

### Pydantic model

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any
from enum import Enum

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

class Message(BaseModel):
    role: MessageRole
    content: str | None = None
    tool_calls: list[dict] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class AgentState(BaseModel):
    session_id: str
    created_at: datetime
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    messages: list[Message] = Field(default_factory=list)
    working_directory: str
    open_files: list[str] = Field(default_factory=list)
    cli_session_ids: dict[str, str] = Field(default_factory=dict)  # cli_name -> session_id
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### State persistence manager

```python
import json
from pathlib import Path

class StateManager:
    def __init__(self, state_dir: Path = Path.home() / ".orchestrator/states"):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: AgentState) -> Path:
        path = self.state_dir / f"{state.session_id}.json"
        temp = path.with_suffix('.tmp')
        temp.write_text(state.model_dump_json(indent=2))
        temp.rename(path)
        return path

    def load(self, session_id: str) -> AgentState | None:
        path = self.state_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return AgentState.model_validate_json(path.read_text())
```

---

## 9. File-based locking fallback

### Cross-platform with filelock

```bash
pip install filelock
```

```python
from filelock import FileLock, Timeout
from pathlib import Path

class FileTaskLock:
    def __init__(self, lock_dir: Path = Path("/tmp/orchestrator_locks")):
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def try_claim(self, task_id: str) -> FileLock | None:
        lock = FileLock(self.lock_dir / f"{task_id}.lock", timeout=0)
        try:
            lock.acquire(blocking=False)
            return lock
        except Timeout:
            return None
```

---

## 10. Permission and sandbox patterns

### Claude Code CLAUDE.md format

```markdown
# Project: Multi-Agent Orchestrator

## Allowed Operations
- Read any file in src/ and tests/
- Write to src/, tests/, and workspaces/
- Run: npm test, npm run lint, python -m pytest

## Denied Operations  
- Never modify .env files
- Never run rm -rf or sudo commands
- Never access ~/.ssh or ~/.aws
```

### Claude Code settings.json

```json
{
  "permissions": {
    "allow": [
      "Read(src/**)", "Read(tests/**)",
      "Write(src/**)", "Write(tests/**)", "Write(workspaces/**)",
      "Bash(npm test:*)", "Bash(python -m pytest:*)", "Bash(git:*)"
    ],
    "deny": [
      "Read(.env*)", "Read(~/.ssh/**)", "Read(~/.aws/**)",
      "Bash(rm -rf:*)", "Bash(sudo:*)", "Write(.env*)"
    ]
  }
}
```

### Safe subprocess execution

```python
import subprocess
from pathlib import Path

class SandboxedExecutor:
    def __init__(self, base_dir: Path, allowed_commands: set[str]):
        self.base_dir = base_dir.resolve()
        self.allowed_commands = allowed_commands

    def execute(self, command: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        cmd_name = Path(command[0]).name
        if cmd_name not in self.allowed_commands:
            raise PermissionError(f"Command not allowed: {cmd_name}")

        return subprocess.run(
            command,
            cwd=str(self.base_dir),
            env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'LANG': 'en_US.UTF-8'},
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout
        )
```

### Path traversal prevention

```python
from pathlib import Path

class PathValidator:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()

    def validate(self, user_path: str, must_exist: bool = False) -> Path | None:
        if '\x00' in user_path:
            return None
        try:
            resolved = (self.base_dir / user_path).resolve()
            if not resolved.is_relative_to(self.base_dir):
                return None
            if must_exist and not resolved.exists():
                return None
            return resolved
        except (OSError, ValueError):
            return None

# Usage
validator = PathValidator(Path("/var/workspaces"))
safe = validator.validate("project/src/main.py")  # OK
blocked = validator.validate("../../../etc/passwd")  # None
```

---

## 11. Complete orchestrator architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         TUI Client                              │
│                   (Textual/Rich, asyncpg)                       │
│                         │                                       │
│            LISTEN/NOTIFY │ ◄──────────────────────┐             │
│                         ▼                          │             │
│  ┌─────────────────────────────────────────────┐   │             │
│  │              PostgreSQL 16                   │   │             │
│  │  ┌─────────┐  ┌──────────┐  ┌───────────┐  │   │             │
│  │  │ tasks   │  │ agents   │  │ sessions  │  │   │             │
│  │  └─────────┘  └──────────┘  └───────────┘  │   │             │
│  │     Advisory Locks │ FOR UPDATE SKIP LOCKED │   │             │
│  └──────────────────────────────────────────────┘   │             │
│                         │                          │             │
│          ┌──────────────┼──────────────┐           │             │
│          ▼              ▼              ▼           │             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐│             │
│  │   Worker 1   │ │   Worker 2   │ │   Worker N   ││             │
│  │ (claim_task) │ │ (claim_task) │ │ (claim_task) ││             │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘│             │
│         │                │                │        │             │
│         └────────────────┼────────────────┘        │             │
│                          ▼                         │             │
│  ┌────────────────────────────────────────────────┐│             │
│  │           Local LLM Router (Qwen3-8B)          ││             │
│  │              llama.cpp :8080                   ││             │
│  │    Task → {category, tool, parameters}        ││             │
│  └──────────────────────┬─────────────────────────┘│             │
│                         │                          │             │
│         ┌───────────────┼───────────────┐          │             │
│         ▼               ▼               ▼          │             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │             │
│  │ Claude Code │ │ Codex CLI   │ │ Gemini CLI  │   │             │
│  │ -p --json   │ │ exec --json │ │ -p --json   │   │             │
│  └─────────────┘ └─────────────┘ └─────────────┘   │             │
│         │               │               │          │             │
│         └───────────────┼───────────────┘          │             │
│                         ▼                          │             │
│              Update task status ───────────────────┘             │
│              NOTIFY 'task_updates'                               │
└─────────────────────────────────────────────────────────────────┘

External Access:
┌──────────────┐     SSH Tunnel      ┌──────────────┐
│   Termux     │ ◄─────────────────► │   WSL2 Host  │
│   (Android)  │   autossh :5432     │   Docker     │
│   psql/TUI   │                     │   PostgreSQL │
└──────────────┘                     └──────────────┘
```

---

## Quick start commands

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Start local LLM router
./llama-server -hf Qwen/Qwen3-8B-GGUF:Q4_K_M --jinja --port 8080 -ngl 99 -c 8192 -fa

# 3. Run orchestrator workers
python -m orchestrator.worker --workers 3

# 4. From Termux (after SSH tunnel)
autossh -M 0 -N -L 5432:localhost:5432 user@192.168.1.100 &
python -m orchestrator.tui
```

This specification provides all implementation-ready configurations for building the multi-agent orchestrator system with PostgreSQL task queuing, cross-platform device access, local LLM routing, and secure CLI integration.