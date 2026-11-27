# Durable GPU Maintenance Sessions

## Objective

Add an authenticated Resource Coordinator protocol that grants an external optimizer temporary exclusive ownership of the managed physical GPU. Keep existing workload arbitration, miner ownership, durable recovery, and restart inhibition authoritative. This branch implements Resource Coordinator only; Mining remains read-only.

## Baseline and scope

- Base: `3d1cefa0596cfba5a68e436589f3bba7edc04a53` (`origin/main` at start).
- Branch: `agent/resource-coordinator-gpu-maintenance-20261111`.
- No production operations, main merge, or deployment.
- No real inference, model operation, miner control, GPU mutation, or Scheduled Task activity in tests.

## Design decisions

1. `LeaseManager` owns the atomic GPU admission boundary. Maintenance sets a short-lived admission fence under its condition lock after checking all known GPU claims. Normal inference/model-load reservations and idle-guarded miner/gaming transitions consult the same fence. No condition lock is held while the miner is stopping or a session remains active.
2. `CoordinatorService` owns session transitions and calls the existing supervisor. Acquisition closes admission and persists intent before stopping the miner; grant requires verified stopped state and coordinator ownership. Failures preserve a recovery hold.
3. `CoordinatorState` gains an optional validated maintenance record. Old journals without the field remain valid. Existing state updates preserve this record and unrelated state. The fencing token is process-local and random; only durable session metadata and recovery state persist. Restart revokes token authority and converts non-idle state to `recovery_required` before startup can launch workloads.
4. A manager serializes lifecycle transitions with its own lock, while `LeaseManager` serializes only the admission boundary. Heartbeats/status use the maintenance manager and remain available while admission is closed.
5. Expiry revokes the current token and changes the persisted record to `recovery_required`; expiry does not clear the miner hold or assert external-process termination.
6. Release records client restoration assertions separately from RC observations. A client Boolean alone does not prove settings restoration. RC always checks its managed miner is stopped and requires a configured restoration-evidence verifier or explicit authenticated operator override; unsupported hardware proof is reported as unavailable.
7. HTTP mutations reuse existing operator authentication. Status and operation-resolution routes are read-only and sanitized. Tokens are returned only on successful acquisition and accepted only in authenticated mutation bodies; they never appear in logs, status, or events.
8. The server supports idempotent operation identity and queryable pending acquisition. The current Mining client does not yet implement the full identity, server-expiry, strict-acknowledgement, token-redaction, or no-legacy-fallback requirements; compatibility results will be reported separately.
9. The authorized release disposition persists `restart_not_before`. Startup re-arms the remaining cooldown and a bounded manual deadline so a process interruption after durable release neither starts KRig early nor leaves a previously running Coordinator-owned miner stopped indefinitely.

## Implementation tasks

### Task 1 — State schema and arbitration boundary

- Add a validated optional maintenance record to `CoordinatorState` and backward-compatible serialization.
- Add maintenance admission fence APIs to `LeaseManager`; check the fence in claim reservation and `run_if_idle` paths.
- Verify unrelated inhibition and state fields survive maintenance updates.

### Task 2 — Session manager and lifecycle

- Add `MaintenanceSessionManager` with `idle`, `acquiring`, `active`, `releasing`, and `recovery_required` states.
- Implement bounded request validation, idempotent acquisition operation identity, cryptographic session/token generation, constant-time token checks, server expiration, heartbeat, release retry, and sanitized status.
- Coordinate durable intent, managed miner stop verification, expiry, and restart reconciliation through `CoordinatorService`.
- Preserve a hold on persistence failure, cancellation, ambiguous process state, or failed restoration.

### Task 3 — Admission and supervisor integration

- Block inference and model-load admission before model reuse logic.
- Reject manual miner start/resume, gaming transitions, automatic start/watchdog/recovery paths while maintenance owns or inhibits the GPU.
- Ensure acquisition conflicts with active/pending claims and other transitions; no new claims cross the fence.

### Task 4 — Authenticated HTTP contract and events

- Add canonical `/_coordinator/maintenance/*` routes and sanitized fields to `/_coordinator/status`.
- Reuse operator authentication for acquire, heartbeat, and release.
- Return non-2xx structured errors for auth, conflict, unavailable, invalid, stale/expired token, and persistence failures.
- Emit bounded observational lifecycle events with stable IDs and no secret values.

### Task 5 — Tests, compatibility review, and evidence

- Add deterministic state, arbitration race, fake-miner lifecycle, gateway authentication, expiry, crash/restart, idempotency, rejection, cancellation, and token-redaction coverage.
- Compare exact Mining commit `4b1f2a57b0bac536d250a7018df1f8a20c78e1c5` read-only and document client-side gaps without modifying that repository.
- Run focused and module regression tests, Ruff, compilation, and diff checks.
- Update this plan's checklist/status, commit validated work, and push the feature branch.

## Safety invariants

- Maintenance admission and protected workload admission share one synchronization boundary.
- The miner is never stopped before durable acquisition intent and admission closure.
- A token is never issued before coordinator-owned miner stop is verified.
- No unowned process is terminated or adopted.
- Expiration, restart, client disconnect, cancellation, or uncertain restoration never clears the hold by themselves.
- A crash during post-release cooldown cannot bypass that cooldown; an eligible Coordinator-owned miner resumes through the existing guarded lifecycle after the durable deadline.
- Release and expiry never clear unrelated operator, gaming, inference, or service holds.
- Logical fencing excludes RC-managed work; it cannot prevent stale external code from directly invoking GPU driver APIs.

## Review focus

1. Acquisition races with a pending lease: pending state must veto grant.
2. Cancellation between intent persistence and miner-stop verification: state remains inhibited and queryable.
3. Coordinator restart with acquiring/active/releasing state: token is revoked and startup remains closed.
4. Existing-model reuse: the maintenance gate runs before any reuse fast path.
5. Duplicate/late release or heartbeat: stale token cannot affect a later owner.
