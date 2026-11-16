# Phase 3 — Durable Workflow Engine, Operation IDs, Receipts, and Resume

**Depends on:** validated Phase 1 guest operations and Phase 2 lifecycle transaction.  
**Core success milestone:** generic vm_lab orchestrates an H4-like setup/checkpoint/acceptance path without custom *host-side* PowerShell.  
**Allowed:** repo changes, isolated mocks and synthetic acceptance; no active H4 mutation.

## Objective

Build a dependable, operation-scoped workflow engine with declarative stages, dependency validation, exact target identity, typed approvals, durable stage receipts, resumable execution, failure classification, and evidence indexing. This replaces most of the H4 runner's orchestration while respecting project-specific acceptance semantics.

## 1. Workflow definition and validation

Implement schema v1 from `ARCHITECTURE.md` using strict JSON fields/types, a closed set of typed stage kinds, unique `stage_id`, acyclic `depends_on`, bounded sizes, immutable normalized definition digest, valid host/guest paths and expected VM identity/ownership. Reject unknown stages, dependency cycles, missing inputs, privileged operations without declared capability, and impossible lifecycle order (e.g. guest.exec when VM still Off).

Expose final CLI operations (names frozen in Phase 0):

- `workflow-plan` — pure validation, dependency graph, resource estimate, required approvals, no mutation.
- `workflow-apply` — executes currently approved stages; stops on interaction boundary.
- `workflow-resume` — same immutable operation ID, revalidates receipts and live postconditions, proceeds only with fresh authorization.
- `workflow-status` — read-only stage progress and next step, JSON or human output.
- `workflow-doctor` — evidence/identity/stale-lock/drift diagnostics, recovery hints.
- `workflow-evidence` — manifests and download/retry status; no blind cleanup.

If the user wants a Windows-native, CLI-friendly experience, maintain existing `vm-lab -o <operation>` conventions, long and short flags, stable structured results and script-logging integration. Do not break old operation names.

## 2. Journal, idempotency and crash consistency

### Creation and identity

Generate operation ID once; never silently assign a new ID on resume. The selected target is identified by host, exact VM GUID, owner manifest, storage/config path and workflow digest. Before creation there is a planned target name/root and expected absence, after creation pin the returned VM ID and verified settings. A different target cannot reuse the same state file.

Use operation-root containment and same-volume, exclusive atomic writes for journal and receipts. Maintain a per-operation lock and per-VM mutation lock with diagnostic rather than destructive stale-lock treatment. Avoid ever trusting success marker alone: all step-specific observable effects must be re-probed on resume.

### At-most-once handling

Classify stages:

- `read_only`: safe to repeat after fresh identity checks.
- `idempotent`: safe to retry if observed target/artifacts match exact expected digest.
- `reconcilable`: external effect may have occurred; probe receipts/state first (VM create, checkpoint, asset finalization).
- `non_repeatable`: arbitrary acceptance mutations or installs not safe to rerun after uncertain transport; require project-provided run ID/status query or manual/authorized decision.

Never promise exactly-once semantics over a broken PS Direct session. Model uncertainty explicitly and reconcile by observed state plus guest-run receipt before repeating mutation.

### State machine

`PLANNED → AWAITING_AUTHORIZATION → RUNNING → [SUCCEEDED | AWAITING_INTERACTION | BLOCKED | PARTIAL | FAILED | INVALIDATED]`. A workflow is `SUCCEEDED` only when all **required** stages succeeded and required evidence is verified. Skipped stages do not become PASS. A failed cleanup never masks original failure.

Each attempt stores input/hash, actor, permission, before/after observations, result, timestamps, stdout/stderr, evidence hash manifest, and recovery hint. `operation.json` is a projection, not the only source of truth; immutable receipts provide forensic history. Retain earlier stage attempts on retry.

## 3. H4-like workflow template (synthetic, no active VM)

Create a reusable **example** workflow and a synthetic external acceptance project with equivalent properties:

1. Host preflight including ISO, RAM/disk, provenance and inventory.
2. `vm.create` for Gen 2 Windows with Secure Boot/vTPM, disconnected NIC, Standard checkpoints.
3. `vm.start` and VMConnect; Windows install/OOBE `AWAITING_INTERACTION` with a genuine stop/resume boundary.
4. `guest.wait` (PS Direct) plus OS/build/admin/Hyper-V identity and clean-inventory policy.
5. `artifact.deploy` Python MSI/EXE, wheel directory, bootstrap source and bundle ZIP with independently trusted SHA.
6. `guest.bootstrap` checks runtimes and offline dependencies.
7. `guest.exec` validates bundle digest/extracted manifest and writes immutable setup receipt **for the same operation ID**.
8. `vm.checkpoint_transaction` requires powered-off Standard checkpoint and records ID/name/time, then restarts VM and awaits PS Direct.
9. `guest.exec` runs synthetic external profiles `offline`, `task`, `full`, five named `rollback` faults and `cleanup` on failure.
10. `evidence.collect` retrieves nested files and manifest, with incomplete transfer report/retry.
11. Final project policy asserts zero real-task skips and complete evidence; otherwise FAIL or INCOMPLETE.
12. Optional user-authorized graceful stop; final summary and artifacts.

