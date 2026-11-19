# Status — `20261119-privexec-session-broker`

- **Current Phase:** Diagnosed & fixed Gate 1 `$LASTEXITCODE` `$null -ne 0` false-failure / `FileSystemAclExtensions` DACL-only reconciliation / structured installer diagnostics; awaiting elevated operator rerun of `Invoke-Gate1And2Elevated.ps1`
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
   - *Confirmed Root Cause:* Timestamp and ACL inspection on `C:\ProgramData\PrivExec` proved `Install-PrivExec.ps1` actually completed all stages at `18:45:17.483Z`–`18:45:17.494Z` (all 5 descriptors written, stale SIDs `-1009`/`-1011` purged, new agent SID `-1013` applied). However, after commit `84a1118a` removed `icacls.exe` calls from `Install-PrivExec.ps1` and the `-Apply` branch lacked an explicit `exit 0`, invoking `& $installScript` in-process left `$LASTEXITCODE` as `$null` in the fresh `pwsh -File` session. In PowerShell, `($null -ne 0)` evaluates to `$true`, triggering `if ($LASTEXITCODE -ne 0) { throw 'Install-PrivExec.ps1 failed.' }` at line 205 before `$evidence['gate1_install']` was saved. Additionally, PowerShell's `Set-Acl` cmdlet can request `SeSecurityPrivilege` / owner writes on already-protected directories during repeated installs.
   - *Fix:*
     - `Install-PrivExec.ps1` now uses `[System.IO.FileSystemAclExtensions]::SetAccessControl(...)` (writing only the DACL without touching SACL/Owner), uses `-DirectFilesOnly` on parent directories so `state`/`work` never transiently inherit agent `RX`, tracks `$installStage`, emits structured JSON error diagnostics on failure, sets `$global:LASTEXITCODE = 0`, and calls `exit 0` on success.
     - `Invoke-Gate1And2Elevated.ps1` runs `Install-PrivExec.ps1` as a `pwsh.exe` child process with captured `exit_code`, `stdout`, `stderr`, parsed error payload, and `partial_install_status` saved to `$evidence['gate1_install_diagnostics']` before evaluating failure; records `error_details`; purges temporary test-account SIDs from `C:\ProgramData\PrivExec` in `finally` before deleting temporary accounts; and cleans up empty `C:\ProgramData\PrivExec-Gate2Run`.

## Verified Test Runs (Latest Working Tree)
- `Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 26/26 C# tests passed
- `python -m pytest -o pythonpath=. -v --basetemp=.pytest_tmp_root/tmp` (in `modules/privileged_execution`) -> 19/19 passed
- `ruff check .` -> All checks passed
- `python -m pytest -q -p no:cacheprovider --basetemp=modules/privileged_execution/.pytest_tmp_root/scripts_help_tmp modules/scripts_help/tests` -> 55/55 passed
- `Install-PrivExec.ps1 -Mode CrossAccountIsolated -AgentAccount ... -Json` (dry-run) -> exit 0

## Next Actionable Step
- Operator runs elevated: `pwsh -NoProfile -File .\scripts\Invoke-Gate1And2Elevated.ps1 -CreateTempTestAccounts` and supplies `C:\ProgramData\PrivExec\gate1-2-evidence.json`.
