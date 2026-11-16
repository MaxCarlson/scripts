# Phase 0 — Current-State Audit, Contracts, and Non-Regression Baseline

**Depends on:** none.  
**Permitted:** read-only repo/host inspection, isolated code/test edits, commit/push feature branch.  
**Not permitted:** live VM changes, elevated operations, mainline merge.  
**Definition:** phase complete when an auditable baseline and approved internal contracts exist; do not merely write a plan and mark phase completed.

## Objective

Establish the actual state of `MaxCarlson/scripts` and the concurrent H4 agent; freeze the minimum stable interfaces needed to implement generic VM workflows. Verify that existing features work in isolation and identify exact cases where the current module fails to replace the custom H4 host-side code.

## Source entrypoints to inspect

- `modules/vm_lab/Invoke-VmLab.ps1`, `vm_lab.psm1`, `vm_lab.psd1`, README.
- `modules/vm_lab/src/{Config,Host,Inventory,Provisioning,Lifecycle,Guest,Bootstrap,Checkpoints,Recovery,Wizard,Output}.ps1`.
- `modules/vm_lab/templates/*.json` and all Pester tests, including `Invoke-VmLabOperationalSmoke.ps1`.
- `scripts_setup/launcher_generator.py`, `modules/script_logging`, `modules/scripts_help`.
- Resource Coordinator H4 `Provision-H4TestVM.ps1`, `Invoke-H4GuestQualification.ps1`, `Bootstrap-H4GuestBundle.ps1`, `windows_acceptance.py`, acceptance documentation and tests.
- Latest validated H4 operation receipts and agent state **read-only**, if visible. Do not load secrets or guest credentials.

## Work packages

### 0.1 Git and concurrent agent inventory

1. Verify `main`/origin SHA, feature and integration refs, worktrees and dirty status; identify active agents, including H4, and their file/VM ownership.
2. Preserve existing worktrees and uncommitted evidence; create an isolated `agent/vm-lab-workflows-YYYYMMDD` worktree from latest validated checkpoint. Never branch automatically from outdated main when another validated checkpoint is more appropriate.
3. Identify any existing workflow/elevated runner implementation added since plan creation; mark covered rows rather than reimplement.
4. Record clean base and exact diff before editing, with no assumptions that H4 state remains at previous snapshot.

### 0.2 Baseline validation and API extraction

- Run all current `vm_lab` Pester suites and launcher/help Python tests with worktree-specific imports.
- AST-parse every `.ps1/.psm1/.psd1` file and import module in a clean PowerShell 7 subprocess.
- List exported functions, CLI operations, positional/short/long flags, JSON output shapes and return/error semantics; record a compatibility baseline in tests.
- Check templates (`windows11-dev`, `light`, `empty`, `h4`) for config schema, default RAM/disk/network/checkpoint type and ownership namespace.
- Validate read-only commands are side-effect free in mocked instrumentation; `-WhatIf` and dry-run always prevent writes.
- Check `Get-VM` permission errors and ensure they don't convert to `VM missing`, `OS not installed`, or misleading success.

### 0.3 H4 decomposition and traceability

Use `WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md` as the canonical checklist. For each requirement ID, record: existing function or source anchor, missing generic operation, RC-specific policy boundary, implementation phase, expected test ID. Include historical contexts:

- Host elevation inaccessible to non-interactive agent; user manually runs reviewed commands.
- H4 Gen2/vTPM/ISO/offline network and interactive boot/OOBE.
- Host/guest identity validation, installed Python/PowerShell, wheelhouse, pinned artifact digests.
- Setup receipt tied to operation `20261115-143723-e58eb8ae` and exact SHA/guest directory.
- Powered-off Standard checkpoint, name and ID, `-VM` vs unsupported `-Id` Hyper-V cmdlet sets.
- Restart and wait on PowerShell Direct with credentialed local account.
- Offline/task/full/5 rollback profiles, cleanup and evidence recovery.

**Do not change live H4 operation artifacts to make the matrix easier to satisfy.**

### 0.4 Finalize core schemas and boundaries

Implement a strict JSON schema validator/parser for future workflow definitions and receipts **without executing any workflow**. Confirm required fields, legal types, allowed operation types, exact path rules and error reporting. Select actual `-o workflow-*` CLI verbs/short flags (the plan's examples are illustrative), and write backward-compatibility tests.

Decide:

- Versioning and deterministic serialization/hash for plan, operation ID, artifact manifest, stage receipt.
- Per-VM and per-operation mutual exclusion and stale-lock diagnosis.
- `SUCCEEDED` derivation versus `PARTIAL/FAILED/BLOCKED/AWAITING_INTERACTION`.
- Capability approvals: host mutation, guest mutation, checkpoint/shutdown, guest executable launch, installer, network/disk change.
- Guest verification policy schema and authorization-controlled environment variables.
- Fake adapters for Hyper-V and PowerShell Direct with real orchestration logic under test.
- Trusted artifact digest provenance and guest test root containment.

Reject unknown schema version/keys before any privileged operations. Design same-volume atomic file writes, no path escape, no symlink/reparse ancestry.

### 0.5 Architecture review and phase reconciliation

Compare the planned interfaces to real source and official docs in `RESEARCH_AND_DECISIONS.md`. Resolve significant decisions in `ARCHITECTURE.md` and record rationale. Adjust plan only on evidence. Preserve current CLI, manifest and wrapper behavior; do not fold Resource Coordinator into vm_lab.

## Deliverables

- Current source/worktree inventory, ownership table and tested base SHA.
- Pester and toolkit baseline execution record (counts, exit codes, provenance).
- Export/CLI/JSON compatibility catalog, ideally machine-testable snapshots.
- Final workflow/receipt/artifact/versioned schemas and chosen public CLI.
- H4 matrix status column with test IDs and phase assignments.
- Phase 0 architecture decisions, files/modules owned by subsequent phases, dependency order.
- Updated `STATUS.md` and validation command log, isolated commit.

## Acceptance tests

- A malformed schema, unknown operation type, unknown key, missing VM ID or invalid path fails before any adapter call.
- Old `-o templates`, `quickstart`, `guest-copy`, `guest-bootstrap`, `checkpoint` and `-j` continue to behave unchanged.
- Host permission denial yields a permission-specific error, not VM absent.
- Different operation IDs/VM IDs or roots cannot reuse journal/receipt.
- A protected VM's presence in inventory does not block unrelated disposable targets, but selecting the protected VM is rejected.
- Fake mutable adapters record zero operations during dry-run.
- No test interacts with a real production VM or existing H4.

## Exit/rollback plan

If API contract disagreement emerges, stop only the breaking-change portion; keep existing module functioning, document alternatives and select backward-compatible option. Do not rewrite manifests in place. If a test fails due to environment permissions, log `INFRA_BLOCKED` and preserve baseline without claiming regression.

## Completion evidence

Provide commit SHA, full command transcript, test counts/exit codes, matrix coverage update, schema examples, static interface comparison, and read-only verification of active agent boundaries. Phase 1 may begin after contracts are stable.
