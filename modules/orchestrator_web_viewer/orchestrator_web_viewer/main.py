#!/usr/bin/env python3
"""
Orchestrator Web Viewer - Main Application
Web-based interface for AI Orchestrator and Knowledge Manager monitoring
"""
import argparse
import asyncio
import base64
import logging
import os
import secrets
from pathlib import Path
from typing import Optional, Annotated

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware

from .api import control, knowledge, logs, memory_proxy, orchestrator, project_tracking, results, telemetry, termdash
from .websocket import manager
from .log_utils import install_log_buffer

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
install_log_buffer()


# Configuration from environment
class Config:
    """Application configuration"""
    # PostgreSQL config (KO_WEB_POSTGRES_* preferred, falls back to POSTGRES_*)
    POSTGRES_HOST: str = os.getenv("KO_WEB_POSTGRES_HOST", os.getenv("POSTGRES_HOST", "localhost"))
    POSTGRES_PORT: int = int(os.getenv("KO_WEB_POSTGRES_PORT", os.getenv("POSTGRES_PORT", "5432")))
    POSTGRES_USER: str = os.getenv("KO_WEB_POSTGRES_USER", os.getenv("POSTGRES_USER", "km_user"))
    POSTGRES_PASSWORD: str = os.getenv("KO_WEB_POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))
    POSTGRES_DB: str = os.getenv("KO_WEB_POSTGRES_DB", os.getenv("POSTGRES_DB", "knowledge_manager"))

    # Task queue path (KO_WEB_TASK_QUEUE_PATH preferred, falls back to TASK_QUEUE_PATH)
    TASK_QUEUE_PATH: str = os.getenv("KO_WEB_TASK_QUEUE_PATH", os.getenv("TASK_QUEUE_PATH",
                                      os.path.expanduser("~/projects/ai-orchestrator/task_queue")))

    # Orchestrator API
    ORCHESTRATOR_API_BASE: str = os.getenv(
        "KO_WEB_ORCH_URL",
        os.getenv("ORCHESTRATOR_API_URL", "http://localhost:8000")
    )

    # Web server config (KO_WEB_HOST, KO_WEB_PORT, KO_WEB_QUIET)
    HOST: str = os.getenv("KO_WEB_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("KO_WEB_PORT", "3000"))
    QUIET: bool = os.getenv("KO_WEB_QUIET", "").lower() in ("1", "true", "yes")

    # Authentication (KO_WEB_AUTH_* preferred, falls back to WEB_AUTH_*)
    AUTH_ENABLED: bool = False
    AUTH_USERNAME: str = os.getenv("KO_WEB_AUTH_USER", os.getenv("WEB_AUTH_USER", "admin"))
    AUTH_PASSWORD: str = os.getenv("KO_WEB_AUTH_PASSWORD", os.getenv("WEB_AUTH_PASSWORD", ""))


config = Config()
os.environ.setdefault("KO_WEB_ORCH_URL", config.ORCHESTRATOR_API_BASE)


def check_auth(request: Request) -> Optional[str]:
    """Check HTTP Basic Auth manually without auto-triggering browser dialog"""
    # If auth is NOT enabled, allow access
    if not config.AUTH_ENABLED:
        return None

    # Auth is enabled - check for Authorization header
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        # No credentials provided - require auth
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=\"Orchestrator Web Viewer\""},
        )

    # Parse Basic auth header
    try:
        scheme, credentials = auth_header.split()
        if scheme.lower() != "basic":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Basic realm=\"Orchestrator Web Viewer\""},
            )

        # Decode base64 credentials
        decoded = base64.b64decode(credentials).decode("utf-8")
        username, password = decoded.split(":", 1)

        # Validate credentials using constant-time comparison
        username_matches = secrets.compare_digest(username, config.AUTH_USERNAME)
        password_matches = secrets.compare_digest(password, config.AUTH_PASSWORD)

        if not (username_matches and password_matches):
            logger.warning(f"Failed login attempt for user: {username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Basic realm=\"Orchestrator Web Viewer\""},
            )

        logger.info(f"Successful login: {username}")
        return username

    except (ValueError, UnicodeDecodeError) as e:
        logger.error(f"Auth header parse error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
            headers={"WWW-Authenticate": "Basic realm=\"Orchestrator Web Viewer\""},
        )


# FastAPI app
app = FastAPI(
    title="Orchestrator Web Viewer",
    description="Real-time monitoring for AI Orchestrator and Knowledge Manager",
    version="0.1.0"
)

# CORS - Allow LAN access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins on LAN
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
ws_manager = manager.ConnectionManager()


# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root(user: Annotated[Optional[str], Depends(check_auth)] = None):
    """Serve main page"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    # Fallback if static files not built yet
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Orchestrator Web Viewer</title>
        <style>
            body {
                font-family: system-ui, -apple-system, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background: #1a1a1a;
                color: #fff;
            }
            .status { color: #10b981; }
            .error { color: #ef4444; }
            pre { background: #2a2a2a; padding: 10px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <h1>🚀 Orchestrator Web Viewer</h1>
        <p class="status">✓ Backend server running</p>
        <h2>Configuration</h2>
        <pre>
PostgreSQL: {config.POSTGRES_HOST}:{config.POSTGRES_PORT}
Database: {config.POSTGRES_DB}
Task Queue: {config.TASK_QUEUE_PATH}
        </pre>
        <h2>API Endpoints</h2>
        <ul>
            <li><a href="/api/orchestrator/stats">/api/orchestrator/stats</a></li>
            <li><a href="/api/tasks">/api/tasks</a></li>
            <li><a href="/api/projects">/api/projects</a></li>
            <li><a href="/termdash">TermDash Viewer</a></li>
            <li><a href="/docs">/docs</a> - API Documentation</li>
        </ul>
        <p><em>Frontend UI coming soon...</em></p>
    </body>
    </html>
    """)


@app.get("/termdash", response_class=HTMLResponse)
async def termdash_viewer(user: Annotated[Optional[str], Depends(check_auth)] = None):
    """Serve TermDash viewer page"""
    termdash_file = STATIC_DIR / "termdash.html"
    if termdash_file.exists():
        return FileResponse(termdash_file)
    
    return HTMLResponse("<h1>TermDash viewer not available</h1>", status_code=404)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "postgres": f"{config.POSTGRES_HOST}:{config.POSTGRES_PORT}",
        "task_queue": config.TASK_QUEUE_PATH
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await ws_manager.connect(websocket)
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "subscribe":
                task_id = data.get("task_id")
                logger.info(f"Client subscribed to task {task_id}")
                # TODO: Track subscription

            elif message_type == "unsubscribe":
                task_id = data.get("task_id")
                logger.info(f"Client unsubscribed from task {task_id}")
                # TODO: Remove subscription

            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        logger.info("Client disconnected")


