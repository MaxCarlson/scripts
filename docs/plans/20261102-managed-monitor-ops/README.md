# LLM Monitor + Agent Benchmark Managed Operations Plan

**Prepared:** 2026-11-02 • **Repository:** [`MaxCarlson/scripts`](https://github.com/MaxCarlson/scripts) • **Status:** Planning artifacts only.

This archive specifies a staged implementation to make LLM Monitor and Agent Benchmark self-managing across process discovery, readiness, authentication, environment diagnostics, bounded recovery and agent operating policy. It is **not** a statement that the features have been implemented, services restarted, inference dispatched, tests executed or branches merged.

## Start here

1. Read [`MASTER_PLAN.md`](MASTER_PLAN.md) for architecture, requirements, priority, dependencies, non-goals, acceptance standards and release strategy.
2. Run [`phases/PHASE_00_BASELINE.md`](phases/PHASE_00_BASELINE.md) **first** to audit current agents, branch/worktrees and the separate in-flight stop implementation. Do not start another agent modifying the same stop files.
3. Treat [`CONTRACTS.md`](CONTRACTS.md) as proposed interfaces/schema to freeze at Phase 00. Read [`SOURCE_NOTES.md`](SOURCE_NOTES.md) for evidence and unresolved uncertainties.
4. Execute Phase 01 through Phase 04 in dependent order, preferably with one primary implementer and checkpoint commits. Use Phase 05 for independent validation and Phase 06 for documentation/integration after approval.
5. Use [`VALIDATION_MATRIX.md`](VALIDATION_MATRIX.md) for adversarial regressions, commands and audit-ready evidence receipts.

## File index

| File | Contents |
|---|---|
| `MASTER_PLAN.md` | Full program architecture, current evidence, dependencies, acceptance and Git/authorization |
| `CONTRACTS.md` | Proposed CLI, managed descriptor, local control security, diagnostic codes, recovery model |
| `VALIDATION_MATRIX.md` | Exact incident regression cases, platform test tiers, evidence receipt |
| `SOURCE_NOTES.md` | Inspected repository paths/SHAs, Microsoft/Python/Uvicorn primary references |
| `phases/PHASE_00_BASELINE.md` | Branch/worktree/agent audit; reuse existing stop work |
| `phases/PHASE_01_LIFECYCLE.md` | Safe start/status/stop/restart and service readiness |
| `phases/PHASE_02_LOCAL_AUTH.md` | Protected local IPC and scoped auth bootstrap |
| `phases/PHASE_03_DOCTOR.md` | Sandbox-aware diagnostic command and errors |
| `phases/PHASE_04_RECOVERY.md` | Bounded preflight recovery with `-r` vs `-x` authorization |
| `phases/PHASE_05_VALIDATION.md` | Independent tests, host/WSL2/Docker qualification, evidence |
| `phases/PHASE_06_ROLLOUT.md` | Documentation, agent policy and safe integration |
| `MANIFEST.sha256` | SHA-256 checksums for content files in this archive |

## Key rules

**Do not compete with the already assigned stop-command agent.** A running Monitor with a config mismatch is **not** automatically restarted. A sandbox denial is **not** proof that the host service is down. Localhost by itself is **not** an authentication credential. No model inference without `-x/--execute`. The plan's optional `-r/--recover-local` is a distinct opt-in allowing startup of an absent *managed* Monitor only.

## Coordination and completion

Each phase supplies a recommended implementation model/effort, objective, constrained file ownership, implementation stages, tests, acceptance criteria and exact deliverables. Phase status should be recorded with commit SHA, changed files, executed test commands and exit codes, log artifacts, unresolved risks, and next gate. Do not claim Windows support from Linux-only mocks or consider a PR description proof of a local live process.
