# Phase D: Controlled Service Integration and Supervised-Test Readiness Architecture & Design Specification

**Document version:** 1.0  
**Date:** 2026-10-19  
**Review Checkpoint:** Checkpoint A — Design  
**Module:** `modules/resource_coordinator`  
**Target Hardware:** Windows 11 / NVIDIA GeForce RTX 5090 (32 GB VRAM)  
**Target Workloads:** LM Studio 0.3.x (Port 1234) & Krig Miner 1.5.6 (PEARL)  

---

## 1. Executive Summary & Objective

The objective of Phase D is to advance `resource_coordinator` from independently tested components toward an operational, coordinator-owned service capable of safely controlling contention between GPU mining and local LLM inference.
The immediate target is a **narrow, human-supervised integration test**, strictly bounded to:
1. One known GPU (RTX 5090).
2. One known coordinator-owned Krig process instance.
3. One preloaded Qwen model in LM Studio.
4. One authorized inference client connecting to port 1235.
5. No concurrent external inference or model swapping.
6. Absolute ban on unverified miner watchdogs or uncontrolled auto-relaunch.

This document establishes the architecture, dependency graph, lifecycle state machine, and centralized admission contract required before proceeding with code implementation.

---

## 2. Component Dependency Graph & Reusable Primitives

The coordinator currently possesses battle-tested, safety-reviewed primitives (151 offline tests passing at baseline `3744c4c2`). Phase D does not rewrite these primitives; it wraps them in a deterministic service lifecycle and centralized admission gate:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        CoordinatorService                              │
│  State: CREATED -> INITIALIZING -> PREFLIGHT -> READY -> DRAINING      │
│  Owns: Startup Verification, Preflight Probes, Bounded Shutdown, Abort │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        AdmissionController                             │
│  Gated by ServiceState.READY                                           │
│  OperationClassifier: METADATA_READ | INFERENCE | MODEL_MUTATION       │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   ▼                                 ▼
┌──────────────────────────────────┐ ┌───────────────────────────────────┐
│         LMStudioGateway          │ │           LeaseManager            │
│  HTTP Proxy / StreamDetector     │ │  Two-stage reserve() -> activate()│
│  Header Sanitization             │ │  Protective RestartInhibition     │
└──────────────────┬───────────────┘ └─────────────────┬─────────────────┘
                   │                                   │
                   └─────────────────┬─────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │           PolicyEngine            │
                   │  resource.lease_requested trigger │
                   │  resource.idle trigger            │
                   └─────────────────┬─────────────────┘
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │         ProcessSupervisor         │
                   │  Single-instance ownership        │
                   │  CREATE_NEW_PROCESS_GROUP         │
                   │  CTRL_BREAK_EVENT Graceful Stop   │
                   └───────────────────────────────────┘
```

### 2.1 Inventory of Existing Reusable Primitives

1. **`LeaseManager` (`core/leases.py`):**
   - Atomic two-stage reservation (`reserve()` async context manager). Synchronously increments `pending_count` and cancels running idle cooldowns before any external side effects occur.
   - Reference-counted shared leases (`gpu.inference`) and exclusive leases (`gpu.model_loading`).
   - Protective non-clearing `RestartInhibition` with authenticated operator recovery.
2. **`ProcessSupervisor` (`core/processes.py`):**
   - Exact Windows creation timestamp verification (`create_time`).
   - Single-instance `_lock` preventing start/stop interleaving races.
   - Graceful console signal delivery (`CTRL_BREAK_EVENT` in dedicated process group).
   - Post-stop verification ensuring process is genuinely absent before reporting success.
3. **`PolicyEngine` & Actions (`core/policies.py`, `core/actions.py`):**
   - Declarative binding of triggers to actions (`StopProcessAction`, `StartProcessAction`).
   - Blocking hooks that veto admission (`VetoOperation`) if a process action fails.
4. **`StreamCompletionDetector` (`adapters/lmstudio/gateway.py`):**
   - Protocol-aware SSE parser detecting `data: [DONE]`, `chat.end`, `response.completed`, and choice-level `finish_reason`.
   - Distinguishes confirmed completion from partial streams, errors, client disconnects, and oversized frames.

---

## 3. Coordinator-Owned Service Lifecycle

The existing implementation uses `uvicorn.run(app)` directly in `cli.py`, which immediately begins listening on the HTTP socket without establishing verified readiness, starting the miner, or handling graceful draining on shutdown.

Phase D introduces `CoordinatorService` with explicit, observable lifecycle states:

```
               ┌───────────────┐
               │    CREATED    │
               └───────┬───────┘
                       │ service.start()
                       ▼
               ┌───────────────┐
               │ INITIALIZING  │
               └───────┬───────┘
                       │ dependencies wired & validated
                       ▼
               ┌───────────────┐     Failure
               │   PREFLIGHT   ├─────────────────┐
               └───────┬───────┘                 │
                       │ checks passed           ▼
                       ▼                  ┌──────────────┐
               ┌───────────────┐          │  NOT_READY / │
               │     READY     │          │    FAILED    │
               └───────┬───────┘          └──────────────┘
                       │ shutdown requested
                       ▼
               ┌───────────────┐
               │   DRAINING    │ (bounded wait for active requests)
               └───────┬───────┘
                       │ active = 0 or timeout
                       ▼
               ┌───────────────┐
               │    STOPPED    │ (processes safely stopped or held)
               └───────────────┘
