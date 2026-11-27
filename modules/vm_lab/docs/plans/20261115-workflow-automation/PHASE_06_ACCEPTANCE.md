# Phase 6 — Real Hyper-V Qualification, Cross-Module Validation, and Closeout

**Depends on:** source-level Phases 0–5 as appropriate; core acceptance of Phases 0–3 may precede optional Phase 5 image support.  
**Critical boundary:** real Hyper-V mutation requires separate, explicit authorization for a new isolated disposable VM and confirmation H4/host resources are available.  
**Outcome:** verified working system with source integration readiness, **not** just green mocked tests.

## Objective

Prove the new `vm-lab` can replace the generic host-side H4 provisioning/setup/lifecycle/test orchestration and survive realistic failures. Distinguish source merge readiness from operational qualification and from project-specific RC acceptance.

## 1. Pre-acceptance safety gate

- Inspect latest H4/RC agent activity, host workload status, all worktrees and current main/feature heads. Do not interrupt productive agents. H4 (`RC-H4-Windows-Acceptance`, ID `d8483f98-8884-4758-abd1-cd6107c83c03`) remains protected and **must not** be adopted, cloned, checkpointed, started or stopped by acceptance.
- Obtain **explicit authorization** for a *new disposable test VM name, root, ISO, RAM/disk budget, operations and eventual cleanup policy*. Authorization to create does not authorize deletion, forced power-off, source merge, host restart or permanent privilege changes.
- Verify host RAM/disk headroom, VRAM/GPU independence, available elevated session, network-disconnected default, Windows 11 setup media and guest account plan. Do not stop production RC/KRig/WSL/Docker/LM Studio to free resources.
- Confirm source hashes, pinned worktree/modules/launcher, trusted installer/wheelhouse provenance and network policy.
- Run read-only `workflow-plan`, `doctor`, and explicit approval review; record expected target ID if existing (new target must be absent).

## 2. Test tracks

### Track A — Static and isolated compatibility (always run)

1. Pester parse/import/legacy module tests; negative `-Apply/-WhatIf`, ownership, path/symlink, crashes and param binding.
2. Python toolkit launcher/help, invocation logging, clean-source provenance. Existing `vm-lab -o` commands must not regress.
3. New workflow schema and journal unit/property tests.
4. Synthetic H4-like workflow runs with fake Hyper-V/PS Direct adapters: full success + failure after each boundary.
5. Host source and module version manifests, Git diff check, tests with explicit exit codes.

### Track B — Real read-only host checks (may run with suitable privileges)

1. Hyper-V module and cmdlet parameter introspection (`Start-VM`/`Stop-VM` support `-VM` on target version).
2. Host available resources, VM inventory, firmware settings and current H4 protected state (read-only).
3. Verify absence of requested disposable name/root and source digest.
4. No VM mutation or application restart.

### Track C — Real disposable Hyper-V lifecycle (requires explicit authorization)

1. Create VM from `windows11-dev` or tailored isolated template using generic `vm-lab`; verify Gen2, 4 vCPU (or approved resources), dynamic RAM, VHDX, ISO, Secure Boot/vTPM, disconnected NIC, disabled auto-start and Standard checkpoints.
2. Open VMConnect; validate boot/UEFI/media diagnostics and initial startup. Record Windows installation as interaction-needed, not falsely complete.
3. Complete Windows Setup/OOBE or use a separately validated generalized image. Establish dedicated guest local admin and authenticated PowerShell Direct.
4. Guest identity/virtualization/permissions preflight; verify host XERES is not target.
5. Deploy verified offline assets (Python/PowerShell installer, wheelhouse, acceptance fixture bundle), compare hashes/manifest and avoid recopy after intentional interruption.
6. Run generic prerequisite profile: Python >=3.12 x64, PowerShell 7, pinned venv dependencies; verify installed versions/imports and record setup receipt with operation ID.
7. Run `vm.checkpoint_transaction` on owned guest: graceful shutdown, poll Off, create exactly one Standard checkpoint, verify ID/type/time, optionally restart and wait for guest PowerShell Direct.
8. Run synthetic external acceptance matrix: offline, task-style, full-style, five rollback fault stages, scoped cleanup on failure. Project fixture returns JSON with `status`, `counts.skipped` and nonzero exit codes; module must enforce declared predicates and preserve original failure evidence.
9. Collect recursive guest evidence back to host with per-file SHA-256, nested logs and failure recovery. Test evidence-only retry.
10. Finalize workflow, verify stage journal/receipt index and `SUCCEEDED` only if mandatory postconditions pass. Optional graceful stop only if separately authorized.
11. Report exact VM/state/checkpoint IDs, timestamps, file hashes, test results, manual OOBE steps, resource use and limitations.

**Do not run actual Resource Coordinator production installer/Task Scheduler/rollback against this generic VM by default.** RC qualification remains RC-owned. A separate RC adapter integration test may run only on an expressly authorized disposable guest with its own application mutation authorization and clean inventories.

### Track D — Real foreground elevated bridge (requires user invocation)

1. Agent prepares a typed request and logs plan digest; non-elevated execution must fail closed.
2. User executes reviewed request from an elevated PowerShell 7 session; runner confirms host ID/VM ID/capabilities.
3. Verify authorized actions occur, unapproved action refused, approval cannot be reused or altered, and result receipt is readable by agent without providing the agent elevated rights.
4. Test abort/interrupted session, transcript sanitization, no password in logs, and operation resume.
5. Privileged runner terminates after completion; no service/task/persistent admin broker remains.

## 3. Fault injection and reconciliation matrix

