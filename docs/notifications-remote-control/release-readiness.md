# Release Readiness & Subsystem Operational Inventory (Phase 09)

**Document Version:** 1.0.0  
**Phase:** Phase 09 — Adoption, Release Integration, and Operational Readiness  
**Repository:** `MaxCarlson/scripts`  
**Base Commit:** `942c096d49a8aee205e6bd595621d8a22def3a9b` (`main`)  
**Feature Branch:** `agent/notifications-p09-adoption-release-20261111`  

---

## 1. Evidence Level Standard

To prevent false confidence derived purely from mock test suites, operational evidence across all subsystems is categorized using this strict five-level hierarchy:

| Level | Classification | Description |
| :---: | :--- | :--- |
| **L1** | **Unit Tested** | Component behavior validated in isolated in-memory unit tests with mocked filesystem/network. |
| **L2** | **Synthetic Integration** | Multi-component contracts, concurrency, and crash recovery validated using local test databases, loopback HTTP, and simulated failures. |
| **L3** | **Workstation Verified** | Process executed manually or via automated harness on the actual Windows workstation (interactive desktop session, WinRT APIs, Windows Task Scheduler). |
| **L4** | **Real External Service** | End-to-end delivery verified against live external infrastructure (real Telegram Bot API over cellular, live Healthchecks.io ping, live Tailscale Funnel). |
| **L5** | **Blocked / Operator Gate** | Operation deliberately disabled by design (e.g. live Resource Coordinator recovery) or requiring explicit operator authorization before execution. |

---

## 2. Subsystem Operational Inventory

### 2.1 Notifications Broker & Storage Engine

- **Module / Entrypoints:** `modules/notifications` | CLI: `scripts-notify` (`notifications.cli:main`), Python API: `notifications.publisher.Publisher`.
- **Config & Secret Locations:**
  - Database: `%USERPROFILE%\.scripts\notifications\events.db` (override: `NOTIFICATIONS_DB_PATH`).
  - Broker Auth Token: `%USERPROFILE%\.scripts\notifications\secrets\broker-token` (override: `NOTIFICATIONS_TOKEN_FILE` / `NOTIFICATIONS_INGEST_TOKEN`). Restrictive ACLs enforced (owner + SYSTEM only).
- **OS Requirements:** Windows 10/11, Linux, macOS, WSL2. (Python 3.10+).
- **Dependencies:** `sqlite3`, `httpx` (for client).
- **Startup Mechanism:** In-process direct SQLite or standalone HTTP ingestion daemon (`scripts-notify serve`).
- **Read-Only Status Commands:** `scripts-notify status`, `scripts-notify incidents list`, `scripts-notify release-check`.
- **Supported Dry-Run Operations:** Default dry-run on pruning/mutations; `-a/--apply` required to write changes.
- **Cross-Component Dependencies:** None; core broker is self-contained.
- **Log & Database Retention:** SQLite WAL mode with automatic checkpoints; prune command (`scripts-notify prune --older-than-days 30`).
- **Failure Behavior:** Fail-closed transactions with SQLite busy timeouts; atomic outbox queueing; client degrades to local logging or error return.
- **Stop / Restart:** Kill process; safe shutdown on SIGTERM/SIGINT.
- **Rollback Method:** Restore backup copy of `events.db`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — 160 unit/integration tests passing.

---

### 2.2 Telegram Android Delivery Provider

- **Module / Entrypoints:** `modules/notifications/notifications/delivery/telegram.py` | CLI: `scripts-notify telegram`.
- **Config & Secret Locations:**
  - Bot Token: Windows Credential Manager `scripts.notifications.telegram.token` or environment `TELEGRAM_BOT_TOKEN`.
  - Chat ID: `%USERPROFILE%\.scripts\notifications\telegram.json` (`owner_chat_id`).