```

### 3.1 Lifecycle Invariants

1. **Gate Closed During Startup:** While in `CREATED`, `INITIALIZING`, or `PREFLIGHT`, all proxy routes **must** reject incoming inference and model requests with HTTP 503 (`coordinator_not_ready`).
2. **Deterministic Preflight Verification:**
   - Configuration is validated against strict schema rules.
   - Resource and policy references are verified for internal consistency.
   - Configured process executables and working directories are checked for existence and accessibility.
   - Host process table is inspected to ensure no unmanaged, orphaned, or competing miner watchdogs are running.
   - If configured to own the miner on boot (`start_miner_on_ready=True`), Krig is launched in a dedicated process group and verified alive before transitioning to `READY`.
3. **Draining and Shutdown Guarantees:**
   - Transitioning to `DRAINING` immediately closes the admission gate: new inference requests receive HTTP 503 (`coordinator_draining`).
   - The service waits up to `drain_timeout_seconds` for active leases and pending reservations to unwind.
   - If active requests fail to terminate within the drain deadline, the service logs an indeterminate outcome and imposes a persistent restart inhibition.
   - **Crucial Rule:** The coordinator **never** restarts a stopped miner merely because the coordinator is shutting down. Mining resumption requires proven idle safety, which shutdown does not establish.

---

## 4. Centralized Request Admission

Currently, routing logic is embedded directly within `gateway.py` methods. Phase D centralizes route evaluation into `OperationClassifier` and `AdmissionController`.

### 4.1 Endpoint Classification Matrix

| Endpoint | Method | Operation Kind | Coordination Action |
| :--- | :--- | :--- | :--- |
| `/v1/models`, `/api/v0/models` | `GET`, `HEAD` | `METADATA_READ` | Direct forward without pausing miner (if service `READY`). |
| `/_coordinator/status` | `GET` | `INTERNAL_STATUS` | Handled internally; returns health, leases, state. |
| `/_coordinator/recover` | `POST` | `INTERNAL_RECOVER`| Authenticated operator recovery override. |
| `/v1/chat/completions` | `POST` | `INFERENCE` | Shared lease `gpu.inference`. Pre-stop miner. Track stream. |
| `/v1/completions` | `POST` | `INFERENCE` | Shared lease `gpu.inference`. Pre-stop miner. Track stream. |
| `/v1/embeddings` | `POST` | `INFERENCE` | Shared lease `gpu.inference`. Pre-stop miner. Non-streaming. |
| `/v1/responses` | `POST` | `INFERENCE` | Shared lease `gpu.inference`. Pre-stop miner. Track stream. |
| `/api/v0/chat/completions` | `POST` | `INFERENCE` | Shared lease `gpu.inference`. Pre-stop miner. Track stream. |
| `/api/v0/model/load` | `POST` | `MODEL_MUTATION` | Exclusive lease `gpu.model_loading`. Pre-stop miner. |
| `/api/v0/model/unload` | `POST` | `MODEL_MUTATION` | Exclusive lease `gpu.model_loading`. Pre-stop miner. |
| `/api/v1/models/load` | `POST` | `MODEL_MUTATION` | Exclusive lease `gpu.model_loading`. Pre-stop miner. |
| *Any other mutating path* | `POST`, `PUT`, `DELETE` | `UNSUPPORTED_MUTATING` | **Fail closed:** HTTP 501 Unsupported. |
| *Unrecognized GET path* | `GET` | `UNKNOWN_READ` | Direct forward (if `READY`) with warning log. |

### 4.2 Admission Execution Flow

For each `INFERENCE` or `MODEL_MUTATION` request:
1. **Readiness Check:** If `service.state != ServiceState.READY`, return HTTP 503 with JSON error `{"error": {"type": "coordinator_not_ready"}}`.
2. **Two-Stage Atomic Reservation:** Enter `async with lease_mgr.reserve(resource, lease_type, request_id)`:
   - Synchronously increments `pending_count`.
   - Synchronously cancels active cooldown timer on the resource.
3. **Blocking Pre-Forwarding Hooks:** Policy executes `StopProcessAction`.
   - Sends `CTRL_BREAK_EVENT` to Krig process group.
   - Waits for process termination and confirms absence via process table query.
   - If stop fails or times out, raises `VetoOperation`. Request is rejected with HTTP 503; request does **not** reach upstream LM Studio.
4. **Lease Promotion:** Await `reservation.activate()`. Pending count decrements, active count increments.
5. **Upstream Forwarding & Stream Tracking:** Forward HTTP request to LM Studio port 1234.
   - For SSE streams: Feed bytes through `StreamCompletionDetector`.
   - If stream completes normally (`[DONE]`, `finish_reason`), mark `completed = True`.
   - If client disconnects or connection drops before `[DONE]`, leave `completed = False`.
6. **Cleanup & Retention:**
   - On close: If forwarded but not completed, invoke `lease_mgr.inhibit_restart(resource, ...)`.
   - Release lease. If active and pending count are 0, and restart is not inhibited, start idle cooldown (30s).
   - If restart is inhibited, idle cooldown does **not** start; miner remains safely stopped.

---

## 5. Scope & Ownership Demarcation

### 5.1 Gemini Implementation Scope (Autonomous)
- Create `resource_coordinator/core/service.py` (`CoordinatorService`, `ServiceState`).
- Create `resource_coordinator/adapters/lmstudio/admission.py` (`OperationClassifier`, `AdmissionController`).
- Integrate service lifecycle and admission controller into `LMStudioGateway` and `cli.py`.
- Add `preflight` and `abort` subcommands to `cli.py`.
- Implement comprehensive offline integration test suite (`tests/test_service_lifecycle.py`, `tests/test_integration_phase_d.py`) covering all 16 specified scenarios.
- Author `EMERGENCY_ABORT_PROCEDURE.md` and update `SUPERVISED_LIVE_ACCEPTANCE_PLAN.md`.

### 5.2 Reserved for Sol Medium Review & Approval
- Any changes to `LeaseManager` arbitration logic, mutex scopes, or `RestartInhibition` invariants.
- Any modification to Windows process creation flags (`CREATE_NEW_PROCESS_GROUP`, `CREATE_NO_WINDOW`).
- Cross-resource transaction semantics (e.g. atomic composite claims between `gpu.inference` and `gpu.model_loading`).
- Durable crash-recovery write-ahead journal semantics (deferred to unattended milestone).
- Final authorization for live execution on RTX 5090.

---

## 6. Offline Test Verification Plan (16 Scenarios)

The offline integration test suite will validate:
1. `test_admission_rejected_before_ready`: Request received during `INITIALIZING` or `PREFLIGHT` returns HTTP 503.
2. `test_preflight_fails_on_invalid_config`: Malformed config or non-existent path triggers `ServiceState.FAILED`.
3. `test_startup_failure_after_partial_init`: Process failure during boot leaves service in `FAILED`, admitting zero requests.
4. `test_full_mining_to_inference_transition`: Clean normal path from mining -> inference -> cooldown -> resumption.
5. `test_miner_stop_unverified_vetoes_forwarding`: Unverified stop raises `VetoOperation`; request never forwarded.
6. `test_inference_during_cooldown_resets_restart`: New arrival immediately cancels pending miner restart.
7. `test_concurrent_inference_and_model_load`: Shared inference leases vs exclusive model loading.
8. `test_cancellation_during_admission_phases`: Client disconnects during pre-stop, activation, or forwarding.
9. `test_streaming_truncation_enforces_inhibition`: Truncated stream leaves protective restart hold.
10. `test_shutdown_draining_with_active_inference`: `DRAINING` blocks new requests and waits for in-flight streams.
11. `test_unexpected_miner_relaunch_detected`: Supervisor auto-relaunch detected and treated as error.
12. `test_recycled_pid_defense`: Process with mismatched creation time rejected without sending kill signals.
13. `test_unsupported_mutating_endpoint_rejected`: POST to unmapped endpoint fails closed with HTTP 501.
14. `test_model_load_bypass_attempt_rejected`: Model load without blocking hook returns HTTP 503.
15. `test_coordinator_restart_with_missing_state`: Startup gates closed on missing or corrupt state file.
16. `test_emergency_abort_safety`: Emergency abort stops admission, cancels restarts, and preserves holds without destructive unknown kills.
