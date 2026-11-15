# `vm_lab` (`vm-lab`)

Disposable Windows Hyper-V lab management module for development, testing, and acceptance environments.

## Operations

| Operation | Purpose | Default behavior |
|---|---|---|
| `list` | Inspect all VMs or `-OwnedOnly` lab-owned VMs | Read-only |
| `status` | Detailed VM configuration, ownership, and health | Read-only |
| `plan` | Validate a proposed VM configuration against host capacity | Read-only |
| `create` | Provision a new lab VM (`Dynamic` or `Fixed` VHDX) and record atomic ownership manifest | Dry-run (`-Apply` / `-a` required) |
| `start` | Start an explicitly selected lab-owned VM after host RAM reserve check | Dry-run (`-Apply` / `-a` required) |
| `stop` | Request graceful guest shutdown (no `-Force` / `-TurnOff`) with bounded wait | Dry-run (`-Apply` / `-a` required) |
| `checkpoint` | Create a named checkpoint on a lab-owned VM and verify its ID | Dry-run (`-Apply` / `-a` required) |
| `checkpoints` | List existing checkpoints for a VM | Read-only |

## CLI Flags (`Invoke-VmLab.ps1` / `vm-lab`)

- `-Operation` / `-o`: Operation name (`list`, `status`, `plan`, `create`, `start`, `stop`, `checkpoint`, `checkpoints`)
- `-Name` / `-n`: VM name
- `-ConfigPath` / `-c`: Path to a declarative JSON VM config
- `-TemplateName` / `-t`: Built-in template name (default: `windows11-h4`)
- `-IsoPath` / `-i`: Installation ISO path override
- `-VmRoot` / `-r`: VM root directory override
- `-SwitchName` / `-s`: Existing Hyper-V virtual switch name override
- `-CheckpointName` / `-m`: Checkpoint name for `checkpoint`
- `-Apply` / `-a`: Authorize mutation
- `-Json` / `-j`: Emit a single valid JSON document on stdout (errors go to stderr with exit code `1`)
- `-OwnedOnly` / `-oo`: Filter `list` to lab-owned VMs
- `-MinReserveBytes` / `-rb`: Minimum free host RAM reserve required before `start` (default: `4GB`)
- `-ShutdownTimeoutSeconds` / `-st`: Bounded wait timeout in seconds for `stop` (default: `30`)
- `-ManifestRoot` / `-mr`: Override directory for ownership manifests
- `-WhatIf`: Dry-run safeguard (prevents all mutations even when combined with `-Apply`)

## Ownership & Safety Model

- **Strict Ownership Predicate**: Every VM created by `vm_lab` gets an atomic JSON manifest (`<VmName>.json` under `$env:LOCALAPPDATA\vm_lab\manifests` or `-ManifestRoot`). Ownership checks verify `schema_version`, `vm_name`, `vm_id`, and a path-boundary-aware `vm_config_path` relationship (exact match or strict descendant on the same volume, rejecting sibling prefix collisions like `C:\Lab\VM` vs `C:\Lab\VM2`, reparse points/symlinks, missing/corrupt manifests, and unmanaged VMs).
- **Atomic & Concurrent Provisioning Safety**: `create` acquires an exclusive `<VmName>.lock` file in `ManifestRoot`, re-runs preflight checks immediately before `New-VHD`/`New-VM`, and writes the manifest via exclusive temp file + non-overwriting `File.Move(..., $false)`. Partial VM/VHDX artifacts are preserved on failure for inspection rather than silently deleted.
- **Lifecycle Safeguards**:
  - `create` implements both `Dynamic` and `Fixed` VHDX formats via `New-VHD` and verifies the resulting VM before writing the manifest.
  - `start` checks host RAM reserve both during planning and immediately before `Start-VM`, handles `Running` idempotently (`already_running`), rejects transitional states, and re-verifies VM identity before mutation.
  - `stop` uses graceful guest shutdown only (never `-Force` or `-TurnOff`), handles `Off` idempotently (`already_stopped`), and returns `shutdown_requested` if the bounded wait times out before reaching `Off`.
  - `checkpoint` rejects `Disabled` checkpoint policies, transitional states, and duplicate names, and verifies the created snapshot ID and timestamp.

## Toolkit Integration & Invocation

- Direct PowerShell invocation:
  ```pwsh
  pwsh -NoProfile -File ./modules/vm_lab/Invoke-VmLab.ps1 -o list -j
  ```
- Clean module import:
  ```pwsh
  Import-Module ./modules/vm_lab/vm_lab.psd1 -Force
  vm-lab -o status -n MyLabVM -j
  ```
- **Scripts Toolkit Integration**: `scripts_setup/launcher_generator.py` discovers `modules/vm_lab/Invoke-VmLab.ps1` as `vm-lab` (`kind: "powershell_script"`), `modules/script_logging/script_logging/launcher.py` executes `powershell_script` targets via `pwsh -NoProfile -File` while recording invocation history, and `modules/scripts_help/scripts_help/registry/registry.py` registers `vm_lab (module)`.

## Known Limitations & Deferred Features

- **Known limitations**: Real Hyper-V execution requires an elevated Administrator or `Hyper-V Administrators` session; unit tests validate behavior against mocked Hyper-V cmdlets. Real end-to-end Hyper-V lifecycle acceptance remains pending until a separately authorized disposable test environment is available.
- **H4 compatibility boundary**: `RC-H4-Windows-Acceptance` (provisioned by `Provision-H4TestVM.ps1`) is visible in read-only `list`/`status` but is not implicitly owned and is rejected by mutating operations.
- **Deliberately deferred**: VM deletion (`Remove-VM`), checkpoint deletion, VHDX destruction, forced/hard shutdown, VM cloning, and VM export.
