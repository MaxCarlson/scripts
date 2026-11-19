# Status — `20261119-privexec-session-broker`

- **Current Phase:** Diagnosed & fixed Gate 2 `UnauthorizedAccount` script-staging failure (exit 64) and implemented `gate2_expiry_check`; awaiting elevated operator rerun of `Invoke-Gate1And2Elevated.ps1`
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Gate 1–2 Failure Diagnosis & Fixes
1. **Cross-account `TEMP` / `Temp:` drive failure:** `Start-Process -Credential` inherited the operator's `TEMP`/`TMP`/`USERPROFILE` (`C:\Users\mcarls\AppData\Local\Temp\`), which standard test accounts cannot traverse. (`-UseNewEnvironment` also ignores `-Environment` in PowerShell 7.6.)
   - *Fix:* `Invoke-Gate1And2Elevated.ps1` creates per-account isolated directories under `C:\ProgramData\PrivExec-Gate2Run\<runId>` with strict ACLs and launches `pwsh.exe` with `-Environment` (without `-UseNewEnvironment`) overriding `TEMP`, `TMP`, `TMPDIR`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `HOME`, `HOMEDRIVE`, `HOMEPATH`. `Test-PrivExecCrossAccount.ps1` validates `GetTempPath()` against `-ExpectedTempDir`. `ProcessExecutor.cs` also pins child `TEMP`/`TMP` to `state\tmp`.
2. **Pipe EOF / missing stderr & evidence:** `PipeBrokerServer.cs` swallowed non-`IOException` exceptions inside `Task.Run(...)` without stderr logging or structured error responses; `Test-PrivExecCrossAccount.ps1` lacked `TokenImpersonationLevel.Impersonation`; `Invoke-Gate1And2Elevated.ps1` did not persist incremental failure evidence before cleanup.
   - *Fix:* `PipeBrokerServer.cs` catches/logs all connection/auth/engine exceptions (`[PRIVEXEC_PIPE_ERROR]`) and returns structured JSON error frames; `BrokerEngine.cs` catches unexpected executor exceptions so SQLite never strands a row in `executing`; `Test-PrivExecCrossAccount.ps1` uses `TokenImpersonationLevel.Impersonation` and actionable EOF diagnostics; `Invoke-Gate1And2Elevated.ps1` writes incremental evidence from `init` through `cleanup` without masking failures.
3. **Transient test account description length limit (<= 48 characters):** Windows `New-LocalUser -Description` failed when given the 65-character tag `"PrivExec Gate 2 temporary test account ($runId)"`.
   - *Fix:* Updated tag format to `PE2:agent:<runId>` (34 chars) and `PE2:unauth:<runId>` (35 chars), strictly under 48 chars while preserving full 24-character `$runId` for ownership tracking.
4. **Gate 2 `state\evidence` `UnauthorizedAccessException` (`run_id: 20261119-161632-11cc62d5`):** ThreadPool continuations across `await` after `NamedPipeServerStream.RunAsClient` carried an active `WindowsIdentity` impersonation context.
   - *Fix:* Added `SecurityAndAcl.RevertImpersonationIfActive`, `RunAsProcessIdentity`, and `RunAsProcessIdentityAsync`, wrapped `_engine.HandleRawRequestAsync` in `PipeBrokerServer.cs` and `WriteSanitizedEvidence` in `ProcessExecutor.cs`.
5. **Stale SID retention & Gate 1 `$LASTEXITCODE` / `Set-Acl` fixes (`run_id: 20261119-184515-5819f80d`):**
   - *Fix:* `Install-PrivExec.ps1` uses `[System.IO.FileSystemAclExtensions]::SetAccessControl(...)` (DACL-only), `-DirectFilesOnly` on parent directories, structured stage/error diagnostics, and explicit `$global:LASTEXITCODE = 0; exit 0`. `Invoke-Gate1And2Elevated.ps1` runs `Install-PrivExec.ps1` via child `pwsh.exe` and purges temporary agent SIDs in `finally`.
6. **Gate 2 `result` lookup `403 unauthorized_identity` (`run_id: 20261119-190051-5e0fceb1`):** `SqliteOperationStore.ReadRecord` passed `(opId, clientSid, requestId, ...)` instead of `(opId, requestId, clientSid, ...)`.
   - *Fix:* Fixed parameter order in `SqliteOperationStore.ReadRecord` and added regression tests in `Phase2Tests.cs` and `Phase3Tests.cs`.
7. **Gate 2 `UnauthorizedAccount` launch exit 64 & `gate2_expiry_check` (`run_id: 20261119-191942-ea536bb8`):**
   - *Confirmed Root Cause:* Gate 1 and all 11 `AuthorizedAgent` checks passed. However, `C:\ProgramData\PrivExec\client\Test-PrivExecCrossAccount.ps1` is ACL-restricted to `SYSTEM`, `Administrators`, `OperatorAccount`, and `AuthorizedAgent` (`PrivExecAg_*`), so `pwsh.exe` running as `UnauthorizedAccount` (`PrivExecUn_*`) exited with code 64 before executing the script or reaching the named pipe. Additionally, `gate2_expiry_check` was not yet wired into `Invoke-Gate1And2Elevated.ps1`.
   - *Fix:* `Invoke-Gate1And2Elevated.ps1` stages a minimal copy of `Test-PrivExecCrossAccount.ps1` inside the unauthorized account's isolated `$unProfile` directory (preserving strict denial on `C:\ProgramData\PrivExec`), and runs `gate2_expiry_check` with a 2s-TTL grant broker after `gate2_unauthorized`. `Test-PrivExecCrossAccount.ps1` strictly validates `pipe_access_denied` (`UnauthorizedAccessException`) or `unauthorized_identity` (rejecting unreachable-pipe errors), records `connection_outcome`/`protocol_outcome`/`expected`/`observed`, and implements `-Role ExpiredGrantCheck`. Added `test_unauthorized_isolated_client_and_expired_grant_checks` in `privexec_phase3_test.py`.

## Verified Test Runs (Latest Working Tree)
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 27/27 C# tests passed
- `python -m pytest -o pythonpath=. -v --basetemp=.pytest_tmp_root/tmp` (in `modules/privileged_execution`) -> 20/20 passed
- `ruff check .` -> All checks passed
- `python -m pytest -q -p no:cacheprovider --basetemp=modules/privileged_execution/.pytest_tmp_root/scripts_help_tmp modules/scripts_help/tests` -> 55/55 passed
- `Install-PrivExec.ps1 -Mode CrossAccountIsolated -AgentAccount ... -Json` (dry-run) -> exit 0

## Next Actionable Step
- Operator runs elevated: `pwsh -NoProfile -File .\scripts\Invoke-Gate1And2Elevated.ps1 -CreateTempTestAccounts` and supplies `C:\ProgramData\PrivExec\gate1-2-evidence.json`.
