# agent_benchmark handoff — Phase 1c core integration gate

## Location and tested commits

- Workspace: C:/Users/mcarls/src/scripts-agent-benchmark
- Branch: agent/agent-benchmark
- Corrective audit pass commit: b7e45f3e
- Prior attempt-flow/review-fixes commit: 641f618674fff82e1572d5a09ee2683bb2a1fc32
- Independent adapter/evidence commit: 709d961d
- Task 1b baseline: 85dca555; preceding handoff d098e519
- Module version: 0.3.0
- Ownership: modules/agent_benchmark. Do not edit another worktree, benchmark_core or local_agent_bridge.

## Hard integration gate

User explicitly says: do NOT merge benchmark_core until they provide its final corrected tested SHA and validation results. The earlier Gate 1 SHA and the currently visible branch tip are insufficient. No core commit has been incorporated. Ask the user for the final tested SHA/evidence, then incorporate the COMPLETE corrected branch at that exact SHA, not only Gate 1. Do not create provisional RunInfo, TrialResult or MetricValue replacements.

Stay on Codex Sol Medium for remaining Phase 1c integration. This is an integration gate, not a cheaper-model handoff. After canonical integration and first real task are proven, use the model allocation table in plans/20261019-implementation/plan.md for fixtures/audits.

## Implemented independent interfaces

- evidence.load_task(Path) -> Task: pinned original smoke task; relative manifest paths validated.
- evidence.prepare_workspace(task, workspace): only seed, instruction and manifest; hidden verifier never copied into worker workspace.
- evidence.capture(workspace, destination) -> Snapshot: exclusive byte-exact archive, frozen byte mapping and tree hash; refuse links/overwrite.
- evidence.verify(snapshot, verifier, output, timeout_seconds=10) -> Verification: stdlib verifier in an owned bounded subprocess against a disposable copy outside worker workspace; archived snapshot checked before/after; stdout/stderr retained. Verification statuses are verifier facts, not a competing TrialResult.
- bridge.connected_bridge(base_url=..., request_seconds=10): official MCP SDK 1.30.0 / offline npx opencode-mcp@3.0.0, auto-serve disabled; raw authenticated httpx requests share configured server. Existing credentials passed through environment, never logged. No shared service lifecycle changes.
- OpenCodeBridge.preflight: read-only explicit connected lmstudio model and local-worker/reviewer role check. Records actual OpenCode version and observed permissions.
- OpenCodeBridge.dispatch: fire once without sessionId; durable IDs retained; uncertain submission never retried. Per-attempt transcript resets. SubmissionUncertain retains any returned receipt IDs.
- OpenCodeBridge.observe: fresh session identity/directory + full messages + current status; exact submitted user turn and assistant parentID, finished final step, no incomplete tools. Terminal cached jobs never authorize cleanup. Missing session status entry means idle only in a valid response map with matching completed messages/session. No live-session samples captured yet: tests use installed-schema-shaped data.
- OpenCodeBridge.cancel: validate latest user turn still owns session before supported job_cancel; acknowledge alone is never proof of termination.
- attempt.run_attempt(task, bridge, guard, workspace_root=..., evidence_dir=..., provider=..., model=..., agent=..., task_seconds=None, grace_seconds=10, poll_seconds=.1, verifier_seconds=10) -> frozen AttemptEvidence. No result serialization/report renderer. Canonical adapter must consume termination, snapshots, verifier, actual changed paths/scope, expired-task vs infrastructure flags and monotonic durations.
- Existing lifecycle.DispatchGuard / cleanup_workspace unchanged. Keep one guard per batch; future CLI must inspect durable unresolved journals across invocations before dispatch. Workspace retained by default, cleanup always separate.

## Evidence and invariants

Each attempt owns a fresh worker directory and exclusive evidence directory. lifecycle.json is written before dispatch and updated with handles/budgets/termination; dispatch.json retains raw receipt; session.json full raw messages; worker-report.json or .txt separate report; S0/S1 archive directories and checkpoints.json hashes; worker.patch; verification/stdout.txt + stderr.txt and disposable workspace.

S1 is never captured while termination is unresolved. Unresolved attempts retain IDs/workspace/diagnostics and latch batch stop. Any post-dispatch journaling error still latches the in-memory guard even if diagnostics cannot be written (e.g. disk full). External asyncio cancellation propagates after guard/diagnostic retention where writable. No process inspection/killing by name, no supervisor, no scheduler.

Critical evidence regression: bad S1 then corrected S3 still retains failed first Verification and unchanged S1 bytes. The CANONICAL TrialResult version of this regression remains required after core gate. Correct code after expired task budget must not turn into a canonical first-attempt pass; request/transport timeout is infrastructure uncertainty, not automatically budget expiration. Cleanup errors must never rewrite a separately verified result.

