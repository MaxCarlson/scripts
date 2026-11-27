# Durable state helpers and crash-recovery requirements

Status: **helpers only; service persistence/startup reconciliation is not implemented.** `config.py` still rejects enabled `state_persistence_path`, and neither `build_system` nor the gateway wires StateCodec into transitions/startup. See [Phase C safety review](PHASE_C_SAFETY_REVIEW.md).

## Implemented and corrected

- `CoordinatorState` serializes process snapshots and restart inhibitions. It does not serialize pending/active/possibly-forwarded requests, manual overrides, config/boot identity, cooldowns, or durable recovery audit.
- `save_atomic` validates the schema, writes a sibling temporary file, flushes/fsyncs the file, then replaces the target. This resists partial writes; it does not establish write-ahead ordering, directory/rename durability on power loss, single-writer authority, or a complete recovery transaction.
- `load` now raises on missing, unreadable, corrupt, incomplete, duplicate-key or unsupported-version state. It never silently converts lost holds into clean state. First-boot initialization must be a separate explicit decision; a missing file can also mean prior state was lost.
- Process permissions/lifecycle values, identity timestamps, booleans and inhibition records are validated. String `"false"` cannot grant restart ownership. All hold records are validated before restore begins.
- `restore_into_leases` restores **inhibitions only**, retaining original timestamps in restoration details. It neither restores active leases nor reconstitutes authority to start/stop a process. Caller must keep execution gated until all holds are installed; interruption or restoration failure cannot open that gate.

## Exact process identity

`reconcile_pid` defaults to zero tolerance and rejects nonzero tolerance requests. It compares finite creation times exactly from the same representation; malformed/missing identities are UNVERIFIABLE, access denial is ACCESS_DENIED, and only confirmed absence is NOT_RUNNING. `query_fn` must never map access denial or unknown state to None. Runtime owned-process lookup also requires a known, exactly matching creation time.

Windows [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) provides creation time in FILETIME, expressed in 100-nanosecond units. That API does not justify a one-second matching window. Existing psutil float values round-trip through JSON; compare the same representation or reject ambiguity rather than widening the match. Future durable Windows identity should retain raw creation FILETIME plus boot/instance and executable identity, with stable process handles where possible. Exact float comparison is a candidate identity check, not proof of ownership or control authority, and does not remove PID-check-to-action races.

Never mark a resource idle simply because an old PID disappeared or was recycled. That says nothing about LM Studio execution, miner descendants or external supervisors.

## Required before unattended operation

1. Keep the gateway and all restart actions gated during startup. Acquire single-instance/writer authority. Unreadable/missing/corrupt state keeps affected resources inhibited until explicit reconciliation.
2. Persist intent **before** forwarding inference or issuing process side effects, and persist verified results before making resources restart-eligible. Do not debounce safety-critical writes behind those effects. Disk failure vetoes forwarding/restart.
3. Record request IDs, affected resource/conflict groups, reserved/possibly-forwarded/active/terminal/uncertain phases and upstream correlation identifiers. Convert all unresolved possibly-forwarded records into inhibitions after a crash, including requests that never reached an in-memory inhibition transition.
4. Persist unresolved holds, manual pause overrides, process launch identity/authority/prior running state and stop/start intent/result, clean-shutdown and boot/config revision, cooldown eligibility, and an attributable recovery audit.
5. Reconcile actual processes, descendants, supervisors and upstream execution before allowing restart. Never replay stale process IDs or a `was_stopped_by_coordinator` boolean as authority. If upstream termination cannot be established, retain inhibition or require an explicit audited operator override.
6. Test crashes, partial writes, rename failure, stale snapshots, competing instances, clock changes and disk errors at every intent/side-effect boundary. Validate real Windows storage/process behavior under separate authorization.

Telemetry SQLite/WAL is a separate, lossy observational stream and must not become the safety journal. Low GPU utilization, model residency, a later successful request, connection closure, or coordinator restart cannot establish that an earlier inference stopped.

The current recovery CLI is an authenticated **operator override** using `RESOURCE_COORDINATOR_RECOVERY_TOKEN`, `--force` and `--reason`. Active/pending claims reject it; it does not verify upstream idle or update a durable safety journal. Diagnostics explicitly report execution_state=unverified and restart_authorized=false. A supervised experiment may defer durable integration only if every crash/restart aborts the experiment and mining stays stopped pending independent reconciliation; do not restart the coordinator to clear a hold.