| Boundary | Injected failure | Expected evidence/result |
|---|---|---|
| Preflight | insufficient RAM/disk, wrong ISO hash | BLOCKED, no VM created |
| Create | disk created, VM registration fails | PARTIAL with preserved VHDX, no forged manifest |
| Own | VM created but manifest write fails | UNCERTAIN/blocked recovery plan, no auto-adopt |
| Boot | missed DVD key, invalid media | AWAITING_INTERACTION/boot diagnostic, no forced reset |
| OOBE | guest account not created | AWAITING_INTERACTION, same operation ID |
| Auth | wrong guest credentials | guest_auth_failed, no guest writes |
| Assets | wrong wheel/installer/ZIP SHA | integrity failure, no execution |
| Transfer | interrupted halfway | PARTIAL, manifest lists missing files, safe retry |
| Installer | exit 3010 | REBOOT_REQUIRED, no auto-reboot |
| Setup | receipt exists but journal missing | reconcile verified receipt, do not repeat setup |
| Stop | shutdown takes too long | shutdown_unconfirmed, no checkpoint |
| Checkpoint | command success but snapshot type wrong | FAIL, no qualified baseline |
| Snapshot | created but receipt write interrupted | inventory re-probe, no duplicate snapshot |
| Restart | guest not yet ready | PARTIAL/awaiting_guest, no blind second VM create |
| Guest exec | exit code nonzero | FAIL, raw outputs kept |
| Guest exec | zero exit but JSON `failed` or real-task skips | FAIL by project policy |
| Guest exec | session lost after possible mutation | UNKNOWN until independent guest receipt; no blind rerun |
| Cleanup | cleanup fails after acceptance failure | original FAIL retained, cleanup failure separate |
| Evidence | incomplete directory copy | INCOMPLETE and evidence-only retry |
| Operation | host console closed and resumed | deterministic reconciliation, same operation ID |
| Trust | VM renamed or ID/root different | INVALIDATED; no mutation |
| Approval | expired, mismatched or replayed | BLOCKED; no mutation |
| Reparse | symlink/junction under allowed root | fail closed; no path escape |

## 4. Performance and resource checks

Measure disk and RAM headroom before each VM start, transfer throughput of bundle/wheelhouse, guest session readiness latency, checkpoint duration, failure recovery latency and journal size. Establish practical bounded defaults from observations; don't invent throughput/timeout guarantees. Avoid running extra local LLM inference or GPU-intensive workloads as part of acceptance.

## 5. Evidence and release artifact

Create a durable directory keyed to a unique **new** operation ID (do not reuse historical H4 ID). Include:

```text
acceptance/<operation-id>/
  manifest.json               # source/runtime/tool versions and digests
  host-preflight.json
  planned-workflow.json
  operation.json
  stage-receipts/
  hyperv-inventory-before.json
  hyperv-inventory-after.json
  guest-identity.json
  asset-integrity.json
  checkpoint-verification.json
  guest-execution-matrix.json
  evidence-manifest.json
  failure-injection-summary.json
  launcher-validation.json
  tests/{pester,pytest,cli}/
  final-summary.json
```

No secrets, passwords, credentials or unrestricted user directory data. Protect evidence against unapproved write access. In `final-summary.json`, distinguish `source_validation`, `live_hyperv_qualification`, `project_adapter_acceptance`, and `production_qualification` rather than conflating them.

## 6. Integration, deployment and final Git safety

- Do not interrupt active Resource Coordinator agent. Inspect branch and worktree state before merge decisions. Preserve uncommitted evidence and concurrent processes.
- Integrate only validated dependency commits into an isolated review branch; reconcile current main without force push or conflicts that erase work.
- Validate CLI, launcher telemetry, scripts-help, PowerShell module import from the *actual proposed merge source*.
- Source merge to `main` requires explicit authorization. Generating/replacing installed `bin/vm-lab.cmd` and modifying host environment are separately reviewed deploy steps.
- After source merge, verify origin/main and wrapper target match tested commit; no production VM mutation by post-merge setup.
- Never automatically delete disposable VM, VHDX, snapshots, answer media or logs. If cleanup is desired, produce a bounded plan and request separate explicit deletion authorization.

## 7. Definition of done

- [ ] Every applicable `WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md` row marked supported/tested or external-project logic with demonstrated generic execution.
- [ ] Generic example H4-like workflow succeeds on controlled fake infrastructure with fault injection and evidence recovery.
- [ ] Real disposable Windows VM reaches fully qualified generic acceptance without custom host PowerShell or unrelated host modifications.
- [ ] Agent privilege bridge demonstrates approved typed execution and no standing elevated process.
- [ ] Windows Setup assistance is correct, or optional advanced parts are explicitly deferred with evidence and manual fallback.
- [ ] No false success from incomplete tests, changed hashes, missing evidence or skipped required acceptance profiles.
- [ ] All existing vm-lab APIs and script-toolkit launch behavior remain backward compatible.
- [ ] All relevant tests executed and evidence recorded with exact exit codes/paths; NOT_TESTED explicitly flagged.
- [ ] Branch reviewed, documented and ready for explicitly authorized mainline merge, or blockers clearly identified.
- [ ] H4, production RC, KRig and host workloads untouched.

## Final agent report

Include: scope implemented, selected architecture, exact branch/commit/worktree, test counts/exit codes/provenance, live VM identity/authorization, real observed results, incomplete work, found regressions, evidence paths, final coverage status, source merge readiness and **whether production or H4 was modified (expected: no)**. If everything passes, recommend integration; do not manufacture another phase.
