# Notifications and Remote Control — Repository Current State & Baseline

**Baseline Date:** 2026-11-11  
**Repository:** `MaxCarlson/scripts`  
**Base Commit:** `9102815920eff843c724f4f98a7957d94d46fbb2` (`main` / `origin/main`)  
**Feature Branch:** `agent/notifications-p00-p01-20261111`  
**Feature Worktree:** `C:\Users\mcarls\src\scripts-notifications-p00-p01` (isolated sibling)

---

## 1. Git Environment & Worktree Topology

Inspection of the primary repository checkout (`C:\Users\mcarls\src\scripts`) revealed:
- **Remotes**:
  - `origin`: `git@github.com:MaxCarlson/scripts.git`
  - `aebndl-upstream`: `https://github.com/estellaarrieta/aebn-vod-downloader.git`
- **Active Branches & Worktrees**:
  - Multiple concurrent worktrees exist under `C:/Users/mcarls/src/scripts/.worktrees/` and `C:/Users/mcarls/.codex/worktrees/`, including active work on `resource-coordinator`, `llm_monitor`, `aebn`, `runmux`, and `snips`.
  - The main branch is at `91028159` ("docs(resource-coordinator): compare target validation stalls").
  - The isolated worktree `C:\Users\mcarls\src\scripts-notifications-p00-p01` was created directly off `91028159` without modifying or disrupting any existing worktrees or uncommitted changes.
- **Resource Coordinator Ownership**:
  - RC has active work recorded in recent commits and branches (`integrate/resource-coordinator-v0117-20261111`, `codex/resource-coordinator-windows-listener-readable-cli-20261106`).
  - **Constraint Enforced**: All files under `modules/resource_coordinator/` are designated as protected. No direct edits or intrusive hooks will be made to RC in this worktree.

---

## 2. Existing Component Inventory

### A. Scheduler (`modules/scheduler/scheduler/notifier.py`)
- **Current Behavior**:
  - Provides a `Notifier` class that uses `shutil.which` to pick a platform notification mechanism:
    1. Termux: `termux-notification`
    2. Linux: `notify-send`
    3. Windows: executes an inline PowerShell script creating a `System.Windows.Forms.NotifyIcon` balloon tip.
    4. macOS: AppleScript via `osascript`.
- **Hazards & Gaps Identified**:
  - The Windows implementation interpolates unescaped title and message strings directly into a PowerShell command string (`$obj.BalloonTipTitle = "{title}"; $obj.BalloonTipText = "{message}";`). This poses a command-injection hazard if notification text contains quotes, backticks, or semicolons.
  - Subprocess calls use `check=False` with `DEVNULL`, meaning delivery failures are silently masked.
  - Lacks persistent queuing, retry logic, remote delivery (e.g. Telegram), or incident lifecycle.
- **Plan**: Replace or wrap with the unified `notifications` client once stable, but leave unchanged in Phase 00–01.

### B. LLM Monitor (`modules/llm_monitor/llm_monitor/alerts.py`)
- **Current Behavior**:
  - Features an `AlertEngine` that evaluates evidence rules against `SystemSnapshot` sessions.
  - Evaluates transitions: `opened`, `reopened`, `reminded`, `resolved`, `acknowledged`.
  - Distinguishes acknowledgement from resolution (`acknowledge_alert` sets status to `acknowledged` without resolving).
  - Explicit rule: missing or stale observations cannot prove a condition has cleared ("Missing or partial observations cannot prove a condition cleared").
  - Incorporates cooldowns (`_cooldown_elapsed`) and deterministic alert hashing (`_alert_id`).
- **Reuse Value**: The incident lifecycle state machine and evidence semantics in `notifications` directly mirror these proven principles.

### C. Web UI Tools (`modules/web_ui_tools/src/web_ui_tools/app.py`)
- **Current Behavior**:
  - Standard helper creating a FastAPI app with `TrustedHostMiddleware`, `WebSocketSessionMiddleware`, and strict headers.
  - Implements a single shared `login_code`, generating an in-memory session token stored in an HTTP cookie (`web_ui_session`).
  - Enforces `LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "host.docker.internal")`.
  - Sets `secure=False` on cookies (acceptable for plain HTTP on local loopback, unsafe for public WAN).
- **Hazards & Gaps Identified**:
  - In-memory sessions do not survive service restarts.
  - `secure=False` and single shared password are not suitable for internet exposure via Tailscale Funnel.
  - WAN rollout (Phase 06–08) will require a dedicated, hardened session store, TOTP multi-factor authentication, and secure cookies (`__Host-` prefix, `Secure=True`).

### D. Runmux (`modules/runmux/src/runmux/web.py` & `ipc.py`)
- **Current Behavior**:
  - Runs a local FastAPI service that communicates with background process supervisors via loopback TCP sockets (`127.0.0.1:<port>`).
  - Authenticates IPC connections using a secret token (`record.auth_token`) sent in the initial request line.
  - Strict timeouts (`DEFAULT_SOCKET_TIMEOUT_SECONDS`) prevent callers from hanging.
- **Reuse Value**: Confirms the pattern of using loopback TCP with shared bearer token authentication and strict timeout handling.

