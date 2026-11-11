# Guarded Actions and Capability Architecture (Phase 07)

**Document Version:** 1.0.0  
**Phase:** Phase 07 — Registered Actions and Guarded Remote Control  
**Module:** `modules/remote_control`  
**Repository:** `MaxCarlson/scripts`  

---

## 1. Architectural Overview

Phase 07 extends the authenticated Remote Control Mobile Dashboard from read-only monitoring to guarded, transactional capability execution.

It establishes a security boundary and execution pipeline ensuring:
- **Zero Arbitrary Execution:** No generic process execution, shell commands, or arbitrary dynamic dispatch. All actions must be statically defined in source code and registered in an immutable code-owned registry.
- **Durable Two-Phase Confirmation:** Mutating actions require explicit preparation, yielding an expiring confirmation challenge (120s TTL) bound to the operator, session, device, and source state fingerprint.
- **Two-Factor Step-Up Authentication:** High-impact mutations require a fresh 6-digit TOTP code verified against the server-held operator secret. Replay protection prevents reusing the login OTP.
- **Atomic Idempotency Journal:** Every execution is reserved in `auth.db` via `BEGIN IMMEDIATE` transaction before any external dispatch. Duplicate submissions return the existing journal record without re-dispatching.
- **State Drift Detection:** The system inspects source subsystem state during preparation and re-verifies the canonical SHA-256 fingerprint during execution. If source state changes between preparation and confirmation, execution is rejected.
- **Deterministic Postcondition Verification:** Actions declare postcondition policies. The transaction is marked `succeeded` only if the verified postcondition is confirmed on the target subsystem.
- **Strict Boundary Protection:** Production Resource Coordinator recovery remains disabled server-side (`capability_disabled`). Incident acknowledgement is strictly decoupled from Resource Coordinator safety holds.

---

## 2. Capability Registry Inventory

The capability registry (`remote_control.actions.registry.ActionRegistry`) defines 6 capabilities:

| Action ID | Effect | Role | Confirmation | Step-Up | Postcondition | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `resource_coordinator.status` | Read | `operator.read` | None | None | None | **Enabled** |
| `resource_coordinator.inspect_recovery` | Read | `operator.read` | None | None | None | **Enabled** |
| `notifications.health` | Read | `operator.read` | None | None | None | **Enabled** |
| `notifications.incident_detail` | Read | `operator.read` | None | None | None | **Enabled** |
| `notifications.acknowledge_incident` | Mutation | `operator.action` | Explicit (120s) | TOTP | Verify State | **Enabled** |
| `resource_coordinator.request_guarded_recovery` | Mutation | `operator.action` | Explicit (120s) | TOTP | Verify State | **Disabled** (Production) |

### Protected Resource Coordinator Invariant
In production, `resource_coordinator.request_guarded_recovery` is configured with `enabled=False` and handler `DisabledRecoveryAdapter`. Any preparation or execution attempt strictly fails closed with HTTP 403 `capability_disabled`. `modules/resource_coordinator/` source code remains 100% untouched.

---

## 3. Database Schema (Schema Version 2)

`auth.db` is additively migrated to Schema Version 2 to introduce durable challenge and execution journals:

### `action_challenges`
Tracks issued, expiring confirmation challenges:
- `challenge_id`: Primary key (`cld_<32hex>`).
- `operator_id`: Binds challenge to issuing operator.
- `session_id_hash`: Binds challenge to specific authenticated session token.
- `device_id`: Binds challenge to registered operator device.
- `action_id`, `action_version`: Target capability.
- `arguments_digest`: SHA-256 hash of canonical action parameters.
- `state_fingerprint`: Canonical SHA-256 hash of observed source state at preparation time.
- `rc_request_id`: Subsystem request correlation ID if available.
- `prepared_at`, `expires_at`: ISO 8601 timestamps (120-second default TTL).
- `status`: Lifecycle status (`pending`, `consumed`, `expired`, `rejected`).
- `consumed_at`: Timestamp of atomic consumption.

