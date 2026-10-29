# Runtime resource policy correction

## Scope

Supersede the benchmark's arbitrary default RAM percentage and fixed available-memory
cutoffs. Keep explicit user-selected limits, observational resource reporting, measured
LM Studio allocation estimates, model identity checks, and safe worker termination.

## Current findings

- `agent-bench experiment run` defaults `--max-ram-percent` to 100, but the scheduler
  does not pass it into `transition_model`; that function has a hidden 90% default.
- `RuntimeMemoryGuard` also has a fixed 4 GiB available-RAM floor, active even when the
  percentage option is disabled.
- Model loading adds fixed 2 GiB GPU and 4 GiB combined-memory reserves, and a separate
  model-file-size estimate multiplied by 1.25. These values do not have a measured
  universal basis for this workload.
- The investigation's trials passed `-M90`; the historical incident evidence establishes
  a severe transient host-memory rise but not a universal safe utilization percentage.

## Decisions

- Default RAM percentage and available-byte limits are disabled. Explicit limits remain
  opt-in and are propagated consistently through dispatch and model transitions.
- Resource utilization remains diagnostic. During model load, compare the exact LM Studio
  allocation estimate against available measured GPU and host capacity without arbitrary
  reserves. Missing measurements or estimate failures remain a pre-load infrastructure
  block; an actual allocation failure remains a recorded model-load failure with no retry.
- Model inventory, busy-state, context identity, command success, and confirmed worker
  termination checks remain in force.
- Record resource values before/after unload and load; do not wait for a percentage threshold.

## Status

Implementation and focused validation are complete. No live model load or inference was part
of this harness-policy change.

## Implementation and verification

- CLI and scheduler defaults are now `None`; the hidden transition default is gone. An explicit
  percentage limit is propagated into both the in-flight worker guard and model transition.
- The runtime 4 GiB floor is opt-in at the guard API; unavailable memory telemetry does not abort
  dispatch unless a limit was explicitly configured.
- Removed the fixed 2 GiB GPU and 4 GiB combined reserves and 1.25x model-size estimate. The exact
  LM Studio estimate must fit current measured GPU and combined host/GPU available capacity; missing
  measurements remain a pre-load block. Model command errors still fail without retry.
- After unload, the transition checks empty model inventory and logs memory measurements. It no
  longer waits for a percentage or fixed-byte threshold. Resource snapshots are logged before and
  after model load.
- Historical memory-safety and context-safety plans are annotated as superseded for those limits.

Validation on the investigation worktree and source import:

- Focused resource policy tests: 14 passed; scheduler propagation test: 1 passed.
- Full Agent Benchmark suite: 397 passed, 3 skipped, 2 synthetic-Git tests failed because the
  nested temporary workspace exceeded Windows path length. Retrying only those two tests with a
  short `%TEMP%` base path: 2 passed. Thus every full-suite test passed across the full run and
  targeted retry; the three symlink-privilege skips remain expected.
- `python -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests` and
  `git diff --check`: passed.

The Windows sandbox hangs in `pytest-asyncio` while creating its loopback socketpair. Tests were
run outside that socket restriction. A shared editable install also redirected imports to the main
checkout; test invocations explicitly loaded the investigation worktree package.

## Next actions

1. [x] Add regression tests for default-disabled guards, explicit thresholds, measured estimate
   capacity, and transition propagation.
2. [x] Implement the smallest compatible behavior change, update module version/docs.
3. [x] Run focused module tests and lint; revise historical memory-safety docs as superseded.
4. [ ] Continue B1 analysis and controlled comparisons after this phase is verified.
