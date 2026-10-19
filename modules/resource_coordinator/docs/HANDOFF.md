# Resource Coordinator Module Handoff

## Current Status (2026-10-19)

- **Module**: `modules/resource_coordinator`
- **Active Branch**: `resource-coordinator-20261019-0915`
- **Worktree**: `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-20261019-0915`
- **Active Plan**: [plans/20261019-0915_resource-coordinator-core/00_implementation-plan.md](plans/20261019-0915_resource-coordinator-core/00_implementation-plan.md)
- **Status**: Stages 1 and 2 Complete, fully tested offline (38 passing tests), lint and formatting clean.

## Work Completed by Gemini Agent

1. **Architecture Reconciliation**:
   - Generic event-driven resource coordination framework created, decoupling core arbitration from specific GPU or LLM models.
   - Five core concepts implemented: Triggers, Conditions, Actions, Events, and Resource Leases.
   - Applications (LM Studio reverse proxy, cryptocurrency miner) implemented as modular adapters.
2. **Generic Core Framework (`resource_coordinator/core/`)**:
   - `events.py`: Sync/async event dispatcher with blocking lifecycle hooks (can veto operations) and isolated observational listeners.
   - `leases.py`: Named resource lease arbitration supporting shared and exclusive leases, active/pending tracking, and idle cooldown timers with immediate cancellation on new activity.
   - `processes.py`: Process supervisor with `ProcessBackend` abstraction, `FakeProcessBackend` for offline testing, and `WindowsProcessBackend` with PID + creation-time validation to prevent PID recycling hazards.
   - `conditions.py`: Extensible predicates supporting composite `All`, `Any`, `Not`, process states, lease states, and numeric threshold checks with hold-duration hysteresis.
   - `actions.py`: Typed action pipeline (`StopProcessAction`, `StartProcessAction`, `CallableAction`, `CommandAction`) with explicit outcome reporting (`SUCCESS`, `FAILURE`, `SKIPPED`, `INDETERMINATE`).
   - `policies.py`: Declarative policy engine binding triggers, conditions, actions, resource leases, and after-release actions.
3. **Monitors & Adapters (`resource_coordinator/monitors/`, `resource_coordinator/adapters/`)**:
   - `monitors/cpu.py`: CPU telemetry with rolling history via `psutil`.
   - `monitors/gpu.py`: Pluggable GPU telemetry provider.
   - `adapters/miners/adapter.py`: Miner adapter coordinating Krig/Kryptex, manual pause overrides, and namespaced events (`mining.stop_requested`, `mining.stopped`, `mining.started`).
   - `adapters/lmstudio/gateway.py`: Transparent Starlette/HTTPX reverse proxy intercepting inference and model-loading requests, streaming SSE chunk-by-chunk without RAM buffering, tracking active inferences, and releasing leases upon stream completion or client disconnect.
4. **Configuration & CLI (`config.py`, `cli.py`)**:
   - Versioned YAML/JSON policy contract (`v1.0`).
   - CLI commands `serve`, `status`, `config show/validate`, `miner status/pause/resume` with dual short/long argument support adhering to repository standards.
   - Console entry points `resource-coordinator` and `gpu-coordinator` registered in `pyproject.toml`.
5. **Offline Test Suite (`tests/`)**:
   - 38 passing offline tests covering the full pipeline: events, leases, concurrency, process supervision, conditions, policies, telemetry, configuration parsing, CLI, and mock upstream streaming gateway.

## Environment & Preconditions Respected

- **No live miner processes** were killed or manipulated during this development.
- **No live LM Studio** inference requests or shared service configurations were altered.
- All testing ran offline against mock ASGI apps and fake process backends.
- Work conducted in isolated worktree `C:\Users\mcarls\src\scripts\.worktrees\resource-coordinator-20261019-0915`.

## Next Steps for Codex Sol Medium

1. **Architecture & Integration Review**: Review the generic core contracts, configuration schema, and adapter designs against repository conventions.
2. **Phase C (Real Miner Validation)**: Under explicit user authorization, test `WindowsProcessBackend` against the live `krig-miner.exe` process (verifying graceful shutdown, stop confirmation, and restart).
3. **Phase D (Model Lifecycle Management)**: Extend native model management policies (managed TTL, persistent exemptions, observational sync with `GET /api/v1/models`).
4. **Phase E (Shared Client Configuration Migration)**: Update client configurations (`modules/lmstui`, `modules/local_agent_bridge`, `modules/llm_local`, and `agent_benchmark`) to route through `127.0.0.1:1235` when enabled.
