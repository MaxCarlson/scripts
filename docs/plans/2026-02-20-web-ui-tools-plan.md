# web_ui_tools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract `orchestrator_web_viewer` into a reusable `web_ui_tools` FastAPI framework with plugin architecture, then migrate the orchestrator-specific code into a plugin in `ai-orchestrator`.

**Architecture:** A plugin-based FastAPI server where `web_ui_tools` provides the core shell (auth, WebSocket, config, CLI, termdash, logs, health) and plugins register via `importlib.metadata` entry points. The ai-orchestrator's `orchestrator_web_viewer` becomes a thin plugin that registers its domain-specific routers.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, WebSockets, importlib.metadata, pytest, httpx

**Design doc:** `docs/plans/2026-02-20-web-ui-tools-design.md`

---

## Phase 1: Framework + First Plugin

### Task 1: Module skeleton and pyproject.toml

**Files:**
- Create: `modules/web_ui_tools/pyproject.toml`
- Create: `modules/web_ui_tools/web_ui_tools/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "web-ui-tools"
version = "0.1.0"
description = "Reusable FastAPI web dashboard framework with plugin architecture."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "mcarls" }]

dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "websockets>=12.0",
    "python-multipart>=0.0.6",
    "jinja2>=3.1.2",
    "watchfiles>=0.21.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "httpx>=0.26.0",
]

[project.scripts]
webui = "web_ui_tools.cli:main"
koweb = "web_ui_tools.cli:main"

[tool.setuptools.packages.find]
include = ["web_ui_tools*"]

[tool.setuptools.package-data]
web_ui_tools = ["static/**/*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --basetemp=.pytest_tmp"
tmp_path_retention_policy = "none"
asyncio_mode = "auto"
```

**Step 2: Create `__init__.py`**

```python
"""web_ui_tools - Reusable FastAPI web dashboard framework with plugin architecture."""

__version__ = "0.1.0"
```

**Step 3: Verify module structure**

Run: `ls modules/web_ui_tools/pyproject.toml modules/web_ui_tools/web_ui_tools/__init__.py`
Expected: Both files listed without error.

**Step 4: Commit**

```bash
git add modules/web_ui_tools/pyproject.toml modules/web_ui_tools/web_ui_tools/__init__.py
git commit -m "feat(web_ui_tools): module skeleton with pyproject.toml"
```

---

### Task 2: Config module

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/config.py`
- Test: `modules/web_ui_tools/tests/config_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.config."""

import os
import pytest
from web_ui_tools.config import Config


def test_default_values():
    cfg = Config()
    assert cfg.HOST == "0.0.0.0"
    assert cfg.PORT == 3000
    assert cfg.AUTH_ENABLED is False
    assert cfg.QUIET is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("WEBUI_PORT", "8080")
    monkeypatch.setenv("WEBUI_HOST", "127.0.0.1")
    cfg = Config()
    assert cfg.PORT == 8080
    assert cfg.HOST == "127.0.0.1"


def test_cli_override():
    cfg = Config()
    cfg.apply_cli_args(host="10.0.0.1", port=9999)
    assert cfg.HOST == "10.0.0.1"
    assert cfg.PORT == 9999


def test_cli_none_does_not_override():
    cfg = Config()
    original_host = cfg.HOST
    cfg.apply_cli_args(host=None, port=None)
    assert cfg.HOST == original_host


def test_auth_enabled_when_both_set(monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_USER", "admin")
    monkeypatch.setenv("WEBUI_AUTH_PASSWORD", "secret")
    cfg = Config()
    cfg.enable_auth_from_env()
    assert cfg.AUTH_ENABLED is True
    assert cfg.AUTH_USERNAME == "admin"
    assert cfg.AUTH_PASSWORD == "secret"


def test_auth_not_enabled_when_partial(monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_USER", "admin")
    # No password set
    cfg = Config()
    cfg.enable_auth_from_env()
    assert cfg.AUTH_ENABLED is False
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/config_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web_ui_tools.config'`

**Step 3: Implement config.py**

Extract from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/main.py:35-63`.
Generalize env var prefix from `KO_WEB_` to `WEBUI_`, keep backward compat with `KO_WEB_` fallback.

```python
"""Application configuration for web_ui_tools."""

import os
from typing import Optional


class Config:
    """Server configuration. Reads WEBUI_* env vars, falls back to KO_WEB_* for compat."""

    def __init__(self) -> None:
        self.HOST: str = self._env("HOST", "0.0.0.0")
        self.PORT: int = int(self._env("PORT", "3000"))
        self.QUIET: bool = self._env("QUIET", "").lower() in ("1", "true", "yes")
        self.AUTH_ENABLED: bool = False
        self.AUTH_USERNAME: str = self._env("AUTH_USER", "admin")
        self.AUTH_PASSWORD: str = self._env("AUTH_PASSWORD", "")

    @staticmethod
    def _env(key: str, default: str) -> str:
        """Read WEBUI_<key>, fall back to KO_WEB_<key>, then default."""
        return os.getenv(f"WEBUI_{key}", os.getenv(f"KO_WEB_{key}", default))

    def apply_cli_args(self, **kwargs: object) -> None:
        """Override config with non-None CLI argument values."""
        for key, value in kwargs.items():
            if value is not None and hasattr(self, key.upper()):
                setattr(self, key.upper(), value)

    def enable_auth_from_env(self) -> None:
        """Enable auth if both username and password are set."""
        user = self._env("AUTH_USER", "")
        password = self._env("AUTH_PASSWORD", "")
        if user and password:
            self.AUTH_ENABLED = True
            self.AUTH_USERNAME = user
            self.AUTH_PASSWORD = password

    def enable_auth(self, username: str, password: str) -> None:
        """Enable auth with explicit credentials (from CLI args)."""
        self.AUTH_ENABLED = True
        self.AUTH_USERNAME = username
        self.AUTH_PASSWORD = password
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/config_test.py -v`
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/config.py modules/web_ui_tools/tests/config_test.py
git commit -m "feat(web_ui_tools): config module with env/CLI override hierarchy"
```

---

### Task 3: Auth module

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/auth.py`
- Test: `modules/web_ui_tools/tests/auth_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.auth."""

