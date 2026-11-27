# H5 and Unattended Recovery Readiness

## Supervised H5 maintenance experiment

**Disposition: not ready on the current installation.** The read-only Coordinator endpoint still reports RC `0.11.3`, while the merged source is `1.0.0`. No installation/upgrade is authorized or performed here. H5 may be considered separately from unattended recovery after all of these gates pass:

1. Disposable Windows installation, task, upgrade, interruption, and rollback acceptance completes with evidence.
2. A separately approved source deployment is performed, then a read-only runtime check proves exact version, source path/revision, process identity, listener ownership, and single-instance state.
3. A preflight establishes no unresolved inference execution, competing launcher, unknown owner, or stale safety hold.
4. Read-only GPU UUID/PCI, driver, power, and supported offset baseline are recorded. Define an operator-present abort and restoration procedure; unsupported values remain unavailable.
5. The exact Mining source, allowed tuning scope, registered child process, lease heartbeat, restoration comparison, and release disposition are reviewed before the run.
6. The operator explicitly authorizes one bounded trial window and has an immediate manual stop/hold procedure. No automatic override is permitted.

Incomplete WDDM process attribution does not automatically prove a supervised, operator-assisted H5 experiment is impossible; the operator must decide whether the scoped process controls and continuous observation are sufficient. It does block trusted automatic release based on complete global process termination and is a strict blocker for unattended recovery. The current runtime/source mismatch and missing disposable acceptance already block H5 today.

## Unattended automatic recovery

**Disposition: blocked; keep disabled.** It requires complete execution-boundary evidence, validated inference coverage, trusted process attribution, explicit recovery policy, audit/monitoring, tested failure rollback, cooldown/restart qualification, deployment verification, and separate authorization. Idle snapshots, low GPU utilization, elapsed time, frontend exit, and WDDM-unavailable memory are not substitutes for authoritative termination evidence.

## Remaining gates

| Gate | Current classification | Next evidence needed |
|---|---|---|
| Disposable Windows install/task/upgrade/rollback | UNAVAILABLE | Named isolated Windows VM/host, owner confirmation, snapshot/reset plan, and authorization for the scoped test matrix. |
| WinError 206 historical upgrade path | PARTIAL | Reproduce through actual isolated upgrade orchestration and prove the file-backed transport path. |
| Installed/running RC source | BLOCKED for H5 | After separately approved deployment, verify exact runtime identity by read-only status and process/listener evidence. |
| RTX 5090 power/offset getters | PARTIAL | Getters read successfully earlier; controlled restoration comparison requires separate H5 authorization. |
| WDDM complete attribution | BLOCKED for unattended recovery | Demonstrate coverage using qualified process inventory or another authoritative execution-boundary observer. |
| LM Studio no-wake/runtime routing | UNAVAILABLE | Separate safe runtime qualification; do not probe stopped backend or issue inference without authorization. |
| H5 bounded supervised run | NOT READY | Complete disposable test, deployment identity, safe preflight, abort plan, and explicit one-run authorization. |
| Unattended recovery | BLOCKED | All execution-boundary, monitoring, rollback, rollout, and approval gates above. |