### `action_executions`
Immutable journal of all executed actions:
- `execution_id`: Primary key (`exec_<32hex>`).
- `action_id`, `action_version`: Capability contract.
- `actor_id`, `session_id_hash`, `device_id`: Actor identity.
- `idempotency_key_hash`: Unique constraint `UNIQUE(action_id, idempotency_key_hash)`.
- `arguments_digest`, `state_fingerprint`: Input and state hashes.
- `started_at`, `finished_at`: Execution duration.
- `status`: `reserved` -> `executing` -> `succeeded` / `denied` / `failed` / `outcome_unknown` / `postcondition_unverified`.
- `result_category`: Category (`success`, `timeout`, `safety_refusal`, `invalid_parameters`, etc.).
- `postcondition_verified`: Boolean indicator.
- `summary`: Human-readable outcome summary (bounded to 1024 characters).
- `details_json`: Sanitized execution details (bounded to 64KB, secrets redacted).

---

## 4. Guarded Execution Workflow

```
Client (PWA)                 Remote Control API                 Subsystem / Adapter
   │                                │                                │
   │  1. POST /actions/{id}/prepare │                                │
   │───────────────────────────────>│ 2. Check capability & roles   │
   │                                │ 3. Read fresh source state ───>│
   │                                │<── Return current state ───────│
   │                                │ 4. Compute state fingerprint   │
   │                                │ 5. Issue 120s challenge in DB  │
   │<───────────────────────────────│                                │
   │  Return Challenge & Preview    │                                │
   │                                │                                │
   │  [Operator Reviews Evidence,   │                                │
   │   Enters 6-Digit TOTP Code]    │                                │
   │                                │                                │
   │  6. POST /actions/{id}/execute │                                │
   │───────────────────────────────>│ 7. Verify TOTP Step-Up         │
   │                                │ 8. Atomically consume challenge│
   │                                │ 9. Check state drift ─────────>│
   │                                │<── Re-read fresh state ────────│
   │                                │ 10. Reserve execution (Atomic) │
   │                                │ 11. Acquire Concurrency Lock   │
   │                                │ 12. Execute mutation ─────────>│
   │                                │<── Return result ──────────────│
   │                                │ 13. Verify postcondition ─────>│
   │                                │<── Confirm target state ───────│
   │                                │ 14. Update journal in DB       │
   │                                │ 15. Write audit log in DB      │
   │<───────────────────────────────│                                │
   │  Return Execution Record       │                                │
```

---

## 5. Acceptance Criteria & Validation Matrix (R05–R10)

Automated testing in `test_synthetic_recovery.py` and `test_actions_workflow.py` validates all Phase 07 acceptance criteria:

- **R05 (Guarded Recovery Workflow):** End-to-end execution flow succeeds with valid state fingerprinting, TOTP step-up, and verified postcondition (`test_r05_successful_guarded_recovery_flow`).
- **R06 (Expired Challenge):** Expired challenges strictly fail with `challenge_expired` (`test_r06_expired_challenge_rejection`).
- **R07 (State Drift Detection):** Subsystem state changes between preparation and execution are detected, rejecting execution with `state_drift_detected` (`test_r07_state_drift_detected_rejection`).
- **R08 (Safety Refusal):** Active/pending claims refuse recovery with `safety_refusal` and journal status `denied` (`test_r08_safety_refusal_on_active_claims`).
- **R09 (Service Not Ready):** Degraded or unavailable subsystem causes clean refusal with `service_not_ready` (`test_r09_service_not_ready_refusal`).
- **R10 (Timeout Handling):** Subsystem execution timeout updates journal record to `outcome_unknown` with result category `timeout` and does not crash the server (`test_r10_execution_timeout_journaled_as_outcome_unknown`).
- **Concurrency Serialization:** Parallel execution requests for the same concurrency key are serialized without race conditions (`test_concurrency_serialization`).
- **Production Guarded Recovery Disabled:** Production `resource_coordinator.request_guarded_recovery` strictly fails closed with `capability_disabled` (`test_disabled_capability_fails_closed`).
- **Incident Acknowledgement:** Transitions notifications broker incident to `acknowledged` with audit logging, without touching Resource Coordinator safety holds (`test_convenience_incident_acknowledge_endpoint`).
- **PWA DOM Safety:** Zero `innerHTML`, `outerHTML`, or `document.write` in `app.js` (`test_app_js_strict_dom_safety`).
