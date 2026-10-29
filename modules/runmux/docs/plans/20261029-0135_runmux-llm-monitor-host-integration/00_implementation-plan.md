# Runmux + LLM Monitor Host-Side Integration Plan

**Date:** October 29, 2026  
**Module:** `modules/runmux/`  
**Feature Branch:** `runmux-llm-monitor-host-integration-20261029`  
**Worktree:** `.worktrees/runmux-llm-monitor-host-integration-20261029`  
**Baseline:** `c34739c5b3fe41f9cd3c63a19c4991e7da519fec` (`origin/main`)  

## 1. Objective

Integrate the merged LLM Monitor 0.5.0 read-only functionality into Runmux Web as an optional, authenticated, read-only monitoring workspace without duplicating collectors, modifying monitoring implementations, or interfering with concurrent agent work.

## 2. Integration Context & Concurrency Boundaries

- **LLM Monitor Baseline:** Merged into `origin/main` at `c34739c5`. Provides `llm_monitor.runmux_adapter.RunmuxMonitoringAdapter`, `ObservabilityService`, and `TelemetryStore`.
- **Runmux Server Lifecycle:** Unmerged on feature branch `runmux-web-server-lifecycle-20261029` (commit `3881681d`). Changes in `web.py` must remain additive and backwards-compatible with both `main` and `3881681d`.
- **Phase 6C History Explorer:** Unmerged on branch `codex/runmux-6c-history-frontend-local-pilot-20261024` (commit `a03b4fa6`), awaiting independent audit. Under Stage 3 rules, `web_static/` ownership remains held by Phase 6C until integration or release. Stages 1 and 2 (lazy integration factory and authenticated HTTP APIs) will be completed, thoroughly tested, and published independently, followed by reporting the blocked frontend stage.
- **Strict Boundary:** Do not modify `modules/llm_monitor/`, `modules/local_agent_bridge/`, or another agent's worktree. Never touch the user's actual Runmux registry, supervised processes, OpenCode database, or telemetry store during testing.

## 3. Architecture & Stage Roadmap

### Stage 1: Optional Integration Factory (`src/runmux/llm_monitor_integration.py`)
- Provide lazy import and capability detection for `llm_monitor` (Python >= 3.11 check, module availability, adapter availability).
- Read server-side environment variables only:
  - `RUNMUX_LLM_MONITOR_ENABLED` (default: false, explicit opt-in)
  - `RUNMUX_LLM_MONITOR_OPENCODE_URL` (default: `http://127.0.0.1:4096`)
  - `RUNMUX_LLM_MONITOR_LMSTUDIO_URL` (default: `http://127.0.0.1:1234`)
  - `RUNMUX_LLM_MONITOR_DATABASE` (optional existing telemetry DB file only; never created if absent)
  - `RUNMUX_LLM_MONITOR_DIRECTORY` (optional OpenCode directory scope)
- Support constructor dependency injection for testing (`service`, `adapter`, `config`).
- Construct one shared `ObservabilityService` and `RunmuxMonitoringAdapter` for the configured endpoint.
- Configure bounded refresh interval (default 5.0s) and bounded `max_sessions` (default 200).
- Wire model metadata callback using public `extract_opencode_model_limits` and `LMStudioClient.list_models` with metadata caching.
- Wire hardware callback using `resource_metrics.gpu` if available; otherwise null.
- Expose stable status API without triggering provider I/O (`disabled`, `unavailable`, `available` with safe reason codes).
- No recording, inference, model mutation, or process lifecycle actions.

### Stage 2: Authenticated HTTP API (`src/runmux/web.py`)
- Mount 6 read-only endpoints on the existing `/api` router:
  1. `GET /api/llm-monitor/v1/status`: Host capability status only; no provider I/O.
  2. `GET /api/llm-monitor/v1/snapshot`: Cached snapshot envelope from adapter.
  3. `GET /api/llm-monitor/v1/sessions/detail`: Snapshot-seeded detail lookup by `provider_instance_id` and `session_id`.
  4. `GET /api/llm-monitor/v1/sessions/timeline`: Bounded historical event page with opaque cursor.
  5. `GET /api/llm-monitor/v1/alerts`: Read-only persisted alert states.
  6. `GET /api/llm-monitor/v1/hardware`: Point-in-time hardware projection from cached snapshot.
- Enforce strict parameter bounds: `provider_instance_id` (max 2048), `session_id` (max 512), `limit` (1..500), `cursor` (max 1024).
- Execute blocking provider/SQLite calls in `run_in_threadpool`.
- Maintain `Cache-Control: no-store`, session cookie authentication, trusted host/origin checks.
- Never leak raw paths, credentials, or exception messages.

### Stage 3: Coordinate Frontend Integration
- Check Phase 6C audit/merge state.
- If unmerged, report frontend ownership block while delivering Stages 1 and 2 with full verification.
- Provide modular JavaScript integration specifications (`assets/llm-monitor.js`) ready for immediate mount once released.

### Stage 4 & 5: LLM Sessions Workspace & Lifetime (Deferred / Specified)
- Detail requirements for top-level view switch, modular rendering, and shared bounded refresh loop.

### Stage 6: Validation & Delivery
- Comprehensive unit, integration, and security tests in `modules/runmux/tests/llm_monitor_integration_test.py` and `modules/runmux/tests/web_llm_monitor_api_test.py`.
- Regression test run across existing Runmux suites.
