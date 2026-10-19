# Trial-local scratch policy

Status: implemented and validated offline; stop at review checkpoint. No inference or shared-service API/configuration changes. Accepted Phase 1d documentation committed as 8bd05cdd; reviewed scratch implementation and regression tests committed as 45a096d50f50948a1a081188a3414c81a76ed292.

## Decision and scope

Use scope policy `trial-local-scratch-v1`, reserved directory `.agent-bench-scratch` inside each fresh trial. Production runs enable this policy; historical evidence without a recorded policy retains strict task-only auditing. Unknown recorded policies fail closed. Task manifests/verifiers and canonical scoring precedence stay unchanged. Package minor version advances to 1.2.0.

Compared alternatives: whitelisting shared Temp/opencode would mix resources and weaken external-write auditing, so it is rejected. A per-project plugin could inject shell.env but adds configuration/code loading and an integration surface; no need for it in this bounded cooperative policy. The selected policy creates scratch before S0, gives the model an explicit path, and tells it to set TMPDIR/TEMP/TMP in each child shell command before launching temp-using programs. It does not pretend those settings were installed in the shared server.

## Source findings

Pinned OpenCode 1.19.3 shell parameters accept command/timeout/workdir, with no env field. Shell processes receive server process.env plus plugin shell.env. workdir alone does not change OS temp selection. The shell prompt renders Global.Path.tmp, explaining competing shared-temp guidance. Accepted API evidence shows the local-worker role permits Temp/opencode, which is distinct from benchmark scope permission. Python tempfile checks TMPDIR, TEMP, TMP and caches its selection; set variables before importing/starting the program. Verify locally with Python and PowerShell subprocesses, without OpenCode tool calls.

