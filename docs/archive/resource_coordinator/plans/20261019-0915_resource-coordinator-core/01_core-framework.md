# Stage 1 Plan: Generic Core Framework

**Goal**: Implement and test the core primitives of `resource_coordinator`: events, leases, processes, conditions, actions, and policies.

## 1. Files & Responsibilities
- `resource_coordinator/core/events.py`: `EventDispatcher` supporting blocking lifecycle hooks (which can veto or delay actions) and non-blocking background listeners.
- `resource_coordinator/core/leases.py`: `LeaseManager` tracking active and pending claims on named resources (`LeaseType.SHARED` vs `LeaseType.EXCLUSIVE`), coordinating idle cooldown timers upon release.
- `resource_coordinator/core/processes.py`: `ProcessSupervisor` and `ProcessBackend` abstraction (with `FakeProcessBackend` and Windows-specific PID/create-time verified backend).
- `resource_coordinator/core/conditions.py`: Predicates with `AllCondition`, `AnyCondition`, `NotCondition`, hold times, and threshold checks.
- `resource_coordinator/core/actions.py`: Action pipeline executing process start/stop, lease acquisition/release, or custom callables with typed outcomes.
- `resource_coordinator/core/policies.py`: `PolicyEngine` matching events against policies, executing conditions, acquiring leases, and performing release actions.

## 2. Test Plan
- `tests/test_events.py`: Registering sync/async listeners, blocking hooks, vetoing operations, exception isolation in non-blocking listeners.
- `tests/test_leases.py`: Shared leases incrementing active count; exclusive leases queueing; cooldown timer starting on final release; incoming lease during cooldown cancelling cooldown; manual release.
- `tests/test_processes.py`: Fake backend start, stop, wait_stopped; ownership tracking (`is_coordinator_owned`); external process detection; restart cooldown.
- `tests/test_conditions.py`: Composite conditions (`All`, `Any`, `Not`), numeric thresholds, hold duration.
- `tests/test_policies.py`: End-to-end policy execution with fake process: event fires -> condition matches -> stop action -> lease acquired -> release -> cooldown -> restart action.
