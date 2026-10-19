# agent_benchmark handoff — P1 corrective integration complete

## Workspace / commits

- C:/Users/mcarls/src/scripts-agent-benchmark; branch `agent/agent-benchmark`. Local commits only; no push or merge to main.
- Baseline: `91d9d26b`, Gemini's scope-audit pass, preserved and reviewed.
- `3560770b`: independent submission-start tracking and persistent unknown-submission blocking; module version 1.0.1.
- `a16d6194ce9e949999807bb2ef3d9e115f8e4003`: positive verifier completion evidence, ownership journaling order, explicit scope uncertainty and regressions.
- Earlier integration preserved: `072683f1` merged complete corrected core through exactly `a185621552368e7ed4442659750a64ae7986ecda`; `f973ee67` fixed canonical package shadowing; `5d9637b0` integrated pipeline/CLI; `2cfd66fd` registered CLI help. Corrective baseline `c299e1b2` remains intact.

## Current outcome

Both P1 findings reproduced with failing offline regressions before fixes. Full offline validation passes. No worker was dispatched and no shared service was contacted/reconfigured during this corrective pass. A new live benchmark requires separate user authorization.

The original live run remains at `reports/20261019T114143Z-dfd3bbc9`: exactly one canonical TrialResult, `timed_out` under the original 60-second task budget, with passing hidden verification. This is not a model task success and is not live validation of the corrected code. Read-only re-audit confirms 1 external path violation, 3 mutation events and 3 unverifiable shell operations. Historical results/evidence were not rewritten. All 32 files under reports/ retained identical path/content digest `e844621bb215b1c9b703fc83e49ba79f4a8d4355c147ff964d21ae9aeaa850b1`. Keep reports/ untracked and retain the live workspace until user review.

## Interfaces and corrections to preserve

- `DispatchGuard.submission_started` is set immediately before dispatch in `attempt.run_attempt`; runner reservation release uses this independent fact, never receipt emptiness. It remains true throughout an attempt. Empty/malformed receipts, transport failures, or lost receipts after possible submission keep pending.json and block later processes/output directories. Known receipt fields are merged with the initial uncertainty marker.
- Lifecycle ownership is journaled before secondary dispatch.json evidence, retaining job/session/message IDs if that secondary write fails. Total storage failure still cannot guarantee evidence persistence; the pre-existing durable pending reservation must remain blocking.
- `evidence.verify` requires both exit zero and a fresh completion.json receipt with matching nonce, status passed and a positive integer checks_completed. It passes AGENT_BENCH_COMPLETION_PATH and AGENT_BENCH_VERIFICATION_NONCE through the child environment. New verifiers must write that receipt only after all assertions pass. Diagnostic stdout, including a printed PASS, is not completion evidence.
- py-grep-smoke catches BaseException specifically at submitted-module import and submitted-function call boundaries, classifying SystemExit/KeyboardInterrupt as incorrect implementation. Abrupt os._exit(0) yields infrastructure_error for missing completion evidence; it cannot pass. This remains trusted-fixture process isolation, not a sandbox against deliberate receipt forgery or arbitrary hostile code.
- Smoke suite version is now 0.1.1 because the verifier contract changed. Historical 0.1.0 artifacts stay unchanged. Default task budget remains 60 seconds; cancellation grace remains 10 seconds. Do not pool different suite versions implicitly.
- `ScopeAudit.to_dict()` retains separate snapshot_violations/transcript_violations and adds compliance: compliant, violated, or uncertain. Relative tool working directories resolve against worker workspace. Failed/non-completed mutations are uncertain because partial writes are possible. Missing/malformed transcripts are uncertain. OpenCode StructuredOutput is a completion-report tool, not opaque filesystem execution.
- `results.trial_from_attempt` continues to use frozen S1 only. Known scope violations fail a verifier-passing attempt, but never overwrite earlier infrastructure_error or expired task timed_out. With only unverifiable scope operations or missing scope audit, a verifier-passing attempt becomes unscored; worker_first_pass and scope_compliance remain unavailable. Known verifier failures remain failed even when scope is uncertain. Known violations set scope_compliance=0. Violation counts are known detections, not a claim of exhaustive coverage.
- Failed S1/corrected S3 canonical persistence regression still passes. Cleanup never changes scores and still requires fresh exact session/turn/tool reconciliation within a bounded deadline. No shared-process termination or general scheduler exists.
- benchmark_core exclusively owns RunInfo, TrialResult, MetricValue, persistence, statistics and reporting. No core source changes in this pass. Tokens/tool telemetry remain unavailable when not collected.

## Validation

Interpreter: C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe. Commands from this worktree root:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/p1-acceptance-final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs --basetemp=modules/benchmark_core/.pytest_tmp_root/p1-acceptance-final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy modules/benchmark_core/benchmark_core
```

Results: agent 144 passed, 2 skipped (Windows symlink privilege in evidence_test.py and lifecycle_test.py); core 80 passed; Ruff clean; core Mypy clean in 9 files. Initial RED runs reproduced empty-receipt release, early-exit false passes, scope-uncertainty scoring, relative-workdir misresolution, partial mutation uncertainty, malformed transcript compliance, missing ownership journal IDs and structured-report misclassification. Final checks have no known failures.

## Deferred reporting correction — Gemini Flash

File `modules/benchmark_core/benchmark_core/reporting.py`, function `render_report_md`: its resource-metric loop currently omits rows when available_count is zero. Render present all-unavailable metrics with mean/median N/A and available/total 0/N instead. Keep measured rows and JSON/CSV unchanged. Add offline reporter tests for entirely unavailable worker tokens and mixed availability. Keep canonical schemas unchanged. This is a small, isolated core-owner task; no core changes were made here.

## Next model allocation / copyable brief

Routine fixture expansion: Gemini Flash. Bounded audit improvements: Luna High. Return to Sol Medium for lifecycle, integration, verifier architecture or attribution issues. Work sequentially; no local-agent delegation or automated model routing.

Copyable next-agent instruction: Work in C:/Users/mcarls/src/scripts-agent-benchmark on agent/agent-benchmark. Confirm status/branch and read this handoff plus docs/plans/20261019-implementation/plan.md. Preserve commits 91d9d26b, 3560770b and a16d6194. Add routine Phase 2 fixtures only after the user chooses that next task; use the bundled task layout and positive verifier completion receipt contract. Do not alter shared schemas, weaken scope uncertainty/first-attempt scoring, retry a worker, repair live S1, modify reports/, or start/reconfigure services. Every live run needs separate authorization. Commit tested scoped work, update the handoff, and return to Sol for architecture/lifecycle problems.
