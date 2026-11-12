# H4 Operational Readiness Ledger

This ledger records the evidence and gates remaining after Part 2/3 source review. It is a planning artifact; no host probing or operational change was performed for this review.

## 1. Verified offline/source behavior

| Area | Status | Evidence / remaining requirement | Gate |
|---|---|---|---|
| Part 2 CLI, package `1.0.0`, status/telemetry and read-only assessment | Verified offline | Part 2 `STATUS.md`; candidate regressions and isolated entry-point validation. Confirm import/version again during integration. | Source integration |
| Maintenance protocol and H3 Mining compatibility | Verified under simulation | H3 passed 8 tests against the integrated review candidate `576fca5805a308db562768fe762ed60d11f73eff` and Mining `deea3e019b35615f4d95e6f510450f7f392fb82a`; fake GPU/process adapters only. | Source integration / H5 |
| Journal revisions, exact-holder recovery, startup canonicalization, AccessDenied classification | Verified with fakes; review adds additional failure ordering coverage | Does not prove cross-process journal safety if the single-instance lock is bypassed. | Source integration |
| RC single-writer service ownership | Verified in source | `CoordinatorService.start()` acquires the configured OS-level `SingleInstanceLock` before startup reconciliation; release occurs through service lifecycle. Direct out-of-band/legacy journal writers remain outside the lock contract and must be stopped before rollback. | H4 rollback procedure |
| v0.14 rollback snapshot compatibility | Verified by loading exported snapshot with parser from commit `737bc6b` | Reconciled request history is archived to a sidecar; unresolved records and all holds remain in the legacy-readable snapshot. Operational downgrade still needs a separately authorized rehearsal. | H4 |
| Request completion / recovery evidence | Verified offline | Automatic recovery accepts proven pre-dispatch requests or genuine terminal protocol completion only. Bounded stream drain is disabled; forwarded uncertain work remains operator-required. | Source integration |
| GPU-idle/manual override and maintenance startup cooldown fixes | Verified with fake miner lifecycle tests | Does not establish production KRig resume behavior. | H4/H5 |

## 2. Safe read-only host observations for H4

These may be gathered only under the separately scoped H4 procedure and must not mutate state:

- Compare installed package version/runtime identity with the running Coordinator image and process.
- Inspect Scheduled Task registration, last result, account identity, and ACLs without editing the task.
- Record current service/task process identities, parent/descendant relationships, executable paths, and lock ownership.
- Identify the configured operator credential file and effective ACL/owner without reading or printing secret contents.
- Identify the RTX 5090 UUID/PCI identity, Windows build/driver, and whether supported NVML read APIs are available; record unsupported values as unavailable.
- Identify the LM Studio runtime version, Windows/WSL identity, and current gateway configuration using already-running-state evidence only. Do not use `lms ps` until its no-wake behavior is established.

## 3. Disposable Windows acceptance requiring system mutation

Run only in a disposable Windows VM or equivalent isolated host with mock Coordinator/miner processes:

- Reproduce and diagnose historical `[WinError 206]` in the upgrade path; exercise file-backed helper invocation, UAC rejection, task registration/startup/relaunch, and rollback.
- Verify service/task credentials, helper/task ACLs, protected operation files, receipt transitions, interruption recovery, and installed-versus-running identity.
- Verify single-instance behavior, descendant/process-group identity, access-denied classification, and no unrelated process mutation.
- Exercise install/upgrade rollback and restart under a disposable Scheduled Task. Elevated Scheduled Task acceptance remains unverified.

## 4. Controlled hardware/runtime tests requiring separate explicit authorization

- Establish supported RTX 5090 NVML power-limit and clock-offset readback before/after simulated or controlled changes; validate UUID, PCI, driver identity, and tolerances.
- Qualify WDDM GPU-process attribution and complete process inventory. Unsupported/incomplete attribution must remain unavailable.
- Verify the actual KRig launcher arguments, executable identity, Coordinator ownership, restoration and cooldown under controlled workloads.
- Verify LM Studio no-wake observation and correct Windows/WSL runtime identity while already running; test direct clients that bypass RC admission and measure GPU memory headroom.
- Perform a first controlled inference/optimizer handoff only after the above checks, with an explicit abort path and no unattended automation.

## 5. Unattended-recovery prerequisites

Unattended recovery remains disabled. Before considering it, qualify the complete Windows/WSL execution boundary, ensure no unsupported Case C process can survive, decide whether safe bounded stream draining can be enabled for specific routes, establish durable-state backup/rollback and single-writer enforcement, and review the post-commit synchronization failure path. Idle model snapshots, elapsed time, frontend PID exit, and low GPU utilization are never sufficient evidence.
