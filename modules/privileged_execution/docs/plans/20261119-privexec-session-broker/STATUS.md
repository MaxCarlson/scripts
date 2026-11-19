# Status — `20261119-privexec-session-broker`

- **Current Phase:** Phases 0, 1, 2, and 3 implementation complete; awaiting authorized Windows elevation & live H4 validation
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Completed Work
- **Phase 0 (`805db2c9`):** Master plan, Phase 0 contract/architecture, and module docs.
- **Phase 1 (`37867b47`):** Python `privexec` CLI + C# `.NET 10` `PrivExecBroker` + Win32 named-pipe transport + authorization.
- **Phase 2 (`ceabcb19`):** `SqliteOperationStore` (`winsqlite3.dll`), `ProcessCapabilityExecutor`, `OutputSanitizer`, concurrent `PipeBrokerServer`, and adversarial tests.
- **Phase 3:**
  - `OperatorMemoryCredentialProvider` (`CredentialProvider.cs`) holding guest `SecureString` in broker memory with transient stdin JSON handoff and immediate BSTR zeroing.
  - H4 PowerShell 7 adapters (`adapters/Invoke-H4PreflightAdapter.ps1`, `Invoke-H4QualifyAdapter.ps1`, `Invoke-H4RecoverAdapter.ps1`, `adapters/README.md`) and pinned descriptors (`descriptors/h4.preflight.json`, `h4.qualify.json`, `h4.recover.json`).
  - Dry-run-by-default staged installer/uninstaller (`scripts/Install-PrivExec.ps1`, `scripts/Uninstall-PrivExec.ps1`) and Windows validation guide (`docs/WINDOWS_VALIDATION.md`).
  - `modules/scripts_help/scripts_help/registry/registry.py` registration + `README.md`.

## Verified Test Runs
- `pwsh -NoProfile -NonInteractive -File scripts/Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 10/10 Phase 1 + 7/7 Phase 2 + 3/3 Phase 3 = 20/20 C# tests passed
- `python -m pytest -v` (in `modules/privileged_execution`) -> 13/13 passed
- `python -m ruff check privexec tests` -> All checks passed
- `python -m pytest tests/scripts_help_test.py --basetemp=...\scripts_help_tmp -v` -> 42/42 passed

## Known Failures / Limitations
- No `.NET SDK` installed on host (`C:\Program Files\dotnet\sdk` absent); `Build-PrivExecBroker.ps1` compiles with VS2022 Roslyn `csc.exe` against `.NET 10.0.15` runtime assemblies.
- `modules/resource_coordinator/**` on `main` does not yet contain `Invoke-H4GuestQualification.ps1` / `Invoke-H4GuestRecovery.ps1` (those currently reside on `fix/rc-h4-task-discovery-20261115` `ea6ad23f`).

## Pending Privilege-Dependent Validation
- Cross-account Windows ACL & named-pipe isolation testing with separate operator and non-administrator agent accounts (`docs/WINDOWS_VALIDATION.md`).
- Elevated `Install-PrivExec.ps1 -Apply` staging into `C:\ProgramData\PrivExec`.
- Live Hyper-V `RC-H4-Windows-Acceptance` qualification/recovery execution (requires separate explicit operator authorization).

## Next Actionable Step
- Review `docs/WINDOWS_VALIDATION.md`, grant explicit authorization for elevated staging and two-account Windows security testing, then stage H4 scripts from the approved Resource Coordinator branch and run `privexec run h4.preflight`.
