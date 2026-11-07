# CLI lifecycle and recovery status

- Active branch: `codex/resource-coordinator-windows-listener-readable-cli-20261106`.
- Latest pushed base before this continuation: `fbd5e33039daccd2a1303276d3b26dfd9f257b60`.
- Current source version: `0.11.5` (transport and recovery reliability fixes).

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

- Installation + recovery presentation + Windows listener + transport suite: **101 passed, 3 skipped** (two opt-in helper/UAC tests; one disposable TCP table test cannot see the socket from this runner).
- CLI architecture: **160 passed, 1 deselected** (raw log-follow byte-stream test hangs in this environment).
- CLI: **17 passed, 1 deselected** (existing CLI preflight test hangs in this environment).
- Protected local-agent-bridge route regression: **1 passed**.
- Credential tests: with only the async restart test deselected, **14 passed, 1 failed, 1 deselected**. The failure is `test_windows_credential_acl_allows_user_and_system_only` against the sandbox-provided pytest temporary directory. Excluding that environment-specific ACL test as well: **14 passed, 2 deselected**.
- Async lifecycle limitation: Python 3.12.10 / pytest-asyncio 1.3.0 hangs at the first `@pytest.mark.asyncio` test before its body runs. A standalone `asyncio.run(asyncio.sleep(0))` reproduced the hang. The two synchronous service-lifecycle tests passed; 25 async tests were deselected.
- Validation tools: targeted Ruff check passed; `python -m compileall -q resource_coordinator` passed; `git diff --check` passed.
- Real Windows normal-privilege integration: **1 passed** using the new read-only `transport_probe` with a 100 KiB request. This exercised PowerShell, the actual file-backed helper, ACL setup/verification, request integrity, result persistence/integrity, and cleanup without querying or changing Scheduled Tasks.
- A separate real `status` helper attempt reached `Get-ScheduledTask` but was denied with `Access to a CIM resource was not available to the client`. Thus ordinary Task Scheduler inventory is not validated in this sandbox.
- Successful elevated/UAC helper execution, task registration/restoration, and disposable elevated-task rollback remain unverified. The opt-in test command for a non-elevated interactive PowerShell session is documented in the README under `RC_WINDOWS_UAC_INTEGRATION=1`.

## Safety and remaining validation

- No production coordinator, miner, GPU setting, LM Studio instance, Scheduled Task, launcher, configuration, credential, or recovery receipt was read or changed during this continuation. The real helper integration used only a disposable temp directory and the test-only `transport_probe` operation.
- Do not merge this branch into `main` without explicit user authorization.
- Before integration, run Ruff, compilation and diff checks, review the complete scoped diff, then push the validated feature head. The separately assigned status/startup UX addendum remains deferred until this recovery work is merged with approval.