- **OS Requirements:** Cross-platform (HTTPS outbound to `api.telegram.org:443`).
- **Dependencies:** `httpx`.
- **Startup Mechanism:** Invoked by outbox delivery worker (`scripts-notify outbox run`).
- **Read-Only Status Commands:** `scripts-notify telegram status`.
- **Supported Dry-Run Operations:** `scripts-notify telegram test` defaults to dry-run preview; `-a/--apply` required to transmit.
- **Cross-Component Dependencies:** Notifications broker outbox.
- **Log & Database Retention:** Failed attempts recorded in outbox with exponential backoff (max 5 retries); tokens strictly redacted in logs.
- **Failure Behavior:** Network/TLS errors increment retry count; HTTP 429 respects `Retry-After`; does not block outbox worker or other providers.
- **Stop / Restart:** Managed via outbox worker lifecycle.
- **Rollback Method:** `scripts-notify telegram revoke` deletes local enrollment.
- **Validation Status:** **Level 2 (Synthetic Integration)** — Mock HTTP transport tests passing. Real transmission is **Level 5 (Operator Gate)**.

---

### 2.3 Windows Desktop Toast Helper

- **Module / Entrypoints:** `modules/notifications/windows_helper/helper.ps1` | CLI: `scripts-notify windows`.
- **Config & Secret Locations:** `%USERPROFILE%\.scripts\notifications\secrets\broker-token` (shared with broker).
- **OS Requirements:** Windows 10/11 Interactive Desktop Session (Session 1+). Specifically prohibited from running elevated (UAC Administrator).
- **Dependencies:** Windows PowerShell 5.1 / PowerShell 7+; WinRT Toast API (`Windows.UI.Notifications`).
- **Startup Mechanism:** User logon Scheduled Task or interactive launch; listens on loopback `http://127.0.0.1:1238`.
- **Read-Only Status Commands:** `scripts-notify windows status`.
- **Supported Dry-Run Operations:** `scripts-notify windows install` and `uninstall` default to preview unless `-a/--apply` passed.
- **Cross-Component Dependencies:** Local broker for notifications dispatch.
- **Log & Database Retention:** Ephemeral in-memory HTTP server; request payload bounded to 32 KB.
- **Failure Behavior:** If user is logged off or helper is down, notifications remain in broker outbox; other providers (Telegram) continue uninterrupted.
- **Stop / Restart:** `POST http://127.0.0.1:1238/shutdown` with shutdown token.
- **Rollback Method:** `scripts-notify windows uninstall -a`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — IPC protocol, token authentication, and bounds tested. Real desktop display is **Level 3 (Workstation Verified)**.

---

### 2.4 Independent Off-Host Heartbeat (Healthchecks.io)

- **Module / Entrypoints:** `modules/notifications/notifications/monitoring/` | CLI: `scripts-notify heartbeat`.
- **Config & Secret Locations:** `%USERPROFILE%\.scripts\notifications\healthchecks.json` (restrictive ACLs; ping URL redacted in logs/status).
- **OS Requirements:** Cross-platform (HTTPS outbound to `hc-ping.com` or custom Healthchecks instance).
- **Dependencies:** Standard library `urllib.request` (zero third-party dependencies).
- **Startup Mechanism:** Independent Windows Scheduled Task `ScriptsNotificationsHostHeartbeat` (runs every 5 minutes).
- **Read-Only Status Commands:** `scripts-notify heartbeat status`, `scripts-notify heartbeat doctor`.
- **Supported Dry-Run Operations:** `scripts-notify heartbeat install|uninstall|repair` default to preview; `-a/--apply` required to mutate Task Scheduler.
- **Cross-Component Dependencies:** **Zero dependencies on broker, SQLite, or desktop session.** Operates completely independently.
- **Log & Database Retention:** Heartbeat payload bounded to 10 KB diagnostic summary.
- **Failure Behavior:** Heartbeat failures log to event log/stderr; withholding pings causes off-host alerting by Healthchecks.io.
- **Stop / Restart:** Scheduled task stop / disable.
- **Rollback Method:** `scripts-notify heartbeat uninstall -a`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — 38 unit/integration tests passing. Live check configuration is **Level 5 (Operator Gate)**.

---

### 2.5 Resource Coordinator Observer

