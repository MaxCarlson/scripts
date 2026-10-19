# Resource Coordinator Documentation

## Architecture & Design

`resource_coordinator` coordinates local resource contention among competing processes.

### Key Components

1. **`core/events.py`**: Generic event dispatcher with support for blocking lifecycle hooks (which can veto or delay an operation until preconditions are met) and non-blocking observational listeners.
2. **`core/leases.py`**: Named resource lease manager. Manages shared and exclusive leases, counts active and pending operations, and drives configurable idle cooldown timers upon the release of the last active lease.
3. **`core/processes.py`**: Process supervisor abstraction (`ProcessBackend`). Distinguishes coordinator-owned processes from external processes, tracks PID and creation times to prevent PID-recycling errors, and provides both a mock/fake backend for offline testing and a robust Windows process manager.
4. **`core/conditions.py`**: Evaluation predicates with logical composition (`All`, `Any`, `Not`), threshold comparison, rolling window aggregation, and hold durations.
5. **`core/actions.py`**: Action executions (process stop, process start, lease acquisition, lease release, custom Python callables) with clear outcome reporting (`SUCCESS`, `FAILURE`, `SKIPPED`, `INDETERMINATE`).
6. **`core/policies.py`**: Policy engine tying triggers, conditions, actions, leases, and release callbacks into declarative rules.
7. **`adapters/lmstudio/gateway.py`**: Transparent asynchronous HTTP reverse proxy intercepting OpenAI-compatible and native LM Studio API endpoints, tracking streaming and non-streaming inference requests, and coordinating leases.
8. **`adapters/miners/adapter.py`**: Application adapter for cryptocurrency miners (such as Krig/Kryptex PearlMiner) managing pause ownership and manual overrides.

## Documentation Index

- [HANDOFF.md](HANDOFF.md): Immediate state, branch info, active plans, risks, and next steps.
- [plans/HANDOFF.md](plans/HANDOFF.md): Plan index and history.
- [plans/20261019-0915_resource-coordinator-core/00_implementation-plan.md](plans/20261019-0915_resource-coordinator-core/00_implementation-plan.md): Master implementation plan for Phase 1 & 2.
