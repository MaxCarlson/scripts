# Implementation Plan — Phase D: Controlled Service Integration and Supervised-Test Readiness

**Document version:** 1.0  
**Date:** 2026-10-19  
**Status:** In Progress (Checkpoint A — Design)  
**Branch:** `resource-coordinator-phase-d`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-phase-d`  
**Baseline Commit:** `3744c4c2`  

---

## 1. Goal & Architectural Boundaries

Advance `resource_coordinator` from independently tested components toward an operational, coordinator-owned service capable of safely controlling contention between GPU mining and local LLM inference.
The target is a **narrow, human-supervised integration test**, not unattended production operation.

### Scope Separation
- **Gemini (Autonomous Implementation):**
  - Application startup/shutdown wiring around existing safety primitives.
  - Configuration loading, validation, and read-only preflight checks.
  - Explicit service readiness state machine (`CREATED -> INITIALIZING -> PREFLIGHT -> READY -> DRAINING -> STOPPED`).
  - Centralized route classification and admission interfaces (`OperationClassifier`, `AdmissionController`).
  - Safe rejection of requests while the service is not ready (503 Service Unavailable).
  - Mock-backed lifecycle integration.
  - CLI diagnostics, preflight, and abort commands.
  - Comprehensive offline integration tests (covering all 16 specified failure & concurrency modes).
  - Documentation and supervised-test procedures.
- **Reserved for Codex Sol Medium Review:**
  - Resource ownership or arbitration semantics.
  - Lease acquisition/release invariants.
  - Process stop/restart authorization.
  - Restart-inhibition clearing rules.
  - Upstream termination guarantees.
  - Cross-resource transactions.
  - Crash recovery and durable safety state.

---

## 2. Stages

- [ ] **Stage 1: Service Lifecycle & Readiness State Machine**
  - Implement `CoordinatorService` and `ServiceState` enum in `resource_coordinator/core/service.py`.
  - Wire startup preflight sequence (configuration verification, capability checks, deterministic dependency order).
  - Wire bounded draining shutdown (refusing new protected operations, tracking active claims, preserving inhibitions, never auto-restarting mining on shutdown).
- [ ] **Stage 2: Centralized Request Admission & Route Classification**
  - Implement `OperationClassifier` in `resource_coordinator/adapters/lmstudio/admission.py` with explicit endpoint mapping (`METADATA_READ`, `INFERENCE`, `MODEL_MUTATION`, `UNSUPPORTED`).
  - Integrate `AdmissionController` into `LMStudioGateway`, gating all proxy routes on `CoordinatorService` readiness.
  - Enforce fail-closed defaults for unknown or uncoordinated mutating endpoints.
- [ ] **Stage 3: Offline Integration Test Suite**
  - Implement `tests/test_service_lifecycle.py` and `tests/test_integration_phase_d.py`.
  - Verify all 16 required offline scenarios (pre-readiness rejection, invalid config, partial init failure, mining-to-inference transition, unverified stop veto, cooldown interleaving, concurrent claims, cancellations at all stages, truncated streaming, shutdown with active claims, unexpected relaunch, recycled PID, unsupported endpoint, model bypass attempt, missing state, emergency abort).
  - Maintain 100% pass rate across existing 151 tests.
- [ ] **Stage 4: Supervised Acceptance Plan, Emergency Abort & Sol Handoff**
  - Author `modules/resource_coordinator/docs/EMERGENCY_ABORT_PROCEDURE.md`.
  - Update `modules/resource_coordinator/docs/SUPERVISED_LIVE_ACCEPTANCE_PLAN.md` with exact process identity verifications and single-client isolation procedures.
  - Author `modules/resource_coordinator/docs/PHASE_D_INTEGRATION_HANDOFF.md` for Sol Medium review.
  - Complete Checkpoint B & C.
