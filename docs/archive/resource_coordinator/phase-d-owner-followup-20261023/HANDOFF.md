# Resource Coordinator current handoff

Date: 2026-10-23

## Current worktree

- Branch: `resource-coordinator-followup-20261023`
- Worktree: `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-phase-d`
- Base: `main` at `a0ff1778ef1737f1c23d8f1cbd7ef57d4973af75`
- State: Phase D and the T1 telemetry integration are committed as `a3bbb53d` on this branch; no push or merge was performed.
- T1 source branch `resource-coordinator-20261019-0915` remains preserved at `dd8dd7ff`.

## Integration result

T1 adds local SQLite WAL telemetry, a bounded observational event queue, query/export/prune commands, and request/resource/model event records. The integration preserves the current Phase D managed service lifecycle, admission gates, abort behavior, completion classification, and CLI commands including `diagnose`, `preflight`, and `abort`.

The collector now maps actual `lmstudio.inference_*` and `lmstudio.model_load_*` events and unwraps nested lease payloads. Telemetry must be explicitly enabled in config; its database defaults to `telemetry.db` relative to the service working directory. The CLI's prune operation requires `--force`. Telemetry is observational, can drop records when its queue is full, and is not the safety journal.

## Validation

- Full offline module suite: **257 passed, 4 skipped** (261 collected).
- Ruff check: passed.
- Ruff format check at 120 columns: 46 files already formatted.
- Mypy with `--ignore-missing-imports`: passed on 22 source files.
- The skips are opt-in Windows/live cases; no live LM Studio, miner, model, or GPU operation was run during this integration.

## Safety state and next work

The historical single-request supervised Qwen acceptance is recorded in this repository; it is not authorization to repeat it. A new live operation requires fresh host checks and separate authorization. Unattended operation remains NO-GO pending crash-safe write-ahead state and startup reconciliation, cross-resource transactions and single-instance authority, process containment, and a strict shutdown deadline.

Next: review the [inference crash-recovery implementation plan](plans/20261023-inference-crash-recovery/00_implementation-plan.md) and approve inline execution. The [approved design](INFERENCE_DURABLE_STATE_DESIGN.md), [durable-state recovery note](DURABLE_STATE_RECOVERY.md), and [cross-resource design boundary](CROSS_RESOURCE_SERIALIZATION.md) describe scope and remaining constraints. See [the safety review](PHASE_D_SAFETY_REVIEW.md), [the acceptance plan](SUPERVISED_LIVE_ACCEPTANCE_PLAN.md), and [the telemetry usage section](../README.md#opt-in-to-local-telemetry).