- **Module / Entrypoints:** `modules/notifications/notifications/integrations/resource_coordinator.py` | CLI: `scripts-notify coordinator`.
- **Config & Secret Locations:** Reads loopback status from `http://127.0.0.1:1235/_coordinator/status`. Advisory lock at `%TEMP%\scripts-rc-observer.lock`.
- **OS Requirements:** Windows 10/11.
- **Dependencies:** `modules/notifications`, loopback HTTP.
- **Startup Mechanism:** Windows Scheduled Task `ScriptsNotificationsCoordinatorObserver` (non-elevated user context).
- **Read-Only Status Commands:** `scripts-notify coordinator status`.
- **Supported Dry-Run Operations:** `scripts-notify coordinator task install|uninstall` dry-run by default.
- **Cross-Component Dependencies:** Resource Coordinator daemon on port 1235; Notifications storage engine.
- **Log & Database Retention:** Observations stored in `rc_observations` table; pruned via `scripts-notify coordinator prune`.
- **Failure Behavior:** Fail-closed advisory locking; degraded state reported if RC port unreachable or returns contradictory status.
- **Stop / Restart:** Scheduled task stop.
- **Rollback Method:** `scripts-notify coordinator task uninstall -a`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — Observer deduplication, fail-closed locking, and transport bounded tests passing. Zero modifications to `modules/resource_coordinator/`.

---

### 2.6 Remote Control Authentication & Mobile PWA

- **Module / Entrypoints:** `modules/remote_control` | CLI: `scripts-remote-control` (`remote_control.cli:main`).
- **Config & Secret Locations:**
  - Database: `%USERPROFILE%\.scripts\remote_control\auth.db` (Argon2id password hashes, TOTP base32 seeds, device enrollments, sessions).
  - Session Cookies: `__Host-rc_session`, `__Host-rc_device` (`SameSite=Strict`, `Secure=True`, `HttpOnly=True`).
- **OS Requirements:** Windows 10/11 workstation host; client runs in Android Chrome mobile browser.
- **Dependencies:** `fastapi`, `uvicorn`, `pyjwt`, `cryptography`, `argon2-cffi`.
- **Startup Mechanism:** Local loopback service binding to `127.0.0.1:8443` (`scripts-remote-control serve`).
- **Read-Only Status Commands:** `scripts-remote-control status`, `scripts-remote-control external doctor`.
- **Supported Dry-Run Operations:** Password/TOTP reset preview; session revocation.
- **Cross-Component Dependencies:** Reads `modules/notifications` storage in read-only mode (`mode=ro`).
- **Log & Database Retention:** Session expiry (24 hours); brute-force rate-limiting (exponential lockout); audit records retained in `action_audit_journal`.
- **Failure Behavior:** Reject unauthenticated requests with HTTP 401; fail-closed on tampered cookies or expired TOTP replay.
- **Stop / Restart:** Terminate `uvicorn` process.
- **Rollback Method:** Revoke sessions via CLI (`scripts-remote-control revoke-session --all`).
- **Validation Status:** **Level 2 (Synthetic Integration)** — 172 tests passing covering auth, CSRF, exact origin, brute force, and sessions. Real phone display is **Level 3/4 (Workstation/Cellular)**.

---

### 2.7 Guarded Incident Acknowledgement & Action Barrier System

- **Module / Entrypoints:** `modules/remote_control/remote_control/actions/` | CLI: `scripts-remote-control reconcile-barrier`.
- **Config & Secret Locations:** SQLite tables in `auth.db` (`action_resource_locks`, `action_resource_barriers`, `action_challenges`).
- **OS Requirements:** Windows 10/11.
- **Dependencies:** `remote_control.actions`.
- **Startup Mechanism:** Subsystem within Remote Control FastAPI server.
- **Read-Only Status Commands:** `scripts-remote-control external status` (lists unresolved barriers).
- **Supported Dry-Run Operations:** Challenge generation; barrier reconciliation requires `-a/--apply` and authoritative evidence.
- **Cross-Component Dependencies:** Ingests incident data from Notifications storage; verifies capabilities against static registry.
- **Log & Database Retention:** Full audit journal in `action_audit_journal` with sensitive parameters redacted.
- **Failure Behavior:** If outcome is ambiguous or connection drops during execution, sets durable `action_resource_barriers` entry; future mutations fail closed with HTTP 409 until reconciled.
- **Stop / Restart:** In-process with web service.
- **Rollback Method:** CLI command `reconcile-barrier -a --barrier-id <id> --evidence <text>`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — Multiprocess crash recovery, barrier identity, and concurrency defect tests passing.