### E. Resource Coordinator (`modules/resource_coordinator/`)
- **`resource_coordinator/core/events.py`**:
  - Event dispatch system supporting blocking lifecycle hooks (`emit_blocking`) and non-blocking observational listeners (`emit`).
  - In-process only; does not survive process crash or publish across process boundaries.
- **`resource_coordinator/cli_parser.py`**:
  - Exposes `resource-coordinator service recover -r/--reason ...` with `--resource` (default: `gpu.inference`) and `--force`.
  - Exposes `status -j/--json`.
- **`resource_coordinator/core/operator_credentials.py`**:
  - Manages operator token at `~/.resource_coordinator/secrets/operator-token`.
  - Windows security: uses `icacls.exe` to enforce inheritance removal and grant Full Control solely to the user SID and `S-1-5-18` (LocalSystem).
- **Coordination Rule**: The `notifications` broker must not alter RC internals.

### F. Phonemon & SSHManager
- **Inspection**:
  - `modules/phonemon`: Terminal-based monitor using `plotille` and `psutil`. Standalone TUI, no background daemon.
  - `modules/sshmanager`: SQLite-based credential and SSH connection manager. Standalone CLI.

---

## 3. Collision & Naming Verification

- **Module Directory**: `modules/notifications` is currently absent in `scripts/modules/`.
- **Package Name**: `notifications` is available and unique within the workspace.
- **CLI Command**: `scripts-notify` is verified absent in:
  - `[project.scripts]` across all existing `pyproject.toml` files.
  - `modules/scripts_help/scripts_help/registry/registry.py`.
  - System PATH.
- **Database Path Default**: `~/.scripts/notifications/events.db` (overrideable via `NOTIFICATIONS_DB_PATH`).
- **Token Secret Path Default**: `~/.scripts/notifications/secrets/broker-token` (overrideable via `NOTIFICATIONS_INGEST_TOKEN`).

---

## 4. Repository & Packaging Conventions

- **Build System**: `setuptools>=68`, `wheel` with standard `[build-system]`.
- **Package Layout**: `modules/notifications/notifications/` with `pyproject.toml` declaring `package-dir = {"" = "."}`.
- **CLI Options**: Both short and long options are mandatory for all user-facing flags (`-v/--verbose`, `-j/--json`, `-f/--file`, `-a/--apply`, etc.).
- **Testing Standards**:
  - Use `pytest` with test files named `*_test.py` or `test_*.py`.
  - Isolated test directory: `addopts = "-q --basetemp=modules/notifications/.pytest_tmp_root"`.
  - Coverage for models, persistence, lifecycle transitions, idempotency, and error handling using temporary databases and fake providers.

---

## 5. Phase 02 Operational Integration & Phase 03 Windows Notifications Status

- **Phase 02 Operational Integration**:
  - Dynamic provider registry (`notifications.delivery.registry.get_registered_providers`) resolves `fake_provider`, `telegram`, and `windows`.
  - Outbox runner (`scripts-notify outbox run`) automatically dispatches to all registered providers with status tracking in `delivery_attempts`.
  - Secret-safe Telegram enrollment (`scripts-notify telegram enroll`) supports interactive masking and `NOTIFY_TELEGRAM_BOT_TOKEN` environment variable without mandatory CLI argument exposure.
- **Phase 03 Windows Desktop Notifications & Hardening**:
  - Interactive Session 1+ helper (`helper.ps1`) runs non-elevated (`asInvoker`) at user logon via Task Scheduler (`ScriptsNotificationsToastHelper`).
  - Hard cumulative request body limit (32,768 bytes) enforced in `helper.ps1` with 5000ms read deadline, rejecting oversized or stalled requests with HTTP 413 or 408.
  - Non-elevation guard strictly enforced: helper immediately aborts with exit code 3 if launched under Administrator privileges.
  - Dedicated `/shutdown` loopback endpoint with dedicated shutdown token support.
  - Safe parameter passing via structured JSON over `stdin` eliminates all PowerShell string interpolation vulnerabilities.
  - Default token path aligned with `config.py` (`~/.scripts/notifications/secrets/broker-token`) with owner-restricted Windows ACLs (`icacls`).
  - Multi-provider isolation (N09) verified: Windows offline status never blocks or aborts Telegram delivery, and Telegram rate limiting never suppresses Windows desktop toasts.
  - Injection resistance (N10) and session availability semantics (N11) verified.
  - Full CLI management (`scripts-notify windows status/install/uninstall/test`) with dry-run default.

---

## 6. Phase 04 Independent Off-Host Outage Monitoring Status

- **Architecture**:
  - Implements the "dead man's snitch" pattern using Healthchecks.io outbound periodic pings.
  - Healthchecks cloud integrates directly with Telegram via `@HealthchecksBot`, alerting the operator's phone if workstation pings cease for 10 minutes (5m period + 5m grace).
  - $0 mandatory spend on Healthchecks.io free Hobbyist plan.
