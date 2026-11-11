# CLI lifecycle and recovery status

- Active branch: `codex/resource-coordinator-windows-listener-readable-cli-20261106`.
- Reviewed feature checkpoint: `734294c070eff71f6c21717b81fccdffba93c9e8`.
- Current source version: `0.11.7` (transport and recovery reliability fixes).

## Implemented

- Bounded Windows task-helper transport uses unique per-operation directories, a protected JSON request file, a short `-File` invocation for the normal path, and a short elevated `Start-Process -Verb RunAs` wrapper. The elevated helper writes an atomic result record; the caller checks operation ID, request digest, result digest, completion state and helper identity before returning.
- Operation DACL changes are limited to the unique temporary operation directory. The persistent managed-root ACL is not reset by read-only status. The DACL is read back and checked for exact expected SIDs and full-control entries. Operation artifacts are retained on timeout, UAC cancellation, process failure or missing/malformed/mismatched completion evidence; cleanup occurs only after verified success.
- The elevated helper now reads the request bytes once, hashes those bytes, and parses those same bytes, closing a request-file substitution window.
- Offline recovery CLI exposes `status`, `diagnose`, `restore`, `resume`, and `reconcile`; recovery status/diagnosis do not require the coordinator HTTP API.
- Recovery restore rechecks listener, process creation identities, task inventory and state, durable journal, coordinator lock and miner state before starting the previous task. It never adopts or kills a miner. A previously running miner is considered restored only after the new coordinator reports an owned process; a captured durable manual hold must still be active and the miner stopped.
- Incident reconciliation accepts only an already-ready, attributable owned runtime with zero active/pending inference and an unchanged, recognized one-shot policy. It archives the receipt and removes only the known policy without restarting the service.
- Automatic rollback is exercised for task-registration failure and post-start runtime verification failure. A live replacement is stopped only after exact runtime, listener, task ancestry, shutdown guarantee, inference state and miner ownership checks; ambiguous/still-running task instances fail closed and preserve the receipt.
- Windows administrative transport validation runs before graceful shutdown in the apply path.
- Recovery has dedicated Rich output and JSON through the existing CLI dispatch, with exit codes distinguishing blocked/recovery-required states.

## Validation evidence

### Agent-run regression and static checks

- Installation + recovery presentation + Windows listener + transport suites: **103 passed, 4 skipped** after adding task XML restore validation.
- CLI architecture + CLI suites: **177 passed, 2 deselected**. The deselections were the raw log-follow byte-stream test and existing CLI preflight test, which hang in this runner.
- Credential tests: **15 passed, 1 deselected**; the deselected test is the async coordinator restart test.
- Administrative-helper preflight failure regression: **1 passed**; it confirms helper validation failure occurs before the graceful shutdown request.
- Real Windows normal-privilege helper probe: **1 passed, 2 skipped** with a 100 KiB request; the helper script parsed and ran, while Task Scheduler access was denied and UAC remained opt-in.
- Ruff targeted checks, Python compilation, and `git diff --check`: passed.
- ACL environment distinction: `test_windows_credential_acl_allows_user_and_system_only` failed under the sandbox AppContainer temp directory, then passed using a pytest `--basetemp` within the feature worktree. This is an execution-context ACL limitation, not a passing result from the default temp path.
- Async limitation remains unresolved: Python 3.12.10 / pytest-asyncio 1.3.0 stalled at async tests, and a bounded subprocess running `asyncio.run(asyncio.sleep(0))` timed out after five seconds. The affected async restart test and the interrupted durable-state run remain unverified.

### User-performed Windows acceptance (reported 2026-11-06)

The user reports running these checks from an isolated Python 3.12 virtual environment with Resource Coordinator 0.11.6 and its development dependencies. These results were not independently re-executed by the agent.

**Interactive UAC elevation — passed (1 test):**

```powershell
$env:RC_WINDOWS_UAC_INTEGRATION = '1'
python -m pytest .\modules\resource_coordinator\tests\test_windows_task_transport_integration.py -q -rs -k uac_helper
```

The user approved the expected administrator prompt. This validates the elevated helper transport with a large request and verified completion evidence.

**Disposable Scheduled Task lifecycle — passed (1 test):**

