# Resource Coordinator current handoff

Current workstream: **minimal LM Studio activity automation**, branch `resource-coordinator-phase-d` at `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-phase-d`, based on preflight commit `44ce5d6ec9b56ecb75c2cfb4ff848b85964c2764`.

Offline implementation adds explicit known model-load handling on the existing `gpu.inference` resource with an exclusive lease, matching process-stop policy and the same cooldown as inference. Pending exclusive reservations now prevent later shared admission, and final idle restart actions share an arbitration lock with request registration. Generic opt-in service/CLI process lifecycle controls were added while retaining legacy miner flags. `LeaseManager` accepts a monotonic clock and async sleeper for deterministic cooldown tests. See [minimal automation configuration and route limits](../README.md) and [implementation plan/status](plans/20261019-1600_minimal-lmstudio-activity/STATUS.md).

**Minimal-workflow code review completed:** review found and fixed a standalone model-load admission gap; see the review record below. Managed model loading remains tied to the configured stop policy and exclusive `gpu.inference` reservation. Offline validation does not establish host readiness or authorize process/model control. The preflight below remains NO-GO; no live test, process control, inference, or shared configuration change occurred.

Implementation commit: `eff159c40f0929ce85f9ca9584e35753e60170c3`.

Validation: the module suite passed with 10 test cases requiring pytest temporary-directory access and one subprocess test excluded. Those temporary-directory cases fail in this Windows sandbox because pytest receives `WinError 3/5` on the module's configured temp root; `test_command_action` cannot launch its subprocess here. Ruff lint passes. Ruff format check reports existing module-wide formatting drift. Mypy reports only missing `types-psutil` stubs in existing files.

### Minimal workflow safety review — 2026-10-19

Reviewed implementation `eff159c40f0929ce85f9ca9584e35753e60170c3` against the Phase D safety findings and acceptance contract. Two ownership/admission gaps were fixed. Standalone gateway mode previously admitted model loads when any blocking hook was registered, including a no-op hook; it now rejects model loads unless a managed service validates the matching stop policy (`717316713cb8a86a8a4d3f5465f31b146414766c`). Automatic restart policies also accepted `only_if_stopped_by_coordinator: false`, which could relaunch a process that the user had already stopped. Config parsing and service preflight now reject that setting (`8d21630f1c5d953b1ec424fd7bb74434c5a10485`).

Arbitration review confirmed FIFO pending-exclusive behavior: an earlier exclusive load blocks later shared inference reservations, while earlier shared reservations drain before the load. Reservations are recorded before hooks; failed process stops veto forwarding. The cooldown starts on final lease release after normal operation completion, uses a monotonic clock, and is cancelled by new reservations. Uncertain forwarded operations retain restart inhibition. The idle-start decision holds the lease condition through the serialized process-start action, so a boundary request waits until start completes and then executes its stop policy, or registers first and blocks the restart. This is safe serialization, not a strict response-time bound; OS calls and callbacks can delay progress.

Validation: the full offline suite passed **230 tests** in the writable test context, including the subprocess test excluded by the earlier sandbox run. The unprivileged attempt reproduced 10 temporary-directory errors, one subprocess-launch failure, and pytest teardown `WinError 5`; the permitted rerun passed. Ruff lint passed; all 36 tracked Python files pass Ruff format at 120 columns. Plain Mypy reports only three existing `psutil` `import-untyped` errors because `types-psutil` is absent; `python -m mypy --ignore-missing-imports modules/resource_coordinator/resource_coordinator` passes on all 16 source files. No unrelated formatter changes were made.

Review outcome: **GO for read-only environmental validation only. NO-GO for the supervised live test** until the independent process/watchdog/client/upstream/headroom/abort gates in [the acceptance plan](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md) are satisfied and separate execution authorization is given. Unattended operation remains NO-GO. No environment facts were newly verified in this code review.

## Historical Phase D supervised-test preflight

Review outcome: **CONDITIONAL GO**, operational NO-GO until independent prerequisites and separate user authorization. Unattended NO-GO. No live operation, merge or push was performed or authorized by this outcome.

The host preflight is recorded in [the environment report](SUPERVISED_TEST_PREFLIGHT_20261019.md). It remains **NO-GO**: Krig is stopped, its binary and static launch arguments are known, but no owned process/group exists to verify; Qwen is resident and labeled IDLE, while request idleness and Qwen-plus-miner headroom are unproven; OpenCode is listening on 4096 and its endpoint is unknown; watchdog absence and crash-time intervention are unresolved. An ignored private config draft is prepared but inactive and has an invalid operator identity. No test or live control occurred.

See [full Phase D findings](PHASE_D_SAFETY_REVIEW.md), [acceptance gates](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md) and [abort/crash protocol](EMERGENCY_ABORT_PROCEDURE.md). Package 0.4.0. Keep T1 dd8dd7ff separate; combined integration is unverified.

Next action for Sol Medium: review the preflight evidence and outstanding gates. Before any fresh execution authorization, the operator must identify and inhibit every relaunch source, agree an exact out-of-band intervention path, establish one-client isolation, and provide independent request-idle and VRAM/compute headroom evidence. Durable recovery and general physical-resource arbitration remain blockers for unattended operation.
