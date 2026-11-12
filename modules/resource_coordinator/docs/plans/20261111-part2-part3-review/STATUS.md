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
- During review, current `main` advanced from `4f4373d2` to `2580fa50`, then to `b45f3950595bec5c9af4b076ea8b2db93711eba0`. GitHub's branch API confirmed the latest published SHA, and a permitted fetch updated local `origin/main` to match it.
- The first 13 commits added since `4f4373d2` change only `modules/agent_benchmark/` and `modules/benchmark_core/`. Two later commits change only `modules/notifications/`. There is no Resource Coordinator or `scripts_help` overlap. Both updates were merged into this isolated review branch; the latest merge candidate is `af56188dd5a7b132022c80e6a05b0f309b0f8df8`, with current `main` as an ancestor. No protected branch was updated.

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

Environment: Windows PowerShell, CPython 3.12.10, pytest 9.0.3. RC imports came from the review worktree. Tests used local fake miners and temporary journals. H3 ran against the exact combined review source. The production Coordinator was not contacted.

| Check | Result |
|---|---|
| RC durable-state, lease, service lifecycle, and timing test selection | **65 passed**, 0 failed/errors/skipped; final JUnit: `modules/resource_coordinator/.pytest_tmp_review_safety_final/junit.xml` |
| Recovery sync ordering, simultaneous calls, and post-commit cancellation | All **3 new regressions passed**; the synchronization-clear regression failed before correction, as expected |
| Timing-sensitive acceptance test alone | **3/3 passes** with separate absolute basetemp roots; it also passed in the 65-test selection |
| v0.14 rollback parser | **Passed** using the actual parser from Git commit `737bc6b`; test snapshot and archive under `.pytest_tmp_rollback_parser_review/case-a017phje` |
| Combined Mining/RC H3 against the current integrated candidate | **8 passed, 0 failed/error/skipped** on RC `af56188dd5a7b132022c80e6a05b0f309b0f8df8` and Mining `deea3e019b35615f4d95e6f510450f7f392fb82a`; JUnit and JSON: `C:\Users\mcarls\AppData\Local\Temp\rc-part23-h3-3be767f586d946149a7b2a5b788c2623\junit.xml` and `summary.json` |
| Changed-code Ruff, compilation, import provenance, and Git diff integrity | **Passed** on the integrated review branch; RC import resolved from this worktree and reported version `1.0.0` |
| Focused RC selection after latest current-main merge | **65 passed**, 0 failed/errors/skipped; JUnit: `modules/resource_coordinator/.pytest_tmp_review_latest_main_3c0a5a94f9b549bbb887d91878db7cd4/junit.xml` |

The timing-sensitive test's prior full-suite instability did not reproduce in four focused executions. There is no evidence yet isolating a particular scheduler, cleanup, or state collision cause; it remains covered in the review suite rather than being declared fixed by this sample. H3 emitted two dependency deprecation warnings (`websockets.legacy` and `WebSocketServerProtocol`), with no product failures. No RC source or test changes followed the H3 run; later commits touch only review tooling and documentation.

H3 ran the unchanged Mining `tests/h3` suite using the production `CoordinatorClient` and `Runner.trial()` against the integrated review candidate's actual RC gateway and manager. RC source and tests were byte-identical to the H3-tested source commit `bef77f29443375b4c96cbeab11f16d350b722f97`; the intervening merge added only unrelated `agent_benchmark` and `benchmark_core` paths. The adapter changed only `h3_support.RC_COMMIT` in memory and asserted exact source imports/commits. It did not edit Mining. The tests used an ephemeral loopback listener, fake GPU observer, fake Coordinator miner, and harmless suspended children.

The merged H3 invocation used the Mining H3 Python `C:\Users\mcarls\src\Mining\.venv\Scripts\python.exe`, RC dependency site-packages `C:\Users\mcarls\src\scripts\.venv\Lib\site-packages`, and a clean detached RC worktree at `af56188dd5a7b132022c80e6a05b0f309b0f8df8`. It emitted the artifacts above; that temporary validation worktree was subsequently removed after confirming it was clean.

Additional regression command (from `modules/resource_coordinator`, exit 0):

```powershell
python -m pytest tests/test_durable_state.py tests/test_leases.py tests/test_service_lifecycle.py tests/test_final_acceptance_readiness.py::test_repeatable_acceptance_runs_preserve_evidence -q --basetemp C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-part2-part3-review-20261111\modules\resource_coordinator\.pytest_tmp_review_safety_final --junitxml C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-part2-part3-review-20261111\modules\resource_coordinator\.pytest_tmp_review_safety_final\junit.xml
```

The original Part 3 full-module evidence remains **849 passed, 7 skipped, 3 deselected, 0 failed**. Its excluded live listener and live-mode tests remain H4/H5 gates; the latter's guard detected running KRig during the earlier attempt, with no process operation. The timing test was excluded from that full run, but passed independently three times and inside the 65-test selection. No full suite rerun was needed after a one-line cleanup-order correction and focused regressions.

The final focused command was run from `modules/resource_coordinator` with `--basetemp` set to the absolute `.pytest_tmp_review_merged_7938bc230d8746999ca77e7033f18596` path and a JUnit report at the path listed above; it exited 0. Ruff checked every changed Python file under `modules/resource_coordinator/`, compilation covered `resource_coordinator/` and `tests/`, import provenance pointed into this review worktree, both committed and working-tree `git diff --check` passed, and a source/test diff against H3 commit `bef77f29` was empty.

An initial sandboxed rerun stalled after 12 cases before producing a failure; it was interrupted. The same isolated fake-backed selection completed under the normal permitted socket context with 65 passed and exit 0. No live Coordinator, KRig, LM Studio, or GPU operation was used.

Exact final H3 invocation (run from the temporary detached RC worktree at the tested commit; the worktree was removed after the clean-state check):

```powershell
& '.\modules\resource_coordinator\docs\plans\20261111-part2-part3-review\run_combined_h3.ps1' -MiningRoot 'C:\Users\mcarls\src\Mining' -RcRepo 'C:\Users\mcarls\src\scripts\.worktrees\rc-h3-review-af56188dd5a7b132022c80e6a05b0f309b0f8df8' -ExpectedRcCommit 'af56188dd5a7b132022c80e6a05b0f309b0f8df8' -PythonExe 'C:\Users\mcarls\src\Mining\.venv\Scripts\python.exe' -RcPythonSitePackages 'C:\Users\mcarls\src\scripts\.venv\Lib\site-packages'
```

Static checks ran after the latest main merge with the scripts repository Python `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`: `python -m ruff check @changed` from the RC module directory (where `$changed` was every changed `.py` path under `modules/resource_coordinator/` relative to that directory), `python -m compileall -q <review-worktree>\modules\resource_coordinator\resource_coordinator <review-worktree>\modules\resource_coordinator\tests`, a Python import/version provenance assertion, `git diff --check origin/main...HEAD`, `git diff --check`, and `git diff --exit-code bef77f29443375b4c96cbeab11f16d350b722f97 HEAD -- modules/resource_coordinator/resource_coordinator modules/resource_coordinator/tests`. All exited 0.

## Integration decision

No authorization to update protected `scripts/main` is present in this handoff; the earlier Part 2/3 instructions also withheld mainline merge authority. Therefore this review will publish a candidate branch and exact fast-forward recommendation only. Part 2/3 source is not merged. Production installation, H4, H5, and unattended recovery remain separate.
