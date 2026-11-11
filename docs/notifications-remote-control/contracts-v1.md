# Notifications and Remote Control — Interface Contracts v1

**Version:** 1.0  
**Effective Date:** 2026-11-11  
**Scope:** Interface definitions for Event Envelopes, Storage Engine, Ingestion, Incident Lifecycle, and Provider Delivery.

---

## 1. Notification Event Schema (`EventEnvelopeV1`)

All notification producers emit structured events conforming to version 1. Unknown or newer `schema_version` values must be rejected explicitly without coercion.

### 1.1 Specification (JSON Schema Equivalent)

```json
{
  "schema_version": 1,
  "event_id": "6da7e5e5-23fe-435b-966d-08d05d97f2f3",
  "source": "resource_coordinator",
  "kind": "miner.recovery_required",
  "incident_key": "resource_coordinator:gpu.inference:recovery",
  "severity": "critical",
  "occurred_at": "2026-11-11T12:00:00Z",
  "summary": "Inference recovery requires operator verification",
  "correlation_id": "request-123",
  "resource": "gpu.inference",
  "details_ref": "local-opaque-reference",
  "labels": {
    "component": "recovery"
  },
  "lifecycle": "open"
}
```

### 1.2 Field Validation Rules

| Field | Type | Required | Validation Rules | Description |
|---|---|---|---|---|
| `schema_version` | integer | Yes | Must equal `1`. Unsupported versions rejected. | Contract version number. |
| `event_id` | string (UUID) | Yes | Valid UUID string (32 or 36 chars, canonical hyphenated). | Globally unique event identifier for idempotency. |
| `source` | string | Yes | Match `^[a-z0-9_-]{1,64}$`. | Subsystem emitting the event (e.g. `resource_coordinator`). |
| `kind` | string | Yes | Match `^[a-z0-9_.-]{1,64}$`. | Event classification code (e.g. `miner.recovery_required`). |
| `incident_key` | string | Yes | Match `^[a-zA-Z0-9_:.-]{1,128}$`. | Stable logical key grouping repeat occurrences. |
| `severity` | string | Yes | One of `["info", "warning", "critical"]`. | Alert severity level. |
| `occurred_at` | string (ISO 8601) | Yes | Valid ISO 8601 timestamp with explicit timezone (UTC required or normalized to UTC). Must not be > 5 minutes in the future. | Timestamp when condition was observed at source. |
| `summary` | string | Yes | Non-empty, length 1–256 characters. Must not contain raw secrets, tokens, or control characters. | Human-readable notification headline. |
| `correlation_id` | string \| null | No | Optional, max length 128. Match `^[a-zA-Z0-9_:.-]*$`. | Tracing/correlation identifier. |
| `resource` | string \| null | No | Optional, max length 64. Match `^[a-zA-Z0-9_:.-]*$`. | Affected target resource (e.g. `gpu.inference`). |
| `details_ref` | string \| null | No | Optional, max length 256. Plain opaque token. Must NOT contain file paths, URIs with credentials, or executable commands. | Opaque reference for local authorized drilldown. |
| `labels` | object | No | Map of string -> string. Max 32 entries. Keys max 64 chars `^[a-z0-9_.-]+$`; values max 128 chars. | Arbitrary structured metadata. |
| `lifecycle` | string | Yes | One of `["open", "update", "acknowledge", "resolve", "reopen"]`. | Action on the associated incident. |

---

## 2. Incident & Occurrence Lifecycle

### 2.1 Identity Invariants
- An **Incident** represents an ongoing problem condition identified by `incident_id = sha256(f"{source}\0{incident_key}")`.
- An **Occurrence** represents a single temporal episode of an incident.
- When an incident is `resolved` and later recurs with `open`, a **NEW** `occurrence_id` must be generated.
- Acknowledge modifies the active occurrence's `acknowledged_at` and silences reminder notifications under policy, but **does not resolve** the incident.
- Missing telemetry or source disappearance marks the incident as `stale` or `unverified`, NEVER `resolved`.

### 2.2 Valid State Transitions

| From Status | Event Lifecycle | Target Status | Rules / Side Effects |
|---|---|---|---|
| *None* (new) | `open` | `open` | Creates incident and new `occurrence_id`. Queues initial delivery. |
| `open` | `update` | `open` | Updates `last_seen`. If severity escalated or cooldown elapsed, queues delivery. |
| `open` | `acknowledge` | `acknowledged` | Sets `acknowledged_at`. Halts reminder loop. |
| `open` \| `acknowledged` | `resolve` | `resolved` | Sets `resolved_at`, closes active occurrence. Requires source evidence. |
| `resolved` | `open` | `open` | Starts a **new** occurrence (`occurrence_id`). Does not inherit previous ack. |
| `resolved` | `reopen` | `open` | Reopens prior occurrence if closure was determined to be premature. |
| `acknowledged` | `update` | `acknowledged` | Updates `last_seen`. Does not reset acknowledgement unless severity increases to `critical`. |

---

## 3. Storage Schema Contract (SQLite WAL)

All tables exist in the broker database (`events.db`). Foreign keys are enforced on all operations.

