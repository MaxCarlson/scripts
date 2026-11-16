# Phase 2 — Verified Lifecycle Transactions, Standard Checkpoints, and Readiness

**Depends on:** Phase 0. **Parallelizable with Phase 1 under separate source ownership.**  
**Primary scope:** `src/Lifecycle.ps1`, `src/Checkpoints.ps1`, a new lifecycle transaction file, tests, CLI.  
**No real VM mutation without separately authorized disposable target.**

## Objective

Replace the handwritten H4 sequence `close PSSession → graceful Stop-VM → wait Off → Standard checkpoint → verify snapshot → optional Start-VM → poll authenticated PowerShell Direct` with one durable, policy-driven transaction that resumes safely after every interruption.

## 1. Exact Hyper-V cmdlet and object contract

Get the target by GUID through `Get-VM -Id <guid>`, revalidate name/config path/ownership, then pass the verified **VM object** to `Start-VM -VM`, `Stop-VM -VM`, `Checkpoint-VM -VM` and `Get-VMSnapshot -VM`. Do **not** use `Start-VM -Id`/`Stop-VM -Id` without checking actual installed cmdlet support: the prior H4 wrapper failed because those parameter sets are not documented. Mock tests must simulate real parameter binding and live acceptance must verify it.

Keep existing `Start-VmLabMachine`, `Stop-VmLabMachine`, `New-VmLabCheckpoint`, `New-VmLabBaselineCheckpoint` public APIs. Add orchestration without changing default semantics.

## 2. State machine and postconditions

Proposed ordered states:

`VALIDATED → GUEST_SESSION_CLOSED → SHUTDOWN_REQUESTED → OFF_CONFIRMED → CHECKPOINT_REQUESTED → CHECKPOINT_VERIFIED → [START_REQUESTED → RUNNING_CONFIRMED → GUEST_READY]`.

Each transition has a persisted stage receipt, fresh identity check, a monotonic bounded deadline, retries for observation but no repeated dangerous mutation on uncertainty. No success based solely on `Stop-VM` or `Start-VM` returning without error.

### Shutdown

- Preflight: target VM owned and stable; valid session/guest-checkpoint policies; enough disk for checkpoint; no conflicting activity.
- End/close vm_lab-owned PS Direct sessions (not arbitrary sessions held by another process).
- Request **graceful** `Stop-VM -VM $vm`; never `-TurnOff/-Force` by default.
- Bounded poll until `Off`; explicitly distinguish `shutdown_requested`, `off_confirmed`, `timeout_unconfirmed`, `guest_shutdown_unavailable` and `vm_transitional`.
- Do not proceed to checkpoint when guest power state is uncertain.
- Preserve rollback choice for the operator; never automatically hard power off.

### Checkpoint

- Verify VM's `CheckpointType=Standard` when required; do not mutate policy implicitly.
- If user authorized configuration change, record old policy and a separately verified change (no surprising fallback).
- Refuse duplicate checkpoint name except when resuming an operation with an exactly verified receipt/checkpoint ID; never silently adopt unrelated snapshot.
- Create `Checkpoint-VM -VM $vm -SnapshotName ... -Passthru`, then verify `Get-VMSnapshot -VM` by exact snapshot ID, name, CreationTime and Standard type.
- Snapshot failure must set `FAIL` for attempted stage, never `NOT_RUN`.
- Persist exact checkpoint identity; checkpoint is **not** a backup, don't advertise as such.

### Optional restart

- Only if specifically authorized; verify host RAM reserve and protected workloads before start.
- Re-resolve exact VM object; `Start-VM -VM $vm`.
- Wait for `Running`, integration Heartbeat as a hint, then credentialed PowerShell Direct availability, expected Windows guest identity/admin.
- Reestablish session with bounded retry intervals and deadline; auth errors do not retry indefinitely.
- If startup works but guest readiness fails, report `PARTIAL`, preserve checkpoint and guest state.

