# Checklist — Phase D: Controlled Service Integration and Supervised-Test Readiness

## Stage 1: Service Lifecycle & Readiness State Machine
- [x] Define `ServiceState` enum (`CREATED`, `INITIALIZING`, `PREFLIGHT`, `READY`, `DRAINING`, `STOPPED`, `FAILED`, `RECONCILIATION_REQUIRED`)
- [x] Implement `CoordinatorService` encapsulating `CoordinatorSystem`
- [x] Implement startup preflight checks (config validity, capability verification, process table check)
- [x] Implement bounded graceful shutdown with active lease tracking and non-restarting guarantees
- [x] Wire service lifecycle into `cli.py` (`serve`, `preflight`, `abort`)
- [x] Write unit tests for `CoordinatorService` lifecycle transitions

## Stage 2: Centralized Request Admission & Route Classification
- [x] Implement `OperationKind` and `OperationClassifier`
- [x] Implement `AdmissionController` gating all incoming proxy traffic on `ServiceState.READY`
- [x] Ensure non-ready states return HTTP 503 (`coordinator_not_ready` / `coordinator_draining`)
- [x] Fail-closed on unsupported state-mutating requests (HTTP 501)
- [x] Fail-closed on model loading without blocking policy hooks (HTTP 503)
- [x] Integrate admission controller into `LMStudioGateway`
- [x] Write unit tests for request classification and admission gating

## Stage 3: Offline Integration Test Suite (16 Scenarios)
- [x] Scenario 1: Request received before startup finishes (HTTP 503)
- [x] Scenario 2: Invalid or incomplete configuration (startup fails closed)
- [x] Scenario 3: Startup failure after partial component initialization
- [x] Scenario 4: Successful simulated mining-to-inference transition
- [x] Scenario 5: Miner stop requested but never verified (veto, inference blocked)
- [x] Scenario 6: New inference arriving during cooldown or pending restart
- [x] Scenario 7: Concurrent protected requests and model-loading operations
- [x] Scenario 8: Cancellation at each major admission transition
- [x] Scenario 9: Normal streaming completion vs truncated/uncertain termination
- [x] Scenario 10: Shutdown with active inference (draining, bounded wait, no miner restart)
- [x] Scenario 11: Unexpected miner relaunch detection
- [x] Scenario 12: Recycled PID or ambiguous process identity handling
- [x] Scenario 13: Unsupported inference endpoint (fail closed 501)
- [x] Scenario 14: Attempted model-management bypass
- [x] Scenario 15: Coordinator restart with unresolved or missing safety state
- [x] Scenario 16: Emergency abort with incomplete identity information

## Stage 4: Documentation, Supervised Acceptance Plan & Sol Review
- [x] Author `EMERGENCY_ABORT_PROCEDURE.md`
- [x] Update `SUPERVISED_LIVE_ACCEPTANCE_PLAN.md` with exact identity & client isolation gates
- [x] Author `PHASE_D_INTEGRATION_HANDOFF.md`
- [x] Run full test suite, Ruff check, Ruff format (120 cols), and Mypy
- [x] Commit Phase D changes and halt for Sol Medium review
