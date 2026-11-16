# `vm_lab` (`vm-lab`)

Disposable Windows Hyper-V lab management module for development, testing, and acceptance environments.

## Operations

| Operation | Purpose | Default behavior |
|---|---|---|
| `list` | Inspect all VMs or `-OwnedOnly` lab-owned VMs | Read-only |
| `status` | Detailed VM configuration, ownership, and health | Read-only |
| `templates` | List built-in VM templates and resource profiles | Read-only |
| `template-info` | Validate and inspect a specific template | Read-only |
| `plan` | Validate a proposed VM configuration against host capacity | Read-only |
| `quickstart` | End-to-end VM plan/create (+ optional `-Start` / `-Connect`) | Dry-run (`-Apply` / `-a` required) |
| `wizard` | Interactive guided VM setup assistant | Interactive (`-WhatIf` / confirm) |
| `create` | Provision a new lab VM (`Dynamic` or `Fixed` VHDX) with atomic manifest | Dry-run (`-Apply` / `-a` required) |
| `start` | Start an explicitly selected lab-owned VM after host RAM reserve check | Dry-run (`-Apply` / `-a` required) |
| `stop` | Request graceful guest shutdown (no `-Force` / `-TurnOff`) with bounded wait | Dry-run (`-Apply` / `-a` required) |
| `connect` | Open VMConnect in the interactive desktop session | Interactive UI launch |
| `start-connect` | Start an owned VM and open VMConnect | Dry-run (`-Apply` / `-a` required) |
| `boot-diagnostics` | Inspect DVD ISO attachment, Secure Boot, and UEFI DVD boot order | Read-only |
| `guest-status` | Inspect Hyper-V Heartbeat, PowerShell Direct, and bootstrap state | Read-only |
| `guest-copy` | SHA-256 verified file transfer (`ToGuest` / `FromGuest`) via PS Direct | Dry-run (`-Apply` / `-a` required) |
| `guest-bootstrap` | Run generic guest profile (`windows-minimal`, `python-dev`, `powershell-dev`) | Dry-run (`-Apply` / `-a` required) |
| `guest-verify` | Verify guest bootstrap state and installed runtime via PS Direct | Read-only |
| `checkpoint` | Create a named checkpoint on a lab-owned VM and verify its ID | Dry-run (`-Apply` / `-a` required) |
| `baseline` | Capture the first verified clean guest checkpoint (default: `clean-baseline`) | Dry-run (`-Apply` / `-a` required) |
| `checkpoints` | List existing checkpoints for a VM | Read-only |
| `recovery-plan` / `doctor` | Non-destructive diagnostics for partial provisioning, locks, and guest state | Read-only |
| `unattend-xml` | Generate bounded `Autounattend.xml` (no passwords; stops at OOBE account) | Dry-run (`-Apply` / `-a` required) |

## End-to-End Workflows

### Scenario A — Create a Windows development VM

1. **Discover templates**:
   ```powershell
   vm-lab -o templates
   vm-lab -o template-info -t windows11-dev
   ```
2. **Preview resources (dry-run)**:
   ```powershell
   vm-lab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -i C:\ISOs\Win11.iso
   ```
3. **Create the VM**:
   ```powershell
   vm-lab -o quickstart -t windows11-dev -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01 -i C:\ISOs\Win11.iso -Apply
   ```
   *(Or use `vm-lab -o wizard` for an interactive guided setup.)*
4. **Start and open VMConnect**:
   ```powershell
   vm-lab -o start-connect -n Dev-Win11-01 -Apply
   ```
   > **UEFI DVD Boot Note**: If you see `SCSI DVD (0,1): The boot loader failed.`, the *"Press any key to boot from CD or DVD..."* prompt timed out. Run `vm-lab -o boot-diagnostics -n Dev-Win11-01`, perform a controlled `stop`/`start` while VMConnect is open, and press a key immediately when prompted. Do **not** disable Secure Boot.
5. **Install Windows and create a local guest account** in VMConnect.
6. **Verify PowerShell Direct & guest readiness**:
   ```powershell
   vm-lab -o guest-status -n Dev-Win11-01 -PromptCredential
   ```
7. **Bootstrap guest developer tooling & capture clean baseline**:
   ```powershell
   vm-lab -o guest-bootstrap -n Dev-Win11-01 -GuestProfile windows-minimal -PromptCredential -Apply
   vm-lab -o guest-verify -n Dev-Win11-01 -GuestProfile windows-minimal -PromptCredential
   vm-lab -o baseline -n Dev-Win11-01 -Apply
   ```

### Scenario B — Reconnect to an existing VM

