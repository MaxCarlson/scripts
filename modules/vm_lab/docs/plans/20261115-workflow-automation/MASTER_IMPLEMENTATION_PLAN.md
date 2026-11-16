# Master Implementation Plan — Reusable Hyper-V VM Workflows

**Project:** `MaxCarlson/scripts/modules/vm_lab`  
**Plan revision:** 1 (2026-11-15)  
**Prepared from:** Worker-ResourceCoordinator history and retrieved H4/`vm-lab` source, not a new local test run.  
**Implementation status:** NOT STARTED for the extensions proposed here; see `STATUS.md`.  
**Scope:** generic host-side orchestration for Windows 11 Hyper-V lab VMs, supporting project-specific guest tests without importing their business logic.

## 1. Outcome and the problem to eliminate

An engineer or coding agent should be able to take a declarative **VM workflow definition**, authorize a bounded set of operations, and execute/recover the full path:

`preflight → provision VM → boot/interactive Windows installation handoff → verify PowerShell Direct → stage verified offline assets → bootstrap Windows guest → clean powered-off Standard checkpoint → restart & wait for readiness → execute project-provided acceptance matrix → collect verified evidence → report / optional graceful shutdown`.

The recurring H4 failure mode was *manual orchestration*, not the absence of individual Hyper-V cmdlets. A 765-line project-specific host runner, repeated elevated command blocks, installation/OOBE interactions, reused operation IDs/receipts, and separate evidence directories were needed to complete the lifecycle. The new module should replace **generic workflow plumbing**, leaving RC-specific assertions, test profiles, mutation gates, and rollback semantics with RC.

**Target user experience:** a small number of documented CLI invocations, one durable operation ID and journal, reusable stage receipts, `plan/status/resume`, stable JSON, and an explicitly authorized elevation handoff. An agent should never ask the user to manually reconstruct 100-line PowerShell sequences if the module can safely drive that sequence.

## 2. Ground truth versus assumptions

### Existing capabilities (inspected in GitHub source)

`vm_lab` already offers `templates`, `template-info`, `plan`, `quickstart`, `wizard`, `create`, `list/status`, `start/stop/connect/start-connect`, `boot-diagnostics`, `guest-status`, `guest-copy`, `guest-bootstrap/guest-verify`, `checkpoint/baseline/checkpoints`, `doctor/recovery-plan`, `unattend-xml` and an explicitly gated operational smoke harness. It uses ownership manifests, `-Apply`/`-WhatIf`, JSON, PowerShell Direct, and script-toolkit launcher/help registration. The integrated source is on `scripts/main` as of the inspection; its exact tip may advance. Do not reimplement this baseline.

### H4 reference (retrieved source)

`modules/resource_coordinator/tools/h4_qualification/Provision-H4TestVM.ps1` (~330 lines), `Invoke-H4GuestQualification.ps1` (~765 lines at inspected H4 commit `a1b9a3a4`), `Bootstrap-H4GuestBundle.ps1` (~106 lines), and `windows_acceptance.py` (~1,095 lines) implement additional orchestration. The user has a running Windows 11 H4 VM, created local guest account `mcarls`, and setup receipt connected to operation `20261115-143723-e58eb8ae`. Later H4 stages (checkpoint, acceptance) had not been positively verified in the examined state. **Do not assume current H4 stage results are unchanged; inspect live agent/evidence for any update, read-only.**

### Evidence classification

- **Verified by reading published source:** function/parameter existence and implementation flow; matrix rows marked `SOURCE`.
- **From recovered conversation and agent summaries:** actual historical blockers, setup/account events, test pass reports; rows marked `HISTORY`.
- **Planned:** schemas/commands in this plan are proposals, not implemented APIs or measured performance.

Full crosswalk: `WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md`.

## 3. Scope, non-goals and protective boundaries

**In scope:** VM workflows, typed guest command execution, verified artifact deployment, file/directory evidence retrieval, guest readiness and identity assertions, lifecycle/checkpoint transactions, resumable journals, bounded host elevation, Windows installation assistance, operational acceptance.

**Out of scope:** moving RC's domain-specific acceptance/rollback implementation into `vm-lab`; general-purpose arbitrary remote shell daemon; bypassing UAC; persisting passwords; forceful VM shutdown by default; unbounded host scripting; managing existing unmanaged VMs; removing VMs/VHDX/checkpoints automatically; silently networking an isolated VM; production RC/KRig changes; local LLM inference.

### Absolute invariants