import base64
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from web_ui_tools.auth import make_auth_dependency
from web_ui_tools.config import Config


def _make_app(config: Config) -> FastAPI:
    app = FastAPI()
    check_auth = make_auth_dependency(config)

    @app.get("/protected")
    async def protected(user=check_auth):
        return {"user": user}

    return app


def test_auth_disabled_allows_access():
    config = Config()
    config.AUTH_ENABLED = False
    client = TestClient(_make_app(config))
    resp = client.get("/protected")
    assert resp.status_code == 200
    assert resp.json()["user"] is None


def test_auth_enabled_rejects_no_header():
    config = Config()
    config.enable_auth("admin", "secret")
    client = TestClient(_make_app(config))
    resp = client.get("/protected")
    assert resp.status_code == 401


def test_auth_enabled_accepts_valid_creds():
    config = Config()
    config.enable_auth("admin", "secret")
    client = TestClient(_make_app(config))
    creds = base64.b64encode(b"admin:secret").decode()
    resp = client.get("/protected", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200
    assert resp.json()["user"] == "admin"


def test_auth_rejects_wrong_password():
    config = Config()
    config.enable_auth("admin", "secret")
    client = TestClient(_make_app(config))
    creds = base64.b64encode(b"admin:wrong").decode()
    resp = client.get("/protected", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 401
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/auth_test.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web_ui_tools.auth'`

**Step 3: Implement auth.py**

Extract from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/main.py:69-121`.

```python
"""HTTP Basic Auth dependency for FastAPI."""

import base64
import logging
import secrets
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status

from .config import Config

logger = logging.getLogger(__name__)

_REALM = "WebUI"


def make_auth_dependency(config: Config):
    """Create a FastAPI dependency that checks HTTP Basic Auth against config."""

    async def check_auth(request: Request) -> Optional[str]:
        if not config.AUTH_ENABLED:
            return None

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            )

        try:
            scheme, credentials = auth_header.split()
            if scheme.lower() != "basic":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authentication scheme",
                    headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
                )

            decoded = base64.b64decode(credentials).decode("utf-8")
            username, password = decoded.split(":", 1)

            if not (
                secrets.compare_digest(username, config.AUTH_USERNAME)
                and secrets.compare_digest(password, config.AUTH_PASSWORD)
            ):
                logger.warning("Failed login attempt for user: %s", username)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
                )

            return username

        except (ValueError, UnicodeDecodeError) as exc:
            logger.error("Auth header parse error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header",
                headers={"WWW-Authenticate": f'Basic realm="{_REALM}"'},
            ) from exc

    return Depends(check_auth)
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/auth_test.py -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/auth.py modules/web_ui_tools/tests/auth_test.py
git commit -m "feat(web_ui_tools): HTTP Basic Auth dependency with constant-time comparison"
```

---

### Task 4: WebSocket connection manager

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/websocket/__init__.py`
- Create: `modules/web_ui_tools/web_ui_tools/websocket/manager.py`
- Test: `modules/web_ui_tools/tests/websocket_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.websocket.manager."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from web_ui_tools.websocket.manager import ConnectionManager


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_connect(manager, mock_ws):
    await manager.connect(mock_ws)
    mock_ws.accept.assert_awaited_once()
    assert mock_ws in manager.active_connections


@pytest.mark.asyncio
async def test_disconnect(manager, mock_ws):
    await manager.connect(mock_ws)
    manager.disconnect(mock_ws)
    assert mock_ws not in manager.active_connections


@pytest.mark.asyncio
async def test_broadcast(manager, mock_ws):
    await manager.connect(mock_ws)
    await manager.broadcast({"type": "test"})
    mock_ws.send_json.assert_awaited_once_with({"type": "test"})


@pytest.mark.asyncio
async def test_broadcast_cleans_dead(manager):
    dead_ws = AsyncMock()
    dead_ws.accept = AsyncMock()
    dead_ws.send_json = AsyncMock(side_effect=Exception("closed"))
    await manager.connect(dead_ws)
    await manager.broadcast({"type": "test"})
    assert dead_ws not in manager.active_connections


@pytest.mark.asyncio
async def test_task_subscribe_and_send(manager, mock_ws):
    await manager.connect(mock_ws)
    manager.subscribe_to_task(mock_ws, "task-1")
    await manager.send_to_task_subscribers("task-1", {"type": "update"})
    mock_ws.send_json.assert_awaited_with({"type": "update"})


@pytest.mark.asyncio
async def test_disconnect_cleans_subscriptions(manager, mock_ws):
    await manager.connect(mock_ws)
    manager.subscribe_to_task(mock_ws, "task-1")
    manager.disconnect(mock_ws)
    assert mock_ws not in manager.task_subscriptions.get("task-1", set())
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/websocket_test.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement websocket manager**

Copy from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/websocket/manager.py` verbatim (it's already general-purpose).

`websocket/__init__.py`:
```python
"""WebSocket connection management."""
```

`websocket/manager.py` - same as the existing code in ai-orchestrator (83 lines, already read above).

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/websocket_test.py -v`
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/websocket/
git add modules/web_ui_tools/tests/websocket_test.py
git commit -m "feat(web_ui_tools): WebSocket connection manager with task subscriptions"
```

---

### Task 5: Log buffer (builtin)

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/builtins/__init__.py`
- Create: `modules/web_ui_tools/web_ui_tools/builtins/logs.py`
- Test: `modules/web_ui_tools/tests/logs_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.builtins.logs."""

import logging
import pytest
from web_ui_tools.builtins.logs import LogBufferHandler, install_log_buffer, get_recent_logs


@pytest.fixture
def handler():
    return LogBufferHandler(capacity=10)


def test_emit_captures_record(handler):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    handler.emit(record)
    logs = handler.get_logs(limit=10)
    assert len(logs) == 1
    assert logs[0]["message"] == "hello"
    assert logs[0]["level"] == "INFO"


def test_capacity_limit(handler):
    for i in range(15):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=f"msg-{i}", args=(), exc_info=None,
        )
        handler.emit(record)
    logs = handler.get_logs(limit=100)
    assert len(logs) == 10  # capacity is 10


def test_min_level_filter(handler):
    for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
        record = logging.LogRecord(
            name="test", level=level, pathname="", lineno=0,
            msg=f"level-{level}", args=(), exc_info=None,
        )
        handler.emit(record)
    logs = handler.get_logs(limit=100, min_level=logging.WARNING)
    assert len(logs) == 2  # WARNING + ERROR


def test_access_log_excluded_by_default(handler):
    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname="", lineno=0,
        msg="GET / 200", args=(), exc_info=None,
    )
    handler.emit(record)
    assert len(handler.get_logs(include_access=False)) == 0
    assert len(handler.get_logs(include_access=True)) == 1
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/logs_test.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement logs.py**

Extract from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/log_utils.py`.
This module provides both the handler AND the API router. Combine `log_utils.py` + `api/logs.py`.

`builtins/__init__.py`:
```python
"""Built-in web_ui_tools features (health, logs)."""
```

`builtins/logs.py` - merge `log_utils.py` (handler/buffer) with `api/logs.py` (router). The `LogBufferHandler`, `install_log_buffer`, `get_recent_logs`, `list_logger_levels`, `update_logger_level` functions come from `log_utils.py`. Add the FastAPI router at the bottom:

```python
router = APIRouter()

@router.get("")
async def read_logs(...):
    ...

@router.get("/levels")
async def get_levels():
    ...

@router.post("/level")
async def set_level(payload):
    ...
```

Keep the existing log_utils code verbatim for the handler class (lines 1-130 of the existing file), then append the router endpoints from `api/logs.py`.

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/logs_test.py -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/builtins/
git add modules/web_ui_tools/tests/logs_test.py
git commit -m "feat(web_ui_tools): log buffer handler + /api/logs router"
```

---

### Task 6: Health builtin

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/builtins/health.py`
- Test: `modules/web_ui_tools/tests/health_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.builtins.health."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from web_ui_tools.builtins.health import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/system")
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "uptime_seconds" in data
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/health_test.py -v`
Expected: FAIL

**Step 3: Implement health.py**

```python
"""Health and system info endpoints."""

import time
from fastapi import APIRouter
from web_ui_tools import __version__

router = APIRouter()
_start_time = time.monotonic()


@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": __version__,
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/health_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/builtins/health.py modules/web_ui_tools/tests/health_test.py
git commit -m "feat(web_ui_tools): /api/system/health endpoint with uptime"
```

---

### Task 7: TermDash router and viewer

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/termdash/__init__.py`
- Create: `modules/web_ui_tools/web_ui_tools/termdash/router.py`
- Create: `modules/web_ui_tools/web_ui_tools/termdash/viewer.py`
- Test: `modules/web_ui_tools/tests/termdash_test.py`

**Step 1: Write failing test**

Adapt from `~/scripts/modules/orchestrator_web_viewer/tests/termdash_api_test.py` (already read above). Change imports to use `web_ui_tools.termdash.router`.

```python
"""Tests for web_ui_tools.termdash."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from web_ui_tools.termdash.router import router, register_dashboard, unregister_dashboard, _attached_dashboards


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/termdash")
    return TestClient(app)


@pytest.fixture
def mock_dashboard():
    from termdash import TermDash, Stat, Line
    dashboard = TermDash(refresh_rate=1.0)
    line = Line("test_line", stats=[
        Stat("count", 42, prefix="Count: "),
        Stat("rate", 1.5, prefix="Rate: ", unit="/s"),
    ])
    dashboard.add_line("test_line", line)
    return dashboard


@pytest.fixture(autouse=True)
def cleanup_dashboards():
    yield
    _attached_dashboards.clear()


def test_list_dashboards_empty(client):
    response = client.get("/api/termdash/dashboards")
    assert response.status_code == 200
    assert len(response.json()["dashboards"]) == 0


def test_register_and_get_state(client, mock_dashboard):
    register_dashboard("test_dash", mock_dashboard)
    response = client.get("/api/termdash/dashboards/test_dash")
    assert response.status_code == 200
    data = response.json()
    assert "lines" in data
    assert data["lines"][0]["name"] == "test_line"


def test_get_not_found(client):
    response = client.get("/api/termdash/dashboards/nonexistent")
    assert response.status_code == 404


def test_unregister(mock_dashboard):
    register_dashboard("test_id", mock_dashboard)
    assert "test_id" in _attached_dashboards
    unregister_dashboard("test_id")
    assert "test_id" not in _attached_dashboards


def test_websocket_stream(client, mock_dashboard):
    register_dashboard("test_dash", mock_dashboard)
    with client.websocket_connect("/api/termdash/dashboards/test_dash/stream") as ws:
        data = ws.receive_json()
        assert data["type"] == "state"
        assert "lines" in data["data"]
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/termdash_test.py -v`
Expected: FAIL

**Step 3: Implement termdash router**

`termdash/__init__.py`:
```python
"""TermDash web viewer integration."""
```

`termdash/router.py`: Copy from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/api/termdash.py` verbatim (96 lines, already read). It's already general-purpose.

`termdash/viewer.py`: Simple HTML page serving for the termdash viewer.

```python
"""Serve the termdash viewer HTML page."""

from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()
STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/termdash", response_class=HTMLResponse)
async def termdash_viewer():
    termdash_file = STATIC_DIR / "termdash.html"
    if termdash_file.exists():
        return FileResponse(termdash_file)
    return HTMLResponse("<h1>TermDash viewer not available</h1>", status_code=404)
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/termdash_test.py -v`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/termdash/
git add modules/web_ui_tools/tests/termdash_test.py
git commit -m "feat(web_ui_tools): termdash router + viewer (extracted from orchestrator)"
```

---

### Task 8: Plugin protocol and loader

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/plugins/__init__.py`
- Create: `modules/web_ui_tools/web_ui_tools/plugins/protocol.py`
- Create: `modules/web_ui_tools/web_ui_tools/plugins/loader.py`
- Test: `modules/web_ui_tools/tests/plugin_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.plugins."""

import pytest
from fastapi import FastAPI
from web_ui_tools.plugins.protocol import WebUIPlugin
from web_ui_tools.plugins.loader import discover_plugins


class FakePlugin:
    """A minimal plugin for testing."""
    name = "fake"
    version = "0.0.1"

    def register(self, app: FastAPI) -> None:
        @app.get("/api/fake/hello")
        async def hello():
            return {"plugin": self.name}

    def get_nav_items(self) -> list[dict]:
        return [{"label": "Fake", "path": "/fake"}]


def test_fake_plugin_satisfies_protocol():
    plugin = FakePlugin()
    # Should not raise - duck-typed protocol check
    assert hasattr(plugin, "name")
    assert hasattr(plugin, "version")
    assert hasattr(plugin, "register")
    assert hasattr(plugin, "get_nav_items")


def test_plugin_registers_routes():
    app = FastAPI()
    plugin = FakePlugin()
    plugin.register(app)
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/fake/hello")
    assert resp.status_code == 200
    assert resp.json()["plugin"] == "fake"


def test_discover_plugins_empty(monkeypatch):
    """With no entry points, should return empty list."""
    import importlib.metadata
    monkeypatch.setattr(
        importlib.metadata, "entry_points",
        lambda group=None, **kw: [],
    )
    plugins = discover_plugins()
    assert plugins == []
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/plugin_test.py -v`
Expected: FAIL

**Step 3: Implement plugin protocol and loader**

`plugins/__init__.py`:
```python
"""Plugin discovery and loading."""
```

`plugins/protocol.py`:
```python
"""Plugin protocol definition."""

from typing import Protocol, runtime_checkable
from fastapi import FastAPI


@runtime_checkable
class WebUIPlugin(Protocol):
    """Protocol that all web_ui_tools plugins must satisfy."""

    name: str
    version: str

    def register(self, app: FastAPI) -> None:
        """Register routers, mount static dirs, add lifecycle hooks."""
        ...

    def get_nav_items(self) -> list[dict]:
        """Return sidebar navigation items for the dashboard shell."""
        ...
```

`plugins/loader.py`:
```python
"""Discover and load plugins via entry points."""

import importlib.metadata
import logging
from typing import Any

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "webui.plugins"


def discover_plugins() -> list[Any]:
    """Scan entry points and instantiate plugin classes."""
    plugins: list[Any] = []
    eps = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)

    for ep in eps:
        try:
            plugin_class = ep.load()
            plugin = plugin_class()
            logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)
            plugins.append(plugin)
        except Exception:
            logger.exception("Failed to load plugin: %s", ep.name)

    return plugins
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/plugin_test.py -v`
Expected: All 3 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/plugins/
git add modules/web_ui_tools/tests/plugin_test.py
git commit -m "feat(web_ui_tools): plugin protocol + entry-point discovery"
```

---

### Task 9: FastAPI app factory

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/app.py`
- Test: `modules/web_ui_tools/tests/app_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.app."""

import pytest
from fastapi.testclient import TestClient
from web_ui_tools.app import create_app
from web_ui_tools.config import Config


@pytest.fixture
def client():
    config = Config()
    app = create_app(config)
    return TestClient(app)


def test_root_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_health_endpoint(client):
    resp = client.get("/api/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_logs_endpoint(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    assert "logs" in resp.json()


def test_websocket_ping(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_nav_includes_builtins(client):
    resp = client.get("/api/nav")
    assert resp.status_code == 200
    items = resp.json()["items"]
    # Should have at least the built-in nav items
    assert any(item["label"] == "Dashboard" for item in items)
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/app_test.py -v`
Expected: FAIL

**Step 3: Implement app factory**

Extract and generalize from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/main.py:124-346`.

```python
"""FastAPI application factory for web_ui_tools."""

import logging
from pathlib import Path
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .auth import make_auth_dependency
from .builtins import health, logs
from .builtins.logs import install_log_buffer
from .config import Config
from .plugins.loader import discover_plugins
from .termdash import router as termdash_router, viewer as termdash_viewer
from .websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: Optional[Config] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if config is None:
        config = Config()

    install_log_buffer()
    check_auth = make_auth_dependency(config)

    app = FastAPI(
        title="WebUI Tools",
        description="Reusable web dashboard framework with plugin architecture",
        version="0.1.0",
    )

    # CORS for LAN access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store config and manager on app state for access by plugins
    ws_manager = ConnectionManager()
    app.state.config = config
    app.state.ws_manager = ws_manager
    app.state.plugins = []

    # Static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Root page
    @app.get("/", response_class=HTMLResponse)
    async def root(user: Annotated[Optional[str], check_auth] = None):
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse(
            "<html><body style='background:#0f0f0f;color:#fff;font-family:system-ui'>"
            "<h1>WebUI Tools</h1><p>Server running. No index.html found.</p>"
            "<p><a href='/docs' style='color:#00d4aa'>API docs</a></p>"
            "</body></html>"
        )

    # WebSocket
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "subscribe":
                    task_id = data.get("task_id")
                    if task_id:
                        ws_manager.subscribe_to_task(websocket, task_id)
                elif msg_type == "unsubscribe":
                    task_id = data.get("task_id")
                    if task_id:
                        ws_manager.unsubscribe_from_task(websocket, task_id)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # Built-in routers
    auth_deps = [Depends(check_auth.__wrapped__)] if config.AUTH_ENABLED else []
    app.include_router(health.router, prefix="/api/system", tags=["system"], dependencies=auth_deps)
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"], dependencies=auth_deps)
    app.include_router(termdash_router.router, prefix="/api/termdash", tags=["termdash"], dependencies=auth_deps)
    app.include_router(termdash_viewer.router, tags=["termdash"])

    # Plugin discovery and registration
    plugins = discover_plugins()
    for plugin in plugins:
        try:
            plugin.register(app)
            app.state.plugins.append(plugin)
            logger.info("Registered plugin: %s v%s", plugin.name, plugin.version)
        except Exception:
            logger.exception("Failed to register plugin: %s", plugin.name)

    # Navigation endpoint (aggregates builtins + plugins)
    @app.get("/api/nav")
    async def nav():
        items = [
            {"label": "Dashboard", "path": "/", "icon": "home"},
            {"label": "TermDash", "path": "/termdash", "icon": "terminal"},
            {"label": "Logs", "path": "/logs", "icon": "list"},
        ]
        for plugin in app.state.plugins:
            try:
                items.extend(plugin.get_nav_items())
            except Exception:
                logger.exception("Error getting nav items from plugin: %s", plugin.name)
        return {"items": items}

    # Lifecycle
    @app.on_event("startup")
    async def startup():
        logger.info("WebUI Tools starting (plugins: %d)", len(app.state.plugins))

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("WebUI Tools shutting down")

    return app
```

Note: The `auth_deps` line needs adjustment. The `make_auth_dependency` returns a `Depends()` wrapper. For the router `dependencies=` parameter, we need the raw callable. Adjust during implementation - either change `make_auth_dependency` to return the raw function, or use a different pattern. The test will reveal the exact API needed.

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/app_test.py -v`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/app.py modules/web_ui_tools/tests/app_test.py
git commit -m "feat(web_ui_tools): app factory with plugin loading, builtins, WebSocket"
```

---

### Task 10: CLI entry point

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/cli.py`
- Test: `modules/web_ui_tools/tests/cli_test.py`

**Step 1: Write failing test**

```python
"""Tests for web_ui_tools.cli."""

import pytest
from unittest.mock import patch, MagicMock
from web_ui_tools.cli import build_parser


def test_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.host is None
    assert args.port is None
    assert args.reload is False
    assert args.verbose is False
    assert args.stop is False


def test_parser_all_flags():
    parser = build_parser()
    args = parser.parse_args([
        "-H", "127.0.0.1",
        "-p", "8080",
        "-r",
        "-v",
        "-q",
        "-u", "admin",
        "-w", "secret",
    ])
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.reload is True
    assert args.verbose is True
    assert args.quiet is True
    assert args.auth_user == "admin"
    assert args.auth_password == "secret"


def test_parser_stop():
    parser = build_parser()
    args = parser.parse_args(["-s"])
    assert args.stop is True


def test_parser_list_plugins():
    parser = build_parser()
    args = parser.parse_args(["--list-plugins"])
    assert args.list_plugins is True
```

**Step 2: Run test to verify it fails**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/cli_test.py -v`
Expected: FAIL

**Step 3: Implement cli.py**

Extract and generalize from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/main.py:349-553`.

```python
"""CLI entry point for web_ui_tools."""

import argparse
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WebUI Tools - Reusable web dashboard framework"
    )
    parser.add_argument("-H", "--host", default=None, help="Host to bind to (default: WEBUI_HOST or 0.0.0.0)")
    parser.add_argument("-p", "--port", type=int, default=None, help="Port (default: WEBUI_PORT or 3000)")
    parser.add_argument("-r", "--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress HTTP access logs")
    parser.add_argument("-u", "--auth-user", default=None, help="Username for HTTP Basic Auth")
    parser.add_argument("-w", "--auth-password", default=None, help="Password for HTTP Basic Auth")
    parser.add_argument("-s", "--stop", action="store_true", help="Stop running webui/koweb servers")
    parser.add_argument("--list-plugins", action="store_true", help="List discovered plugins and exit")
    return parser


def _stop_servers(port: int) -> None:
    """Stop running webui/koweb servers on host and in Docker."""
    current_pid = os.getpid()
    pids: set[int] = set()

    # 1. Check host processes via lsof
    try:
        result = subprocess.run(
            ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    pids.add(int(line))
    except FileNotFoundError:
        pass  # lsof not available (Termux)

    # 2. Check host processes via pgrep
    for pattern in ("webui", "koweb"):
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    pid = int(line)
                    if pid == current_pid:
                        continue
                    try:
                        with open(f"/proc/{pid}/cmdline", "r", encoding="utf-8") as fh:
                            cmdline = fh.read().replace("\x00", " ")
                    except (FileNotFoundError, PermissionError):
                        cmdline = ""
                    if "--stop" in cmdline:
                        continue
                    if pattern in cmdline:
                        pids.add(pid)
        except FileNotFoundError:
            pass

    # 3. Check Docker containers
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=koweb", "--filter", "name=webui",
             "--format", "{{.ID}} {{.Names}}"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            containers = [
                line.split()[0] for line in result.stdout.splitlines() if line.strip()
            ]
            for cid in containers:
                subprocess.run(["docker", "stop", cid], capture_output=True, check=False)
                print(f"Stopped Docker container: {cid}")
    except FileNotFoundError:
        pass  # Docker not installed

    # Kill host processes
    if not pids:
        print("No running webui/koweb servers found (host)")
    else:
        killed = 0
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
            except ProcessLookupError:
                continue
        print(f"Stopped {killed} server(s)")

    sys.exit(0)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    from .config import Config
    config = Config()

    if args.stop:
        _stop_servers(args.port or config.PORT)

    if args.list_plugins:
        from .plugins.loader import discover_plugins
        plugins = discover_plugins()
        if not plugins:
            print("No plugins discovered.")
        else:
            for p in plugins:
                print(f"  {p.name} v{p.version}")
        sys.exit(0)

    # Apply CLI overrides
    config.apply_cli_args(host=args.host, port=args.port)
    if args.quiet:
        config.QUIET = True
    if args.auth_user and args.auth_password:
        config.enable_auth(args.auth_user, args.auth_password)
    elif args.auth_user or args.auth_password:
        logger.warning("Both -u/--auth-user and -w/--auth-password required to enable auth")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Configure uvicorn
    import copy
    import uvicorn

    log_config = None
    quiet_mode = args.quiet or config.QUIET
    if quiet_mode:
        log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        log_config["loggers"]["uvicorn.access"]["handlers"] = []
        log_config["loggers"]["uvicorn.access"]["propagate"] = False

    uvicorn.run(
        "web_ui_tools.app:create_app",
        factory=True,
        host=config.HOST,
        port=config.PORT,
        reload=args.reload,
        log_level="debug" if args.verbose else "info",
        log_config=log_config,
        access_log=not quiet_mode,
    )
```

**Step 4: Run test to verify it passes**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/cli_test.py -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/cli.py modules/web_ui_tools/tests/cli_test.py
git commit -m "feat(web_ui_tools): CLI with -s/--stop (host + Docker), --list-plugins"
```

---

### Task 11: Static files (minimal dashboard shell)

**Files:**
- Create: `modules/web_ui_tools/web_ui_tools/static/index.html`
- Create: `modules/web_ui_tools/web_ui_tools/static/style.css`
- Create: `modules/web_ui_tools/web_ui_tools/static/app.js`
- Copy: `modules/web_ui_tools/web_ui_tools/static/termdash.html` (from ai-orchestrator)

Create minimal placeholder files that follow the Grafana-style design system from `skills/web-ui-dev/references/design-system.md`. These are initial shells - Phase 2 will fully redesign them.

**Step 1: Create index.html**

Minimal dark dashboard shell with sidebar nav placeholder, WebSocket connection indicator, and a content area. Use CSS variables from the design system. Reference `/static/style.css` and `/static/app.js`.

**Step 2: Create style.css**

Define all CSS custom properties from the design system (colors, typography, spacing). Basic dark theme layout with sidebar, metric card, and table styling.

**Step 3: Create app.js**

Minimal JS: WebSocket connection management, navigation rendering (fetches `/api/nav`), plugin panel placeholder loading.

**Step 4: Copy termdash.html**

Copy from `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/static/termdash.html`.

**Step 5: Take screenshot via web-ui-dev skill workflow**

Start dev server, take baseline screenshot, verify dark theme renders correctly.

Run: `cd ~/scripts/modules/web_ui_tools && uvicorn web_ui_tools.app:create_app --factory --port 3001`

Use Playwright to navigate to http://localhost:3001 and screenshot. Evaluate against design system.

**Step 6: Commit**

```bash
git add modules/web_ui_tools/web_ui_tools/static/
git commit -m "feat(web_ui_tools): Grafana-style dashboard shell (index, CSS, JS, termdash)"
```

---

### Task 12: Create `__init__.py` files and tests/conftest.py

**Files:**
- Create: `modules/web_ui_tools/tests/__init__.py` (empty)
- Create: `modules/web_ui_tools/tests/conftest.py`

**Step 1: Create conftest.py**

```python
"""Shared test fixtures for web_ui_tools."""

import pytest
from fastapi.testclient import TestClient
from web_ui_tools.app import create_app
from web_ui_tools.config import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)
```

**Step 2: Run all tests**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/ -v`
Expected: All tests PASS.