```powershell
$env:RC_WINDOWS_TASK_INTEGRATION = '1'
python -m pytest .\modules\resource_coordinator\tests\test_windows_task_transport_integration.py -q -rs -k disposable_task
```

The test registered a uniquely named disposable task, exported a snapshot, changed its action, restored the snapshot, and verified the restored definition. The user then queried `RC-Disposable-*`; no matching task remained.

The disposable task lifecycle uses Windows Task Scheduler cmdlets directly. It does **not** exercise task registration/restoration through the full elevated Resource Coordinator helper path. The UAC helper transport and Task Scheduler lifecycle were verified separately. Neither test is a full end-to-end transactional upgrade or rollback test.

## Safety and remaining validation

- No production coordinator, miner, GPU setting, LM Studio instance, Scheduled Task, launcher, configuration, credential, or recovery receipt was read or changed during this continuation. The real helper integration used only a disposable temp directory and the test-only `transport_probe` operation.
- Do not merge this branch into `main` without explicit user authorization.
- Before integration, run Ruff, compilation and diff checks, review the complete scoped diff, then push the validated feature head. The separately assigned status/startup UX addendum remains deferred until this recovery work is merged with approval.

## Final targeted review — 2026-11-06

- Reviewed the feature diff against its `81d740c2` merge base and checked divergence from `origin/main` (`f37e27bf`): main is 9 commits ahead and this branch is 5 commits ahead. The changed path sets do not overlap. `git merge-tree` reported no textual conflicts. No merge/rebase was performed.
- Found and fixed an automatic rollback elevation-routing defect: internal `recovery("restore", _transaction_lock_held=True)` could relaunch the original CLI arguments (including `system upgrade -a`) instead of continuing rollback. Internal recovery now uses the bounded task helper directly. Regression was observed failing before the fix and passing afterward.
- Added a disposable Windows Scheduled Task test that uses a unique `RC-Disposable-*` name, refuses collisions, registers disabled/future-trigger task, exports a snapshot, mutates, restores, verifies action/principal/enabled state and removes only that task.
- Focused validation after the fix: installation/recovery/presentation/listener suite **102 passed, 4 skipped**; CLI suites **177 passed, 2 deselected**; credential suite with only async restart excluded **15 passed, 1 deselected**. The identity/attribution/state run was interrupted while hanging in `test_durable_state.py` after 15 displayed passes; the full state suite remains unverified in this runner.
- Real Windows normal helper probe passed with a 100 KiB payload. The disposable Scheduled Task test was attempted and skipped with `Access to a CIM resource was not available to the client`; no task registration was confirmed. UAC test was not run because it requires an interactive approval prompt. The README now gives separate commands for the disposable task test and UAC helper test.
- The credential ACL test fails when pytest uses the sandbox's AppContainer temp root, but passes with `--basetemp` inside the feature worktree. A bounded subprocess reproduction of `asyncio.run(asyncio.sleep(0))` timed out after 5 seconds; the async credential restart test remains unverified.
- No production service, task, process, GPU setting, configuration or recovery artifact was changed. Read-only production state was not queried during this review.
- Review correction was regression-tested red/green, linted, compiled, diff-checked, committed, and pushed at `734294c070eff71f6c21717b81fccdffba93c9e8`. The feature branch remains unmerged. Do not merge or begin the dependent CLI addendum without the user's explicit integration approval.
- Final privileged-restore review found that recovery accepted task XML based on receipt shape without validating its action and principal before elevated registration. Python now validates task XML, restricted PowerShell arguments, launcher path/marker, task mode and privilege level during Windows preflight and before restore; the elevated helper independently validates task name, principal SID/logon type/run level, PowerShell executable, safe `-File` arguments and managed launcher path before `Register-ScheduledTask`. Acceptance/rejection tests pass. This new 0.11.7 hardening has not yet been exercised with an actual elevated restore; the user-performed 0.11.6 UAC and disposable-task tests are recorded above and remain distinct from this path.
- Final regression after this guard: **103 passed, 4 skipped**; CLI **177 passed, 2 deselected**; credentials **15 passed, 1 deselected**; targeted Ruff, compilation and diff checks passed. The ordinary helper probe passed and compiled the updated PowerShell helper body. The feature is now 6 commits ahead of its merge base after the pending scoped checkpoint commit; verify exact branch counts after pushing.

