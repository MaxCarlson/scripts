# Implementation Status — vm-lab Workflow Automation

**Initialized:** 2026-11-15. **State:** SOURCE_PHASES_0_TO_6_COMPLETED / LIVE_HYPERV_NOT_TESTED.  
**Owner:** Antigravity (`agent/vm-lab-workflows-20261115`).  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-vm-lab-workflows-20261115` (branched from `origin/main` `2def44c9`).  
**Source Plan Provenance:** `C:\Users\mcarls\Downloads\vm_lab_workflow_master_plan_20261115\modules\vm_lab\docs\plans\20261115-workflow-automation` (`MANIFEST.sha256` verified: 13 files matched).

## Source observations at Phase 0 audit

- `origin/main` is `2def44c9` (`Merge integration/vm-lab-review-20261115 into main`), which includes `a6da283e` and `6fee2b05`.
- `modules/resource_coordinator/tools/h4_qualification/` on `main` contains `Provision-H4TestVM.ps1`, `Bootstrap-H4GuestBundle.ps1`, `windows_acceptance.py`, etc.; `Invoke-H4GuestQualification.ps1` is on `fix/rc-h4-task-discovery-20261115`.
- Protected H4 VM `RC-H4-Windows-Acceptance` (`d8483f98-8884-4758-abd1-cd6107c83c03`) and `modules/resource_coordinator/` are untouched.
- Baseline verification on `agent/vm-lab-workflows-20261115`:
  - `AST_AND_IMPORT_OK` (`Parser::ParseFile` + `Import-Module vm_lab.psd1 -Force`, exit 0).
  - Existing `vm_lab.Tests.ps1` + `Invoke-VmLabOperationalSmoke.Tests.ps1`: **36 Passed, 0 Failed, 0 Skipped** (exit 0).
  - Phase 0 `Contracts.Tests.ps1`: **4 Passed, 0 Failed, 0 Skipped** (exit 0).
  - Python toolkit (`modules/script_logging/tests` + `modules/scripts_help/tests`): **147 Passed, 0 Failed** (exit 0).

## Phase board

| Phase | State | Validated commit | Executed tests | Blockers |
|---|---|---|---|---|
| 0 — Baseline/design | COMPLETED | `61010661` | 36 baseline Pester + 4 Contracts Pester + 147 Python | none |
| 1 — Guest operations | COMPLETED | `7803eab1` | 5 GuestOperations Pester (`GuestOperations.Tests.ps1`) | none (live VM `NOT_TESTED`) |
| 2 — Lifecycle transaction | COMPLETED | `ec0fbdbb` | 3 LifecycleTransaction Pester (`LifecycleTransaction.Tests.ps1`) | none (live VM `NOT_TESTED`) |
| 3 — Durable workflows | COMPLETED | `47c925a5` | 3 WorkflowEngine Pester (`WorkflowEngine.Tests.ps1`) | none (live VM `NOT_TESTED`) |
| 4 — Elevated runner | COMPLETED | `8e2f036d` | 2 ElevationAndSetup Pester (`ElevationAndSetup.Tests.ps1`) | live elevation `NOT_TESTED` (requires explicit authorization) |
| 5 — Windows setup | COMPLETED | `8e2f036d` | 2 ElevationAndSetup Pester (`ElevationAndSetup.Tests.ps1`) | live OOBE/VM `NOT_TESTED` (requires separate authorization) |
| 6 — Acceptance/integration | PREPARED_BLOCKED_ON_LIVE_AUTH | `0667ea62` -> P0/P1 fix pending commit | Full Pester (59 tests) + AST/import + Python toolkit (147) + CLI checks | live Hyper-V qualification `NOT_TESTED` (requires separate elevated authorization on a disposable VM) |

## Post-review security & contract corrections

- **P0 Mandatory Operation Capabilities (`Contracts.ps1`, `WorkflowEngine.ps1`, `Elevation.ps1`)**: Added `Get-VmLabOperationCapabilityPolicy`; `Test-VmLabWorkflowSchema` rejects missing/mismatched/downgraded capabilities on mutating stages (including `evidence.collect` -> `host_mutation` and `vm.connect` -> `vm_lifecycle`); `Test-VmLabWorkflowPlan` and `Invoke-VmLabWorkflow` derive required capabilities from the central policy; `New-VmLabApprovedPlanRequest` and `Test-VmLabApprovedPlanRequest` reject under-authorized capability sets.
- **P1 Checkpoint Resume Compatibility (`WorkflowEngine.ps1`, `LifecycleTransaction.ps1`)**: Added `ConvertTo-VmLabNormalizedCheckpoint` and aligned both `WorkflowEngine.ps1` and `LifecycleTransaction.ps1` with the actual `Get-VmLabCheckpoint` (`vm_name`, `name`, `id`, `snapshot_type`, `created_at`) and `New-VmLabCheckpoint` (`status = 'checkpoint_created'`, `snapshot_type`) contracts; resume reconciliation enforces VM identity/ownership, exact unique match, `Standard` type, prior receipt ID consistency, and expected VM power/readiness state.
- **Approved-Runner Binding (`Invoke-VmLabApprovedPlan.ps1`)**: `-OperatorConsent` execution now requires `-ExpectedRequestDigest` in addition to atomic single-use `FileMode::CreateNew` receipt claiming, durable `FAIL` exception receipts, `-ExpectedWorkflowDigest`, and `-ExpectedVmId`.
- **Remaining Live Gate**: Real Hyper-V VM provisioning, `Standard` checkpointing, PowerShell Direct guest execution, and Windows 11 OOBE remain `NOT_TESTED` pending separate explicit elevated authorization on a disposable VM.

## First agent actions

1. Inventory branches/worktrees, pending agents, main tip and any dirty state.
2. Read all plan documents and compare to current code; update outdated facts rather than silently reusing stale commits.
3. Run T0/T1/T2 baseline tests and record exact commands/output, source hashes and platform information.
4. Document selected public CLI, JSON schemas and source ownership boundaries.
5. Execute Phase 0 then Phase 1 without unnecessary prompts. Protect H4 VM/production state.

## Per-checkpoint status template

```text
Phase:
Branch/worktree:
Commit SHA (local and remote):
Changed files:
Tests executed (command, exit code, pass/fail/skip, provenance):
Real Hyper-V observations: NOT_TESTED | read-only | live authorized
Evidence locations:
Contract/API changes:
Invariants validated:
Unresolved issues or blockers:
Next safe action:
Merge status: NOT_AUTHORIZED | REVIEW_READY | MERGED
```

Never claim success from unexecuted tests or a stale log; distinguish model, code and infrastructure failures.
