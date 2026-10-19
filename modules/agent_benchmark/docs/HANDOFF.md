# agent_benchmark handoff — integrated Phase 1c, scope audit corrected, live gate pending

## Workspace / commits

- C:/Users/mcarls/src/scripts-agent-benchmark; branch agent/agent-benchmark. All changes local; no push/merge to main.
- 072683f1: merged complete core history through exactly a185621552368e7ed4442659750a64ae7986ecda (authorized), preserving history.
- f973ee67: reproduced/fixed core outer/inner package shadowing; canonical class identity preserved. benchmark-core version 0.1.1.
- 5d9637b0: tested canonical integration, strict scoring, persistent dispatch blocking, installed CLI, packaged task. agent-benchmark version 1.0.0.
- 2cfd66fd: associated required CLI help registration; scripts_help metadata 0.6.0.
- Baseline corrective pass c299e1b2 preserved.
- Current commit: scope audit corrective pass (transcript-based mutation auditing, external path detection, protected-file restoration detection, traceable re-audit utility, and regression tests).

## Current outcome

The Phase 1c software pipeline is integrated and validated offline. The first live py-grep-smoke acceptance run completed at the infrastructure level (recording timed_out due to exceeding 60s budget).

A scope auditing gap discovered during that run was addressed:
- The filesystem snapshot audit authoritatively monitors observable S0/S1 workspace mutations, but misses external filesystem mutations (e.g., worker writing to `C:\Users\mcarls\AppData\Local\Temp\opencode\test_grep_smoke.py`) and mutations reverted before S1 capture.
- Transcript auditing (`audit_transcript`) inspects raw OpenCode tool calls for mutation tools (`write`, `edit`, `patch`, `delete`, `rm`, `remove`).
- Resolves relative paths against execution directory (`workdir` or workspace root), normalizes Windows case, and enforces directory boundary prefixes.
- Identifies external mutations and edits to protected files (`instruction.md`, etc.).
- Excludes read/inspection tools (`read`, `cat`, `glob`, `grep`, etc.) from mutation classification.
- Classifies opaque commands (`bash`) or malformed tool inputs as `UnverifiableOperation` without guessing.
- `audit_scope` combines snapshot and transcript audits into a unified `ScopeAudit` record, persisted to `scope-audit.json` and recorded in `checkpoints.json`.
- `results.py` includes `scope_audit` in canonical `TrialResult.details` and respects strict scoring precedence (`timed_out` remains `timed_out` even when scope violations occur).
- Non-destructive `reaudit_trial` supports offline verification of historical trial evidence without overwriting existing files. Verified against `reports/20261019T114143Z-dfd3bbc9`: correctly identifies 1 external violation (`test_grep_smoke.py`), 3 mutation events, and 3 unverifiable operations (`bash`). Historical acceptance run files in `reports/` were preserved untouched.

## Interfaces to preserve

- results.trial_from_attempt consumes frozen AttemptEvidence and returns canonical benchmark_core.TrialResult. Core alone owns RunInfo, MetricValue, persistence, statistics and reports. No duplicate schemas/renderers.
- runner.run_benchmark: one task, one explicit variant, one repetition per invocation. Reserves stable persistent state before connecting; core save_run/append_result/summarize/generate_reports. Includes ordinary infrastructure/caller-cancellation outcomes as one canonical record when storage is writable.
- Strict scoring order: uncertainty/missing evidence/execution errors -> infrastructure_error; expired worker budget -> timed_out; abnormal non-completed worker termination -> infrastructure_error; verifier infrastructure failures -> infrastructure_error; scope violation -> failed; otherwise independent verifier. Verifier pass never overrides these facts. Missing token/tool usage is unavailable, not zero.
- Critical regression: failed canonical S1 persisted/reloaded remains failed after corrected S3 passes. No retry/repair path exists in Phase 1c. Cleanup is separate and never rewrites canonical scores.
- state.command_lock uses OS file locking (no process/PID manager). pending.json survives exit and blocks all subsequent runs sharing the state dir, even with different report outputs. No stale-time/force override. Crash releases OS lock but retains receipt. Before-dispatch preparation failures safely release reservations when no submission was possible.
- Default state ~/.local/share/agent-benchmark. Keep the same state dir across invocations; explicit separate state dirs are intended for isolated tests. Pending evidence pointer/diagnostics must not be removed to bypass unresolved execution.
- runner.cleanup_trial previews unless execute=True. With execution, revalidates exact recorded handle/workspace and fresh remote termination; supported cancellation when needed. Unresolved confirmation preserves resources/blocking. Confirmed cleanup filesystem failure is separate from evaluation and may release dispatch blocking. No shared process termination.
- bridge.py preserves corrective null/malformed-time, named aborted-error, worker report and sanitized MCP error behavior; transient HTTP observations recover within original task budget. No resubmission.
- OpenCode 1.19.3 source confirms final StructuredOutput may retain tool-calls. This exception requires requested json_schema, completed StructuredOutput tool in final assistant, completed timestamp, idle session and no unfinished tools. Arbitrary non-null structured or ambiguous multi-assistant ordering cannot authorize cleanup. See TERMINATION.md for primary source links. Future version/schema changes require source/live evidence, not relaxed confirmation.
- Byte-exact S0/S1 archives outside worker workspace; authoritative verification on disposable copy. Trusted fixtures only, not a hostile-code sandbox.

