# Resource Coordinator Read-Only Monitoring and Incident Integration

## 1. Overview and Architecture

Phase 05 of the Notifications and Remote Control infrastructure establishes an independent, decoupled, out-of-process monitoring integration between the Resource Coordinator (RC) and the `notifications` event broker. Safe, read-only status inspection is exposed to the Phase 06 authenticated mobile dashboard.

```
┌─────────────────────────────────┐
│     Resource Coordinator        │
│    (Port 1235 on loopback)      │
│  - /status (read-only inspect)  │
└────────────────┬────────────────┘
                 │ HTTP GET (Bounded 5.0s timeout, loopback-only)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ notifications: ResourceCoordinatorObserver                  │
│  - Loopback validation (127.0.0.1, localhost, ::1 only)     │
│  - Status contract parser (modern v1 vs legacy)             │
│  - State deduping & storm suppression                       │
│  - Durable persistence: rc_observations table in SQLite     │
│  - Incident lifecycle reconciler (Publisher)                │
└────────────────┬────────────────────────────┬───────────────┘
                 │ Persist observation        │ Reconcile incident lifecycle
                 ▼                            ▼
┌─────────────────────────────────────────────────────────────┐
│ Durable SQLite Broker (notifications.db, schema v2)         │
│  - rc_observations table (append-only ledger of polls)      │
│  - incidents / occurrences / outbox tables                  │
└─────────────────────────────────────────────▲───────────────┘
                                              │ Read-only URI mode
                                              │ (file:... ?mode=ro)
                                ┌─────────────┴───────────────┐
                                │ remote_control:             │
                                │ ReadOnlyCoordinatorAdapter  │
                                │  - /api/coordinator         │
                                │  - /api/summary             │
                                └─────────────────────────────┘
```

---

## 2. Strict Architectural Boundaries

To preserve isolation, security, and safety:

1. **Zero Modifications to Resource Coordinator**:
   `modules/resource_coordinator/` is completely untouched and preserved.
2. **Zero Code Imports**:
   The observer and dashboard adapters do NOT import any modules, classes, or functions from `modules/resource_coordinator/`. The boundary is strictly external via JSON status payload inspection and read-only SQLite queries.
3. **Loopback-Only Target Binding**:
   Target endpoints are strictly validated against loopback hosts (`127.0.0.1`, `localhost`, `::1`). Non-loopback or public hostnames (e.g. `example.com`, `192.168.1.50`) are rejected immediately with a `ValueError`.
4. **Strictly Read-Only Observer**:
   The observer and adapter perform zero control code operations, zero miner process mutations, and zero recovery actions.

---

## 3. Status Contract Discovery & Normalization

The observer automatically discovers and normalizes both modern and legacy status contracts exposed by the Resource Coordinator:

### Modern Contract (Contract Version: `v1`)
The modern contract (defined in `RESOURCE_MONITOR_CONTRACT.md`) contains structured recovery and journal capabilities under `gpu_inference.recovery`:
```json
{
  "service": "resource_coordinator",
  "status": "healthy",
  "gpu_inference": {
    "status": "active",
    "recovery": {
      "required": true,
      "inhibition": {
        "active": true,
        "reason": "model load timeout on miner-1",
        "timestamp": "2026-11-11T12:00:00Z"
      },
      "requests": [...],
      "journal_status": "available"
    }
  },
  "miner": {
    "state": "inhibited"
  }
}
```

### Legacy Contract
Legacy payloads lack the `gpu_inference.recovery` sub-object, providing top-level or inference-level state fields:
```json
{
  "status": "healthy",
  "inference_inhibition": true,
  "inhibition_reason": "worker unresponsive",
  "miner_status": "stopped"
}
```

### Normalization and Uncertainty Preservation
When parsing:
- If `gpu_inference.recovery` is present, `has_recovery_contract` is `True`, `contract_version` is `"v1"`, and `recovery_required` is parsed as a strict boolean.
- If `gpu_inference.recovery` is missing, `has_recovery_contract` is `False`, `contract_version` is `"legacy"`, and `recovery_required` is preserved as `None` (`"unknown"`).
- **Mandatory Rule**: A missing recovery contract must **never** be assumed to mean `recovery_required=False`.

---