## Isolated integration candidate validation — 2026-11-11

- Candidate branch: `integrate/resource-coordinator-v0117-20261111`.
- Candidate worktree: `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-integration-candidate-20261111`.
- Candidate merge checkpoint before this evidence update: `f01e490e1e5ca2883b3a30b47c4af39b0c5a7d26` (target `main` `11cb33970338a957f1a9ec3abe60060a4ffbdd8f` plus feature `aadae74515ba1ed6d7ac62bb2562a40c29e6debd`). Target is an ancestor; target and feature changed 49 and 13 paths from their common ancestor respectively, with **zero path overlap**.
- Fresh candidate-local `.venv` installed Resource Coordinator 0.11.7, repository-local `resource_metrics`, and declared dev dependencies. Import verification resolved `resource_coordinator` under this candidate's module directory. Each test invocation used a distinct candidate-local absolute `--basetemp`.
- `python -m pytest -vv tests/test_installation.py --basetemp <suite-installation-20261111> -ra`: **85 passed**.
- `python -m pytest -vv tests/test_operator_credentials.py -k 'not credential_survives_coordinator_service_restart' --basetemp <suite-operator-credentials-20261111> -ra`: **15 passed, 1 deselected**. The deselected async test stalls in isolation.
- `python -m pytest -vv tests/test_durable_state.py -k 'not restore_into_leases' --basetemp <suite-durable-state-nonasync-20261111> -ra`: **7 passed, 1 deselected**. The deselected async lease-restore test stalls after collection.
- `python -m pytest -vv tests/test_recovery_presentation.py --basetemp <suite-recovery-presentation-20261111> -ra`: **2 passed**.
- `python -m pytest -vv tests/test_cli_architecture.py tests/test_cli.py -k 'not log_follow and not preflight' --basetemp <suite-cli-20261111> -ra`: **172 passed, 7 deselected**. A separate full `test_cli.py` run passed its first 15 cases, then stalled in `test_cli_cmd_preflight`; a 12-second subprocess watchdog reproduced the stall after test entry.
- `python -m pytest -vv tests/test_windows_task_transport_integration.py --basetemp <suite-task-transport-20261111> -ra`: **3 skipped** because disposable Task Scheduler, ordinary helper, and UAC paths are opt-in. No task was registered and no elevation prompt was launched.
- Privileged task XML acceptance/rejection is covered by the in-process `test_task_restore_rejects_untrusted_xml_and_accepts_owned_launcher`; selected XML/helper/recovery/CLI architecture regressions: **3 passed**. The production helper intentionally allows only the two production task names, so a uniquely named disposable task cannot exercise its elevated registration path without weakening policy. No disposable VM was available in the inspected environment; full elevated restore acceptance remains a documented gap.
- `ruff check` on changed Python files, `python -m compileall -q resource_coordinator`, and `git diff --check <target>..HEAD`: **passed**. Whole-module Ruff has 74 existing findings outside the changed-file check; no unrelated lint cleanup was applied.
- Async diagnostic: Python 3.12.10 in the candidate venv, pytest 9.2.0, pytest-asyncio 1.4.1.post1, `asyncio_mode=auto`. A standalone `asyncio.run(asyncio.sleep(0))` subprocess printed `before` and exceeded an 8-second watchdog before printing `after`. The async credential restart test exceeded 12 seconds after pytest entered the test; durable lease restore stalled after entering its case. This indicates a local event-loop execution stall before coroutine completion, but does not identify a specific Windows process restriction. These cases remain incomplete, not passed.
- The earlier `WinError 32` occurred while two separate suites were run concurrently against the same temp root. The isolated credential cleanup regression passed alone, and the full installation suite passed alone with a distinct temp root; the prior `WinError 32` is therefore attributed to this validation run's shared-temp collision, not a confirmed product cleanup defect.
- No production coordinator, miner, launcher, credential, Scheduled Task, GPU setting, model, or WSL service was inspected or changed. No code defect was confirmed and no source fix was made.
- Recommendation: **READY WITH DOCUMENTED LIMITATIONS** only if the operator accepts the async execution and real elevated restore gaps. Otherwise defer merge until the async runner works in a normal Windows test context and elevated restore is exercised in a disposable isolated Windows environment. No merge to production `main` or deployment is authorized by this status update.