Sources: [shell environment and execution](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/tool/shell.ts), [parameters and shared-temp prompt](https://github.com/anomalyco/opencode/blob/v1.19.3/packages/opencode/src/tool/shell/prompt.ts), [Python temp selection](https://github.com/python/cpython/blob/v3.12.0/Lib/tempfile.py).

## Interfaces and evidence

A small scratch-policy module owns the version, fixed path, provisioning, safe classification and prompt text. No general shell parser or process manager. prepare_workspace takes optional scope_policy for legacy callers; new run_attempt always uses the versioned policy. Reject reserved fixture/task-path collisions before Git initialization (including empty seed directories). Full S0/S1 snapshots retain scratch bytes within the recorded evidence limits; audits separately identify task_changed_paths and scratch_changed_paths. Hidden verification receives a copy excluding scratch. Protected root Git metadata and task-forbidden paths remain protected; aliases, traversal escapes, links/junctions and Windows ambiguous path spellings do not gain scratch permission. Shell execution stays explicitly unverifiable. Scope policy is recorded in run metadata, lifecycle/runtime, audit and canonical details, with no new result schema.

Cleanup continues to require confirmed termination and owned-workspace checks; scratch has no separate cleanup command. Unknown active workers retain workspace and block dispatch. Windows junction cleanup must leave external targets intact. No host/shared temp cleanup or global environment mutation.

## Work packages and verification

1. Sol Medium: freeze this interface; write failing tests for legacy/new scope, path safety, snapshot/verifier separation and reserved collisions; implement minimal helper/audit integration.
2. Sol Medium: integrate provisioning/prompt/provenance; test mocked end-to-end canonical persistence, timeout precedence, frozen first-attempt attribution and recorded-policy re-audit.
3. Sol Medium: run agent/core suites, Ruff, core/helper Mypy and actual local Python/PowerShell temp-selection/cleanup regressions; verify all existing report hashes unchanged; update handoff and stop.

No model handoff mid-integration. Luna High can later perform bounded policy audit/test expansion; Gemini Flash handles routine fixtures only on further instruction. A separately authorized live trial is required to observe model adherence, actual OpenCode shell environment selection and interactions with its built-in shared-temp guidance. Scratch support does not redesign scoring or make opaque shell side effects known-compliant.

## Implemented contract and limitations

- New `scratch.py`: version validation, reserved-name check, safe Windows spelling, resolved containment/link/hardlink classification, command-local environment settings, provenance and prompt text. No bridge API or service configuration change. prepare_workspace(scope_policy=None) preserves legacy behavior; the production run path supplies the new policy.
- Full task snapshots include scratch. `changed_paths` retains the complete captured file-change list; worker.patch is a bounded preview, summarizing scratch/binary/large changes with hashes and pointing to snapshots for exact bytes. `task_changed_paths` and `scratch_changed_paths` identify the regions separately; a change under the scratch region can still violate protection rules. `.git` under scratch, root .git, forbidden task paths, traversal to protected/external paths, prefix lookalikes, ADS, trailing dot/space aliases, device paths and device names are not granted scratch permission. Extant links/junctions and multiply linked scratch files cannot gain permission; bounded capture refuses links, junctions, hardlinks and non-regular entries. A global filesystem monitor/sandbox was not added; deleted transient aliases or opaque shell effects cannot be exhaustively reconstructed.
- `verify(..., scope_policy=...)` makes a separate copy excluding scratch; archived bytes are retained and integrity-checked. Existing positive completion receipts remain required.
- `ScopeAudit` retains policy and task/scratch changed paths; mutation events carry a category. Failed/unknown tool operations remain uncertain. Known external writes still fail scope, and canonical timeout/infrastructure precedence and frozen S1 attribution are unchanged. A passing verifier with only opaque shell operations can still be unscored; scratch permission does not make shell execution fully auditable.
- Provenance is in read-only CLI plan, RunInfo metadata (even runtime-unavailable failures), runtime/lifecycle journals, checkpoint/audit evidence, and canonical TrialResult details. `environment_delivery=worker_command_local` and `automatic_server_redirection=false` distinguish requested settings from measured worker behavior. `reaudit_trial` selects only the recorded lifecycle scope policy; absent means legacy strict, unknown means error. Historical canonical records are never rewritten or reclassified automatically.
- Cleanup is the existing termination-confirmed whole-workspace cleanup. The real Windows junction regression proves its external target survives. Unresolved workers retain scratch and stop allocation/dispatch. No shared temp cleanup, new process management, shell parser, plugin, or scratch-only deletion route.
- Initial fixtures and verifier suite remain 0.1.1; package source becomes 1.2.0. Scratch permission changes the environment/compliance policy, so compare runs only with explicit policy awareness; do not silently pool legacy strict runs and scratch-enabled runs. Statistical/scoring redesign remains deferred. Editable imports/entry points work without wrapper changes; installation metadata should be refreshed through the usual package update when adopted.

## Initial implementation validation — 2026-10-19

From C:/Users/mcarls/src/scripts-agent-benchmark with the existing scripts virtualenv:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/scratch-checkpoint
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs --basetemp=modules/benchmark_core/.pytest_tmp_root/scratch-final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core --no-cache
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/agent_benchmark/.pytest_tmp_root/mypy-scratch-final modules/agent_benchmark/agent_benchmark/scratch.py
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/benchmark_core/.pytest_tmp_root/mypy-scratch-final modules/benchmark_core/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m agent_benchmark plan
```

Agent: 207 passed, 3 skipped in 35.50 seconds. Skips are unavailable Windows symlink privilege in evidence_test.py, lifecycle_test.py and scratch_policy_test.py. Junction escape/cleanup and local PowerShell/Python temp tests actually ran and passed. Core: 83 passed. Ruff clean; new helper Mypy clean (1 file), core Mypy clean (9 files). No claim of clean agent-wide Mypy; the previous documented legacy diagnostics are outside this scope.

RED/GREEN: new policy API initially absent; failure-path policy provenance and empty reserved directory reproduced failures; Windows trailing-dot workdir and NUL/CON/COM1 aliases reproduced false compliance before rejection. The policy suite has 32 passed/1 skip; full suite retains unknown-submission restart blocking, timeout precedence and failed-S1/passed-S3 regressions. Full mocked canonical run persists/reloads one passed result with separate scratch paths and identical recorded-policy re-audit. Legacy re-audit remains strict; unknown policies fail.

All 114 existing files under reports/ (both live runs plus Phase 1d non-inference acceptance, including its saved probe and repository evidence) match their original per-file SHA-256 inventory; none were added, removed or changed in this phase. No inference worker or local shared-service API call was made.

## Review / later live requirements

Review the cooperative policy and unchanged uncertainty behavior first. No further development-agent delegation or inference is authorized. A separately authorized live trial must check actual model obedience to trial scratch despite OpenCode's competing shared-temp tool instructions, command-local temp environment on every relevant shell command, actual S1 scratch/task separation and canonical scope attribution. Its original task/grace budgets must remain intact; do not retry or relax the policy to make it pass. Runtime enforcement/plug-ins and scoring redesign require their own design and authorization if later needed.

## Final focused self-review — 2026-10-19

Implementation/test commit: 45a096d50f50948a1a081188a3414c81a76ed292. No worker or shared-service API/configuration action occurred. Follow-up integration is proposed in [integration-smoke-proposal.md](integration-smoke-proposal.md); it is not authorized or executed.

| Review concern | Finding / correction |
|---|---|
| Fixture editing limits versus scratch | The prompt explicitly supplements fixture editing limits only for scratch; original instruction.md/task.json and verifier remain unchanged. The permission is versioned environment policy, not a rewrite of the task's deliverables. |
| Deliverables / temporary files / verifier / Git | Separate task/scratch lists and full retained snapshot bytes, scratch excluded from verifier input, protected root/nested scratch Git metadata disallowed. New bounded capture also refuses hardlinks/non-regular files, avoiding archive copies that erase alias metadata. |
| Windows paths and external writes | Existing traversal/prefix/case/ADS/device/junction regressions pass. Review reproduced raw target whitespace being stripped into an allowed scratch path; fixed for both target and workdir, retaining original raw target evidence. Shared temp never receives benchmark permission. |
| Historical compatibility | Absent scope_policy remains strict task-only; unknown policy fails closed. New-policy re-audits honor recorded evidence limits; legacy archive reads/interpretation remain unchanged. Canonical historical results are never regenerated or overwritten. All 114 existing evidence files are byte-identical. |
| Resource consumption | Initial capture and scratch diff duplication were unbounded. Added streaming bounded directory traversal/reads (4,096 entries including directories, 2 MiB/file, 16 MiB/checkpoint; root .git bookkeeping excluded as before). Post-stat reads are bounded too. Archives retain their limits for integrity checks. Patch previews <=256 KiB avoid scratch payload duplication and expensive diffs on large/line-heavy files. |

Limit breach handling is fail-closed: no partial S0/S1 archive is created from an incomplete read, no hidden verifier runs on incomplete S1, and canonical status is infrastructure_error. evidence-limit.json retains checkpoint, limiting path, observed/limit values and complete_snapshot=false; lifecycle ownership is journaled before S0. A confirmed stopped worker's workspace is retained and the no-longer-active dispatch reservation can be released. Unconfirmed execution still preserves the persistent block. Limits are in CLI plan, RunInfo, runtime and lifecycle provenance and shown to the worker. Bounds cover capture/preview resources; they are not an OS disk quota, a total pipeline memory/time limit, or a raw transcript/provider/verifier-output buffer limit. The retained workspace may exceed capture limits and must be reviewed before owned cleanup.

Final commands (same existing Python as above):

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/scratch-review-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs --basetemp=modules/benchmark_core/.pytest_tmp_root/scratch-review-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core --no-cache
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/benchmark_core/.pytest_tmp_root/mypy-scratch-review modules/benchmark_core/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/agent_benchmark/.pytest_tmp_root/mypy-scratch-review modules/agent_benchmark/agent_benchmark/scratch.py
```

Results: 218 agent passed/3 symlink-privilege skips in 38.96 seconds; 83 core passed; Ruff/core/helper Mypy clean. The additional 11 self-review regressions pass (including a fresh run after type-only annotations); combined policy/review suite 43 passed/1 skip. Optional broad agent Mypy freshly reports the same 22 legacy diagnostics in 5 files (14 files checked); no new diagnostics in bounded capture/patch code. The new path/resource failures were reproduced RED before correction. No production trial or scored comparison was run.

## Diagnostic follow-up correction

Gemini identified that the original linked smoke proposal required an unconfirmed complete provider trace and attempted to inspect per-turn evidence before that turn existed. The revised proposal/implemented smoke entry point removes that prerequisite. Intended configuration is checked before submission; saved user prompt/session attribution is checked afterward. Complete provider payload is optional/unverified; unavailable tracing does not block a diagnostic. Shared production reservation/cancellation/release logic is reused. Implementation/tests 6e319c8a; source 1.3.0; no change to scratch/verifier policy or historical records. Current validation/command/remaining live gate are in the revised integration-smoke-proposal.md and HANDOFF.md.