## 4. Incident Lifecycle Mapping & Reconciliation

Observations are reconciled against the notifications incident lifecycle engine (`IncidentLifecycleEngine` / `Publisher`):

| Incident Key | Trigger Condition | Severity | Resolution Condition |
| :--- | :--- | :--- | :--- |
| `rc_service_unavailable` | Coordinator loopback connection failed, timed out, or HTTP 5xx | `warning` | Coordinator connectivity restored (`status == "available"`) |
| `gpu_inference_recovery` | Modern: `recovery_required == True`<br>Legacy: `inhibition_active == True` | `critical` (modern)<br>`warning` (legacy) | Authoritatively cleared (`recovery_required == False` or `inhibition_active == False`) |
| `rc_recovery_journal_unavailable` | Modern: `journal_status == "unavailable"` | `warning` | Journal restored (`available` or `not_configured`) |

### Critical Safety Invariants
1. **Coordinator Outage Never Clears Safety Holds**:
   If the Resource Coordinator goes down (`rc_service_unavailable`), any active `gpu_inference_recovery` incident **remains open**. An unreachable service must never silently clear safety holds on GPU recovery.
2. **Notification Storm Suppression**:
   Repeated polls with identical state do not generate duplicate incident events. The observer tracks internal incident state and emits lifecycle events only on state transitions.
3. **Database Ledger Persistence**:
   Every poll writes a record to `rc_observations` in SQLite schema v2, capturing `observed_at`, `status`, `contract_version`, `has_recovery_contract`, `recovery_required`, `inhibition_active`, `inhibition_reason`, `journal_status`, `miner_state`, `error_message`, and raw JSON details.

---

## 5. Read-Only Dashboard Adapter (`/api/coordinator`)

The Phase 06 remote control dashboard queries coordinator status through `ReadOnlyCoordinatorAdapter` (`modules/remote_control/remote_control/adapters/coordinator_adapter.py`):

- **URI Mode**: Opens `notifications.db` using `file:... ?mode=ro` (strict read-only SQLite connection).
- **Response Format**:
  ```json
  {
    "ok": true,
    "status": "available",
    "available": true,
    "message": "Resource Coordinator is reachable and monitored.",
    "last_observation_time": "2026-11-11T12:00:00Z",
    "observation_age_seconds": 15.2,
    "is_stale": false,
    "contract_capabilities": {
      "version": "v1",
      "has_recovery_contract": true
    },
    "recovery_required": true,
    "inhibition_active": true,
    "inhibition_reason": "model load timeout on miner-1",
    "journal_status": "available",
    "miner_state": "inhibited",
    "active_incidents": [...]
  }
  ```
- **Uncertainty Fallback**:
  If the coordinator is unreachable, `status` reports `"unavailable"`, `available` reports `false`, and `recovery_required` and `inhibition_active` strictly report `"unknown"` (never `false`).
  If no observations exist yet, `status` reports `"unmonitored"`.

---

## 6. CLI Operational Commands

The `scripts-notify` CLI provides the `coordinator` subcommand group:

```powershell
# Check current observation and active safety incidents
scripts-notify coordinator status -d data/notifications.db

# Output JSON
scripts-notify coordinator status -d data/notifications.db -j

# Execute a one-time status poll against loopback target
scripts-notify coordinator poll -u http://127.0.0.1:1235/status -d data/notifications.db

# Dry-run loopback target validation (no network calls, verifies host constraints)
scripts-notify coordinator test -u http://127.0.0.1:1235/status
```

---

## 7. Verification Evidence

1. **Unit and Integration Tests**:
   - `modules/notifications/tests/test_rc_observer.py`: 12 dedicated tests covering loopback validation, contract normalization, malformed payloads, outage preservation of holds, duplicate suppression, and database migration.
   - `modules/notifications/tests/test_cli.py`: CLI validation covering status, test, and loopback enforcement.
   - `modules/remote_control/tests/test_api.py`: Dashboard integration covering unmonitored, active recovery, and uncertainty preservation.
2. **Suite Results**:
   - `modules/notifications/tests`: 141 passed, 1 skipped.
   - `modules/remote_control/tests`: 44 passed.
   - `modules/scripts_help/tests`: 55 passed.
   - Total workspace tests: 240 passed, 1 skipped.
