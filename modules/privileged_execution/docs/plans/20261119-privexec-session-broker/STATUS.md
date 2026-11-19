# Status — `20261119-privexec-session-broker`

- **Current Phase:** Diagnosed & fixed Gate 2 `state\evidence` `UnauthorizedAccessException` (async thread impersonation leak) and stale-SID ACL reconciliation in `Install-PrivExec.ps1`; awaiting elevated operator rerun of `Invoke-Gate1And2Elevated.ps1`
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Gate 1–2 Failure Diagnosis & Fixes
1. **Cross-account `TEMP` / `Temp:` drive failure:** `Start-Process -Credential` inherited the operator's `TEMP`/`TMP`/`USERPROFILE` (`C:\Users\mcarls\AppData\Local\Temp\`), which standard test accounts cannot traverse. (`-UseNewEnvironment` also ignores `-Environment` in PowerShell 7.6.)
   - *Fix:* `Invoke-Gate1And2Elevated.ps1` creates per-account isolated directories under `C:\ProgramData\PrivExec-Gate2Run\<runId>` with strict ACLs and launches `pwsh.exe` with `-Environment` (without `-UseNewEnvironment`) overriding `TEMP`, `TMP`, `TMPDIR`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `HOME`, `HOMEDRIVE`, `HOMEPATH`. `Test-PrivExecCrossAccount.ps1` validates `GetTempPath()` against `-ExpectedTempDir`. `ProcessExecutor.cs` also pins child `TEMP`/`TMP` to `state\tmp`.
2. **Pipe EOF / missing stderr & evidence:** `PipeBrokerServer.cs` swallowed non-`IOException` exceptions inside `Task.Run(...)` without stderr logging or structured error responses; `Test-PrivExecCrossAccount.ps1` lacked `TokenImpersonationLevel.Impersonation`; `Invoke-Gate1And2Elevated.ps1` did not persist incremental failure evidence before cleanup.
   - *Fix:* `PipeBrokerServer.cs` catches/logs all connection/auth/engine exceptions (`[PRIVEXEC_PIPE_ERROR]`) and returns structured JSON error frames; `BrokerEngine.cs` catches unexpected executor exceptions so SQLite never strands a row in `executing`; `Test-PrivExecCrossAccount.ps1` uses `TokenImpersonationLevel.Impersonation` and actionable EOF diagnostics; `Invoke-Gate1And2Elevated.ps1` writes incremental evidence from `init` through `cleanup` without masking failures.
3. **Transient test account description length limit (<= 48 characters):** Windows `New-LocalUser -Description` failed when given the 65-character tag `"PrivExec Gate 2 temporary test account ($runId)"`.
   - *Fix:* Updated tag format to `PE2:agent:<runId>` (34 chars) and `PE2:unauth:<runId>` (35 chars), strictly under 48 chars while preserving full 24-character `$runId` for ownership tracking. Validated description and username length (<= 20 chars) in `New-TransientTestUser` before execution. Enhanced cleanup in `finally` to match exact description, `PE2:*:$runId` pattern, and sweep any orphaned accounts created with this run ID.
4. **Gate 2 `state\evidence` `UnauthorizedAccessException` (`run_id: 20261119-161632-11cc62d5`):** `synthetic.mutate` `dry_run` launched `pwsh.exe` successfully (under process primary token) but threw `UnauthorizedAccessException: Access to the path 'C:\ProgramData\PrivExec\state\evidence' is denied` in `WriteSanitizedEvidence` after `await process.WaitForExitAsync`.
   - *Root Cause:* Reproducible in `PrivExecBroker.Tests`: after `NamedPipeServerStream.RunAsClient`, ThreadPool continuations across `await` can resume on a thread carrying an active `WindowsIdentity` impersonation context (`Impersonation`), causing filesystem operations on `state\evidence` to execute under the unprivileged client token rather than the broker's privileged process token.
   - *Fix:* Added `SecurityAndAcl.RevertImpersonationIfActive`, `RunAsProcessIdentity`, and `RunAsProcessIdentityAsync` (`WindowsIdentity.RunImpersonatedAsync(SafeAccessTokenHandle.InvalidHandle, ...)`), wrapped `_engine.HandleRawRequestAsync` in `PipeBrokerServer.cs` and `WriteSanitizedEvidence` in `ProcessExecutor.cs`, and added regression test `Phase3.PipeServerDoesNotLeakImpersonation`.
5. **Stale SID retention on `Install-PrivExec.ps1` reinstall:** `icacls /inheritance:r /grant:r` only updated ACEs for `SYSTEM`, `Administrators`, and `OperatorAccount`, leaving prior temporary agent SIDs (e.g. `S-1-5-21-...-1009`) on `descriptors`.
   - *Fix:* Added `Set-StrictDirectoryAcl` in `Install-PrivExec.ps1` using a fresh protected `DirectorySecurity` (`SetAccessRuleProtection($true, $false)`) and resetting child inheritance so stale ACEs are purged on every install/reinstall. Added regression test `test_installer_reconciles_and_purges_stale_acls`.

## Verified Test Runs (Latest Working Tree)
- `Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 26/26 C# tests passed
- `python -m pytest -o pythonpath=. -v --basetemp=.pytest_tmp_root/tmp` (in `modules/privileged_execution`) -> 19/19 passed
- `ruff check .` -> All checks passed
- `python -m pytest -q -p no:cacheprovider --basetemp=modules/privileged_execution/.pytest_tmp_root/scripts_help_tmp modules/scripts_help/tests` -> 55/55 passed
- `Install-PrivExec.ps1 -Mode CrossAccountIsolated -AgentAccount ... -Json` (dry-run) -> exit 0

## Next Actionable Step
- Operator runs elevated: `pwsh -NoProfile -File .\scripts\Invoke-Gate1And2Elevated.ps1 -CreateTempTestAccounts` and supplies `C:\ProgramData\PrivExec\gate1-2-evidence.json`.