**Step 3: Commit**

```bash
git add modules/web_ui_tools/tests/
git commit -m "test(web_ui_tools): shared conftest fixtures"
```

---

### Task 13: Install module and verify CLI

**Step 1: Install web_ui_tools in editable mode**

Run: `cd ~/scripts && .venv/bin/pip install -e modules/web_ui_tools`
Expected: Successful install with `webui` and `koweb` entry points.

**Step 2: Verify CLI entry points**

Run: `webui --help`
Expected: Shows help text with all flags.

Run: `webui --list-plugins`
Expected: "No plugins discovered." (no plugins installed yet).

Run: `koweb --help`
Expected: Same output as `webui --help` (alias).

**Step 3: Start and stop the server**

Run: `webui -p 3001 &` (background)
Expected: Server starts on port 3001.

Run: `webui -s -p 3001`
Expected: "Stopped 1 server(s)"

**Step 4: Commit (nothing to commit, just verification)**

---

### Task 14: Orchestrator plugin in ai-orchestrator

**Files:**
- Create: `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/plugin.py`
- Modify: `~/projects/ai-orchestrator/orchestrator_web_viewer/pyproject.toml` (add entry point)
- Modify: `~/projects/ai-orchestrator/orchestrator_web_viewer/orchestrator_web_viewer/main.py` (thin wrapper)

