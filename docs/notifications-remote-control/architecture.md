# Notifications and Remote Control — Architecture and System Design

## 1. System Overview

The `notifications` and `remote_control` modules provide an extensible, secure, and $0-cost notification and remote-control foundation for the `scripts` repository.

The system is organized into decoupled layers:

```
[Producers]
  ├─ Resource Coordinator (recovery required, miner holds)
  ├─ Scheduler (job failures, missed runs)
  ├─ LLM Monitor (context limits, provider stalls)
  └─ Other Modules / CLI
         │
         ▼
[Local Ingestion & Broker] (modules/notifications)
  ├─ In-process Python API (same-process)
  ├─ Authenticated Loopback Ingestion (cross-process, token-guarded)
  ├─ Durable Storage (SQLite WAL, migrations, event journal)
  ├─ Incident State Machine (open, update, acknowledge, resolve, reopen)
  └─ Outbox Delivery Engine (queue, exponential backoff, retry limits)
         │
         ├───────────────────────────────┐
         ▼                               ▼
[Delivery Providers]            [Windows Desktop Helper]
  ├─ Phase 01: FakeProvider      └─ Phase 03: AppNotificationManager
  └─ Phase 02: Telegram Bot                   (User-session helper)
         │
         ▼
[Operator Android Device]

[Independent Watchdog] (Phase 04)
  └─ Outage Heartbeat Task (Windows Scheduled Task) ──> Healthchecks.io ──> Telegram

[Future Remote Control Gateway] (Phases 06–08, modules/remote_control)
  ├─ Authenticated PWA Dashboard (TOTP, session cookies)
  ├─ Read-Only Incident / Module Projections
  └─ Guarded Action Registry (explicit allowlist, confirmation, idempotent execution)
```

## 2. Module Boundaries and Ownership

To prevent coupling and preserve system stability:

1. **`notifications` (`modules/notifications`)**:
   - **Owns**: Normalized incident lifecycle, durable event journal, outbox, delivery providers, retry policy, and local ingestion interfaces.
   - **Does NOT own**: Any subprocess execution, mining workloads, Task Scheduler tasks, or LLM operations.
   - **Principle**: The ability to publish a notification event conveys *no authority* to control or execute actions on the producer.

2. **`remote_control` (`modules/remote_control`, Phase 06+)**:
   - **Owns**: Web UI, authentication, device enrollment, sessions, CSRF protection, action registry, and execution audit.
   - **Does NOT own**: Producer internal logic. It reads incident status through read-only adapters and invokes actions solely through strictly allowlisted, validated capability descriptors.

3. **`resource_coordinator` (`modules/resource_coordinator`)**:
   - **Owns**: Process leases, GPU conflict arbitration, safety inhibition, recovery policies, and operator credentials.
   - **Ownership boundary**: Resource Coordinator remains completely independent. No source files within `modules/resource_coordinator` are edited or wrapped directly in Phase 00–01.

4. **`outage_heartbeat` (Phase 04)**:
   - **Owns**: An independent Windows Scheduled Task executing a lightweight outbound HTTPS ping to Healthchecks.io.
   - **Boundary**: Completely detached from the broker and Resource Coordinator so that a host crash, power loss, or broker failure can be detected off-host.

## 3. Incident Lifecycle vs Delivery State

A fundamental architectural requirement is the strict decoupling of **Incident State** from **Delivery State**:

### Incident State Machine
- `open`: A new incident is detected and registered. A unique `incident_id` and initial `occurrence_id` are assigned.
- `update`: A repeat observation for an active incident updates `last_seen`, payload metadata, or increases severity.
- `acknowledge`: The human operator has seen the alert. Reminders are silenced according to policy, but **the incident remains unresolved** and the underlying condition (e.g. miner inhibition) is NOT cleared.
- `resolve`: The source condition has cleared with verified evidence. Network absence or source disappearance is NOT resolution (it is treated as `stale` or `unverified`).
- `reopen`: The same verified occurrence has re-triggered prior to resolution. A new occurrence after verified closure constitutes a *new* incident occurrence with a new `occurrence_id`, avoiding state aliasing.

