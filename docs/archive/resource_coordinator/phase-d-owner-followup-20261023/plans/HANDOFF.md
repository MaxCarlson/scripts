# Resource Coordinator Plans Handoff

## Current workstream

- Active plan: [Telemetry T1 integration](20261023-telemetry-t1-integration/STATUS.md).
- Branch/worktree: `resource-coordinator-followup-20261023` at `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-phase-d`.
- Base: current `main` commit `a0ff1778`.
- State: offline integration complete and validated in commit `a3bbb53d`; not pushed or merged.
- T1 source branch/worktree remains available at `resource-coordinator-20261019-0915` / `dd8dd7ff`.

## Completed historical plans

- [Core framework / Phase B](20261019-0915_resource-coordinator-core/STATUS.md): offline core and reliability work completed; unattended operation remains blocked.
- [Phase D controlled integration](20261019-1250_phase-d-controlled-integration/STATUS.md): service lifecycle, admission, and safety review completed. Its final review is recorded in [PHASE_D_SAFETY_REVIEW.md](../PHASE_D_SAFETY_REVIEW.md).
- [Minimal LM Studio activity](20261019-1600_minimal-lmstudio-activity/STATUS.md): managed model-load path, mock HTTP harness, usability work, and one separately authorized acceptance request are historically complete.
- [Telemetry T1 original plan](20261019-1145_telemetry-phase-t1/STATUS.md): T1 implementation is integrated into the current follow-up worktree; its original source branch remains intact.
- Active plan: [Inference Crash-Recovery](20261023-inference-crash-recovery/STATUS.md); plan drafted, awaiting user review and inline execution approval. The approved design is [INFERENCE_DURABLE_STATE_DESIGN.md](../INFERENCE_DURABLE_STATE_DESIGN.md). Requirements and broader blockers are in [DURABLE_STATE_RECOVERY.md](../DURABLE_STATE_RECOVERY.md).

## Remaining safety work

Telemetry is not crash recovery. Unattended use remains NO-GO until the coordinator has crash-safe write-ahead safety state and startup reconciliation, cross-resource transactions and machine-wide instance authority, process containment, and a strict total shutdown bound. Any new live operation remains separately authorized and requires fresh host evidence.