**Step 1: Create plugin.py**

```python
"""WebUI plugin for AI Orchestrator."""

from fastapi import FastAPI


class OrchestratorPlugin:
    name = "orchestrator"
    version = "0.2.0"

    def register(self, app: FastAPI) -> None:
        from .api import (
            control, knowledge, lmstudio, logs as orch_logs,
            memory_proxy, orchestrator, project_tracking,
            results, system_stats, telemetry,
        )

        app.include_router(orchestrator.router, prefix="/api/orchestrator", tags=["orchestrator"])
        app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
        app.include_router(project_tracking.router, prefix="/api/project-tracking", tags=["project_tracking"])
        app.include_router(telemetry.router, prefix="/api/telemetry", tags=["telemetry"])
        app.include_router(memory_proxy.router, prefix="/api/memory", tags=["memory"])
        app.include_router(control.router, prefix="/api/control", tags=["control"])
        app.include_router(results.router, prefix="/api/results", tags=["results"])
        app.include_router(system_stats.router, prefix="/api/system", tags=["system"])
        app.include_router(lmstudio.router, prefix="/api/lmstudio", tags=["lmstudio"])

    def get_nav_items(self) -> list[dict]:
        return [
            {"label": "Orchestrator", "path": "/orchestrator", "icon": "cpu"},
            {"label": "Knowledge", "path": "/knowledge", "icon": "database"},
            {"label": "Projects", "path": "/projects", "icon": "folder"},
            {"label": "LM Studio", "path": "/lmstudio", "icon": "zap"},
            {"label": "System", "path": "/system", "icon": "activity"},
        ]
```