## Validation and limitations

From modules/agent_benchmark, using the repo virtualenv:

```powershell
& "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m pytest tests -q --basetemp=.pytest_tmp_root/phase1c-final --tb=short
& "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m ruff check agent_benchmark tests tasks
```

80 passed, 2 skipped (Windows symlink privileges); Ruff passed cleanly.

### Corrective pass fixes (Priority 1, 2, 3)

1. **OpenCode termination correctness**:
   - Fixed `parse_observation()` in `bridge.py`: intermediate assistant turns with `finish="tool-calls"` and `"structured": None` were previously confirmed due to checking `"structured" in final`. Now requires `final.get("structured") is not None`.
   - Handled aborted/error assistant turns (e.g. `MessageAbortedError`) where `time.completed` was missing/None: treats authoritative `error` dict as abnormal terminal evidence when session is idle and no tools remain running.
   - Guarded message history sorting (`_ordered`) and observation parsing against null/malformed timestamps and non-dict fields.
2. **Confirmed correctness & diagnostics**:
   - Fixed `attempt.py` dropping worker text report (`worker-report.txt`) when `structured: None`.
   - Preserved MCP error text diagnostics in `connected_bridge.call_tool` from `result.content` when tool execution fails, while sanitizing any `OPENCODE_SERVER_PASSWORD` credentials (`***`).
   - Added offline `connected_bridge` unit tests (invalid timeout, missing npx, health failure, tool error & credential masking).
   - Added bounded observation recovery on transient `httpx.HTTPError` (up to 3 consecutive errors within task budget, never resubmitting workers or converting unavailable observations into termination).
   - Documented explicit venv Python path in `README.md` and `HANDOFF.md`.
3. **Supervision boundaries**:
   - Documented `owned_pids=[]` in `lifecycle.json` as intentionally empty because worker processes belong to OpenCode's shared process tree, not local subprocess supervision.

Read-only runtime readiness: connected_bridge(request_seconds=2) failed ConnectTimeout before MCP startup. No worker/model dispatched, no real benchmark success, no shared services changed. Offline tests do not establish real MCP execution, effective role isolation or cancellation termination against live OpenCode. Package usage currently programmatic from module directory; task packaging and installed CLI acceptance remain pending. Trusted fixtures and unprivileged processes, not a hostile-code sandbox.

## Protocol notes for Sol Medium

1. When `finish == "tool-calls"`, `structured` is absent or `None` unless the tool call step was accompanied by structured completion data.
2. On abort (`MessageAbortedError`), OpenCode populates `assistant.info.error = {"name": "MessageAbortedError", ...}` but omits or sets `time.completed` to `None`. The session status transitions to idle (or disappears from `/session/status` map, which OpenCode treats as idle). Our implementation requires `bool(error)` plus `idle` session state plus `tools_running == False` to confirm termination.
3. `opencode-mcp` tool errors return `{content: [{type: 'text', text: msg}], isError: true}` without structuredContent; the bridge extracts and sanitizes this text for diagnostics.

## Remaining Phase 1c

1. User supplies final corrected complete core SHA + validation; incorporate exactly it, run focused core checks, import authoritative contracts.
2. Add canonical TrialResult mapping and core persistence/evidence layout. Exactly one result per repetition; worker_first_attempt_full_success. Missing tokens unavailable, never zero. Unconfirmed termination without reliable evaluation remains infrastructure_error/uncertainty. No retry/repair improves S1.
3. Add canonical bad-S1 / corrected-S3 regression and cleanup-failure-does-not-overwrite-score integration regression.
4. Add guarded CLI/read-only plan/status/cleanup and explicit -x/--execute run authorization. Paired short/long flags. Obtain narrow help-registry ownership exception before editing outside this module; none was requested or used yet. Ensure cross-invocation unresolved journal detection.
5. Recheck existing runtime availability without starting/configuring services. Real-model validation only when explicitly executed; report unavailable runtime honestly. Freeze task/verifier contract after real evidence, update tested handoff then switch cheaper agent for routine fixtures/audits.

## Copyable resume instruction

Resume Phase 1c in C:/Users/mcarls/src/scripts-agent-benchmark, branch agent/agent-benchmark. Confirm cwd/branch/status. Read this handoff and plan task 1c. First obtain the user's FINAL corrected tested benchmark_core SHA and validation; do not integrate an earlier commit or current unapproved branch tip. Independent code/tests are complete (80 passed, 2 skips; Ruff clean). Use authoritative core imports for canonical emission and add immutable first-attempt attribution regressions. No local-agent delegation or unrelated edits. No real-model success has been validated. Continue with Sol Medium for integration; use tested commits and update this handoff at the next useful model-switch checkpoint.

