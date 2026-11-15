# H4 Disposable Environment Decision

Date: 2026-11-14 (Pacific)
Source baseline: RC `1.0.0`, `main` `0f983428c2a5e0ae02517f94dec6a38b1a4cec4b`

## Decision

No suitable disposable Windows guest is available on the current host. Do not create or start one here under this assignment. Use a separately authorized, idle Windows test host with a dedicated Hyper-V VM and checkpoint support for the actual installation, Scheduled Task, reboot, interruption, and rollback matrix. A restrictive Windows Sandbox is a second choice for limited task/helper tests, but its ephemeral lifecycle is a poor fit for repeatable service upgrade and rollback across guest restarts.

## Read-only host inventory

The preflight was run in the current Windows user context on 2026-11-14. It found Windows 11 Pro build `26300`, an enabled Hyper-V feature set, a present hypervisor, enabled WSL/VirtualMachinePlatform, and running Hyper-V compute/management, WSL, and Docker services. Windows Sandbox (`Containers-DisposableClientVM`) is disabled. `Get-VM -ComputerName localhost` and the virtualization CIM inventory returned no VMs. The host had 61.6 GB total RAM and about 3.4 GB free at observation time. The live KRig miner, Docker, and WSL activity was present; none was controlled.

This is enough to reject local guest creation as an appropriate next step: enabling Sandbox would mutate Windows features and may require reboot, while creating/starting a Hyper-V guest would consume scarce free memory alongside active workloads. Hyper-V being enabled does not imply a disposable VM exists. No VM ownership or disposable status was inferred from the mere presence of Hyper-V.

## Option comparison

| Option | Existing availability | Isolation and exposure | Restart/rollback fidelity | Decision |
|---|---|---|---|---|
| Windows Sandbox | Supported Windows edition appears present, but feature disabled | Ephemeral guest; network, clipboard, vGPU, and folder sharing must be explicitly restricted. Requires host feature enablement and likely reboot. | Supports guest restarts on modern Windows 11, but closing destroys guest state; inadequate for a multi-checkpoint rollback sequence. | Not available without host mutation; reserve for narrowly scoped helper/task checks on an idle authorized host. |
| Dedicated Hyper-V VM | Hyper-V components enabled; no existing VM identified | Strong guest disk/process boundary when no production shares, credentials, or network are attached. | Checkpoints, guest restarts, and independent disks support repeatable upgrade/interruption/rollback tests. | Preferred on a separate, authorized idle Windows host. No VM was provisioned here. |

Windows Sandbox configuration documentation describes configurable networking and read-only folder mapping. Any future `.wsb` should disable networking, vGPU, clipboard, printers, audio/video input, and writable host mappings; map only a sanitized bundle read-only if needed; and contain no automatic command. See [Windows Sandbox overview](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview) and [configuration](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file). Hyper-V feature availability is not authorization to provision a guest; consult [Hyper-V installation requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v).

`sandbox-restricted-template.wsb` is a non-running template with networking, vGPU, clipboard, printers, audio, and video disabled; its only mapped folder is read-only and must be staged deliberately. It has no logon command. It was not launched because Sandbox is disabled on this host.

## Authorization boundary

The only remaining permission needed before actual disposable installation/task/upgrade mutations is confirmation of a named disposable Windows guest (or isolated host), its owner, reset/checkpoint procedure, and permission for the specific H4 test matrix. This report does not request or exercise permission to mutate the primary host. H5 production changes and live GPU work need separate authorization.