The module should know **nothing** about Resource Coordinator's actual task names, installer versions, source trees, ports, rollback labels or application authorization phrase. The synthetic adapter tests the same *shape* and error semantics.

### Project adapter contract

Project supplies:

- Validated external guest executable/script with release digest, argument array and explicit working root.
- `stage_profile` and idempotency classification.
- Optional expected JSON schema or typed predicates (`exit=0`, `status=passed`, `counts.skipped=0`), including project-specific safety preconditions.
- Scoped project cleanup descriptor when permitted; cleanup result is recorded separately and never replaces original failure.
- Allowed environment variables whose values are provided at execution time and not logged if secrets.
- A guest read-only status/receipt probe to determine whether a non-repeatable phase completed before a lost session.

No project's workflow definition can directly mutate host processes or bypass `vm_lab` ownership and approval gate.

## 4. Failure and resume matrix

| Failure point | Required behavior |
|---|---|
| Before create | Plan valid; no VM, retry with same operation. |
| After New-VM before manifest | Preserve partials, record uncertain owner; recovery plan, no automatic adoption. |
| After manifest before journal | Re-read ownership/VM, pin exact ID and reconcile; no duplicate VM. |
| During artifact transfer | Preserve completed verified files; retry missing only. |
| Installer returns 3010 | `AWAITING_REBOOT`, no automatic guest reboot; resume after explicit lifecycle authorization. |
| After setup receipt before journal | Revalidate receipt and bundle digest; no repeat Setup. |
| During Stop-VM wait | Report partial, wait/diagnose; no checkpoint until Off. |
| After checkpoint before journal | Enumerate snapshot and match exact ID/creation window, refuse ambiguous duplicate. |
| After Start-VM before PS Direct | Wait/probe only, don't restart blindly. |
| Guest exec transport loss | Query guest run ID/receipt; never re-run `non_repeatable` blindly. |
| Acceptance guest status failed | Preserve FAIL, trigger separately authorized project cleanup if specified. |
| Evidence copy interrupted | `INCOMPLETE`, keep guest data and enable evidence-only retry. |
| Host terminal killed | Resume from operation ID and validate every completed stage. |
| Target identity changed | INVALIDATED and fail closed; no mutation. |
| Approval absent/expired | BLOCKED; don't execute new mutation. |
| State corrupt/reparse escape | INVALIDATED; preserve bytes and provide forensic diagnosis. |

## 5. Observable status and alerts

Provide `status` with current stage, completion %, last success, blocker, required capability, next specific command and evidence locations. Include optional machine-readable `requires_intervention` flag; do not promise background notifications unless integrated with an actual supervising process and explicitly authorized interface. If the user later wants mobile/desktop alerts, add a transport-agnostic event emitter, not a new always-on daemon by default.

Make logs lean for agents but retain durable full logs and structured outcomes. Avoid unnecessary repeated large stdout dumps.

## 6. Tests

1. Schema validation: invalid keys, types, cycles, missing dependency, impossible power-state sequence.
2. Journal: atomic write interrupted, corrupted JSON, wrong VM ID, wrong host/root/digest, reparse path, concurrent operations, duplicate op ID.
3. Resume from every failure point above, with mutation call-count assertions.
4. Fake H4-like workflow through setup→checkpoint→five rollback profiles→evidence collection; all statuses and receipts tied to one ID.
5. Authorization: per-stage capability required, prior approval does not authorize future resume; `-WhatIf` zero writes.
6. Log/evidence corruption: a PASS cannot be declared if required stdout/stderr/source proof missing.
7. JSON stdout exactly one document with correct exit semantics; script logging and help integration.
8. Stress bounded high-volume wheel manifest and evidence directory; journal remains consistent.
9. Test two distinct VM workflows concurrently; no cross-target state leak and proper per-VM lock.
10. Project callback failure/retry/cancel semantics, ensuring project CLEANUP doesn't change prior FAIL.

Use real orchestration objects with fake Hyper-V/PS Direct adapters; no active H4 mutation and no local inference.

## Deliverables

- Documented workflow definition and runtime schemas, operation journal/receipt store.
- CLI implementation including plan/apply/resume/status/doctor/evidence.
- A complete H4-*like* example JSON and synthetic guest runner with five rollback scenarios.
- Deterministic fault-injection Pester suite and test evidence.
- Updated docs/README and coverage matrix state for every row in sections B–E.
- Validated commit, `STATUS.md`, and evidence bundles for success and failure.

## Acceptance gate (major architecture review point)

- [ ] No custom host PowerShell is necessary to orchestrate the synthetic H4-like scenario using typed `vm_lab` operations.
- [ ] One operation ID and immutable receipts survive process restarts; no duplicate setup, snapshot or acceptance mutation.
- [ ] Project-specific assertions remain external and are enforced by the generic runner's result policy.
- [ ] Per-file/evidence integrity and statuses prevent false PASS.
- [ ] Execution approval is granular; no privileged operations run from plan-only invocation.
- [ ] Mocked core end-to-end tests and legacy toolkit tests pass.

This phase proves the core value. Record a design/validation checkpoint and only then continue to privileged execution bridge and Windows setup automation. No additional high-level research handoff required unless actual blockers demand it.
