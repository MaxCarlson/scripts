# Runmux Web Server Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide robust existing-instance discovery, exact credential recovery, post-bind startup reporting, and graceful authenticated stop/status controls for `runmux web`, while guaranteeing managed process independence.

**Architecture:** A dedicated `server_lifecycle.py` module in `runmux` encapsulates owner-scoped instance descriptors (`server_{port}.json`), filesystem security (symlink rejection and Windows ACL / POSIX 0600 mode enforcement), zero-knowledge HMAC challenge-response verification, pre-bound loopback socket initialization, internal ASGI control routes (`/_runmux/health`, `/_runmux/control/shutdown`), and CLI integration for `runmux web`, `runmux web -x/--stop`, and `runmux web -S/--status`.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, psutil, Windows icacls / POSIX permissions, socket, hmac/hashlib.

**Spec:** User request: "Runmux Web UI — Server Lifecycle Management and LLM Monitor Integration", October 29, 2026.

## Global Constraints

- Retain CLI compatibility: short and long options for all arguments.
- Stopping Web UI must never stop, kill, pause, or restart supervised Runmux processes.
- Disallow unauthenticated disclosure of login credentials or control secrets.
- Zero-knowledge HMAC challenge-response: never send control secrets to an unverified service.
- Reject attacker-controlled symbolic links and unverified filesystem paths.
- Enforce owner-only permissions on instance descriptors on Windows (via icacls ACL restriction) and POSIX (0600 mode).
- Do not modify `modules/local_agent_bridge/` or `modules/llm_monitor/`.
- Do not modify shared frontend files while Phase 6C is unmerged.
- Workstream A must be fully deliverable and testable independently.

## Review Focus

1. **Simultaneous startup race:** When two instances start concurrently, one binds the socket, the other catches the bind collision, verifies the running instance, and prints the existing connection details with exit code 0.
2. **Stale descriptor detection:** When a descriptor exists on disk but the PID is dead or reused by an unrelated process, process creation timestamp and challenge-response failure detect it as stale; startup cleans it up, while `--status` reports diagnostic information.
3. **Unrelated port occupancy:** If an alien process occupies the port, the client attempts zero-knowledge challenge-response, safely detects that it is not a genuine Runmux instance, and reports the conflict without leaking secrets.
4. **Independent process supervisor invariant:** Stopping the Web UI server terminates only the Uvicorn/FastAPI process and its telemetry worker; supervised processes in the registry continue running without interruption.
5. **Symlink and malformed descriptor protection:** Descriptor reader rejects symlinks and invalid JSON, failing closed without disclosing unverified credentials.

---

### Task 1: Server Descriptor and Filesystem Security Model

**Files:**
- Create: `modules/runmux/src/runmux/server_lifecycle.py`
- Test: `modules/runmux/tests/web_server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `ServerDescriptor`: dataclass containing `instance_id: str`, `version: int`, `protocol: str`, `host: str`, `port: int`, `state_dir: str`, `pid: int`, `process_create_time: float | None`, `started_at: str`, `access_code: str`, `control_token: str`
  - `descriptor_path(state_dir: Path, port: int) -> Path`
  - `write_descriptor(path: Path, descriptor: ServerDescriptor) -> None`
  - `read_descriptor(path: Path) -> ServerDescriptor | None`
  - `remove_descriptor(path: Path) -> None`
  - `enforce_owner_permissions(path: Path) -> None`
  - `verify_owner_permissions(path: Path) -> bool`

- [ ] **Step 1: Write failing tests for descriptor serialization and security**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement `ServerDescriptor`, serialization, owner-only ACL/mode enforcement, and symlink protection**
- [ ] **Step 4: Run tests to verify pass**

---

### Task 2: Zero-Knowledge Verification and Control Protocol

**Files:**
- Modify: `modules/runmux/src/runmux/server_lifecycle.py`
- Test: `modules/runmux/tests/web_server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `verify_running_instance(descriptor: ServerDescriptor, timeout: float = 2.0) -> VerificationResult`
  - `request_instance_shutdown(descriptor: ServerDescriptor, timeout: float = 5.0) -> bool`
  - `mount_control_routes(app: FastAPI, descriptor: ServerDescriptor, shutdown_event: asyncio.Event) -> None`

- [ ] **Step 1: Write failing tests for HMAC challenge-response verification and signed shutdown request**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement HMAC challenge generation, server response verification, and signed shutdown trigger**
- [ ] **Step 4: Run tests to verify pass**

---

### Task 3: Startup Correctness and Pre-bound Socket Management

**Files:**
- Modify: `modules/runmux/src/runmux/server_lifecycle.py`
- Modify: `modules/runmux/src/runmux/web.py`
- Test: `modules/runmux/tests/web_server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - `bind_loopback_socket(host: str, port: int) -> socket.socket`
  - `create_managed_web_server(state_dir: Path, host: str, port: int, login_code: str, ...) -> tuple[uvicorn.Server, ServerDescriptor, Callable[[], None]]`

- [ ] **Step 1: Write failing tests for socket pre-binding and post-bind startup notification**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement socket pre-binding with `SO_EXCLUSIVEADDRUSE` on Windows / `SO_REUSEADDR` on POSIX and server startup handler**
- [ ] **Step 4: Run tests to verify pass**

---

### Task 4: CLI Web Discovery, Stop (`-x/--stop`), and Status (`-S/--status`)

**Files:**
- Modify: `modules/runmux/src/runmux/cli.py`
- Modify: `modules/runmux/src/runmux/server_lifecycle.py`
- Test: `modules/runmux/tests/web_cli_test.py`
- Test: `modules/runmux/tests/web_server_lifecycle_test.py`

**Interfaces:**
- Produces:
  - CLI arguments `-x/--stop` and `-S/--status`
  - `handle_web(args: argparse.Namespace) -> int` supporting:
    - Discovery of running server -> print "Already running", existing URL, original access code, PID, return 0
    - `--status` -> print current status, URL, code, PID, state directory without mutating
    - `--stop` -> authenticated graceful shutdown, wait for termination, clean descriptor, return 0 (or report "Not running" if already stopped)

- [ ] **Step 1: Write failing CLI tests for discovery, stop, and status**
- [ ] **Step 2: Run tests to verify failure**
- [ ] **Step 3: Implement CLI argument parsing and lifecycle dispatch in `cli.py`**
- [ ] **Step 4: Run tests to verify pass**

---

### Task 5: Security, Invariant, and Integration Verification

**Files:**
- Test: `modules/runmux/tests/web_server_lifecycle_test.py`
- Test: `modules/runmux/tests/web_test.py`
- Test: `modules/runmux/tests/web_cli_test.py`

- [ ] **Step 1: Implement full integration test verifying that stopping the Web UI leaves managed runs alive**
- [ ] **Step 2: Implement security test verifying unauthorized callers cannot trigger shutdown or steal credentials**
- [ ] **Step 3: Implement concurrency test simulating simultaneous startup race**
- [ ] **Step 4: Run all runmux test suites and Ruff checks**