```sql
-- Schema migrations tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Immutable raw event journal
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    correlation_id TEXT,
    resource TEXT,
    details_ref TEXT,
    labels_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
);

-- Normalized incidents
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    incident_key TEXT NOT NULL,
    active_occurrence_id TEXT,
    status TEXT NOT NULL, -- open, acknowledged, resolved, stale
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    last_notified_at TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1
);

-- Discrete incident occurrences
CREATE TABLE IF NOT EXISTS occurrences (
    occurrence_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    resolution_evidence TEXT
);

-- Append-only state transition audit
CREATE TABLE IF NOT EXISTS transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    transition_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

-- Transactional delivery outbox
CREATE TABLE IF NOT EXISTS outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL, -- pending, attempting, provider_accepted, retryable_error, terminal_error
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 5,
    next_retry_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);

-- Provider delivery attempt log
CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    outbox_id INTEGER NOT NULL REFERENCES outbox(outbox_id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_message_id TEXT,
    duration_ms INTEGER,
    error_category TEXT,
    error_message TEXT
);

-- Operator incident acknowledgements
CREATE TABLE IF NOT EXISTS acknowledgements (
    ack_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
    occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id) ON DELETE CASCADE,
    acknowledged_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT
);

-- Indexes for performant lookup and queue polling
CREATE INDEX IF NOT EXISTS idx_events_incident_key ON events(source, incident_key);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_outbox_queue ON outbox(status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_transitions_incident ON transitions(incident_id, timestamp);
```

---

## 4. Local Ingestion Interface

### 4.1 In-Process Python API (`Publisher`)

```python
class Publisher:
    def __init__(self, storage: StorageEngine, policy: Optional[IncidentPolicy] = None):
        ...

    def publish(self, event: EventEnvelopeV1) -> PublishResult:
        """Synchronously persist and queue event. Raises on validation or storage error."""
```

`PublishResult` contains:
- `accepted: bool`
- `event_id: str`
- `incident_id: str`
- `occurrence_id: str`
- `transition: str` (e.g. `opened`, `updated`, `acknowledged`, `resolved`, `deduplicated`)
- `outbox_queued: bool`

### 4.2 Authenticated Loopback Ingestion (`POST /api/v1/publish`)

- **Binding**: Strictly `127.0.0.1:<port>`.
- **Headers**:
  - `Authorization: Bearer <token>` (matches token loaded from ACL-secured storage or env var).
  - `Content-Type: application/json`
- **Request Body**: JSON representation of `EventEnvelopeV1`.
- **Response Codes**:
  - `202 Accepted`: Event persisted, incident updated, outbox queued.
    Body: `{"ok": true, "result": {"event_id": "...", "incident_id": "...", "occurrence_id": "...", "transition": "..."}}`
  - `400 Bad Request`: Schema validation error, unknown version, or malformed fields.
  - `401 Unauthorized`: Missing or invalid bearer token.
  - `409 Conflict`: Reused `event_id` with conflicting payload content.
  - `503 Service Unavailable`: Storage busy or database full. Never block caller.

---

## 5. Provider Delivery Abstraction

```python
from dataclasses import dataclass
from typing import Optional, Protocol

@dataclass(frozen=True)
class RenderedNotification:
    notification_id: str
    event_id: str
    incident_id: str
    severity: str
    title: str
    body: str
    deep_link: Optional[str] = None
    created_at: str = ""

@dataclass(frozen=True)
class DeliveryReceipt:
    provider_id: str
    status: str  # "provider_accepted", "retryable_error", "terminal_error"
    provider_message_id: Optional[str] = None
    retry_after_seconds: Optional[float] = None
    error_category: Optional[str] = None
    error_message: Optional[str] = None

class DeliveryProvider(Protocol):
    provider_id: str

    async def send(self, notification: RenderedNotification) -> DeliveryReceipt:
        """Send notification. Must not raise uncaught network exceptions."""
        ...
```

### 5.1 Retry and Backoff Policy
- Initial delay: 2.0 seconds.
- Multiplier: 2.0 (exponential).
- Jitter: random 10% variation.
- Maximum delay: 300 seconds (5 minutes).
- Maximum retries: 5 attempts before transitioning to `terminal_error`.
- When provider returns `retry_after_seconds` (e.g. HTTP 429), honor the provider value up to 600s.

---

## 6. Forward Compatibility: Resource Coordinator Proposal

For Phase 05, the `notifications` adapter will read RC status without altering RC source code.

Proposed read-only status schema from RC:
```json
{
  "service": "resource_coordinator",
  "version": "0.11.7",
  "status": "healthy",
  "fingerprint": "a1b2c3d4e5f6...",
  "timestamp": "2026-11-11T12:00:00Z",
  "resources": {
    "gpu.inference": {
      "state": "inhibited",
      "reason": "model_load_timeout",
      "last_inhibition_at": "2026-11-11T11:58:30Z",
      "active_lease": null
    }
  }
}
```
If RC currently provides a slightly different shape via `resource-coordinator status -j`, the adapter in Phase 05 will parse the existing JSON structure and propose enhancements to the RC maintainer if version fingerprints are missing.