### Outbox Delivery State Machine
- `pending`: An event or transition is scheduled for delivery to an enabled provider.
- `attempting`: The worker has claimed the delivery item with an active lock.
- `provider_accepted`: The remote provider (e.g., Telegram Bot API or FakeProvider) acknowledged receipt. This does NOT imply phone display or operator acknowledgement.
- `retryable_error`: Delivery failed due to transient network, HTTP 429, or 5xx error. Rescheduled with bounded exponential backoff and jitter.
- `terminal_error`: Delivery failed permanently (e.g. invalid credentials, unresolvable recipient). Marked terminal to avoid infinite loops and flagged for operator diagnostics.

## 4. Local Ingestion Mechanism & Trust Boundary

### Account Boundaries
- On Windows, producer processes may execute under the logged-in interactive user account (e.g., CLI tools, Scheduler in user session) or under `NT AUTHORITY\SYSTEM` (e.g., Resource Coordinator service daemon).
- Desktop notification display (Phase 03) requires execution inside the interactive user's desktop session. Elevated/SYSTEM processes cannot reliably or safely post Windows App SDK toast notifications directly.

### Ingestion Interface Architecture
Two ingestion paths are supported:
1. **In-Process Python API (`Publisher`)**:
   Used by Python applications running in the same process or having direct access to the `notifications` storage engine.
2. **Authenticated Loopback HTTP Ingestion (`127.0.0.1:<port>`)**:
   - Binds strictly to `127.0.0.1` (never `0.0.0.0`).
   - Requires bearer token authentication (`Authorization: Bearer <token>`).
   - The token is loaded from an ACL-restricted credential file (`~/.notifications/secrets/broker-token` or environment variable `NOTIFICATIONS_INGEST_TOKEN`). On Windows, the file ACL grants permissions solely to the user and `S-1-5-18` (SYSTEM), mirroring `modules/resource_coordinator/resource_coordinator/core/operator_credentials.py`.
   - **Localhost is NOT authentication**: Unauthenticated requests are rejected with HTTP 401. Cross-origin browser requests are denied.
   - **Bounded latency**: Calls have a strict client timeout (default 1.0–2.0s). If the broker is unreachable or database is busy, the client raises `BrokerUnavailableError` without blocking safety-critical operations.
   - **Synchronous persistence acknowledgment**: HTTP 202/200 is returned ONLY after the event and outbox entries are committed to SQLite. No false positives.

## 5. Storage Architecture (SQLite WAL)

- **Engine**: SQLite 3 with Write-Ahead Logging (`PRAGMA journal_mode=WAL`), foreign keys enabled (`PRAGMA foreign_keys=ON`), and a bounded busy timeout (`PRAGMA busy_timeout=5000`).
- **Single-Writer Authority**: The broker process owns migrations and outbox queue dispatching.
- **Idempotency**: `event_id` is globally unique. Inserting an existing `event_id` with an identical payload is a no-op returning the existing record; an existing `event_id` with a conflicting payload is rejected with a validation/conflict error.
- **Atomic Operations**: Ingestion commits the event envelope, incident/occurrence transition, and outbox delivery record within a single ACID transaction.

## 6. Security & Defense in Depth

1. **Secret Scrubbing**:
   - Notification summaries and payloads are sanitized. Tokens, passwords, TOTP seeds, Windows credentials, and private paths are scrubbed.
   - Full Telegram API URLs contain bot tokens by design (`api.telegram.org/bot<TOKEN>/...`); HTTP exceptions and traces must scrub the token before logging.
2. **No Arbitrary Shell Execution**:
   - Event templates and summaries are plain text. No shell string interpolation (addressing the PowerShell injection risk identified in `scheduler/notifier.py`).
   - Events cannot specify executable paths, shell scripts, or commands to run.
3. **Storage Quotas & Eviction**:
   - Critical events and unresolved incidents are protected from FIFO eviction.
   - Outbox queue size and delivery attempt history are bounded to prevent disk exhaustion.
