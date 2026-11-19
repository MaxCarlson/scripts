# Status — `20261119-privexec-session-broker`

- **Current Phase:** Diagnosed & fixed `SqliteOperationStore.ReadRecord` `RequestId`/`ClientSid` parameter-order bug (which caused `403 unauthorized_identity` on result lookup of `op-ff6347bbd67448b0`); awaiting elevated operator rerun of `Invoke-Gate1And2Elevated.ps1`
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
4. **Gate 2 `state\evidence` `UnauthorizedAccessException` (`run_id: 20261119-161632-11cc62d5`):** `synthetic.mutate` `dry_run` launched `pwsh.exe` successfully (under process primary token) but threw `UnauthorizedAccessException: Access to the path 'C:\ProgramData\PrivExec\state\evidence' is denied` in `WriteSanitizedEvidence` after `await process.WaitForExitAsync`.
   - *Root Cause & Fix:* After `NamedPipeServerStream.RunAsClient`, ThreadPool continuations across `await` could resume on a thread carrying an active `WindowsIdentity` impersonation context (`Impersonation`). Added `SecurityAndAcl.RevertImpersonationIfActive`, `RunAsProcessIdentity`, and `RunAsProcessIdentityAsync`, wrapped `_engine.HandleRawRequestAsync` in `PipeBrokerServer.cs` and `WriteSanitizedEvidence` in `ProcessExecutor.cs`, and added regression test `Phase3.PipeServerDoesNotLeakImpersonation`.
5. **Stale SID retention on `Install-PrivExec.ps1` reinstall:** `icacls /inheritance:r /grant:r` only updated ACEs for `SYSTEM`, `Administrators`, and `OperatorAccount`, leaving prior temporary agent SIDs on `descriptors`.
   - *Fix:* Added `Set-StrictDirectoryAcl` in `Install-PrivExec.ps1` using a fresh protected `DirectorySecurity` (`SetAccessRuleProtection($true, $false)`) and resetting child inheritance so stale ACEs are purged on every install/reinstall.
6. **Gate 1 `Install-PrivExec.ps1 failed.` false failure (`run_id: 20261119-184515-5819f80d`) & repeated-install `SeSecurityPrivilege` hardening:**
   - *Root Cause & Fix:* Replaced PowerShell `Set-Acl` with `[System.IO.FileSystemAclExtensions]::SetAccessControl(...)` (DACL-only), added explicit `$global:LASTEXITCODE = 0; exit 0` and structured stage/error diagnostics to `Install-PrivExec.ps1`, and invoked `Install-PrivExec.ps1` via child `pwsh.exe` in `Invoke-Gate1And2Elevated.ps1` with full diagnostic capture (`gate1_install_diagnostics`).
7. **Gate 2 `result` lookup `403 unauthorized_identity` (`run_id: 20261119-190051-5e0fceb1`, `op-ff6347bbd67448b0`):**
   - *Confirmed Root Cause:* Read-only SQLite query on `C:\ProgramData\PrivExec\state\privexec.db` confirmed `op-ff6347bbd67448b0` (`synthetic.mutate` `apply`) succeeded and was persisted with `client_sid = "S-1-5-21-4067329743-3279872635-954170557-1015"` and `request_id = "gate2-appmut-08af9df5"`. However, `SqliteOperationStore.ReadRecord` called `new OperationRecord(opId, clientSid, requestId, ...)`, whereas `OperationRecord` in `Models.cs` has constructor order `(string OperationId, string RequestId, string ClientSid, ...)`. Swapping arguments 2 and 3 populated `rec.ClientSid` with `"gate2-appmut-08af9df5"` and `rec.RequestId` with `"S-1-5-21-...-1015"`, causing `BrokerEngine.HandleResultLookup`'s ownership check (`rec.ClientSid == client.Sid`) to fail with `Client SID does not own this operation record.`
   - *Fix:* Corrected `SqliteOperationStore.ReadRecord` to pass `(opId, requestId, clientSid, ...)`. Updated `Test-PrivExecCrossAccount.ps1` and `Invoke-Gate1And2Elevated.ps1` to persist individual subtest results (`status`, `synthetic_read_only`, `synthetic_mutate_dry_run`, `synthetic_mutate_apply`, `synthetic_mutate_result_lookup`, etc.) into `$evidence['gate2_agent']` even if a later subtest fails. Added regression assertions in `Phase2Tests.cs` and `Phase3.SqliteEngineOwnershipAndCrossAgentIdempotency` in `Phase3Tests.cs`.

## Verified Test Runs (Latest Working Tree)
- `Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 27/27 C# tests passed
- `python -m pytest -o pythonpath=. -v --basetemp=.pytest_tmp_root/tmp` (in `modules/privileged_execution`) -> 19/19 passed
- `ruff check .` -> All checks passed
- `python -m pytest -q -p no:cacheprovider --basetemp=modules/privileged_execution/.pytest_tmp_root/scripts_help_tmp modules/scripts_help/tests` -> 55/55 passed
- `Install-PrivExec.ps1 -Mode CrossAccountIsolated -AgentAccount ... -Json` (dry-run) -> exit 0

## Next Actionable Step
- Operator runs elevated: `pwsh -NoProfile -File .\scripts\Invoke-Gate1And2Elevated.ps1 -CreateTempTestAccounts` and supplies `C:\ProgramData\PrivExec\gate1-2-evidence.json`.
