# Status

## Current checkpoin

- Base: `b75cf86e102e43e1ea3ca17b1f3422b4201291e8` (validated v0.12.0 feature).
- Branch: `agent/resource-coordinator-upgrade-reliability-20261111`.
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-upgrade-reliability-20261111`.
- Current source edits are uncommitted; final commit SHA will be recorded after static review.
- Primary checkout and prior v0.12 worktree remain untouched.
- No merge, push, deployment, model load, GPU operation, Scheduled Task change, credential change, WSL change, or production service/miner operation was performed.

## Upgrade failure investigation

- Read-only historical receipt: `C:\Users\mcarls\.resource_coordinator\upgrade-receipt-reconciled-c0d7fc3c7c104a1a.json`; sanitized facts are `WinError 206`, `phase=RECOVERY_REQUIRED`, `failed_at=OLD_STOPPED`, and source runtime version `0.11.3`.
- In the present source, `TASK_UPDATED` was written only after `WindowsStartupTaskBackend.install()` returned. Therefore the old receipt localizes the failure to the post-stop task-install interval, but not the exact subprocess/API call. The historical operation directory and helper artifacts are gone; the audit contains no operation ID or stack/call detail.
- The observed task action, launcher, and path values in the receipt were short. Current transport writes the authenticated helper and request to ACL-protected files and passes short paths to PowerShell; it does not place the large request payload on the process command line. This weakens, but does not disprove for the older 0.11.3 runtime, the initial command-line-length hypothesis.
- No isolated reproduction of WinError 206 was obtained. The failure is not claimed fixed. Added `TASK_INSTALLING` before task registration and made that phase eligible for recovery/reconciliation/health reporting. This preserves precise evidence and automatic rollback if the task-install step fails again. Existing pre-stop helper validation and automatic rollback tests pass.
- Production deployment remains gated on a controlled, non-production Windows Scheduled Task acceptance and better diagnosis of the exact historical failure. No destructive trial against the production task was attempted.

## Model-load outcomes and retry safety

- All post-dispatch HTTP failures, read/connect/overall timeouts, client disconnects, failure-shaped streams, and truncated responses remain uncertain because the current documented LM Studio contract does not provide authoritative operation-specific negative terminal evidence.
- Tests explicitly cover HTTP 400/500/502 as uncertain. A restart inhibition is persisted and remains fail-closed.
- Closed a concrete retry gap: when `gpu.inference` is restart-inhibited or the lease manager has a global restart block, admission now rejects new inference and explicit model-load operations with HTTP 503 `recovery_required` before forwarding. Authenticated operator recovery remains the path to resume admission. This prevents repeated stop/retry cycles while the hold is unresolved.
- No separate per-model terminal-failure circuit breaker was added because the upstream has no verified terminal failure category to key it on. The durable global inhibition and admission gate protect uncertain cases; future terminal-only retry cooldown requires documented backend evidence.

## Existing-instance reuse and events

- Explicit model-load requests with positive `context_length` perform a bounded (at most 5 s) read-only `GET /api/v1/models` preflight. Reuse requires exact model key, nonempty instance ID, matching effective context length, and exact type/value equality for every requested supported setting. Unknown settings, absent or malformed inventory, unavailable inventory, or mismatch fall through to the normal exclusive-load lease.
- Verified reuse returns the current instance ID plus `x-coordinator-model-instance-reused: true`, does not acquire a GPU lease, and does not stop/restart the fake miner. The response reports zero new load duration; it does not claim that a new instance was created.
- Added observational `resource_coordinator.model_load_failed`, `resource_coordinator.recovery_required`, and `resource_coordinator.miner_restart_inhibited` events with stable `event_key`, timestamp, severity, operation classification, request/model identity, miner-state classification, and safe action. The notification contract is documented in `docs/plans/20261111-reliable-inference-recovery/RESOURCE_MONITOR_CONTRACT.md`. No notification transport was added. A verified managed start remains represented by existing `process.started`; the notification client may derive `miner_resumed` when it can associate process identity/origin safely.

## Validation

Environment: Windows, Python 3.12.10, pytest 9.2.0, pytest-asyncio 1.4.1.post1; candidate venv. Import check resolved `resource_coordinator` to this worktree. Async suites required a narrowly scoped normal-socket-permission run; all test processes used fake process backends/mock LM Studio and distinct absolute basetemp roots under `modules/resource_coordinator/.pytest_tmp_root/`.

| Command | Result |
|---|---|
| `python -m pytest -vv --basetemp <unique> tests/test_gateway.py -ra` | Exit 0; 45 passed. Includes new model-instance reuse matching/mismatch checks, HTTP 400/500/502 uncertainty and retry rejection, event envelope on timeout, fake-miner behavior, and existing real loopback HTTPX timeout tests. |
| `python -m pytest -vv --basetemp <unique> tests/test_installation.py -ra` | Exit 0; 86 passed. Covers task install failure rollback and newly parameterized `TASK_INSTALLING` reconciliation. |
| `python -m pytest -vv --basetemp <unique> tests/test_phase1_request_arbitration.py -ra` | Exit 0; 10 passed. |
| `python -m pytest -vv --basetemp <unique> tests/test_durable_state.py tests/test_operator_credentials.py tests/test_config.py -ra` | Exit 0; 38 passed. |
| `python -m pytest -vv --basetemp <unique> tests/test_leases.py tests/test_policies.py -ra` | Exit 0; 8 passed. |
| Ruff on `gateway.py`, `admission.py`, `installation.py`, `test_gateway.py`, `test_installation.py` | Exit 0; all checks passed. |
| `python -m compileall -q resource_coordinator` | Exit 0. |
| `git diff --check` | Exit 0. |

The first new reuse test exposed a missing fixture policy and was corrected before passing. The first full installation run exposed an existing fixture that accidentally read the real local Coordinator status endpoint; it safely blocked before changing a task/service. The test now stubs that status call and passes. No process, service, task, miner, credential, journal, or configuration mutation occurred. Pytest emits the existing unset `asyncio_default_fixture_loop_scope` deprecation warning.

Opt-in UAC and actual Windows Task Scheduler integration tests were not run; there is no disposable Windows VM/environment available in this worktree and production task mutation is prohibited. Historical prior v0.11.6 acceptance does not establish the newest production restore/upgrade path.

## Review and disposition

- Changed behavior is additive: new admission error `recovery_required`, reuse marker header, reuse response for a positively compatible instance, and observational event names. Existing CLI, recovery endpoint, timeout defaults, and durable request schema are unchanged.
- The primary safety hold remains authoritative: no timer, GPU sample, empty inventory, HTTP error, or local disconnect clears it. Global inhibition blocks new GPU requests until authenticated recovery; after recovery, existing resource/ownership checks and cooldown gate miner start.
- Source candidate is suitable for isolated integration review with documented limits. Do not treat it as ready for production deployment until the exact WinError 206 call is understood or an isolated Windows Task Scheduler acceptance verifies the task install/rollback sequence.
- Current production state was not independently queried as part of final validation; one test's real status query was discovered and replaced by a stub before rerun. No further production reads were made.

## Next actions

1. Complete final diff review and commit on this branch.
2. Integration review against local main (no merge/push authorized).
3. Before deployment, use an isolated Windows VM or approved disposable task environment to validate elevated registration, rollback, and the new `TASK_INSTALLING` receipt path; preserve the protected recovery-token launcher, operator credentials, Scheduled Tasks, miner ownership/state, and persistent WSL LM Studio mask.
4. Keep the no-terminal-negative-evidence limitation explicit until LM Studio documents a request-specific terminal failure/status/cancel contract.
