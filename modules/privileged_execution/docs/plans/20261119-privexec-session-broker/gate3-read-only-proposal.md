# PrivExec Gate 3 Proposal — Read-Only H4 Preflight (`h4.preflight`)

**Status:** **PROPOSAL ONLY — NOT YET AUTHORIZED FOR EXECUTION**  
**Source Branch / Commit:** `feat/privexec-session-broker-20261119` (`288ee8a3`+)  
**Target VM:** `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`)  
**Protected Checkpoint:** `9f45b469-382c-4be0-a50e-7a71384c7922`  
**Expected Guest Host:** `DESKTOP-1ITSJV0`

---

## 1. Exact Capability and Target

- **Capability:** `h4.preflight` (`descriptors/h4.preflight.json`, `supports_dry_run: true`, `supports_apply: false`, `is_mutating: false`)
- **Mode:** `dry_run` (only supported mode)
- **Target:** `type: "hyperv_vm"`, `id: "d8483f98-8884-4758-abd1-cd6107c83c03"` (`RC-H4-Windows-Acceptance`)
- **Parameters:** `{"vm_name": "RC-H4-Windows-Acceptance", "expected_guest_host": "DESKTOP-1ITSJV0"}`

## 2. Exact Proposed Execution Sequence

1. **Operator pre-check (read-only, elevated PowerShell 7):**
   Verify the VM and protected checkpoint exist before starting the broker:
   ```powershell
   Get-VM -Id d8483f98-8884-4758-abd1-cd6107c83c03 | Select-Object Id, Name, State
   Get-VMSnapshot -VMName RC-H4-Windows-Acceptance | Where-Object { $_.Id -eq '9f45b469-382c-4be0-a50e-7a71384c7922' } | Select-Object Id, Name, CreationTime
   ```
2. **Operator binds staged ACLs to the designated non-admin agent account and starts a read-only broker session** (prompting interactively for guest credential via `-g`, with `allow_mutation: false`, `allowed_capabilities: ["h4.preflight"]`, `allowed_targets: ["d8483f98-8884-4758-abd1-cd6107c83c03"]`, short TTL e.g. `ttl_seconds: 300`):
   ```powershell
   privexec broker start -c C:\ProgramData\PrivExec\gate3-preflight-grant.json `
       -b C:\ProgramData\PrivExec\bin\PrivExecBroker.dll `
       -d C:\ProgramData\PrivExec\descriptors -s C:\ProgramData\PrivExec\state -g
   ```
