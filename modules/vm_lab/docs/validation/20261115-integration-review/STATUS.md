# vm_lab Integration Review, Source Corrections & Qualification Status

- **Date**: 2026-11-15
- **Feature Branch (preserved)**: `agent/vm-lab-hardening-20261115` (`6ea4058192fa7ff1a1f51f7b541225147fe19c90`)
- **Integration Review Branch**: `integration/vm-lab-review-20261115`
- **Mainline Baseline**: `origin/main` (`df57dd69`, 0 commits behind `origin/main`)
- **Protected Concurrent VM**: `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) — untouched.

## 1. Defects Fixed in This Pass

1. **Protected-VM Inventory Filtering & Identity Revalidation (`modules/vm_lab/tests/Invoke-VmLabOperationalSmoke.ps1`)**:
   - Fixed the inventory filter bug where the mere presence of `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) aborted tests for unrelated disposable VMs.
   - `Assert-VmLabSmokeTargetSafe` now filters to the requested target, rejects protected names/IDs (including renamed H4), rejects unmanaged VMs and manifest/Hyper-V ID mismatches, and revalidates target identity immediately before every mutating step.
2. **Resumable Staged Operational Acceptance (`Invoke-VmLabOperationalSmoke.ps1`)**:
   - Replaced single-shot `status = 'completed'` with explicit resumable phases (`preflight`, `provision`, `guest`, `finalize`, `full`), persistent `acceptance-state.json`, per-phase authorization (`-AuthorizeDisposableTest`, `-AuthorizeProvision`, `-AuthorizeGuest`, `-AuthorizeFinalize`, `-AuthorizeShutdown`), and evidence-based statuses (`preflight_passed`, `provisioned`, `awaiting_windows_installation`, `awaiting_guest_credentials`, `guest_ready`, `acceptance_passed`, `acceptance_failed`, `partial`, `blocked`) with matching exit codes.
3. **Python Dependency Version & Compatibility Verification (`modules/vm_lab/src/Bootstrap.ps1`)**:
   - Added `Get-VmLabRequirementSpecs` (supports PEP 508 specs, comments, line continuations, recursive `-r/--requirement` with cycle detection; explicitly rejects `-c/--constraint`, `-e/--editable`, `--hash`, direct URL/VCS/archive refs, and unknown pip flags).
   - Added `Test-VmLabPythonDependencies` (preserves `expected_specs`, evaluates version constraints and environment markers via `packaging.requirements.Requirement` / `pip._vendor.packaging.requirements.Requirement`, runs `python -m pip check` for dependency graph compatibility, and fails on missing `pip` or malformed JSON).
4. **Whitespace & Provenance Hygiene (`modules/script_logging/tests/test_launcher.py`)**:
   - Removed trailing blank line flagged by `git diff --check`.

## 2. Source & Integration Review Against `origin/main`

- **Non-`vm_lab` delta**:
  - `modules/resource_coordinator/`: Contains 2 prior H4 commits (`a7961811`, `0a55287d`) from the `fix/rc-h4-task-discovery-20261115` base commit; untouched in this pass.
  - `scripts_setup/launcher_generator.py`: `scan_repository_programs` discovers `vm-lab` (`kind='powershell_script'`, `target='modules/vm_lab/Invoke-VmLab.ps1'`).
  - `modules/script_logging/script_logging/launcher.py`: Supports `powershell_script` execution via `pwsh -NoProfile -File` and logs to SQLite.
  - `modules/scripts_help/scripts_help/registry/registry.py`: Registers `vm_lab (module)`.
- **Worktree Import Provenance**: Host environment has an editable `script_logging` hook pointing to main; `run_pytest.py` stripped editable finders and verified `script_logging` and `scripts_help` imported directly from `integration/vm-lab-review-20261115`.

## 3. Executed Verification & Evidence

| Check | Command / Scope | Result | Exit Code | Coverage Type |
| --- | --- | --- | --- | --- |
| PowerShell AST & Import | `Parser::ParseFile` on all `modules/vm_lab/**/*.ps*1` + `Import-Module vm_lab.psd1` | `AST_AND_IMPORT_OK` | `0` | Real |
| Full `vm_lab` Pester Suite | `Invoke-Pester -Script @('vm_lab.Tests.ps1', 'Invoke-VmLabOperationalSmoke.Tests.ps1') -PassThru` | **34 Passed, 0 Failed, 0 Skipped** (42.63s) | `0` | Real Bootstrap/Config/Manifest/Smoke logic + Mocked Hyper-V/PS-Direct boundaries |
| Python Toolkit Suite | `modules/script_logging/tests` + `modules/scripts_help/tests` via `run_pytest.py` | **147 Passed, 0 Failed** (60.92s) | `0` | Real |
| Isolated CLI Templates | `pwsh -NoProfile -File Invoke-VmLab.ps1 -o templates -j` | Valid JSON for 4 templates | `0` | Real |
| Launcher & Help Discovery | `REGISTRY` lookup + `scan_repository_programs` + `write_wrapper` | `vm-lab` discovered & `.cmd` wrapper written | `0` | Real (isolated temp dir) |
| Real Hyper-V Lifecycle | Live VM creation/boot/PS-Direct on host | **NOT_TESTED** (unprivileged session; no Hyper-V Admin rights) | N/A | Blocked by host privileges |

## 4. Operational Acceptance Procedure (Disposable VM)

Run from an **elevated Administrator / Hyper-V Administrators** PowerShell 7 session using a fresh disposable VM name (never `RC-H4-Windows-Acceptance`):

1. **Read-only preflight** (verifies permissions, host RAM, disk, ISO, and H4 isolation):
   ```powershell
   .\modules\vm_lab\tests\Invoke-VmLabOperationalSmoke.ps1 -VmName "VM-Lab-Accept-01" -VmRoot "C:\VMs\VM-Lab-Accept-01" -TemplateName windows11-light -IsoPath "C:\ISOs\Win11.iso" -Phase preflight
   ```
2. **Provision disposable VM** (creates VM + starts + opens VMConnect; stops at `awaiting_windows_installation`):
   ```powershell
   .\modules\vm_lab\tests\Invoke-VmLabOperationalSmoke.ps1 -VmName "VM-Lab-Accept-01" -VmRoot "C:\VMs\VM-Lab-Accept-01" -TemplateName windows11-light -IsoPath "C:\ISOs\Win11.iso" -Phase provision -AuthorizeDisposableTest -Start -Connect
   ```
3. **Complete Windows installation & OOBE** in VMConnect and create the local guest account.
4. **Resume guest acceptance** (PowerShell Direct, bootstrap, verify, round-trip file transfer, qualified baseline checkpoint):
   ```powershell
   $cred = Get-Credential
   .\modules\vm_lab\tests\Invoke-VmLabOperationalSmoke.ps1 -VmName "VM-Lab-Accept-01" -VmRoot "C:\VMs\VM-Lab-Accept-01" -Phase guest -GuestProfile python-dev -Credential $cred -AuthorizeDisposableTest
   ```
5. **Finalize & optional graceful shutdown**:
   ```powershell
   .\modules\vm_lab\tests\Invoke-VmLabOperationalSmoke.ps1 -VmName "VM-Lab-Accept-01" -VmRoot "C:\VMs\VM-Lab-Accept-01" -Phase finalize -AuthorizeDisposableTest -AuthorizeShutdown
   ```
   Inspect `C:\VMs\VM-Lab-Accept-01\acceptance-state.json` for durable per-phase evidence.
