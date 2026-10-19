# One-run unscored integration smoke — revised after Gemini review

Status: implemented and tested offline. Live execution requires separate explicit authorization; no inference has been run. Implementation/tests: `6e319c8af78cde38458e40163c762dac5ff5b866`. Package source 1.3.0. This revision supersedes the earlier proposal's unsupported mandatory provider-tracing prerequisite.

## Exact entry point and future command

Source: `agent_benchmark/diagnostic.py:run_diagnostic`, exposed by the existing CLI as `smoke`. Trusted public probe: `agent_benchmark/temp_probe.py`. No new console-script wrapper, independent scheduler or copied reservation manager.

From C:/Users/mcarls/src/scripts-agent-benchmark, only after a separate one-execution authorization:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m agent_benchmark smoke -x -m qwen38_23GB -p lmstudio -a local-worker -u http://127.0.0.1:4096 -o .\integration-acceptance
```

The actual supported help is `python -m agent_benchmark smoke --help`. `-x/--execute` is mandatory; without it no state or network is touched. The command uses the same default state directory as scored runs: ~/.local/share/agent-benchmark. Observation budget is fixed at 60 seconds; cancellation/confirmation grace is fixed at 10 seconds, with no smoke flags to increase them. Existing services must already be operational and the desired model/context (baseline qwen38_23GB, 32768) configured. The harness does not load models or set/independently prove the effective LM Studio context length. No shared-service startup, shutdown, reconfiguration, retry, repair, extra turn or additional worker is permitted.

## Before inference: checks that are available before the turn exists

1. Hold the existing command lock, refuse pending/corrupt dispatch state, and reserve the new evidence directory durably. Shared `state.reserved_trial` is now used by both scored runs and diagnostics. Its sticky guard is set before the possible submission and never inferred from receipt contents.
2. Build a disposable copy of the trusted grep fixture with integration-only identity and a protected public temp_probe.py. The canonical fixture and all historical evidence remain unchanged. Prepare a unique committed Git workspace; freeze bounded S0.
3. Build the deterministic intended user prompt from this fixture, workspace and versioned scratch instructions. Persist exact UTF-8 bytes as submitted-prompt.txt and their SHA-256 in prompt.json before any worker submission. This is the adapter's user prompt, not the complete provider-bound request.
4. Use the existing supported preflight to validate configured/connected provider/model and role, exact project/root/worktree, and available role permission/tool metadata. Role prompt SHA-256 and safe profile fields are recorded; absent tool metadata is explicitly unavailable. Role data does not prove the final injected tool schema or all global instructions.
5. Create exactly one empty session and validate persisted ID/directory/project binding, empty history and idle status before `opencode_fire`. Reuse this validated sessionId for the one submission attempt. Failed validation submits nothing.

No provider-turn trace is requested or required before dispatch: the turn does not yet exist. No supported complete provider-request endpoint is demonstrated by this implementation.

## After inference: attribution and independent evidence

- Reconcile fresh session state, tools and terminal message through the existing bounded lifecycle code. Preserve actual job/session/message identifiers, exact directory, full stored history and fresh session identity. An abort acknowledgement alone never proves termination.
- Compare the stored single user turn's ID/session and text against the saved intended prompt. Verify the fresh session directory/project against the expected trial. Mismatch is a failed attribution check; missing/ambiguous evidence is unverified. Neither outcome becomes provider-payload verification.
- Compare frozen S0/S1 task and scratch changes; preserve transcript mutations, known external/protected violations and opaque operations as separate facts. Scratch remains excluded from hidden verifier input. Hidden verification is a functional observation, not a canonical benchmark score.
- Check the trusted probe's S0/S1 bytes against the installed source. The documented exact PowerShell command sets TEMP/TMP/TMPDIR in the same command and invokes the existing Python with -I -B. The probe checks tempfile.gettempdir(), retains a random temporary marker inside scratch and writes/prints a compact JSON observation. Validate retained marker/hash/env paths against S1 and match one completed exact shell invocation, zero exit and matching output. Missing/modified artifacts or command attribution remain failed/unverified. This is trusted-fixture evidence, not an OS sandbox or proof against deliberate external tampering.
- Keep three outcomes distinct: intended configuration validated; submitted user prompt attributed; provider-bound payload verified/unverified. The current harness always records the last as optional/unverified because no safe supported complete-payload mechanism is demonstrated. Session history is not evidence of the full system prompt or injected tool schemas. A separately available safe per-turn trace could supplement a later manual report, but its absence does not block this smoke or require service changes.

## Guard, cancellation and result separation

`state.reserved_trial` wraps both entry points, reusing command_lock/reserve/release/safely_finished and DispatchGuard. `attempt.run_attempt` and the existing bridge handle submission, polling, cancellation and termination confirmation for both. Diagnostics do not copy those algorithms. Empty/malformed/partial/lost receipts, caller cancellation and diagnostic-report write failure retain the persistent reservation whenever a worker may be active. The existing cleanup command consumes the same lifecycle journal and requires fresh reconciliation; it is not called automatically by smoke. Workspaces/evidence stay retained for review. An uncertain empty-session creation with no prompt attempted remains a no-inference preflight failure; its workspace/diagnostics are retained.

Outputs are only under `integration-acceptance/smoke-<UTC>-<unique>/` plus the existing owned state workspace. They contain purpose=integration_smoke and comparison_eligible=false. No benchmark_core run.json, trials.jsonl, statistical summary or scored comparison input is produced. The diagnostic fixture has a distinct task ID. A completed diagnostic never counts as worker-first-attempt benchmark success.

The command exits 0 for integration_status=completed_with_limitations: required project/session/prompt/probe/termination checks completed without known scope violations, task-budget expiry or execution error. Provider payload remains unverified and opaque shell side effects remain uncertain. Functional hidden-verifier status is reported separately and does not become a benchmark score. Incomplete diagnostics exit 1; CLI/setup errors exit 2, caller interruption 130. No further worker is dispatched on any outcome.

## Expected artifacts (when the stage is reached)

- acceptance.json: purpose/comparison exclusion, intended/prompt/provider checks, trusted-probe observations, identity, termination, budget/error, scope breakdown, timings and functional verifier status.
- fixture/: diagnostic-only task/instructions/seed/probe and external hidden verifier.
- evidence/trial-001/: lifecycle.json, runtime.json, submitted-prompt.txt, prompt.json, session-preflight.json, dispatch.json, session.json, session-identity.json, S0/, S1/, checkpoints.json, bounded worker.patch, scope-audit.json, worker report and verification/ outputs. Capture-limit failures retain evidence-limit.json instead of inventing complete S1.
- Normal owned workspace under ~/.local/share/agent-benchmark/workspaces/trial-*. It and the evidence remain until review; no automatic cleanup.

For recovery, `python -m agent_benchmark status` reads the shared pending state. Inspect acceptance.json directly; status --run-dir is for canonical benchmark records. Existing `cleanup --run-dir <diagnostic-directory>` previews recovery; executing cleanup requires separate explicit authorization and fresh session reconciliation.

## Offline validation

236 agent tests passed, 3 Windows symlink-privilege skips; core 83 passed. Ruff clean; core Mypy clean (9 files); focused diagnostic/probe Mypy clean (2 files, imported legacy diagnostics suppressed). Fresh broad agent Mypy retains the established 22 diagnostics in 5 legacy areas (16 source files checked), no new diagnostic errors.

Commands from the assigned worktree, existing scripts virtualenv:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/dg-final-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs --basetemp=modules/benchmark_core/.pytest_tmp_root/dg-full
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/agent_benchmark/__init__.py modules/benchmark_core --no-cache
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --cache-dir modules/benchmark_core/.pytest_tmp_root/mypy-dg modules/benchmark_core/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy --follow-imports=silent --cache-dir modules/agent_benchmark/.pytest_tmp_root/mypy-dg-isolated modules/agent_benchmark/agent_benchmark/diagnostic.py modules/agent_benchmark/agent_benchmark/temp_probe.py
```

The 18 focused diagnostic cases cover real adapter preflight/session ordering on mocked HTTP/MCP, exact prompt bytes (including reproduced Windows newline translation), missing optional tracing, prompt/session/ID mismatches, known/unknown receipts, restart blocking, caller cancellation, confirmed observation timeout, acceptance-write failure, preview/confirmed cleanup, retained scratch versus hidden verifier input and no canonical outputs. The actual trusted probe runs locally in a bounded PowerShell/Python test without OpenCode or inference. The complete suite retains the earlier failed-S1/passed-S3 regression.

All 114 existing historical/acceptance files are unchanged. No local shared-service request, inference, worker dispatch or service change occurred. Ready for one explicitly authorized Qwen diagnostic once its existing runtime is operational. Stop here until that authorization arrives.