1. **Target identity:** exact Hyper-V VM ID + expected name + host + ownership manifest + configuration path; revalidate before each mutation.
2. **No adoption:** an externally created VM (including H4) remains read-only to `vm-lab` until a separately designed and explicitly approved delegation mechanism exists. Do not forge a `vm_lab` ownership manifest.
3. **Authorization:** dry-run by default; `-Apply` alone does not authorize arbitrary guest code, checkpoint power changes, elevated plans or future resume mutations. Each phase requires its declared capability approval.
4. **No secrets in artifacts:** prompt for guest credentials; never serialize `PSCredential`, password, session object, token or user-provided secret environment variables.
5. **No unsafe success:** `PASS` requires an independently verified postcondition plus evidence. `SKIPPED`, `BLOCKED`, `NOT_TESTED`, `INCOMPLETE`, and `PARTIAL` are separate states.
6. **Preserve partials:** no implicit re-create, rollback, deletion or checkpoint apply. Stop on uncertain identity or partial mutation; supply a recovery plan.
7. **Production isolation:** preserve RC, KRig, GPU workloads, WSL/Docker/LM Studio, scheduled tasks, services and network state.
8. **Resource-aware:** avoid starting a fresh VM without RAM/disk preflight and user-approved reservation; do not assume memory availability remains constant.

## 4. Target architecture

- **Hyper-V layer (`vm_lab` existing):** host inventory, paths, ownership, provisioning, VMConnect, guest sessions, guest copy, bootstrap, checkpoint primitives.
- **Generic operations layer (new):** trusted guest-command runner, artifact deployment, artifact integrity, recursive evidence pull, guest identity policy, lifecycle transaction, explicit transition postconditions.
- **Workflow layer (new):** schema v1, dependency DAG (acyclic with deterministic topological order), operation ID, stage receipt, atomic journal and reconciliation, retries/resume, evidence index, CLI.
- **Authorization layer (new):** typed bounded operation plan, independent source hash, approved phase/capability/VM ID, foreground elevated PowerShell runner with explicit invocation and short-lived consent; no general command server.
- **Project adapters (outside vm-lab):** optional workflow definitions and guest executables supplied by RC/other projects. They define business assertions and cleanup policies; `vm_lab` only executes declared operations and classifies results.

Use PowerShell 7 throughout host code, with Windows PowerShell-compatible session payloads where necessary. Avoid new mandatory Python, YAML, database, web server or network dependency for the core orchestration. Use JSON as the canonical machine format (human-facing docs can show illustrative YAML only if clearly labeled noncanonical).

Detailed schemas and boundaries: `ARCHITECTURE.md`.

## 5. Phases, dependencies and gates

| Phase | Document | Required deliverable | Gate |
|---|---|---|---|
| 0 | `PHASE_00_BASELINE.md` | Verified baseline and architecture/contracts; plan reconciled to active source and agents | No unexpected interface break; tests captured |
| 1 | `PHASE_01_GUEST_OPERATIONS.md` | Guest command runner, batch staging, trusted manifests, recursive evidence collection | No false success; asset hash and command failure tests |
| 2 | `PHASE_02_LIFECYCLE.md` | Graceful Off → Standard checkpoint → optional Start → PS Direct readiness transaction | Proven state transitions, identity checks, no hard stop |
| 3 | `PHASE_03_WORKFLOWS.md` | Durable typed DAG workflow, operation journals, receipts, recovery, reusable CLI | Synthetic H4-equivalent end-to-end *orchestration* with interruptions |
| 4 | `PHASE_04_ELEVATION.md` | Bounded, explicitly elevated execution bridge | Denied/mismatched plans fail closed; approval not reusable |
| 5 | `PHASE_05_WINDOWS_SETUP.md` | Answer-file media/boot/OOBE assistant and optional generalized images | Supported setup behavior, no credential leak or destructive disk install |
| 6 | `PHASE_06_ACCEPTANCE.md` | Live disposable VM qualification, compatibility, deployment/integration closeout | Actual Hyper-V evidence, not just mocks |

**Dependency:** 0 → (1 and 2 can be parallelized with separate ownership) → 3 → 4/5 (partly independent after 3) → 6. Phase 6's *preparation* is permitted earlier; live steps require separate authorization and resource availability.

**Core milestone:** phases 0–3; this replaces most reusable host-side H4 code.  
**Agent automation milestone:** phase 4; removes repetitive command copying with explicit privilege controls.  
**Full setup milestone:** phase 5; reduces installation/OOBE intervention.  
**Proven operations milestone:** phase 6.

## 6. Repository interfaces and backward compatibility

- Keep existing exported functions and CLI operation names. Add new functions under `modules/vm_lab/src/` by concern; update module export list, CLI dispatcher, tests, README and managed launcher help together.
- Do not convert a current `vm-lab -o ...` invocation into an incompatible subcommand; introduce a compatible `-o workflow-*` family or separate explicit `workflow` entry point. In Phase 0 select one, test exact argument handling, and document short and long flags.
- CLI examples in plans are **proposed contracts**; actual flags must be finalized before external usage.
- JSON stdout = exactly one document; diagnostic/progress output to stderr; numeric exit code and structured `status/reason_code` for scripts. Windows PowerShell native script execution must not swallow guest nonzero codes.
- Manifest schema remains backward-compatible; new workflow journal is separate from VM ownership manifest.
- Standardized operation/evidence roots must not collide with H4's `C:\H4-VM-Staging` or `C:\H4-Guest-Work`.

## 7. Operation state model

