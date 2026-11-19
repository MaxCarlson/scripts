# Status — `20261119-privexec-session-broker`

- **Current Phase:** Security review, hardening, deployment readiness, and unprivileged end-to-end validation complete; pending authorized elevated/H4 acceptance gates
- **Branch:** `feat/privexec-session-broker-20261119`
- **Worktree:** `C:\Users\mcarls\src\scripts-privexec`
- **Base Commit:** `e7b9f36d5296d8b8fe301ef47e9f35adc64f886b`

## Completed Work
- **Phases 0–3:** Master plan, contract, `PrivExecBroker` (.NET 10), `privexec` CLI, SQLite ledger (`winsqlite3.dll`), process executor, H4 PowerShell 7 adapters/descriptors, dry-run installer/uninstaller, and `scripts_help` registry integration.
- **Security Review & Hardening Fixes:**
  - Enforced `allowed_h4_stages` in `SessionAuthorizer.cs` and `Program.cs` so `h4.qualify` `Acceptance` cannot run under a `Setup`-only grant.
  - Replaced `CheckIdempotency` + `InsertOperation` TOCTOU race with atomic `TryInsertOperation` (handling `SQLITE_CONSTRAINT` cleanly under concurrent requests).
  - Handled `OperationCanceledException` during execution in `BrokerEngine.HandleRunAsync` to persist `outcome_unknown` immediately on broker shutdown.
  - Added broker-side `--pipe` name regex validation in `Program.cs`.
  - Pinned `SECURITY_SQOS_PRESENT | SECURITY_IMPERSONATION` (preventing delegation) on Win32 `CreateFileW` in `privexec/transport.py`.
  - Removed inherited `PYTHONPATH`/`PYTHONHOME` in `ProcessExecutor.cs`.
  - Hardened `Build-PrivExecBroker.ps1` (stale binary cleanup) and `Install-PrivExec.ps1` (fail-closed missing H4 scripts, source reparse-point checks, post-install descriptor SHA-256 verification).
  - Expanded `docs/WINDOWS_VALIDATION.md` into the 5-Gate Operator Readiness Runbook.

## Verified Test Runs
- `pwsh -NoProfile -NonInteractive -File scripts/Build-PrivExecBroker.ps1 -IncludeTests` -> exit 0
- `dotnet broker/bin/PrivExecBroker.Tests.dll` -> 22/22 C# tests passed (10 Phase 1 + 7 Phase 2 + 5 Phase 3)
- `python -m pytest -v` (in `modules/privileged_execution`) -> 14/14 passed
- `python -m ruff check privexec tests` -> All checks passed
- `python -m pytest tests/scripts_help_test.py --basetemp=...\scripts_help_tmp -v` -> 42/42 passed

## Pending Privilege-Dependent Validation (Gates 1–4 in `docs/WINDOWS_VALIDATION.md`)
- **Gate 1:** Elevated `Install-PrivExec.ps1 -Apply` into `C:\ProgramData\PrivExec` + `icacls` verification.
- **Gate 2:** Cross-account isolation with separate privileged operator and non-administrator agent Windows accounts.
- **Gate 3:** Live read-only `h4.preflight` against `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`).
- **Gate 4:** Separately approved live H4 qualification/recovery stage runs.
