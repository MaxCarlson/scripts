# Research, Evidence, and Architecture Decisions

**As-of:** 2026-11-15. Links are official primary technical documentation; source-code observations refer to read-only GitHub inspection, not executed local behavior.

## 1. Primary references and their engineering consequences

| Topic | Primary source | Relevant verified guidance | Decision |
|---|---|---|---|
| PowerShell Direct | [Microsoft: Manage Windows VMs with PowerShell Direct](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/powershell-direct) | Local Windows host and running Windows guest with configured user; Hyper-V host admin and guest credentials; does not require guest network; `New-PSSession -VMId`, `Invoke-Command`, `Copy-Item -ToSession/-FromSession`. | Use PowerShell Direct for Windows guest control; no network/WinRM dependency. |
| Integration services | [Microsoft: Hyper-V integration services](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/integration-services) | PowerShell Direct uses VM session service; integration services including Heartbeat provide signals. | Distinguish heartbeat from authenticated guest readiness. |
| Start cmdlet | [Microsoft: Start-VM](https://learn.microsoft.com/en-us/powershell/module/hyper-v/start-vm) | Accepts `-VM` object or `-Name`, not `-Id` in the documented cmdlet set. | Resolve exact GUID through Get-VM, validate, then pass `-VM`. |
| Stop cmdlet | [Microsoft: Stop-VM](https://learn.microsoft.com/en-us/powershell/module/hyper-v/stop-vm) | `-VM` accepted; default requests guest OS shutdown; `-Force/-TurnOff` have differing risks. | Graceful shutdown only by default; confirm Off before downstream checkpoint. |
| Checkpoint cmdlet | [Microsoft: Checkpoint-VM](https://learn.microsoft.com/en-us/powershell/module/hyper-v/checkpoint-vm) | `-VM`, `-SnapshotName`, `-Passthru`, no documented `-Id`; object verification is supported. | Bind exact VM object, verify returned snapshot ID/type/time and live inventory. |
| Checkpoint semantics | [Microsoft: Hyper-V checkpoints](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/checkpoints) | Standard captures VM state incl. memory if running, Production uses VSS/file-freeze; neither is an independent backup. | Powered-off Standard checkpoint transaction is a lab policy, not universal default. |
| Windows Setup answer files | [Microsoft: Automate Windows Setup](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/automate-windows-setup) | `Autounattend.xml` may automate Setup pages; Setup searches appropriate media; `/unattend` valid in WinPE context. | Treat XML creation, media delivery, consumed-by-Setup verification as separate steps. |
| Answer-file search | [Microsoft: Windows Setup Automation Overview](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-setup-automation-overview) | Search paths/precedence include root of removable read-only or read/write media; format and pass matter. | Use documented secondary media; test exact Windows build; avoid guessing a generated file will be discovered. |
| Setup switches | [Microsoft: Windows Setup command-line options](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-setup-command-line-options) | `/unattend:<file>` applies when booted from WinPE, not normal in-place setup. | No automatic in-guest fallback that assumes `/unattend` works in installed Windows. |
| Prepared images | [Microsoft: Sysprep generalize](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/sysprep--generalize--a-windows-installation) | New deployment image should be generalized; unique ID/SID removed, store app provisioning caveats apply. | A reusable VHDX image requires Sysprep, provenance/licensing controls and separate approval. |
| Hyper-V host creation | [Microsoft: New-VM](https://learn.microsoft.com/en-us/powershell/module/hyper-v/new-vm) | Cmdlet has parameter sets including `-NewVHDPath/-NewVHDSizeBytes` and `-VHDPath` for existing disk. | Continue current `New-VHD` + `New-VM -VHDPath` flow unless live tests show issue; test parameter sets on target host. |

## 2. Source inspection evidence

### Existing `vm_lab` on `MaxCarlson/scripts/main`

Read-only retrieval found:

- `src/Provisioning.ps1`: `Test-VmLabPlan`, `New-VmLabMachine`, `Invoke-VmLabQuickstart`, `New-VmLabUnattendXml`.
- `src/Lifecycle.ps1`: `Start-VmLabMachine`, `Stop-VmLabMachine`, `Connect-VmLabMachine`, boot diagnostics.
- `src/Guest.ps1`: `New-VmLabPSSession`, session invocation, one-file guest transfer, guest status.
- `src/Bootstrap.ps1`: Windows/Python/PowerShell profiles with version and package-spec validation.
- `src/Checkpoints.ps1`: standalone `New-VmLabCheckpoint`, `New-VmLabBaselineCheckpoint`, `Get-VmLabCheckpoint`.
- `tests/Invoke-VmLabOperationalSmoke.ps1`: staged disposable-VM smoke harness, state journal, protected VM rules; **this is qualification scaffolding, not a generic workflow engine**.
- `templates/windows11-dev.json` and `templates/windows11-h4.json`: Gen 2, Dynamic RAM, Secure Boot/vTPM, no network, Standard checkpoint settings.

As of inspection, the vm-lab integration commit `a6da283eb9d007f30d4abca55667e6d1e46af260` was an ancestor of `main`. Do not use this statement as a substitute for checking the current remote commit and local dirty state.

### H4 reference on `MaxCarlson/scripts`

- `Provision-H4TestVM.ps1` checks ISO/paths/resources and configures Hyper-V generation, memory, vTPM, NIC, checkpoint type and boot order.
- `Invoke-H4GuestQualification.ps1` implements `Preflight/Setup/Checkpoint/Acceptance/All`, structured results, operation IDs, guest identity checks, wheelhouse/bundle transport, guest installers, dependency setup, receipts, powered-off Standard checkpoints, guest restart/PS Direct polling, acceptance matrix, evidence return and failure classifications.
- `Bootstrap-H4GuestBundle.ps1` validates trusted expected bundle digest and extracted component integrity.
- `windows_acceptance.py` is a fail-closed project-specific runner with mutation gates, Task Scheduler/inventory/port guards, supported profiles, fault-stage rollback tests and scoped cleanup.

**Known historical issue:** a previous H4 runner used invalid `Start-VM`/`Stop-VM -Id` and was corrected to `-VM` with verified Hyper-V object. The planning contract explicitly locks the supported cmdlet parameter sets and requires real-host acceptance tests.

## 3. Design decisions

**D01: Keep PowerShell 7.** Existing code/tools/tests already use PowerShell and native Hyper-V cmdlets. A Python orchestrator would add avoidable runtime dependencies to the privileged host boundary.

**D02: Canonical workflow JSON, not YAML initially.** PowerShell's `ConvertFrom-Json` is available without additional parser dependencies. Support a machine-readable strict schema with versioning and deterministic hashing; optionally add YAML later if there is real demand.

**D03: File-backed state first.** Per-operation JSON, immutable receipts and atomic files are simpler and more transparent than an always-on database for bounded local workflows. SQLite/FTS is out of scope until durable scale/concurrency evidence warrants it.

**D04: Typed operations only.** Plans cannot embed arbitrary host PowerShell. External project logic executes inside a separately authorized, pinned guest executable with scoped arguments. Prevent host code injection and maintain auditability.

**D05: Isolate ownership model.** Never bypass or forge manifests for existing H4 VM. Future VMs should be created and owned by vm-lab; delegated ownership is a separate future design if needed.

**D06: Prefer staged execution to synchronous all-in-one.** Windows OOBE and PowerShell Direct readiness can require human interaction. Workflow must be resumable; no success claim based on VHDX size or ISO boot attempt.

**D07: Privileged runner is foreground, explicit.** No UAC bypass, persistent privileged service, hidden scheduled task, or continuously listening endpoint. Avoid authorization token reuse and credentials on disk.

**D08: Evidence survives failure.** Guest command nonzero, transfer partial or cleanup failure must preserve original result and enable evidence retry, not force deletion or mark PASS.

**D09: Windows prepared image optional.** Phase 5 only; `Sysprep /generalize` and OEM/activation/licensing requirements need explicit testing. Avoid cloning the active H4 VM.

**D10: Live operational test cannot be faked.** Pester mocks are unit evidence, not proof of Hyper-V, VMConnect, PS Direct, checkpoint type or OOBE behavior. Isolated disposable guest is a required final gate.

**D11: Use resource preflight, not forced shutdown.** Ensure available host memory/disk and avoid interfering with GPU mining, production RC, WSL/Docker, LM Studio or any other processes.

## 4. Remaining verification tasks (not pre-deferred research)

1. Actual target Windows 11 / PowerShell 7 / Hyper-V cmdlet versions and installed environment.
2. Exact `vm-lab` CLI aliases and backward compatibility with managed `.cmd` launcher on Windows.
3. VMConsole/ISO firmware boot edge cases on the Windows build being deployed.
4. Safe VHDX/media mechanism for `Autounattend.xml` and its interaction with generation 2 boot order; test with a **new** disposable VM.
5. Guest command timeout/disconnect reconciliation for non-replayable commands.
6. Operator approval identity, expiration and proof semantics for privileged runner; hashes alone do not authorize operations.
7. Existing H4 agent progress and final source/evidence since inspected commits; keep its VM off limits.

## 5. Excluded shortcuts

- Do not use `BypassNRO`/`ms-cxh:localonly` as a foundational guaranteed OOBE solution on current builds; support is inconsistent. Prefer Microsoft-documented Setup configuration and interactive fallback.
- Do not assume Hyper-V integration services can start an OS that is still at OOBE or bypass valid guest credentials.
- Do not treat a `PowerShell Direct` session probe as proof that a specific app/test environment is correctly installed.
- Do not use an untrusted `.sha256` file shipped beside its own archive as publisher authentication.
- Do not use a Standard checkpoint as a backup or skip guest power-state verification.
- Do not add self-elevating persistence or agent-controlled host-wide execution privileges.

## 6. Source status provenance

This research was done without running any real Hyper-V command against XERES. Source observations are about published repository content; historical acceptance states are from the user-provided Worker-ResourceCoordinator conversation. Phase 0 must update any drift to actual current branch/source and explicitly label new findings.