States: `PLANNED`, `AWAITING_AUTHORIZATION`, `RUNNING`, `AWAITING_INTERACTION`, `BLOCKED`, `PARTIAL`, `FAILED`, `SUCCEEDED`, `INVALIDATED`. A journal's `SUCCEEDED` state is derived from required stage receipts, never merely a successful process exit.

Every stage records: `operation_id`, `stage_id`, input/config hashes, host ID, VM ID, expected guest identity policy, authorizing capability (without credentials), started/completed timestamps, attempt number, state, observed postconditions, stdout/stderr/evidence paths, errors and cleanup limitations.

After a crash, reconcile from *observed state* before retry: e.g. if VM exists and has trusted manifest, do not create it again; if a checkpoint with expected name exists, verify ID/type/time; if bundle extracted, reverify manifest and digest instead of overwrite. Preserve competing successful artifacts.

Use atomic write+fsync/rename where supported and test storage/reparse safety; constrain path roots and reject symlink/junction escape. A per-VM/operation lock prevents concurrent mutation, with stale lock diagnosis rather than automatic deletion.

## 8. Test model and evidence

Testing tiers:

1. **T0 static:** AST parser, module import, interface schema and docs checks.
2. **T1 deterministic unit:** real orchestration logic with fake host/guest adapters, clocks and faults.
3. **T2 integration:** isolated PowerShell CLI subprocesses, SQLite invocation logging, scripts-help, manifest/transfer filesystem tests, no Hyper-V mutation.
4. **T3 real read-only:** Hyper-V inventory/VMConnect status if privileges permit, never infer live guest from VHD size.
5. **T4 live disposable VM:** explicit opt-in, dedicated clean VM, verified ownership, quota/resources, real PowerShell Direct/transfer/stop/checkpoint/start/acceptance.

Log exact commands, worktree provenance, exit codes, test counts, source SHA, Windows/PowerShell versions, VM ID, durations and actual evidence paths. Failure in test infrastructure must be separated from application defect. Keep a stable summary file for the coordinating agent.

## 9. Priority and scope management

1. **Do not block Phases 1–3 on hard unattended OOBE.** First reproduce H4-style automation after interactive Windows setup.
2. **Do not run real H4 acceptance with new generic runner on the active VM.** Create a synthetic RC-like test plugin (mock acceptance) and later a separate disposable Windows guest.
3. **Do not over-generalize workflows.** Versioned JSON typed steps (`vm.create`, `vm.start`, `guest.wait`, `artifact.deploy`, `guest.exec`, `vm.checkpoint_transaction`, `evidence.collect`) cover the observed use cases. No arbitrary scripts in host-side plans.
4. **Keep a safe escape hatch:** unsupported project-specific behavior stays in project adapter and is launched as a signed/hash-pinned guest executable by the generic runner.
5. **Consider operational cost:** prefer native tools, tested bounded polling, and no persistent daemon unless warranted.
6. **Checkpoint commits:** each phase concludes with audited tests, status update, and commit. Do not merge into main until explicitly authorized and source verified.

## 10. Acceptance criteria for the entire project

- [ ] All rows in `WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md` either `SUPPORTED_AND_TESTED` or intentionally `PROJECT_SPECIFIC` with generic execution coverage; no unsupported row silently dropped.
- [ ] H4-like VM can be planned, created, booted, paused for OOBE, resumed, staged, bootstrapped, checkpointed (powered-off Standard), restarted, and driven through an external acceptance matrix under one journal without custom host-side PowerShell.
- [ ] One immutable operation ID links setup receipts, checkpoint records, acceptance outcomes and evidence root across process restarts.
- [ ] Trusted assets and output artifacts verified by SHA-256; no "copied" or "passed" on partial transfers.
- [ ] An unprivileged agent can prepare an operation and inspect receipts; only an explicitly authorized elevated operator executes permitted host mutations. No bypass or standing privileged remote control.
- [ ] Host/in-guest identity and isolation gates fail closed, including a protected VM sharing the same inventory.
- [ ] Failure injection covers each mutating boundary and credible interrupted/partial states; no duplicate provisioning, checkpoints, or acceptance runs after resume.
- [ ] Real Hyper-V acceptance on independent disposable VM passes; record variants that remain NOT_TESTED.
- [ ] All legacy `vm-lab` CLI flags, manifests, wrapper logging, and documented workflows remain functional.
- [ ] No production RC/KRig, active H4 VM, guest secrets, or unrelated host state modified.

## 11. Handoff and integration protocol

Agent inspects actual worktree/commit/dependency state, reconciles Phase 0 plan, implements independently testable phases, writes `STATUS.md` with checkpoint SHA/tests and runs staged validation. When current approved work is complete, submit a merge-ready branch with provenance; **do not auto-merge**. Real Hyper-V mutation, elevated runner execution, credential entry, host changes and any irreversible cleanup require separate concrete authorization.

No recurring additional handoff is required for routine phase-to-phase source implementation. If Phase 3 passes, review journal/receipt/adapter contracts before proceeding to privilege-sensitive Phase 4 or OOBE-dependent Phase 5. Stop only on a genuine blocker, not to ask questions already answered by this plan.