---

### 2.8 Tailscale Funnel External Lifecycle

- **Module / Entrypoints:** `modules/remote_control/remote_control/external/` | CLI: `scripts-remote-control external`.
- **Config & Secret Locations:** Host Tailscale CLI credentials (managed by Tailscale client).
- **OS Requirements:** Windows 10/11 with Tailscale client installed and logged in.
- **Dependencies:** `tailscale.exe` on PATH or `%ProgramFiles%\Tailscale\tailscale.exe`.
- **Startup Mechanism:** Invoked via `scripts-remote-control external enable -a`.
- **Read-Only Status Commands:** `scripts-remote-control external status`, `scripts-remote-control external doctor`, `scripts-remote-control external plan`.
- **Supported Dry-Run Operations:** `enable`, `disable`, `repair` all default to dry-run preview unless `-a/--apply` is passed.
- **Cross-Component Dependencies:** Local Remote Control service on `127.0.0.1:8443`.
- **Log & Database Retention:** Command execution logs; public URL recorded in status output.
- **Failure Behavior:** Refuses enablement if preflight checks fail (`ready_for_public_enable=False`); forbids `--skip-listener-check` with `--apply`.
- **Stop / Restart:** `scripts-remote-control external disable -a`.
- **Rollback Method:** `tailscale funnel --https=8443 off` or `scripts-remote-control external disable -a`.
- **Validation Status:** **Level 2 (Synthetic Integration)** — Mock CLI client and preflight doctor tests passing. Real activation is **Level 5 (Operator Gate)**.

---

## 3. Release Readiness Matrix

| Subsystem | Unit Tests | Synthetic Integration | Workstation Verified | External Real Service | Operational Status |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Notifications Broker** | Passed (L1) | Passed (L2) | Ready (L3) | N/A | **Ready for Release** |
| **Telegram Provider** | Passed (L1) | Passed (L2) | Ready (L3) | Pending (L4) | **Ready (Mocked); Gate Pending** |
| **Windows Toast Helper** | Passed (L1) | Passed (L2) | Ready (L3) | N/A | **Ready for Local Use** |
| **Healthchecks Heartbeat** | Passed (L1) | Passed (L2) | Ready (L3) | Pending (L4) | **Ready (Mocked); Gate Pending** |
| **RC Observer** | Passed (L1) | Passed (L2) | Ready (L3) | N/A | **Ready (Read-Only)** |
| **Remote Control Web/PWA** | Passed (L1) | Passed (L2) | Ready (L3) | Pending (L4) | **Ready for Loopback/LAN** |
| **Guarded Actions & Barriers**| Passed (L1) | Passed (L2) | Ready (L3) | N/A | **Ready (Read-Only Ack)** |
| **Tailscale Funnel Lifecycle**| Passed (L1) | Passed (L2) | Ready (L3) | Pending (L4) | **Ready (Disabled by Default)** |

---

## 4. Key Gaps & Invariants Identified

1. **Consumer Adoption Gap:** Prior to Phase 09, `modules/scheduler` used raw PowerShell balloon tips with string interpolation; resolved in Stage B.
2. **Registry Gap:** `remote_control` was not indexed in `modules/scripts_help/scripts_help/registry/registry.py`; resolved in Stage C.
3. **Documentation Discrepancy:** `public-https-setup.md` erroneously suggested passing `--skip-listener-check` during live activation; resolved in Stage E.
4. **Public Exposure Gate:** Tailscale Funnel must remain disabled until operator runs manual cellular acceptance tests (Runbook W01–W05).
5. **Resource Coordinator Protection:** Live recovery remains disabled. Zero changes to `modules/resource_coordinator/`.
