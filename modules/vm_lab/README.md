# `vm_lab` (`vm-lab`)

Disposable Windows Hyper-V lab management module for development, testing, and acceptance environments.

## Operations

| Operation | Purpose | Default behavior |
|---|---|---|
| `list` | Inspect all VMs or `-OwnedOnly` lab-owned VMs | Read-only |
| `status` | Detailed VM configuration, ownership, and health | Read-only |
| `plan` | Validate a proposed VM configuration against host capacity | Read-only |
| `create` | Provision a new lab VM and record atomic ownership manifest | Dry-run (`-Apply` / `-a` required) |
| `start` | Start an explicitly selected lab-owned VM after host RAM reserve check | Dry-run (`-Apply` / `-a` required) |
| `stop` | Request graceful guest shutdown (no `-Force` / `-TurnOff`) | Dry-run (`-Apply` / `-a` required) |
| `checkpoint` | Create a named checkpoint on a lab-owned VM | Dry-run (`-Apply` / `-a` required) |
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
- `-Json` / `-j`: Emit JSON output for automation
- `-OwnedOnly`: Filter `list` to lab-owned VMs
- `-MinReserveBytes`: Minimum free host RAM reserve required before `start` (default: `4GB`)
- `-WhatIf`: Dry-run safeguard (prevents all mutations even when combined with `-Apply`)

## Ownership & Safety Model

- Every VM created by `vm_lab` gets an atomic JSON manifest (`<VmName>.json` under `$env:LOCALAPPDATA\vm_lab\manifests` or `-ManifestRoot`) recording `vm_name`, `vm_id`, `created_at`, `vm_config_path`, `vhdx_path`, `template_id`, `owner_namespace`, and `operation_id`.
- Ownership checks verify both `vm_id` and configuration path against the live VM. Name prefixes alone never grant ownership, and unmanaged VMs are never silently adopted or modified.
- `start` checks free host RAM against `MemoryStartup + MinReserveBytes` both during planning and immediately before `Start-VM`.

## Known Limitations & Deferred Features

- **Known limitations**: Real Hyper-V execution requires an elevated Administrator or `Hyper-V Administrators` session; unit tests validate behavior against mocked Hyper-V cmdlets.
- **Deliberately deferred**: VM deletion (`Remove-VM`), checkpoint deletion, VHDX destruction, forced/hard shutdown, VM cloning, and VM export.