- **Independence & Isolation (N12 / N13)**:
  - Completely independent of the local notification broker daemon, SQLite `events.db`, local Telegram bot token, and interactive user desktop session.
  - Zero imports or dependencies on `notifications.broker`, `notifications.storage`, `sqlite3`, or `modules/resource_coordinator/`.
  - Standalone runner entrypoint: `python -m notifications.monitoring.runner`.
- **Security & Redaction**:
  - Secrets and UUIDs in ping URLs are automatically redacted (`[REDACTED_PING_UUID]`, `[REDACTED_UUID]`) from all logs, stdout, error messages, and JSON status reports.
  - HTTPS scheme strictly enforced on ping URLs; plaintext HTTP rejected.
  - Configuration saved to `~/.scripts/notifications/secrets/healthchecks.json` with owner-restricted ACLs (`icacls`).
  - Task Scheduler registration script receives arguments as structured JSON via `stdin` to eliminate PowerShell interpolation risks.
- **Diagnostics & Operations**:
  - Full CLI suite: `scripts-notify heartbeat configure`, `status`, `test`, `ping`, `install`, `repair`, `uninstall`, and `doctor`.
  - Diagnostic doctor probe checks configuration file ACLs, Task Scheduler status, and live HTTPS connectivity to `hc-ping.com`.
  - All operational mutations default to dry-run and require `-a/--apply`.
- **Automated Test Validation**:
  - Total automated notifications suite: 124 passing tests (38 dedicated to Phase 04 monitoring).
  - Broader repository test suite: 55 `scripts_help` tests passing.

---

## 7. Phase 04 Operational Stabilization & Phase 06 Read-Only Mobile Dashboard Status

- **Phase 04 Operational Stabilization**:
  - **Atomic Configuration Writes**: Replaced direct secret file writes in `save_healthchecks_config` with unpredictable temporary files (`tempfile.mkstemp`), pre-securing Windows owner-only ACLs before atomic destination replacement (`os.replace`).
  - **Headless Task Scheduler Differentiation**: Added `--headless` / `--system` flag and execution mode detection to `modules/notifications/notifications/monitoring/service.py` (`ServiceAccount` / `NT AUTHORITY\SYSTEM` running 24/7 without active user logon vs `InteractiveToken` user mode requiring active logon).
  - **Runner Exception Redaction**: Protected top-level uncaught exceptions in `runner.py` with secret redaction.
  - **Outage Documentation**: Added comprehensive execution mode matrix and local logged-off reboot validation procedures in `docs/notifications-remote-control/outage-monitoring.md`.
  - Checkpoint committed to `agent/notifications-p04-stabilization-p06-dashboard-20261111` as commit `6e22ca92`.

- **Phase 06 Authenticated Read-Only Remote Dashboard & Mobile PWA**:
  - **Module Directory**: `modules/remote_control/` with CLI entrypoint `scripts-remote-control`.
  - **Zero Spending**: Operates with $0 mandatory cost; zero paid hosting, cloud subscriptions, or external accounts required.
  - **Strict Read-Only Boundary**: Non-mutating queries only. All queries against the durable notifications database open SQLite connections in strict read-only URI mode (`file:... ?mode=ro`). Zero arbitrary process execution, shell commands, or Resource Coordinator mutations.
  - **Authentication Architecture**:
    - Single human operator policy bootstrapped strictly via host console (`scripts-remote-control bootstrap`).
    - Argon2id password hashing + RFC 6238 TOTP two-factor authentication.
    - TOTP replay prevention tracking consumed timesteps in SQLite.
    - Rate limiting and brute force lockout (5 failed attempts within 15m triggers HTTP 429 lockout).
    - Session management with sliding window idle timeout (4h) and absolute lifetime (7d).
    - Personal device tracking with permanent device revocation.
    - Append-only security audit ledger in `auth.db`.
  - **HTTP Security & Network Isolation**:
    - Hardened cookies: `HttpOnly`, `SameSite=Strict`, `Path=/`, and conditional `Secure` (`__Host-` prefix).
    - Mandatory `X-CSRF-Token` validation on all state-changing endpoints.
    - Security headers: strict Content-Security-Policy (CSP), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
    - Disallowed Host header rejection (400) and cross-origin Origin rejection (403).
    - `Cache-Control: no-store, no-cache, must-revalidate` on all `/api/*` endpoints.
    - Initially bound strictly to `127.0.0.1:8443` (loopback only).
  - **Mobile PWA Capabilities**:
    - Mobile-first responsive UI (48px touch targets, dark/light themes, offline status banner).
    - Standalone home screen launch support via `manifest.json`.
    - Service Worker (`sw.js`) caching static shell assets only, with strict network passthrough for `/api/*` requests.
    - DOM-safe XSS-free UI logic (`h()` element creator, no `innerHTML`).
  - **Forward Compatibility**:
    - Phase 05 Resource Coordinator placeholder contract (`/api/coordinator`).
  - **Validation Evidence**:
    - Remote control test suite: 34 passing tests (`modules/remote_control/tests/`).
    - Notifications test suite: 128 passing tests, 1 skipped (`modules/notifications/tests/`).
    - Scripts help test suite: 55 passing tests (`modules/scripts_help/tests/`).


