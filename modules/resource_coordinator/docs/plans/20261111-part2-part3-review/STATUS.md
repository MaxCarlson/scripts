# RC Parts 2–3 Integration Review Status

## Source and worktree state

- Repository: `C:\Users\mcarls\src\scripts`
- Review worktree/branch: `.worktrees/resource-coordinator-part2-part3-review-20261111`, `integration/rc-part2-part3-review-20261111`
- Review branch began at Part 3 `7230d61e97632f6dfce65a2a9323568ceaf5b5b5`; Part 2 ancestor `19255b2e90b7a8904ddf324856687bc40c5e30d4`; mainline `4f4373d2533e4e0c6bd115eda6623ed65fbadc49`.
- Main → Part 2 = 4 ahead/0 behind; Part 2 → Part 3 = 2 ahead/0 behind; main → Part 3 = 6 ahead/0 behind. Part 2 and Part 3 form one direct ancestry chain.
- Main, Part 2, and Part 3 original worktrees were clean by status when ignoring inaccessible submodule metadata. The primary checkout's ordinary Git status could not inspect `pscripts` metadata (`.git/modules/pscripts` permission denied); scoped status with `--ignore-submodules=all` was clean.
- Only the Part 3 review branch contains review edits. No active competing RC assignment was reported by the agent inventory. Other worktrees were left untouched.
- The V3 plan is present by ancestry, unchanged: SHA-256 `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`; Git blob `3a1c2f7662a54469bb6dc15ad6462a4295ec93e6`.
- The Mining repository is read-only for this assignment. Its `master` was verified at `deea3e019b35615f4d95e6f510450f7f392fb82a`.

## Confirmed defect and correction

Review of `CoordinatorService.auto_recover()` found that after the atomic journal commit it removed the durable `recovery_sync` marker before removing the matching in-memory marker. An injected in-memory clear failure therefore left the process restart-denied but removed the persisted hold. A subsequent Coordinator restart could lose that protection.

The isolated red regression failed at the durable-hold assertion with `KeyError: 'gpu.inference'`, confirming the journal no longer held the recovery marker. The correction reverses that cleanup order: memory synchronization completes first, and the durable marker is the final protective record removed. A crash or memory-clear failure before that final durable write leaves the marker available to startup reconciliation.

Added regressions cover this failure boundary and two simultaneous automatic-recovery calls. Both passed after the fix. The Part 3 published branch was not rewritten; the correction lives on this review branch.

## Safety review findings

- `StateCodec` mutation entry points serialize their full load/modify/save path through the process-local `RLock`; revisions are incremented in `save_atomic()` once and stale revisions fail closed. Recovery's multi-field journal update is one atomic replacement.
- Cross-process protection relies on the service's OS-level `SingleInstanceLock`, derived from the configured durable state path, acquired before startup reads/reconciles the journal and released only on clean stop/start failure paths. The Python lock alone does not serialize an external or legacy writer that bypasses the instance lock. Such out-of-band writers must be stopped before downgrade or journal recovery. File replacement does not claim power-loss durability.
- `export_legacy_compatible()` leaves the active journal untouched, archives `RECONCILED` history separately, and preserves unresolved requests and holds. A disposable exported snapshot was successfully loaded with the actual v0.14.0 parser from commit `737bc6b2db7b68c041abffb66017164f3c883228`; both an unresolved request and primary/additional holds survived. This is source compatibility, not an operational downgrade rehearsal.
- Recovery fencing blocks GPU reservations/promotion, maintenance acquisition, idle callbacks, and supervisor operations through the common lease manager. External stage-two observations run outside the arbitration condition. Final checks and one journal transaction occur under the fence. The branch keeps Case C unavailable and does not treat idle observations as execution termination.
- Gateway ordering persists `POSSIBLY_FORWARDED` before `client.send()`. Real terminal protocol completion is stored separately as `TERMINAL_VERIFIED`; interrupted forwarded work remains `UNCERTAIN` and operator-required.
- The LM Studio observer remains unavailable by default; no probe can wake a runtime. Existing manual, gaming, crash-backoff, maintenance cooldown, and Coordinator-owned process checks remain in place.

## Validation

Environment: Windows PowerShell, CPython 3.12.10, pytest 9.0.3. RC imports came from the review worktree. Tests used local fake miners and temporary journals. H3 combined-candidate execution is in progress; see checklist and final update.

| Check | Result |
|---|---|
| RC durable-state, lease, service lifecycle, and timing test selection | **64 passed**, 0 failed/errors/skipped; JUnit under `modules/resource_coordinator/.pytest_tmp_review_safety_core/junit.xml` |
| New synchronization and concurrent-recovery regressions | **2 passed** with normal socket permissions; the synchronization-clear regression failed before the correction, as expected |
| Timing-sensitive acceptance test alone | **3/3 passes** with separate absolute basetemp roots; it also passed in the 64-test selection |
| v0.14 rollback parser | **Passed** using the actual parser from Git commit `737bc6b`; test snapshot and archive under `.pytest_tmp_rollback_parser_review/case-a017phje` |
| Changed-code Ruff/compile/diff | **Passed** for the correction before docs were added; final checks to be recorded after documentation and H3 |
| Combined H3 against review candidate | Pending |

The timing-sensitive test's prior full-suite instability did not reproduce in four focused executions. There is no evidence yet isolating a particular scheduler, cleanup, or state collision cause; it remains covered in the review suite rather than being declared fixed by this sample.

## Integration decision

No authorization to update protected `scripts/main` is present in this handoff; the earlier Part 2/3 instructions also withheld mainline merge authority. Therefore this review will publish a candidate branch and exact fast-forward recommendation only. Part 2/3 source is not merged. Production installation, H4, H5, and unattended recovery remain separate.
