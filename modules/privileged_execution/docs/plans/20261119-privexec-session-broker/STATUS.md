# Status — `20261119-privexec-session-broker`

- **Current Phase:** Diagnosed & fixed Gate 1–2 cross-account TEMP, pipe EOF, and account description length limits; awaiting interactive operator UAC rerun of `Invoke-Gate1And2Elevated.ps1`
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Gate 1–2 Failure Diagnosis & Fixes
1. **Cross-account `TEMP` / `Temp:` drive failure:** `Start-Process -Credential` inherited the operator's `TEMP`/`TMP`/`USERPROFILE` (`C:\Users\mcarls\AppData\Local\Temp\`), which standard test accounts cannot traverse. (`-UseNewEnvironment` also ignores `-Environment` in PowerShell 7.6.)
   - *Fix:* `Invoke-Gate1And2Elevated.ps1` creates per-account isolated directories under `C:\ProgramData\PrivExec-Gate2Run\<runId>` with strict ACLs and launches `pwsh.exe` with `-Environment` (without `-UseNewEnvironment`) overriding `TEMP`, `TMP`, `TMPDIR`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `HOME`, `HOMEDRIVE`, `HOMEPATH`. `Test-PrivExecCrossAccount.ps1` validates `GetTempPath()` against `-ExpectedTempDir`. `ProcessExecutor.cs` also pins child `TEMP`/`TMP` to `state\tmp`.
2. **Pipe EOF / missing stderr & evidence:** `PipeBrokerServer.cs` swallowed non-`IOException` exceptions inside `Task.Run(...)` without stderr logging or structured error responses; `Test-PrivExecCrossAccount.ps1` lacked `TokenImpersonationLevel.Impersonation`; `Invoke-Gate1And2Elevated.ps1` did not persist incremental failure evidence before cleanup.
   - *Fix:* `PipeBrokerServer.cs` catches/logs all connection/auth/engine exceptions (`[PRIVEXEC_PIPE_ERROR]`) and returns structured JSON error frames; `BrokerEngine.cs` catches unexpected executor exceptions so SQLite never strands a row in `executing`; `Test-PrivExecCrossAccount.ps1` uses `TokenImpersonationLevel.Impersonation` and actionable EOF diagnostics; `Invoke-Gate1And2Elevated.ps1` writes incremental evidence from `init` through `cleanup` without masking failures.
3. **Transient test account description length limit (<= 48 characters):** Windows `New-LocalUser -Description` failed when given the 65-character tag `"PrivExec Gate 2 temporary test account ($runId)"`.
   - *Fix:* Updated tag format to `PE2:agent:<runId>` (34 chars) and `PE2:unauth:<runId>` (35 chars), strictly under 48 chars while preserving full 24-character `$runId` for ownership tracking. Validated description and username length (<= 20 chars) in `New-TransientTestUser` before execution. Enhanced cleanup in `finally` to match exact description, `PE2:*:$runId` pattern, and sweep any orphaned accounts created with this run ID. Added regression tests in C# and Python.

## Partial Gate 1–2 State Observed Before Rerun
- `C:\ProgramData\PrivExec` exists with proper ACLs and broker binary.
- No temporary accounts exist currently on the machine.
- Previous run failed cleanly in `prepare_accounts` before creating temporary directories or accounts.

## Verified Test Runs (Latest Working Tree)
- `Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 25/25 C# tests passed
- `python -m pytest -o pythonpath=. -v --basetemp=.pytest_tmp_root/tmp` (in `modules/privileged_execution`) -> 18/18 passed
- `ruff check .` -> All checks passed
- `Install-PrivExec.ps1 -Mode CrossAccountIsolated -AgentAccount ... -Json` (dry-run) -> exit 0

## Next Actionable Step
- Operator runs elevated: `pwsh -NoProfile -File .\scripts\Invoke-Gate1And2Elevated.ps1 -CreateTempTestAccounts` and supplies `C:\ProgramData\PrivExec\gate1-2-evidence.json`.