**Step 2: Add entry point to pyproject.toml**

Add to `~/projects/ai-orchestrator/orchestrator_web_viewer/pyproject.toml`:

```toml
[project.entry-points."webui.plugins"]
orchestrator = "orchestrator_web_viewer.plugin:OrchestratorPlugin"
```

Also add `web-ui-tools` as a dependency:

```toml
dependencies = [
    "web-ui-tools>=0.1.0",
    # ... existing deps minus fastapi/uvicorn/websockets (now from web-ui-tools)
    "asyncpg>=0.29.0",
    "psycopg2-binary>=2.9.9",
    "python-multipart>=0.0.6",
    "jinja2>=3.1.2",
    "httpx>=0.26.0",
    "docker>=7.1.0",
]
```

**Step 3: Simplify main.py**

Replace the full app creation in `main.py` with a thin wrapper that delegates to `web_ui_tools`:

```python
"""Orchestrator Web Viewer - delegates to web_ui_tools framework."""

from web_ui_tools.cli import main

# Keep cli() as an alias for backward compat
cli = main

if __name__ == "__main__":
    cli()
```

This is a significant change. The existing `main.py` (558 lines) becomes ~10 lines. The orchestrator-specific routes are now in `plugin.py`, and the framework code lives in `web_ui_tools`.

