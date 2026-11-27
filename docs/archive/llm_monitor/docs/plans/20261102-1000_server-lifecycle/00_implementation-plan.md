# LLM Monitor Web Server Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native CLI and programmatic controls to discover, inspect status, preview shutdown, gracefully stop, and forcefully terminate LLM Monitor web instances reliably without guessing PIDs or corrupting active recordings.

**Architecture:** A dedicated `server_lifecycle.py` module encapsulates owner-scoped instance descriptors (`server_{port}.json`), filesystem security (reparse point / symlink rejection, Windows icacls owner-only ACLs, POSIX 0600 mode), zero-knowledge HMAC challenge-response verification, pre-bound loopback socket management, internal loopback ASGI management routes (`/_llm_monitor/health`, `/_llm_monitor/control/shutdown`), active request draining, and durable inference recorder flush verification before server exit. The CLI integrates `status` and `stop` actions with dry-run preview, `-x/--execute`, and `-f/-F/--force` support while strictly preserving legacy startup CLI syntax.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, psutil, Windows icacls / POSIX permissions, socket, hmac/hashlib, sqlite3.

**Spec:** User request: "Implementation Handoff — LLM Monitor Server Status & Stop Commands", November 2, 2026.

## Global Constraints

- Retain exact existing startup syntax: `llm-monitor web -p 8788 --gateway -R content` must start the server without modification.
- Support `-p/--port`, `-x/--execute`, and `-f/-F/--force` with defaults consistent with the existing CLI.
- Disallow forced termination unless `-x/--execute` is explicitly supplied.
- Never terminate a process based solely on port number or executable name; verify PID and process creation time.
- Zero-knowledge HMAC challenge-response: never send control secrets across HTTP; verify server ownership via challenge signature.
- Reject symlinks, junctions, and reparse points for descriptor files and runtime state directories.
- Enforce owner-only permissions on descriptors (icacls on Windows, 0600 mode on POSIX).
- Graceful shutdown must reject new requests, drain active requests, and flush the inference recorder; if recorder flush fails, report failure explicitly and do not convert incomplete recording into a clean shutdown.
- Support Windows 11 first, with appropriate POSIX behavior for Linux/macOS.
- Never interrupt currently running user services or active benchmarks during testing; use disposable test instances with temporary isolated state roots.

## Review Focus

1. **Recorder flush failure reporting:** If recorder.flush() fails or times out during graceful shutdown, shutdown endpoint reports recorder flush failure, and stop command returns non-zero without pretending success.
2. **Stale PID and PID reuse protection:** When a descriptor file exists but the PID does not exist or has a different creation timestamp, the server is identified as not running (stale descriptor) and safely cleaned up without killing any process.
3. **Simultaneous startup race / already running instance:** When a second server is launched on an already-occupied port running a verified LLM Monitor instance, it reports that the server is already running with its URL and PID and exits 0 cleanly.
4. **Port occupied by unrelated or unmanaged service:** When a port is occupied by an alien service or legacy unmanaged instance without verified descriptors, status/stop refuses to terminate and reports unmanaged/unverifiable state.
5. **Dry-run preview invariant:** `llm-monitor web stop -p 8788` without `-x/--execute` previews the server to be stopped and explains how to execute without terminating the process or modifying state.

---

### Task 1: Server Descriptor, Filesystem Security Model, and Process Identity

**Files:**
- Create: `modules/llm_monitor/llm_monitor/server_lifecycle.py`
- Test: `modules/llm_monitor/tests/server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `ServerDescriptor`: dataclass containing `instance_id: str`, `version: int`, `protocol: str`, `host: str`, `port: int`, `pid: int`, `process_create_time: float | None`, `started_at: str`, `control_token: str`, `gateway_enabled: bool`, `recording_mode: str | None`, `database_path: str | None`
  - `default_runtime_dir(state_dir: Path | str | None = None) -> Path`
  - `descriptor_path(port: int, host: str = "127.0.0.1", state_dir: Path | str | None = None) -> Path`
  - `is_reparse_point_or_symlink(path: Path) -> bool`
  - `enforce_owner_permissions(path: Path, is_dir: bool = False) -> None`
  - `verify_owner_permissions(path: Path) -> bool`
  - `write_descriptor(path: Path, descriptor: ServerDescriptor) -> None`
  - `read_descriptor(path: Path) -> ServerDescriptor | None`
  - `remove_descriptor(path: Path) -> bool`
  - `list_descriptors(state_dir: Path | str | None = None) -> list[ServerDescriptor]`
  - `is_process_alive(pid: int, expected_create_time: float | None = None) -> bool`
  - `verify_process_identity(descriptor: ServerDescriptor) -> bool`

- [ ] **Step 1: Write failing tests for descriptor serialization, filesystem ACL/mode enforcement, symlink rejection, and PID verification**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement `ServerDescriptor`, secure descriptor persistence, and PID / creation time validation in `server_lifecycle.py`**
- [ ] **Step 4: Run test to verify pass**

---

### Task 2: Zero-Knowledge Verification and Authenticated Shutdown Protocol

**Files:**
- Modify: `modules/llm_monitor/llm_monitor/server_lifecycle.py`
- Test: `modules/llm_monitor/tests/server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `compute_challenge_hmac(token: str, instance_id: str, challenge: str) -> str`
  - `compute_shutdown_hmac(token: str, instance_id: str, timestamp: float, nonce: str) -> str`
  - `verify_running_instance(descriptor: ServerDescriptor, timeout: float = 2.0) -> dict[str, Any] | None`
  - `request_instance_shutdown(descriptor: ServerDescriptor, timeout: float = 5.0) -> tuple[bool, str | None]`
  - `mount_control_routes(app: FastAPI, descriptor: ServerDescriptor, shutdown_event: asyncio.Event, recorder: Any | None = None, live_store: Any | None = None) -> None`

