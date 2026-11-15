# vm_lab Integration Review & Qualification Status

- **Date**: 2026-11-15
- **Hardening Branch**: `agent/vm-lab-hardening-20261115` (`6ea40581`)
- **Integration Review Branch**: `integration/vm-lab-review-20261115` (reconciled with `origin/main`)
- **Protected Concurrent VM**: `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) — untouched.

## Implemented Hardening (Stages A–D)

1. **Guest Bootstrap (`modules/vm_lab/src/Bootstrap.ps1`)**:
   - `python-dev`: Enforces Python `>= 3.12` (64-bit), rejects `WindowsApps` execution alias stubs, refreshes `PATH` and standard install roots after installer execution, requires explicit `-RequirementsPath` or `-Packages` with either `-WheelhousePath` (offline) or `-AllowOnlineInstall` (online), refuses `--upgrade pip`-only wheelhouse fallback, and verifies installed packages via `pip list --format=json` using PEP 503 normalized names.
   - `powershell-dev`: Enforces `.msi` installer extension, optional SHA-256 verification (`-ExpectedInstallerSha256`), handles `msiexec` exit code `3010` as `reboot_required` (`completed = $false`) without auto-rebooting, and probes `pwsh.exe >= 7.0`.
   - State persistence: Atomic temp-file write + replace (`schema_version = 2`) with per-profile `profiles` map and legacy v1 read support.
   - `Test-VmLabGuestVerify`: Conditionally returns `verified`, `incomplete`, or `failed` based on marker validity, completion state, reboot-required state, runtime version, and expected packages. `Invoke-VmLab.ps1` exits `1` when `guest-verify` status is not `verified`.
2. **PowerShell Direct & File Transfer (`modules/vm_lab/src/Guest.ps1`)**:
   - Bounded transient connection retries (`-MaxConnectAttempts`, `-RetryDelayMs`), explicit `PSSessionOption` open/operation timeouts, auth-vs-connectivity error separation (never retries auth failures), and guaranteed `Remove-VmLabPSSession` cleanup.
   - `Copy-VmLabGuestItem`: Re-verifies VM identity/Running state, rejects relative/UNC/`..` guest paths and reparse-point targets, checks local source hash stability, stages via `.vm_lab_tmp` with SHA-256 verification before atomic `File.Move`, and cleans up temp files on failure.
3. **Workflow & Reporting Fixes (`Provisioning.ps1`, `Checkpoints.ps1`, `Recovery.ps1`, `Output.ps1`)**:
   - `Invoke-VmLabQuickstart`: Reports `actual` vs `requested` configuration and `configuration_drift` / `drift_details` for existing owned VMs.
   - `New-VmLabUnattendXml`: Explicitly notes that generating XML does not attach it to media or execute Windows Setup.
   - `New-VmLabBaselineCheckpoint`: Reports `guest_verified` and `baseline_qualified`, and supports `-RequireGuestVerified`.
   - `Get-VmLabRecoveryPlan`: Reports lock timestamp/uncertainty (`may be active or stale`) rather than assuming locks are stale.

## Verified Checks (on `integration/vm-lab-review-20261115`)

- **Pester (`modules/vm_lab/tests/vm_lab.Tests.ps1`)**: `28 Passed, 0 Failed, 0 Skipped` (includes real non-mocked bootstrap/verify logic against fake guest directories/shims, file-transfer hardening, quickstart drift, baseline qualification, and isolated `pwsh` CLI exit-code checks).
- **Python Toolkit (`modules/script_logging/tests`, `modules/scripts_help/tests`)**: `147 passed in 77.26s`.
- **Isolated CLI (`Invoke-VmLab.ps1 -o templates -j`)**: Exited `0`, returned valid JSON for all 4 built-in templates.

## Real Hyper-V Qualification Boundary

- Host session is unprivileged (no Hyper-V Administrators rights); live Hyper-V VM lifecycle execution was **not** run in this session.
- Gated operational smoke harness added at `modules/vm_lab/tests/Invoke-VmLabOperationalSmoke.ps1` (requires `-AuthorizeDisposableTest` and explicit disposable `-VmName`, and explicitly refuses `RC-H4-Windows-Acceptance` and pre-existing VMs).