# Include API routers (with auth dependency if enabled)
if config.AUTH_ENABLED:
    app.include_router(
        orchestrator.router,
        prefix="/api/orchestrator",
        tags=["orchestrator"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        knowledge.router,
        prefix="/api",
        tags=["knowledge"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        project_tracking.router,
        prefix="/api/project-tracking",
        tags=["project_tracking"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        telemetry.router,
        prefix="/api/telemetry",
        tags=["telemetry"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        memory_proxy.router,
        prefix="/api/memory",
        tags=["memory"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        logs.router,
        prefix="/api/logs",
        tags=["logs"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        control.router,
        prefix="/api/control",
        tags=["control"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        results.router,
        prefix="/api/results",
        tags=["results"],
        dependencies=[Depends(check_auth)]
    )
    app.include_router(
        termdash.router,
        prefix="/api/termdash",
        tags=["termdash"],
        dependencies=[Depends(check_auth)]
    )
else:
    app.include_router(orchestrator.router, prefix="/api/orchestrator", tags=["orchestrator"])
    app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
    app.include_router(project_tracking.router, prefix="/api/project-tracking", tags=["project_tracking"])
    app.include_router(telemetry.router, prefix="/api/telemetry", tags=["telemetry"])
    app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
    app.include_router(memory_proxy.router, prefix="/api/memory", tags=["memory"])
    app.include_router(control.router, prefix="/api/control", tags=["control"])
    app.include_router(results.router, prefix="/api/results", tags=["results"])
    app.include_router(termdash.router, prefix="/api/termdash", tags=["termdash"])


# Background tasks
@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("=" * 60)
    logger.info("Orchestrator Web Viewer Starting")
    logger.info(f"PostgreSQL: {config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}")
    logger.info(f"Task Queue: {config.TASK_QUEUE_PATH}")
    logger.info(f"Orchestrator API: {config.ORCHESTRATOR_API_BASE}")
    logger.info(f"Listening on: http://{config.HOST}:{config.PORT}")
    if config.AUTH_ENABLED:
        logger.info(f"Authentication: ENABLED (user: {config.AUTH_USERNAME})")
    else:
        logger.info("Authentication: DISABLED (open access)")
    if config.QUIET:
        logger.info("Access Logging: DISABLED (quiet mode)")
    logger.info("=" * 60)

    # TODO: Start background tasks
    # - PostgreSQL LISTEN/NOTIFY subscriber
    # - Task queue filesystem watcher
    # - Worker status poller


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down Orchestrator Web Viewer...")
    # TODO: Cleanup background tasks


def cli():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Orchestrator Web Viewer - Real-time monitoring interface"
    )
    parser.add_argument(
        "-H", "--host",
        default=None,
        help="Host to bind to (default: from KO_WEB_HOST env or 0.0.0.0)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=None,
        help="Port to listen on (default: from KO_WEB_PORT env or 3000)"
    )
    parser.add_argument(
        "-g", "--postgres-host",
        default=None,
        help="PostgreSQL host (default: from POSTGRES_HOST env or localhost)"
    )
    parser.add_argument(
        "-P", "--postgres-port",
        type=int,
        default=None,
        help="PostgreSQL port (default: from POSTGRES_PORT env or 5432)"
    )
    parser.add_argument(
        "-d", "--postgres-db",
        default=None,
        help="PostgreSQL database (default: from POSTGRES_DB env or knowledge_manager)"
    )
    parser.add_argument(
        "-t", "--task-queue",
        default=None,
        help="Task queue path (default: from TASK_QUEUE_PATH env)"
    )
    parser.add_argument(
        "-O", "--orchestrator-url",
        default=None,
        help="Base URL for AI Orchestrator API (default: KO_WEB_ORCH_URL env or http://localhost:8000)"
    )
    parser.add_argument(
        "-r", "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress HTTP access logs (reduce console spam)"
    )
    parser.add_argument(
        "-u", "--auth-user",
        default=None,
        help="Username for HTTP Basic Auth (enables authentication)"
    )
    parser.add_argument(
        "-w", "--auth-password",
        default=None,
        help="Password for HTTP Basic Auth"
    )
    parser.add_argument(
        "-s", "--stop",
        action="store_true",
        help="Stop any running koweb servers"
    )

    args = parser.parse_args()

    # Handle --stop command
    if args.stop:
        import os
        import signal
        import subprocess
        import sys

        def _list_koweb_pids() -> set[int]:
            """Return PIDs for running koweb processes (excluding this one)."""
            pids: set[int] = set()
            current_pid = os.getpid()
            target_port = args.port or config.PORT

            # Try to capture any processes currently bound to the configured port
            try:
                port_result = subprocess.run(
                    ["lsof", "-t", f"-iTCP:{target_port}", "-sTCP:LISTEN"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if port_result.returncode == 0:
                    for line in port_result.stdout.splitlines():
                        line = line.strip()
                        if line:
                            pids.add(int(line))
            except FileNotFoundError:
                # lsof may not be installed (Termux/Android). Fall back to process scans below.
                pass

            # Fall back to scanning for koweb commands
            try:
                proc_result = subprocess.run(
                    ["pgrep", "-f", "koweb"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError:
                proc_result = None

            if proc_result and proc_result.returncode == 0:
                for line in proc_result.stdout.splitlines():
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
                    if "--stop" in cmdline or "koweb" not in cmdline:
                        continue
                    pids.add(pid)

            return pids

        try:
            targets = _list_koweb_pids()
            if not targets:
                print("✓ No running koweb servers found")
                sys.exit(0)

            killed = 0
            for pid in targets:
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed += 1
                except ProcessLookupError:
                    continue
            print(f"✓ Stopped {killed} koweb server(s)")
            sys.exit(0)
        except Exception as exc:
            print(f"✗ Error stopping servers: {exc}")
            sys.exit(1)

    # Update config from CLI args (only if provided)
    if args.host:
        config.HOST = args.host
    if args.port:
        config.PORT = args.port
    if args.postgres_host:
        config.POSTGRES_HOST = args.postgres_host
    if args.postgres_port:
        config.POSTGRES_PORT = args.postgres_port
    if args.postgres_db:
        config.POSTGRES_DB = args.postgres_db
    if args.task_queue:
        config.TASK_QUEUE_PATH = args.task_queue
    if args.orchestrator_url:
        config.ORCHESTRATOR_API_BASE = args.orchestrator_url
        os.environ["KO_WEB_ORCH_URL"] = config.ORCHESTRATOR_API_BASE

    # Enable authentication if credentials provided
    if args.auth_user and args.auth_password:
        config.AUTH_ENABLED = True
        config.AUTH_USERNAME = args.auth_user
        config.AUTH_PASSWORD = args.auth_password
        logger.info("Authentication enabled")
    elif args.auth_user or args.auth_password:
        logger.warning("Both --auth-user and --auth-password must be provided to enable authentication")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine quiet mode (CLI arg overrides env var)
    quiet_mode = args.quiet or config.QUIET

    # Configure uvicorn logging
    log_config = None
    if quiet_mode:
        # Disable access logging to reduce console spam
        import copy
        log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
        log_config["loggers"]["uvicorn.access"]["handlers"] = []
        log_config["loggers"]["uvicorn.access"]["propagate"] = False

    # Run server
    uvicorn.run(
        "orchestrator_web_viewer.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=args.reload,
        log_level="info" if not args.verbose else "debug",
        log_config=log_config,
        access_log=not quiet_mode  # Disable access log in quiet mode
    )


if __name__ == "__main__":
    cli()