## Task location / CLI

Original fixture bytes unchanged, relocated to agent_benchmark/tasks/py-grep-smoke for wheel package data. Tests and default CLI resolve the bundled location. Future fixtures belong beside it; update package-data patterns only if new asset types require it. Public worker files remain seed + instruction + manifest. Hidden verifiers never copied into worker tree.

Installed console command agent-bench and python -m agent_benchmark support plan/run/status/cleanup; all args have short/long forms. run requires -x/--execute. plan/status/cleanup preview are read-only. Example live command (ONLY after separate authorization and runtime readiness):

```powershell
agent-bench run -m EXACT_MODEL_ID -x -o reports
```

Inspect `agent-bench status -r reports/RUN_ID`. Cleanup preview `agent-bench cleanup -r reports/RUN_ID`; execute `... -x` only for owned trial resources. For pending worker recovery, cleanup can find the trial from the shared state receipt without -r. A corrupt or unknown-submission receipt fails closed; inspect retained diagnostics instead of blind retries.

Canonical report structure: reports/<run_id>/{run.json,trials.jsonl,summary.json,summary.csv,report.md,evidence/trial-001/...}. Actual runtime/version/permission facts are saved in RunInfo metadata when available. Context/reasoning/warm-state fields remain explicitly unknown/unverified if not measured. No coordinator token savings claims.

## Verification

Actual interpreter: C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe. Both editable installs point to this worktree; normal and modules-first canonical imports verified for both modules. New console entry point requires reinstall/refresh when adopted elsewhere.

From repository root:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/integration-final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy modules/benchmark_core/benchmark_core
```

Agent: 113 passed, 2 skipped (Windows symlink privilege). Core: 80 passed; Ruff clean; Mypy clean in 9 files.
Scope audit regression tests verify:
- External temporary file write/edit detection.
- Protected workspace file mutation and restoration detection (reverted edits).
- Compliant workspace edits and non-mutating tool calls (reads/globs).
- Malformed/unverifiable tool invocations recorded transparently as `UnverifiableOperation`.
- Scoring precedence preservation: `timed_out` preserved over scope violations when budget expired.
- Read-only `reaudit_trial` accurately audits historical run `reports/20261019T114143Z-dfd3bbc9` offline.

## Next model allocation / copyable brief

Architecture and offline integration are resolved. Gemini Flash can own routine Phase 2 fixture expansion; 6-Luna-High can own later bounded audit utilities. Keep live lifecycle/integration debugging with Sol Medium. No local-agent delegation, automated model router, generic scheduler or supervisor.

Copyable fixture brief: Work sequentially in C:/Users/mcarls/src/scripts-agent-benchmark on agent/agent-benchmark. Confirm cwd/branch/status; read this handoff and Phase 2 task descriptions in docs/plans/20261019-implementation/plan.md. Add only independently verifiable fixtures/tests under modules/agent_benchmark, using the bundled task structure. Preserve canonical scoring, lifecycle/resource ownership, CLI authorization and persistent unresolved blocking. Do not alter benchmark_core or unrelated modules, dispatch local development agents, start services, or claim real-model acceptance. Pin imported task revisions and retain actual attribution/licenses. Run focused tests plus module suite with -rs, commit tested work, update handoff. Return to Sol if verifier contracts/lifecycle architecture need changes. Live smoke acceptance still requires the user's runtime/model/authorization; do not silently treat it as done.
