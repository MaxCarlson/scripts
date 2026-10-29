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

## Follow-up investigation (2026-10-29)

The RAM-policy phase was committed and pushed as `d1e6342a`. Its historical 90% and fixed-byte
threshold findings above describe the pre-fix code; they are not current dispatch policy.

The B1 analogue analysis and a small first workflow comparison are recorded in
`experiments/qwen_runtime_investigation/evidence/b1-workflow-comparison.md`. On task revision
1.0.1, fresh single-stage `none`, task-derived checklist, and one bounded repair each reached
edits and terminated normally, but all three failed an independent lifecycle assertion. A
separate revision-1.0.0 repair passed; do not combine the task revisions or infer reliability
from one success. The checklist did not prevent the visibility-resume bug. The repair fixed that
behavior but regressed `close()` abort and single-flight behavior.

The first live Monitor 0.6.0 observation on the isolated 4196 session saw streaming text deltas
during inference, but zero reasoning-delta events. Persisted history was complete; the live
snapshot ended at its deadline. Monitor-reported effective options did not match the project-local
OpenCode config, so actual outbound reasoning-field delivery is still unverified. See the workflow
report for counts and attribution limits.

The Monitor `found=false` cases are resolved: two earlier sessions have no trial-local recorder
log, so their Monitor history was never persisted. Two later recorded sessions were queried
against the shared evidence DB instead of their per-run databases. Querying each correct
`runs/EXP_.../telemetry.sqlite3` with endpoint 4196 returns complete history and zero gaps.

The task-instruction append variant is implemented in Agent Benchmark and has seven focused tests.
It records the variant file's resolved path, SHA-256 and byte count in experiment metadata. Raw
run directories, session logs and the telemetry database remain experimental evidence and must
not be staged as implementation artifacts.

## Remaining work

1. [x] Complete code-level B1 visibility-resume and single-flight root-cause analysis.
2. [x] Run one matched single-stage, checklist, and bounded-repair comparison; preserve all first
   attempt verdicts and report failures separately.
3. [x] Validate live text-event delivery and compare it with persisted history; retain the
   outbound-parameter provenance gap.
4. [x] Diagnose Monitor `found=false` cases by recorder lifecycle and database/session scoping;
   update coverage claims without reconstructing missing telemetry.
5. [x] Resolve whether to expand the current matrix: no further same-condition repeat is
   justified now. The three matched B1 workflow conditions all failed different correctness
   checks, so another unchanged run would not test a new intervention. Keep the result as a
   stage-gate failure; test again only after a concrete workflow change, and keep the local
   policy at independently verified small tasks with escalation on failed verification.
6. [x] Validate and push the allowlisted implementation/report checkpoint as `f6ca0d59` to the
   isolated branch. Raw telemetry, prompts, logs and runtime caches were excluded.
7. [x] Retain the live OpenCode outbound-parameter capture gap as unresolved. Project config,
   mock captures, and zero reasoning-token observations are not request-level proof. Do not add
   transport interception without a reviewed path; correlate any future capture with an already-
   planned correctness inference.