## 3. Qualifying a clean baseline

The H4 policy requires a powered-off Standard checkpoint **after** verified prerequisites and **before** acceptance. Add a generic qualification policy capable of checking specific prerequisite receipts, immutable bundle hash, guest identity, and a project-provided read-only verification command. Do not mark `baseline_qualified` merely because checkpoint exists.

For a non-H4 development VM, baseline can be created without these strict project receipts, but the response must clearly mark `guest_verified=false / baseline_qualified=false` unless actually verified.

## 4. Cancellation, resumption and operator boundaries

- On shutdown timeout: leave VM in observed state, return `PARTIAL/shutdown_not_confirmed`, retain operation ID.
- If process dies after checkpoint creation before receipt: re-enumerate snapshots, compare expected unique name and creation window and require manual resolution if ambiguous; do not create duplicate.
- If process dies after Start-VM but before readiness: inspect live state, no second start if Running.
- Capability checks at each new mutating action (`vm_shutdown`, `checkpoint_create`, `vm_start`); approvals from prior invocation cannot silently authorize later resume.
- `-WhatIf` covers entire plan with no guest or host mutation.

## 5. Readiness and diagnostics

Provide generic readiness probe with policy-driven deadline and classification: `vm_missing`, `permission_denied`, `off`, `starting`, `running_guest_unknown`, `heartbeat_ok_no_credentials`, `ps_direct_auth_failed`, `oobe_account_missing`, `guest_ready`, `reboot_required`, `guest_state_mismatch`.

Avoid asserting that one failed PowerShell Direct attempt proves OOBE incomplete: credentials/guest service/host permissions may be cause. Test against fake guest-state transitions.

## 6. Testing and integration

Scenarios:

1. Running → graceful Off → Standard snapshot → optional Running → PS Direct ready.
2. Already Off and valid operation: checkpoint proceeds without Stop.
3. Timeout while waiting Off: no snapshot.
4. Stop-VM parameter binding rejects `-Id`; test ensures object usage.
5. Snapshot created but returned object null; verify via inventory or fail closed.
6. Snapshot duplicate with same name but different ID: refuse adoption.
7. Snapshot `Production` despite requested `Standard`: FAIL, don't silently qualify.
8. Crash after snapshot before journal: reconciliation, no second snapshot.
9. Guest readiness auth failure vs temporary boot delay.
10. Host RAM availability drops before restart: block before Start.
11. VM name/ID/path changes between steps: fail closed.
12. `-WhatIf` and missing capability: no mutation.
13. Externally created H4 remains read-only/unmanaged.
14. Stop/initiation failure: preserve all prior receipts and correct stage status.

Use Pester with fake VM transitions and realistic cmdlet parameter sets. Add read-only real-host compatibility probes when privileges permit, not mutation. Real guest test waits until independently authorized Phase 6.

## Deliverables

- New checkpoint transaction operation and readiness wait command.
- Typed transaction plan/receipt fields incorporated into journal contract.
- Exact `-VM` cmdlet use, supported parameter inspection recorded.
- Test matrix demonstrating all failure, resume and identity cases.
- Module export/CLI/help updates without breaking existing behavior.
- Source checkpoint, executed validation and `STATUS.md` update.

## Acceptance criteria

- [ ] A single module-level invocation can safely perform powered-off Standard checkpoint and optional restart/ready wait.
- [ ] H4's `Start-VM`/`Stop-VM -Id` regression cannot reoccur through the new APIs.
- [ ] No checkpoint occurs unless exact VM is verified Off when the policy demands it.
- [ ] Every requested stage ends `PASS`, `FAIL`, `BLOCKED` or `PARTIAL`; no incorrect `NOT_RUN` after a failure.
- [ ] Resumption does not duplicate checkpoint or power operations.
- [ ] No hard/forced shutdown or guest auto-restart without distinct explicit permission.
