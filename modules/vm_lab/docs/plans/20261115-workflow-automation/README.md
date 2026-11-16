# vm-lab Workflow Automation — Plan Bundle

**Status:** design package, not implementation. **Prepared:** 2026-11-15. **Target:** `MaxCarlson/scripts`, `modules/vm_lab`.

This package contains a master plan and seven implementation phases (0–6), based on the observed Windows Hyper-V work in **Worker-ResourceCoordinator**, the H4 qualification scripts, and the `vm-lab` code that has been integrated into `main`.

## Read first

1. [`MASTER_IMPLEMENTATION_PLAN.md`](MASTER_IMPLEMENTATION_PLAN.md) — scope, milestones, priorities, cross-phase dependencies, acceptance definition.
2. [`WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md`](WORKER_RESOURCECOORDINATOR_COVERAGE_MATRIX.md) — every recovered VM-related H4 operation/problem mapped to existing features or an implementation phase.
3. [`ARCHITECTURE.md`](ARCHITECTURE.md) — trust boundaries, interfaces, durable schemas, idempotency, security, CLI contracts.
4. [`RESEARCH_AND_DECISIONS.md`](RESEARCH_AND_DECISIONS.md) — official references, verified source observations, decisions and unresolved risks.
5. [`STATUS.md`](STATUS.md) — initial status; owning agent updates this after validating actual repo and executing tests.
6. `PHASE_00_BASELINE.md` through `PHASE_06_ACCEPTANCE.md` — executable scopes and verification gates.

## Extraction

ZIP paths are rooted at `modules/vm_lab/docs/plans/20261115-workflow-automation/`. Extract **at the root of the `scripts` repository** so these documents land at the intended location. This bundle is documentation only; it does not mutate a repository or virtual machine. If this path already contains local work, review collisions before extraction.

## Operating rule

The active H4 workflow is **not** a migration target. Its running VM, operation ID, setup receipt, checkpoints and acceptance evidence are protected. Implement and test generic capabilities in an isolated worktree; reproduce an **H4-like** workflow with synthetic fixtures and a separate authorized disposable VM, not by taking over active H4.

## Agent start

Read the five overview documents and Phase 0. Audit actual current branches/worktrees and source before editing. Reconcile the plan against any newer source changes; preserve source APIs. Commit Phase 0 artifacts and validated code checkpoints. Continue into safe phases; stop at real VM mutation/elevation/production boundaries that need separate authorization.
