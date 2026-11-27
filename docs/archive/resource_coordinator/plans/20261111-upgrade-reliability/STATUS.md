# Status

## Current checkpoint

- Base: `b75cf86e102e43e1ea3ca17b1f3422b4201291e8` (validated v0.12.0 feature).
- Branch: `agent/resource-coordinator-upgrade-reliability-20261111`.
- Worktree: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-upgrade-reliability-20261111`.
- Code commit: `e10ce1b55ed12874cf4f403f48a4e5303e28dbb2`.
- Primary checkout and prior v0.12 worktree remain untouched.
- No merge, push, deployment, model load, GPU operation, Scheduled Task change, credential change, WSL change, or production service/miner operation was performed.

## Upgrade failure investigation

- Read-only historical receipt: `C:\Users\mcarls\.resource_coordinator\upgrade-receipt-reconciled-c0d7fc3c7c104a1a.json`; sanitized facts are `WinError 206`, `phase=RECOVERY_REQUIRED`, `failed_at=OLD_STOPPED`, and source runtime version `0.11.3`.
- In the present source, `TASK_UPDATED` was written only after `WindowsStartupTaskBackend.install()` returned. Therefore the old receipt localizes the failure to the post-stop task-install interval, but not the exact subprocess/API call. The historical operation directory and helper artifacts are gone; the audit contains no operation ID or stack/call detail.
- The observed task action, launcher, and path values in the receipt were short. Current transport writes the authenticated helper and request to ACL-protected files and passes short paths to PowerShell; it does not place the large request payload on the process command line. This weakens, but does not disprove for the older 0.11.3 runtime, the initial command-line-length hypothesis.
- No isolated reproduction of WinError 206 was obtained. The failure is not claimed fixed. Added `TASK_INSTALLING` before task registration and made that phase eligible for recovery/reconciliation/health reporting. This preserves precise evidence and automatic rollback if the task-install step fails again. Existing pre-stop helper validation and automatic rollback tests pass.
- Production deployment remains gated on a controlled, non-production Windows Scheduled Task acceptance and better diagnosis of the exact historical failure. No destructive trial against the production task was attempted.

## Final Windows upgrade acceptance gate (2026-11-11)

- Reconfirmed branch `agent/resource-coordinator-upgrade-reliability-20261111` at `d47833d8c1ea9ec768b899e2c5f6ab885400191c`; the worktree was clean before this gate. Primary `main` remains at `9102815920eff843f1a9ec3abe60060a4ffbdd8f` with its pre-existing unrelated dirty files preserved.
- The historical `OLD_STOPPED` receipt still does not identify a failing call. In the current transition, the candidates are operation-directory ACL setup, helper process launch/execution (including `Register-ScheduledTask`), the post-install status query, or writing the next receipt. `start()` runs only after `TASK_UPDATED` and is excluded by the old receipt phase.
- The current transport uses a protected on-disk request and helper. The elevated wrapper contains only the helper path, digest, and request path; a Windows loopback run passed a 100 KB request without placing its payload on the command line. This makes command-line overflow unlikely for the tested current transport, but does not establish what failed in the older v0.11.3 runtime or inside Task Scheduler.
- Added sanitized failure dimensions for both operation-directory ACL launch and helper launch/return failures: operation and stage, executable basename and path length, command-line character count, managed/operation/helper/request/result path lengths, and Windows error code. Full command lines, request data, and credentials are not included. `test_task_transport_acl_launch_failure_reports_safe_dimensions` and `test_task_transport_launch_failure_reports_safe_operation_dimensions` inject WinError 206 and verify the diagnostic while checking that a secret-shaped payload value is absent.
- Pre-stop `validate` continues to obtain elevation and verify the allowlisted existing task and `Register-ScheduledTask` cmdlet. It exercises the same protected helper transport but does not register a task and cannot prove task replacement permissions or behavior.
- Environment inventory found no registered Hyper-V VMs (`Get-VM` count 0), and `WindowsSandbox.exe` is absent. The real disposable Scheduled Task lifecycle test was attempted and skipped because the current execution identity receives `Access to a CIM resource was not available to the client`. UAC acceptance was not initiated. No production task was queried or modified.
- Windows evidence: `RC_WINDOWS_INTEGRATION=1 python -m pytest tests/test_windows_task_transport_integration.py -vv -rs --basetemp <candidate-module-temp> -k windows_helper_processes_large_request` passed (1 passed, 2 deselected, 1.64 s). The disposable task command with `RC_WINDOWS_TASK_INTEGRATION=1` exited 0 with 1 skipped, 2 deselected, reason above. Focused synthetic diagnostic tests passed (2 passed, 86 deselected). Full `test_installation.py` passed (88 passed, 3.13 s) under Python 3.12.10 / pytest 9.0.3 after setting `--basetemp` inside the candidate module. An initial run pointed `--basetemp` outside the candidate and had 64 fixture setup errors (WinError 5); rerunning with the module-local temp root passed.
- No isolated Windows end-to-end upgrade, elevated task replacement, rollback, or UAC rejection acceptance was possible. Root cause remains unproven; diagnostics improve the next safe reproduction but are not a fix for the historical error. Production deployment remains blocked pending acceptance in a disposable Windows VM/task environment that can exercise registration, startup, rollback, and receipt reconciliation.

## Model-load outcomes and retry safety

- All post-dispatch HTTP failures, read/connect/overall timeouts, client disconnects, failure-shaped streams, and truncated responses remain uncertain because the current documented LM Studio contract does not provide authoritative operation-specific negative terminal evidence.
- Tests explicitly cover HTTP 400/500/502 as uncertain. A restart inhibition is persisted and remains fail-closed.
- New behavior: when `gpu.inference` is restart-inhibited or the lease manager has a global restart block, admission rejects new inference and explicit model-load operations with HTTP 503 `recovery_required` before forwarding. Authenticated operator recovery remains the path to resume admission. This prevents repeated stop/retry cycles while the hold is unresolved.
- No separate per-model terminal-failure circuit breaker was added because the upstream has no verified terminal failure category to key it on. The durable global inhibition and admission gate protect uncertain cases; a terminal-only retry cooldown requires documented backend evidence.

## Existing-instance reuse and events

- Explicit model-load requests with positive `context_length` perform a bounded (at most 5 s) read-only `GET /api/v1/models` preflight. Reuse requires exact model key, nonempty instance ID, matching effective context length, and exact type/value equality for every requested supported setting. Unknown settings, absent or malformed inventory, unavailable inventory, or mismatch fall through to the normal exclusive-load lease.
- Verified reuse returns the current instance ID plus `x-coordinator-model-instance-reused: true`, does not acquire a GPU lease, and does not stop/restart the fake miner. The response reports zero new load duration; it does not claim a new instance was created.
- Added observational `resource_coordinator.model_load_failed`, `resource_coordinator.recovery_required`, and `resource_coordinator.miner_restart_inhibited` events with stable `event_key`, timestamp, severity, operation classification, request/model identity, miner-state classification, and safe action. The notification contract is documented in `docs/plans/20261111-reliable-inference-recovery/RESOURCE_MONITOR_CONTRACT.md`. No notification transport was added. A verified managed start remains represented by existing `process.started`; notification consumers may derive `miner_resumed` when process identity/origin can be associated safely.

## Validation

Environment: Windows, Python 3.12.10, pytest 9.2.0, pytest-asyncio 1.4.1.post1; candidate venv. Import check resolved `resource_coordinator` to this worktree. Async suites required narrowly scoped normal-socket-permission execution; tests used fake process backends/mock LM Studio and distinct absolute basetemp roots under `modules/resource_coordinator/.pytest_tmp_root/`.

| Command / scope | Result |
|---|---|
| `python -m pytest tests/test_gateway.py` | Exit 0; 45 passed. Includes loaded-model matching/mismatch, HTTP 400/500/502 uncertainty and retry rejection, event envelope, fake-miner behavior, and existing loopback HTTPX timeout tests. |
| `python -m pytest tests/test_installation.py` | Exit 0; 86 passed. Covers task-install failure rollback and newly parameterized `TASK_INSTALLING` reconciliation. |
| `python -m pytest tests/test_phase1_request_arbitration.py` | Exit 0; 10 passed. |
| `python -m pytest tests/test_durable_state.py tests/test_operator_credentials.py tests/test_config.py` | Exit 0; 38 passed. |
| `python -m pytest tests/test_leases.py tests/test_policies.py` | Exit 0; 8 passed. |
| Ruff on changed Python implementation/test files | Exit 0; all checks passed. |
| `python -m compileall -q resource_coordinator` | Exit 0. |
| `git diff --check` | Exit 0. |

An earlier combined test invocation had 61 setup errors; the error did not reproduce in the isolated single test or full installation suite. A new loaded-model test initially had a missing inference-policy fixture and was corrected before pass. The first installation-suite run exposed a fixture that accidentally queried the live Coordinator and safely blocked before task/service changes; the fixture now stubs the status call. No process, service, task, miner, credential, journal, or configuration mutation occurred. Pytest emits an existing unset `asyncio_default_fixture_loop_scope` deprecation warning.

Opt-in UAC and actual Windows Task Scheduler integration tests were not run; there is no disposable Windows VM/environment available here and production task mutation is prohibited. Prior v0.11.6 acceptance does not validate the newest privileged restore/upgrade path.

## Review and disposition

- Changed behavior is additive: admission error `recovery_required`, model-instance reuse marker/response, and observational event names. Existing CLI, recovery endpoint, timeout defaults, and durable request schema are unchanged.
- No timer, GPU sample, empty inventory, HTTP error, or local disconnect clears the safety hold. Global inhibition blocks new GPU requests until authenticated recovery; after recovery, existing resource/ownership checks and cooldown gate miner start.
- Source candidate is suitable for isolated integration review with documented limits. Do not treat it as ready for production deployment until the exact WinError 206 call is understood or an isolated Windows Task Scheduler acceptance verifies task install/rollback.
- Current production state was not independently queried as part of final validation. During one test attempt, the real status endpoint was reached read-only and correctly prevented recovery; the fixture was changed to stub that call, and no further production reads were made.

## Next actions

1. Source integration validation is recorded below; merging the candidate into `main` remains a separate approval-gated action.
2. Before deployment, use an isolated Windows VM or approved disposable task environment to validate elevated registration, rollback, and the `TASK_INSTALLING` receipt path; preserve the protected recovery-token launcher, operator credentials, Scheduled Tasks, miner ownership/state, and persistent WSL LM Studio mask.
3. Keep the no-terminal-negative-evidence limitation explicit until LM Studio documents a request-specific terminal failure/status/cancel contract.

## v0.12.0 source integration validation (2026-11-11)

- `origin/main` was fetched and verified at `9102815920eff843f1a9ec3abe60060a4ffbdd8f`. Feature branch `agent/resource-coordinator-upgrade-reliability-20261111` and its remote both pointed to `7a5fb2a50a31953f49f1da064f6971ff0ab8d6fb`; merge base is `origin/main`, feature is 11 commits ahead and zero behind. The isolated integration branch was fast-forwarded from `origin/main` to the feature commit. No textual or ancestry conflict occurred.
- The complete integration-branch comparison contains 24 paths, all under `modules/resource_coordinator/`, with 2,577 insertions and 74 deletions. Changed implementation is confined to inference/model-load gateway and admission, configuration, operator credentials, CLI recovery, and Windows installation/recovery. Tests and plan/status/interface documentation are included. No Mining or production configuration source was changed.
- Test environment: Windows 10.0.26300, Python 3.12.10 from `C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe`, pytest 9.0.3, pytest-asyncio 1.3.0. Import resolved to this integration worktree's `resource_coordinator` package. Each test run used a distinct absolute directory under `modules/resource_coordinator/.pytest_tmp_root/integration-*`.

| Command / test scope | Result |
|---|---|
| `python -m pytest -v -ra tests/test_gateway.py` | Exit 0; 45 passed. Includes configured HTTPX phase timeouts, extended model-load deadline, sync/stream completion, timeout uncertainty, recovery/admission rejection, loaded-model reuse, and fake-miner restart behavior. |
| `python -m pytest -v -ra tests/test_cli.py tests/test_cli_architecture.py` | Exit 0; 188 passed. |
| `python -m pytest -vv -ra tests/test_operator_credentials.py` | Exit 0; 16 passed. |
| `python -m pytest -v -ra tests/test_durable_state.py tests/test_argon_adversarial_review.py` | Exit 0; 18 passed. |
| `python -m pytest -v -ra tests/test_config.py` | Exit 0; 14 passed. |
| `python -m pytest -v -ra tests/test_phase1_request_arbitration.py` | Exit 0; 10 passed. |
| `python -m pytest -v -ra tests/test_factory_gateway_integration.py tests/test_phase4_unattended_reliability.py` | Exit 0; 14 passed. |
| `python -m pytest -v -ra tests/test_leases.py tests/test_policies.py` | Exit 0; 8 passed. |
| `python -m pytest -v -ra tests/test_service_lifecycle.py -k 'not test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window'` | Exit 0; 18 passed, 1 deselected. The excluded test passed alone (1 passed); its in-suite failure is recorded above and was reproduced on unchanged `origin/main`. |
| `python -m pytest -v -ra tests/test_installation.py` | Exit 0; 88 passed, including task-install rollback and `TASK_INSTALLING` recovery handling. |
| Opt-in `test_windows_http_gateway_real_listener_with_mocked_success_and_cleanup` and `test_windows_http_gateway_mock_failure_keeps_restart_inhibited` | Exit 0; 2 passed. Uses unique disposable `cscript.exe` processes and a mock-only upstream; no LM Studio/GPU workload. |
| PowerShell `$env:RC_WINDOWS_INTEGRATION='1'; python -m pytest -v -ra tests/test_windows_task_transport_integration.py -k windows_helper_processes_large_request` | Exit 0; 1 passed, 2 deselected. The protected file-backed helper processed a 100 KB request. |

The test results total 423 passed, with the one documented lifecycle case deselected in-suite and verified alone. No actual UAC prompt or Scheduled Task registration test was run, as required. The source files tested are byte-identical to feature commit `7a5fb2a`; the integration branch's follow-up commit records validation only.

The distinct pytest temp roots, relative to `modules/resource_coordinator/.pytest_tmp_root/`, were `integration-gateway-final`, `integration-cli-normal`, `integration-credentials-normal`, `integration-durable-normal`, `integration-config`, `integration-arbitration`, `integration-factory-phase4-normal`, `integration-leases-policy-normal`, `integration-service-lifecycle`, `integration-service-lifecycle-single`, `integration-installation`, `integration-windows-helper`, and `integration-windows-http-process`. Test stdout/results are recorded in this status table; no raw logs or sensitive production data were copied into the repository.

Ruff passed for the changed Python files except `tests/test_phase1_request_arbitration.py`. Ruff reports nine existing unused-import/redefinition findings in that file; the same nine were reproduced from `origin/main`, and this branch's change there is limited to two test lines. No unrelated lint cleanup was made. `python -m compileall -q resource_coordinator` and `git diff --check origin/main...HEAD` passed.

An initial gateway invocation used a module-local temp child before its parent `.pytest_tmp_root` existed; it failed during fixture setup, then passed after the parent was created. Several default-sandbox async runs stopped advancing; bounded retries with normal socket permissions passed. These were execution/setup issues, not failed product assertions.

## Integration disposition

- Source integration candidate is internally consistent and regression-tested at the feature source SHA. The candidate branch can be pushed for review and fast-forwarded to `main` after explicit merge authorization.
- This does not validate elevated Scheduled Task replacement, startup, rollback, or the historical WinError 206. The disposable Windows Task Scheduler gate and production deployment remain blocked pending a separately authorized isolated Windows acceptance.
- For a future isolated Mining maintenance-session branch, use the validated integration candidate commit after its source merge is approved; no maintenance-session implementation is included here.