- [ ] **Step 1: Write failing tests for HMAC challenge verification, signed shutdown requests, and loopback protection**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement HMAC challenge calculation, verification protocol, loopback origin checks, and control route handlers**
- [ ] **Step 4: Run test to verify pass**

---

### Task 3: Graceful Request Draining, Durable Recorder Flush, and Forced Termination

**Files:**
- Modify: `modules/llm_monitor/llm_monitor/server_lifecycle.py`
- Modify: `modules/llm_monitor/llm_monitor/gateway.py`
- Test: `modules/llm_monitor/tests/server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - Shutdown handler rejects new gateway/inference requests (`503 Service Unavailable`)
  - Waits for active inference requests (`live_store.active_request_count() == 0`) with bounded timeout
  - Drains and flushes `recorder.flush(timeout=5.0)` and verifies commit
  - Returns explicit error if recorder flush fails; does not proceed with normal clean shutdown
  - `force_terminate_process(descriptor: ServerDescriptor) -> bool`
  - `stop_server(port: int | None = None, host: str = "127.0.0.1", execute: bool = False, force: bool = False, state_dir: Path | str | None = None, timeout: float = 5.0, as_json: bool = False) -> int`

- [ ] **Step 1: Write failing tests for graceful request drain, recorder flush verification, dry-run preview, and explicit force termination**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement request rejection on shutdown in gateway, recorder flush handling in control route, preview mode, and force termination**
- [ ] **Step 4: Run test to verify pass**

---

### Task 4: Web Server Runner Integration, Pre-bound Socket, and Status Command

**Files:**
- Modify: `modules/llm_monitor/llm_monitor/server_lifecycle.py`
- Modify: `modules/llm_monitor/llm_monitor/web.py`
- Test: `modules/llm_monitor/tests/server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `bind_loopback_socket(host: str, port: int) -> socket.socket`
  - `LLMMonitorWebServer(uvicorn.Server)`
  - `status_server(port: int | None = None, host: str = "127.0.0.1", state_dir: Path | str | None = None, as_json: bool = False) -> int`
  - Updated `run_web` in `web.py` supporting socket pre-binding, existing instance detection, descriptor lifecycle, and control route registration.

- [ ] **Step 1: Write failing tests for `status_server`, socket binding, and `run_web` integration**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Implement socket binding with exclusive address protection, server subclass, status reporter, and `run_web` integration**
- [ ] **Step 4: Run test to verify pass**

---

### Task 5: CLI Command Syntax Integration & Regression Tests

**Files:**
- Modify: `modules/llm_monitor/llm_monitor/cli.py`
- Test: `modules/llm_monitor/tests/cli_test.py`
- Test: `modules/llm_monitor/tests/server_lifecycle_test.py`

**Interfaces:**
- CLI commands:
  - `llm-monitor web -p 8788 --gateway -R content` (starts server)
  - `llm-monitor web status -p 8788` (inspects server status)
  - `llm-monitor web stop -p 8788` (preview dry-run)
  - `llm-monitor web stop -p 8788 -x` (gracefully stops server)
  - `llm-monitor web stop -p 8788 -x --force` (force termination if graceful fails)

- [ ] **Step 1: Write failing CLI tests for all required CLI forms, options, and error cases**
- [ ] **Step 2: Run test to verify failure**
- [ ] **Step 3: Wire CLI arguments and handlers in `cli.py`**
- [ ] **Step 4: Run test to verify pass**

---

### Task 6: Full Verification, Documentation, and Handoff

**Files:**
- Modify: `modules/llm_monitor/README.md`
- Update: `modules/llm_monitor/docs/plans/20261102-1000_server-lifecycle/STATUS.md`
- Update: `modules/llm_monitor/docs/plans/20261102-1000_server-lifecycle/checklist.md`
- Update: `modules/llm_monitor/docs/HANDOFF.md`

- [ ] **Step 1: Run all module tests, Ruff, and integration scenarios**
- [ ] **Step 2: Update documentation and CLI examples in module README**
- [ ] **Step 3: Record verification evidence and update status ledger**