3. **Authorized non-admin agent executes `h4.preflight`:**
   ```powershell
   privexec run h4.preflight -t d8483f98-8884-4758-abd1-cd6107c83c03 -T hyperv_vm -m dry_run `
       -p '{"vm_name":"RC-H4-Windows-Acceptance","expected_guest_host":"DESKTOP-1ITSJV0"}'
   privexec result <operation_id> -f json
   ```
4. **Operator stops the broker session** (`privexec broker stop` or `Ctrl+C`).

## 3. Required Account, Elevation, and Authentication

- **Broker / Operator account:** `XERES\mcarls` in an elevated Administrator PowerShell 7 session (required for Hyper-V WMI/PowerShell Direct access).
- **Agent account:** Dedicated standard-user account (e.g. `XERES\CodexSandboxOffline`) authenticated over the named pipe via `TokenImpersonationLevel.Impersonation` (`RunAsClient`).
- **Guest authentication:** Operator supplies guest local administrator credentials interactively at broker startup (`-g` / `--prompt-guest-credential`). Held only in `OperatorMemoryCredentialProvider` (`SecureString`), passed to `Invoke-H4PreflightAdapter.ps1` over redirected stdin, and never logged or written to disk.

## 4. Expected Read-Only Operations & 5. Non-Mutating Classification

| Step | Component | Classification | Details & Why Non-Mutating |
|---|---|---|---|
| 1 | `PrivExecBroker` (`ProcessExecutor.cs`) | Pure host-side inspection + local broker evidence write | Verifies SHA-256 and absence of reparse points on `pwsh.exe`, `Invoke-H4PreflightAdapter.ps1`, and `C:\ProgramData\PrivExec\work`. Passes guest credential on stdin. Writes broker sanitized output to `C:\ProgramData\PrivExec\state\evidence\<operation_id>\sanitized-result.json`. |
| 2 | `Invoke-H4PreflightAdapter.ps1` | Pure host-side inspection | Reads stdin credential into memory, verifies SHA-256 (`b636da4e...`) and reparse points on `C:\ProgramData\PrivExec\h4_scripts\Invoke-H4GuestQualification.ps1`, invokes it with `-Stage Preflight -Json:$true` and **never** passes `-Apply` or `-AuthorizeGuestMutation`. |
| 3 | `Invoke-H4GuestQualification.ps1` (`-Stage Preflight`, `$Apply=$false`) | Pure host-side inspection | Calls `Get-VM -Id d8483f98-8884-4758-abd1-cd6107c83c03`, asserts `Name -eq 'RC-H4-Windows-Acceptance'`, hashes `C:\H4-VM-Staging\...` assets (`BundleZip`, `Bootstrap-H4GuestBundle.ps1`, `PythonInstaller`, `PwshInstaller`, `WheelsManifest`). Because `$isMutatingMode` is `$false`, **skips** `New-Item $hostEvidenceDir` and `Save-H4JsonArtifact` is a no-op (zero host H4 writes). |
| 4 | `Invoke-H4GuestQualification.ps1` (`Assert-H4GuestIdentity`) | Guest-side read-only command | Opens PowerShell Direct (`New-PSSession -VMId`) and runs `Invoke-Command` querying `Win32_ComputerSystem`, `Win32_OperatingSystem`, `WindowsIdentity`/`WindowsPrincipal`, `Get-ScheduledTask`, `Get-Service`, and `Win32_Process`. Closes session in `finally`. **Zero guest filesystem, registry, task, or service writes.** |

## 6. Preconditions and Environmental Checks

- `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) must already be in `Running` state (Preflight will **not** start a stopped VM; it throws if `State -ne 'Running'`).
- Host staging assets under `C:\H4-VM-Staging\` (`bundle-rc1-v10\h4-windows-acceptance.zip`, `guest-deps\wheels-sha256.txt`, wheels, Python 3.12.10, PowerShell 7.6.10 MSI) must be present and match expected SHA-256 digests, or `Preflight` fails closed before opening PowerShell Direct.
- `C:\ProgramData\PrivExec` must be installed and reconciled to the designated non-admin agent account via `Install-PrivExec.ps1 -Apply -Mode CrossAccountIsolated`.

## 7. Protected Checkpoint Verification

- **Gap identified in `Invoke-H4GuestQualification.ps1`:** During `-Stage Preflight`, `Invoke-H4GuestQualification.ps1` calls `Get-H4HostVm` (`Get-VM`) but does **not** call `Get-H4HostCheckpoints` (`Get-VMSnapshot`).
- **Mitigation:** Operator runs the read-only `Get-VMSnapshot` pre-check in Section 2 before launching the Gate 3 broker session to confirm checkpoint `9f45b469-382c-4be0-a50e-7a71384c7922` is intact.

## 8. Credential Requirements and Protection

- Guest credentials are supplied only by the operator at `privexec broker start -g` (`SecureString` prompt), never passed in `privexec run` arguments, never stored in `privexec.db`, and redacted by `OutputSanitizer`.

## 9. Expected Output and Evidence

- `privexec run h4.preflight` returns JSON with `state: "succeeded"`, `exit_code: 0`, `result.stage_results.Preflight == "PASS"`, `result.apply_requested == false`, `result.guest_authorized == false`, `result.guest_os` populated, and `evidence` pointing to `C:\ProgramData\PrivExec\state\evidence\<operation_id>\sanitized-result.json`.

## 10. Fail-Closed Conditions

- VM ID/name mismatch or VM not `Running`.
- Any SHA-256 mismatch or reparse point on adapter, H4 scripts, or staging assets.
- Missing guest credential (`missing_guest_credential`).
- Guest hostname != `DESKTOP-1ITSJV0` (or `== 'XERES'`), non-Hyper-V hardware, non-Windows 11 OS, non-admin guest user, or any pre-existing `ResourceCoordinator`/`KRig` task, service, or process.
- Any attempt to pass `apply` mode (`supports_apply: false` -> `mode_not_allowed`).

## 11. Abort and Cleanup Procedure

- `privexec broker stop` (or `Ctrl+C` in the elevated broker console) immediately revokes the in-memory `SessionGrant`, cancels active execution, and exits.
- Delete temporary `gate3-preflight-grant.json` if not retained.
- No guest artifacts or host H4 directories are created by `h4.preflight`, so no VM/checkpoint rollback is required.

## 12. Explicitly Excluded Mutations

- **Excluded:** `h4.qualify` (`Setup`, `Checkpoint`, `Acceptance`, `All`), `h4.recover`, `Start-VM`, `Stop-VM`, `Checkpoint-VM`, `Restore-VMSnapshot`, `Remove-VMSnapshot`, `Copy-Item -ToSession`, guest installer/task/service modifications, and permanent user creation.

## 13. Acceptance Criteria

1. `h4.preflight` executes in `dry_run` mode via the non-admin agent CLI and succeeds (`state == "succeeded"`, `exit_code == 0`).
2. Broker evidence confirms `apply_requested == false`, `guest_authorized == false`, and `stage_results.Preflight == "PASS"`.
3. Zero credentials appear in `privexec.db`, stdout/stderr, or `sanitized-result.json`.
4. Protected checkpoint `9f45b469-382c-4be0-a50e-7a71384c7922` and VM state remain untouched.

## 14. Required Operator Authorization

Gate 3 requires explicit operator approval authorizing:
1. Binding `C:\ProgramData\PrivExec` ACLs to the chosen non-admin agent identity (if testing with a permanent sandbox account).
2. Running the read-only `Get-VM` / `Get-VMSnapshot` pre-check and starting a `h4.preflight`-only broker session with interactive guest credential entry.
3. Executing **one** read-only `h4.preflight` (`dry_run`) operation against `RC-H4-Windows-Acceptance`.
