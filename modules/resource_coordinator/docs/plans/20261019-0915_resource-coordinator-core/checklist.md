# Implementation Checklist: Resource Coordinator Core

## Stage 1: Generic Core Framework
- [x] Implement `resource_coordinator/core/events.py` (sync/async event dispatcher, blocking pre-action hooks, non-blocking listeners)
- [x] Implement `resource_coordinator/core/leases.py` (lease manager, shared/exclusive modes, pending queue, idle cooldowns)
- [x] Implement `resource_coordinator/core/processes.py` (process supervisor, backend protocol, fake backend, Windows backend with PID+create_time verification)
- [x] Implement `resource_coordinator/core/conditions.py` (predicates, composite All/Any/Not, numeric comparisons, hold duration)
- [x] Implement `resource_coordinator/core/actions.py` (process start/stop, lease acquire/release, custom callables, action outcomes)
- [x] Implement `resource_coordinator/core/policies.py` (policy definition, trigger-condition-action-lease pipeline execution)
- [x] Implement `tests/test_events.py`
- [x] Implement `tests/test_leases.py`
- [x] Implement `tests/test_processes.py`
- [x] Implement `tests/test_conditions.py`
- [x] Implement `tests/test_policies.py`
- [x] Verify Stage 1 tests pass offline

## Stage 2: Telemetry Monitors, Adapters, Gateway & CLI
- [x] Implement `resource_coordinator/monitors/cpu.py` (CPU utilization provider)
- [x] Implement `resource_coordinator/monitors/gpu.py` (GPU utilization provider)
- [x] Implement `resource_coordinator/adapters/miners/adapter.py` (miner adapter with ownership and manual override)
- [x] Implement `resource_coordinator/adapters/lmstudio/gateway.py` (reverse proxy ASGI app, SSE streaming passthrough, activity tracking)
- [x] Implement `resource_coordinator/config.py` (YAML/JSON policy configuration contract and validator)
- [x] Implement `resource_coordinator/cli.py` (`resource-coordinator` and `gpu-coordinator` CLI entrypoint)
- [x] Implement `tests/test_miner_adapter.py`
- [x] Implement `tests/test_gateway.py` (mock upstream, concurrent requests, streaming, disconnect cancellation)
- [x] Implement `tests/test_config.py`
- [x] Implement `tests/test_cli.py`
- [x] Verify Stage 2 tests pass offline

## Stage 3: Verification, Documentation & Handoff
- [x] Run full test suite with coverage
- [x] Run code format and lint checks (`ruff check`, `black --check`)
- [x] Update README, HANDOFF, and STATUS docs with execution evidence
- [ ] Commit staged deliverables
- [ ] Deliver final report and handoff to Codex Sol Medium
