# Supervised live acceptance — blocked preparation checklist

**Review recommendation: NO-GO.** This is preparation, not authorization or an executable command sequence. The earlier six-phase plan relied on nonexistent CLI commands, incompatible console flags and unsafe recovery/rollback assumptions. See [Phase C safety review](PHASE_C_SAFETY_REVIEW.md).

## Facts required before reconsidering GO

- Implement and review one coordinator-owned startup/shutdown harness or authenticated daemon-side control path. `serve` opens the proxy but does not start Krig; `start` and `start-process` do not exist. Standalone `miner pause/resume` are intentionally disabled. Running a second coordinator or manually launching an external miner does not repair ownership.
- The harness must gate requests during startup, launch the reviewed miner in a dedicated process group sharing the coordinator console, record PID/create-time/executable identity, and serialize its actions with inference. Shutdown/cancellation must prevent delayed restart and reconcile any process already started.
- Use one explicitly reviewed, private local config copied from the placeholder template. Replace paths and literal wallet/worker arguments locally; environment placeholders are not expanded. `new_console: false`, external stop/restart/adoption false, force termination false, and `only_if_stopped_by_coordinator: true` remain the intended scope. Do not enable force merely to bypass failed stop verification.
- Independently verify upstream idle, no competing coordinator/client traffic, the actual executable and process tree, and absence/disablement of all external watchdog/relaunch paths. A historical topology note is insufficient.
- Preload the intended Qwen model through separately authorized means; keep it resident. Use only the reviewed `/v1/chat/completions` path, one isolated client, no model operations or automatic model loading and no external process actions. No model-load blocking hook is configured in the template, so explicit load routes are rejected.
- For this narrow single-domain experiment, enforce the restrictions above. General cross-resource use additionally requires the pending arbitration design and tests; a snapshot idle check is insufficient.
- Review an exact-identity abort procedure with the operator present. Do not kill by image name (`python.exe` or every Krig instance), attach foreign consoles, alter shared client/service configurations, or claim automatic CUDA cleanup. Before any terminate/kill, reverify the recorded PID/create time and approved target; ambiguity means no action pending operator reconciliation.

## Current read-only CLI syntax

These commands inspect config/code only; they were not used to run live services during review:

```powershell
python -m resource_coordinator.cli config validate --config <private-reviewed-config.yaml>
python -m resource_coordinator.cli --help
```

`diagnose` is read-only but does query the GPU, configured process table and coordinator status; no such live probe was run in this review. Its exit code means the diagnostic command completed, not that the system is safe. Low utilization or a model list cannot establish upstream termination or miner ownership. `status` currently exposes inference lease/hold data, not the process-ownership display assumed by the old plan.

## Proposed first experiment after the gates are closed and authorization is explicit

1. Record exact software/config identities and establish the isolated single-client/preloaded-model conditions.
2. Through the reviewed same-process harness, start the single authorized miner and record verified launch identity and signalable console group. Failure to establish identity/group stops the test.
3. Send one explicitly authorized non-streaming inference through the proxy. Observe pending reservation and cooldown cancellation before stop, actual miner/descendant absence before upstream forwarding, terminal HTTP completion, and active/pending returning to zero.
4. Observe one full **configured** cooldown (template: 30 seconds) and exactly one authorized miner resume. Check Qwen remains loaded. This review does not certify that mining can safely coexist with the resident model's VRAM allocation.
5. Stop using the reviewed lifecycle path; reconcile the exact miner and upstream execution state. Record evidence and stop at the next checkpoint.

Client-abort/stream interruption, native tool workflows, operator recovery and crash/restart scenarios are separate experiments requiring separate scope and approval. If any unexpected state occurs, stop admission, leave mining stopped, and establish actual upstream termination independently. Never use recovery or coordinator restart simply because GPU utilization appears low. No automated model unload/reload or shared service/client rollback is prescribed.

## Completion evidence required for a future GO

| Gate | Current result |
| --- | --- |
| Offline corrections and tests | Implemented; see review report |
| Supported coordinator-owned starter with serialized shutdown | Missing — blocker |
| Reviewed real config, exact process/console topology | Not established — blocker |
| Single-domain/client isolation and no independent watchdog | Not established — blocker |
| Exact-identity abort plan and operator sign-off | Not established — blocker |
| Explicit authorization for the live experiment | Not granted by review |

No live operation is authorized by a GO recommendation, should a later review reach one.