```powershell
vm-lab -o list -OwnedOnly
vm-lab -o status -n Dev-Win11-01
vm-lab -o start -n Dev-Win11-01 -Apply
vm-lab -o connect -n Dev-Win11-01
vm-lab -o guest-status -n Dev-Win11-01 -PromptCredential
```

### Scenario C — Recover interrupted setup

```powershell
# Host-wide stale lock check
vm-lab -o doctor

# VM-specific partial-artifact and state diagnostics (read-only)
vm-lab -o recovery-plan -n Dev-Win11-01 -r C:\VMs\Dev-Win11-01
```
Inspect any reported `.lock` files or preserved VHDX/config directories before resuming with `quickstart`, `start`, or `guest-bootstrap`.

## Ownership, Credential & Safety Model

- **Strict Ownership Predicate**: Every VM created by `vm_lab` gets an atomic JSON manifest (`<VmName>.json` under `$env:LOCALAPPDATA\vm_lab\manifests` or `-ManifestRoot`). Ownership checks verify `schema_version`, `vm_name`, `vm_id`, and a path-boundary-aware `vm_config_path` relationship (rejecting sibling prefix collisions, cross-volume paths, reparse points/symlinks, missing/corrupt manifests, and unmanaged VMs).
- **Credential Safety**: PowerShell Direct operations (`guest-status`, `guest-copy`, `guest-bootstrap`, `guest-verify`) accept `-Credential` or `-PromptCredential`, never log or persist passwords, and always close sessions in `finally` blocks.
- **Toolkit Integration**: `scripts_setup/launcher_generator.py` discovers `modules/vm_lab/Invoke-VmLab.ps1` as `vm-lab` (`kind: "powershell_script"`), `modules/script_logging/script_logging/launcher.py` executes it via `pwsh -NoProfile -File` with invocation history, and `modules/scripts_help/scripts_help/registry/registry.py` registers `vm_lab (module)`.

## Workflow Automation, Guest Execution & Bounded Elevation

`vm_lab` supports declarative, resumable host-and-guest automation via `Invoke-VmLab.ps1`:

- **Generic Guest Operations**: `guest-command-plan`, `guest-exec` (allowlisted env, stdout/stderr/exit capture, optional JSON result validation, `REBOOT_REQUIRED` on exit `3010`), `artifact-plan`, `artifact-deploy` (pinned SHA-256 staging + optional immutable ZIP extraction), `evidence-plan`, and `evidence-collect` (recursive download with per-file manifests and `INCOMPLETE` failure state).
- **Transactional Lifecycle**: `lifecycle-transaction` closes active PS Direct sessions, gracefully stops the VM with bounded polling, enforces `Standard` checkpoints, and optionally restarts and waits for PowerShell Direct readiness.
- **Durable Workflows**: `workflow-plan`, `workflow-apply`, `workflow-status`, `workflow-resume`, and `workflow-doctor` maintain an atomic operation journal (`journal.json`), stage receipts, and single-owner operation locks across host restarts. See [examples/h4-like-acceptance.workflow.json](examples/h4-like-acceptance.workflow.json).
- **Bounded Elevated Runner**: `New-VmLabApprovedPlanRequest` writes a SHA-256-sealed, expiring, capability-bounded plan request; an operator executes it in an elevated console via `Invoke-VmLabApprovedPlan.ps1 -RequestPath <path> -ExpectedRequestDigest <sha256> -AuthorizeElevation`, which enforces single-use replay protection and records an execution receipt.
- **Windows Setup Assistance**: `New-VmLabAnswerMediaStaging`, `Get-VmLabSetupProgressReport`, and `Test-VmLabPreparedImagePolicy` provide password-free offline OOBE answer media, VMConnect boot guidance, and Sysprep policy checks.
- **Live Operational Acceptance**: End-to-end Hyper-V qualification against a disposable VM is **not** executed automatically during source validation; it requires separate explicit elevated authorization against a non-protected VM.

## Known Limitations & Deferred Features

- **Known limitations**: Real Hyper-V execution requires an elevated Administrator or `Hyper-V Administrators` session; current tests validate behavior against mocked Hyper-V and PowerShell Direct cmdlets. Real end-to-end Hyper-V lifecycle acceptance remains pending until a separately authorized disposable test environment is available.
- **H4 compatibility boundary**: `RC-H4-Windows-Acceptance` (provisioned by `Provision-H4TestVM.ps1`) is visible in read-only `list`/`status` but is not implicitly owned and is rejected by mutating operations.
- **Deliberately deferred**: VM deletion (`Remove-VM`), checkpoint deletion, automatic checkpoint rollback, VHDX destruction, forced/hard shutdown, and VM cloning/export.