**Step 4: Re-install and verify plugin discovery**

Run: `cd ~/scripts && .venv/bin/pip install -e ~/projects/ai-orchestrator/orchestrator_web_viewer`

Run: `webui --list-plugins`
Expected: `  orchestrator v0.2.0`

**Step 5: Start server and verify orchestrator routes**

Run: `webui -p 3001 -v`
Expected: Log shows "Loaded plugin: orchestrator v0.2.0" and "Registered plugin: orchestrator v0.2.0"

Test an orchestrator-specific endpoint:
Run: `curl -s http://localhost:3001/api/orchestrator/stats | python -m json.tool`
Expected: Returns orchestrator stats (or a sensible error if DB isn't running).

**Step 6: Commit both repos**

In `~/scripts`:
```bash
# Nothing new in scripts repo for this task
```

In `~/projects/ai-orchestrator`:
```bash
cd ~/projects/ai-orchestrator
git add orchestrator_web_viewer/orchestrator_web_viewer/plugin.py
git add orchestrator_web_viewer/pyproject.toml
git add orchestrator_web_viewer/orchestrator_web_viewer/main.py
git commit -m "refactor(web-viewer): migrate to web_ui_tools plugin architecture"
```

---

### Task 15: Delete stale scripts module

**Step 1: Verify web_ui_tools replaces orchestrator_web_viewer**

Run: `webui --list-plugins`
Expected: Shows orchestrator plugin.

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/ -v`
Expected: All tests pass.

**Step 2: Remove stale module**

Run: `rm -rf ~/scripts/modules/orchestrator_web_viewer`

**Step 3: Uninstall old package**

Run: `.venv/bin/pip uninstall -y orchestrator-web-viewer`
(Note: the editable install from the scripts module, not the ai-orchestrator one)

**Step 4: Verify nothing breaks**

Run: `webui -p 3001 &`
Run: `curl -s http://localhost:3001/api/system/health`
Expected: `{"status": "healthy", ...}`

Run: `webui -s -p 3001`

**Step 5: Commit**

```bash
cd ~/scripts
git add -A modules/orchestrator_web_viewer/  # stages the deletion
git commit -m "chore: remove stale orchestrator_web_viewer (replaced by web_ui_tools)"
```

---

### Task 16: Update docker-compose.yml

**Files:**
- Modify: `~/projects/ai-orchestrator/docker-compose.yml`

**Step 1: Update koweb service**

Change the koweb service to use the `webui` entry point and ensure `web_ui_tools` is available in the container. The service currently runs `koweb` which will still work (it's an alias), but update the command and any volume mounts.

Read the current docker-compose.yml to understand the service definition, then update:
- Command: `koweb` -> `webui` (both work, but prefer the new name)
- Ensure `web_ui_tools` package is installed in the Docker image
- Environment variables: keep `KO_WEB_*` (backward compat via `Config._env` fallback)

**Step 2: Commit**

```bash
cd ~/projects/ai-orchestrator
git add docker-compose.yml
git commit -m "chore: update koweb service to use webui entry point"
```

---

### Task 17: Run full test suite

**Step 1: Run web_ui_tools tests**

Run: `cd ~/scripts/modules/web_ui_tools && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS.

**Step 2: Run any orchestrator_web_viewer tests**

Run: `cd ~/projects/ai-orchestrator && python -m pytest orchestrator_web_viewer/tests/ -v --tb=short`
Expected: Tests pass (may need updates for new import paths).

**Step 3: Integration test**

Run: `webui -p 3001 &`
Run the following curl checks:
```bash
curl -s http://localhost:3001/api/system/health
curl -s http://localhost:3001/api/nav
curl -s http://localhost:3001/api/logs
curl -s http://localhost:3001/api/termdash/dashboards
curl -s http://localhost:3001/ | head -5
```
Expected: All return valid JSON or HTML.

Run: `webui -s -p 3001`

**Step 4: Commit any test fixes**

---

## Phase 2: Grafana-Style UI Redesign

Phase 2 is a separate effort focused on the frontend. It should use the `web-ui-dev` skill for visual iteration throughout. Each task below involves editing static files and verifying via screenshots.

### Task 18: Dashboard shell (sidebar + grid layout)

**Files:**
- Modify: `modules/web_ui_tools/web_ui_tools/static/index.html`
- Modify: `modules/web_ui_tools/web_ui_tools/static/style.css`
- Modify: `modules/web_ui_tools/web_ui_tools/static/app.js`

**Workflow:** Use the `web-ui-dev` skill (edit-screenshot-evaluate loop).

1. Start dev server: `webui -r -v -p 3001`
2. Take baseline screenshot
3. Build the sidebar navigation component:
   - Fixed left sidebar (240px width, collapsible)
   - Nav items loaded from `/api/nav`
   - Active item highlighted with accent color (#00d4aa)
   - Plugin nav items grouped by plugin
4. Build the main content grid:
   - CSS Grid with auto-fill columns, 16px gap
   - Responsive breakpoints per design system
5. Screenshot and evaluate at 1920px, 1366px, 768px
6. Iterate until design system compliant
7. Commit

---

### Task 19: Metric card component

**Files:**
- Modify: `modules/web_ui_tools/web_ui_tools/static/style.css`
- Modify: `modules/web_ui_tools/web_ui_tools/static/app.js`

**Workflow:** Use `web-ui-dev` skill.

1. Implement reusable metric card in JS (renders into grid cells)
2. Card shows: large value, small label, optional sparkline
3. CSS matches design system: `#1a1a2e` background, `#00d4aa` accent
4. Wire to `/api/system/health` for sample data (uptime, version)
5. Screenshot, evaluate, iterate
6. Commit

---

### Task 20: Data table component

**Files:**
- Modify: `modules/web_ui_tools/web_ui_tools/static/style.css`
- Modify: `modules/web_ui_tools/web_ui_tools/static/app.js`

**Workflow:** Use `web-ui-dev` skill.

1. Reusable table component with sortable headers
2. Alternating row backgrounds, monospace numerics
3. Status badges with semantic colors
4. Wire to `/api/logs` for sample data
5. Screenshot, evaluate, iterate
6. Commit

---

### Task 21: WebSocket real-time updates

**Files:**
- Modify: `modules/web_ui_tools/web_ui_tools/static/app.js`
- Modify: `modules/web_ui_tools/web_ui_tools/static/style.css`

1. WebSocket connection indicator in header (green dot when connected, red when disconnected)
2. Auto-reconnect with exponential backoff
3. Live feed panel (newest items at top, fade-in animation)
4. Wire metric cards to update via WebSocket messages
5. Test by sending messages from server and observing UI updates
6. Screenshot, verify no layout shifts during updates
7. Commit

---

### Task 22: TermDash redesign

**Files:**
- Modify: `modules/web_ui_tools/web_ui_tools/static/termdash.html`

**Workflow:** Use `web-ui-dev` skill.

1. Restyle termdash.html to match the new Grafana-style design system
2. Same sidebar, same color palette, same typography
3. Dashboard selector as dropdown or tab bar
4. Live stats rendered as metric cards (not raw terminal output)
5. Screenshot, evaluate, iterate
6. Commit

---

### Task 23: Final visual QA pass

**Workflow:** Run through `skills/web-ui-dev/references/visual-qa-checklist.md` completely.

1. Screenshot at 1920px, 1366px, 768px
2. Color compliance check
3. Typography check
4. Spacing check
5. Component check (metric cards, tables, nav)
6. Real-time elements check
7. Final polish (border-radius, transitions, favicon)
8. Fix any issues found
9. Commit

---

## Dependency Graph

```
Task 1 (skeleton)
  └─> Task 2 (config)
       └─> Task 3 (auth)
       └─> Task 10 (CLI)
  └─> Task 4 (WebSocket)
  └─> Task 5 (logs)
  └─> Task 6 (health)
  └─> Task 7 (termdash)
  └─> Task 8 (plugins)
       └─> Task 9 (app factory) [depends on 2-8]
            └─> Task 10 (CLI) [depends on 2, 9]
                 └─> Task 11 (static files)
                      └─> Task 12 (conftest)
                           └─> Task 13 (install + verify)
                                └─> Task 14 (orchestrator plugin)
                                     └─> Task 15 (delete stale)
                                     └─> Task 16 (docker-compose)
                                └─> Task 17 (full test suite)

Phase 2 (all depend on Phase 1 completion):
Task 18 (shell) → Task 19 (cards) → Task 20 (tables) → Task 21 (WebSocket UI) → Task 22 (termdash) → Task 23 (QA)
```

## Parallelizable Tasks

Within Phase 1, Tasks 2-8 can be developed in parallel (they share no dependencies beyond Task 1). Task 9 depends on all of 2-8. Tasks 14-16 can run in parallel after Task 13.

Within Phase 2, tasks are sequential (each builds on the previous UI state).
