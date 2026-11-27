# Stage 2 Plan: Telemetry Monitors, Adapters, Gateway & CLI

**Goal**: Implement the LM Studio reverse proxy gateway, miner adapter, telemetry monitors, configuration loading, and CLI.

## 1. Files & Responsibilities
- `resource_coordinator/monitors/cpu.py`: CPU telemetry provider via `psutil`.
- `resource_coordinator/monitors/gpu.py`: Pluggable GPU telemetry provider.
- `resource_coordinator/adapters/miners/adapter.py`: Miner adapter coordinating Krig/Kryptex with manual pause overrides.
- `resource_coordinator/adapters/lmstudio/gateway.py`: Reverse proxy ASGI app using Starlette & HTTPX, intercepting `/v1/*` and `/api/v1/*`, forwarding streaming SSE responses, tracking active requests.
- `resource_coordinator/config.py`: YAML/JSON configuration parser and policy builder.
- `resource_coordinator/cli.py`: CLI entrypoint supporting `serve`, `status`, `config show`, etc.

## 2. Test Plan
- `tests/test_miner_adapter.py`: Pause, resume, manual override, ownership verification.
- `tests/test_gateway.py`:
  - Mock upstream server simulating LM Studio responses and SSE streaming.
  - Proxying normal chat completions and streaming SSE chunks.
  - Verifying lease acquisition and release per request.
  - Verifying concurrent requests share a single process stop.
  - Verifying client disconnect or upstream error releases the lease without corruption.
  - Verifying non-inference endpoints (e.g. `/v1/models`) do not trigger mining stop.
- `tests/test_config.py`: Parsing valid and invalid YAML policies.
- `tests/test_cli.py`: CLI argument parsing, status output, JSON formatting.
