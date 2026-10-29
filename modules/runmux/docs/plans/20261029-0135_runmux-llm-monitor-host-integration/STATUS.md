# Runmux + LLM Monitor Host-Side Integration Status

**Branch:** `runmux-llm-monitor-host-integration-20261029`  
**Worktree:** `.worktrees/runmux-llm-monitor-host-integration-20261029`  
**Baseline:** `c34739c5b3fe41f9cd3c63a19c4991e7da519fec` (`origin/main`)  
**State:** Stages 0, 1, and 2 completed and fully verified. Stage 3 coordinated (frontend blocked by unmerged Phase 6C; complete specification delivered in `FRONTEND_INTEGRATION_SPEC.md`).  
**Next:** Update documentation (`README.md`, `HANDOFF.md`), stage intended files, and report completion.

## Concurrency Ledger & Implementation Evidence

- **Baseline SHA:** `c34739c5b3fe41f9cd3c63a19c4991e7da519fec`.
- **LLM Monitor Baseline:** Merged on `main` at `c34739c5`. Provides `llm_monitor.runmux_adapter.RunmuxMonitoringAdapter`, `ObservabilityService`, `TelemetryStore`.
- **Phase 6C Status:** Unmerged on `codex/runmux-6c-history-frontend-local-pilot-20261024` (`a03b4fa65d49bde59287dc4a246603f13a91b974`), awaiting independent audit. Under Stage 3 instructions, `web_static/` was kept untouched to prevent collisions with Phase 6C. Stages 1 and 2 are delivered independently with 17 passing tests, along with `FRONTEND_INTEGRATION_SPEC.md`.
- **Runmux Server Lifecycle:** Commit `3881681d` is unmerged into `main`. Changes in `create_runmux_web_app` add optional `llm_monitor_integration` and `default_cwd` parameters, remaining backwards-compatible with all existing call sites.

## Stage 1 & 2 Completed Capabilities

1. **`llm_monitor_integration.py`:**
   - Lazy loading, preserving Python 3.10 compatibility.
   - Explicit opt-in via `RUNMUX_LLM_MONITOR_ENABLED` (disabled by default).
   - Validates server-side URLs (rejects userinfo, queries, fragments).
   - Only accepts existing database files; never creates a database or initializes a recorder.
   - Cached model metadata provider (300s TTL) matching exact loaded model IDs.
   - Point-in-time hardware metrics via `resource_metrics.gpu`.
   - Safe status method that never triggers provider I/O.
2. **`web.py` API Endpoints:**
   - `GET /api/llm-monitor/v1/status`: non-blocking capability status.
   - `GET /api/llm-monitor/v1/snapshot`: cached snapshot envelope.
   - `GET /api/llm-monitor/v1/sessions/detail`: snapshot-seeded detail lookup by `provider_instance_id` and `session_id`.
   - `GET /api/llm-monitor/v1/sessions/timeline`: bounded event pagination with opaque cursors.
   - `GET /api/llm-monitor/v1/alerts`: read-only persisted alert query with validated status enum.
   - `GET /api/llm-monitor/v1/hardware`: point-in-time hardware projection.
   - Enforces session cookie authentication, trusted host/origin validation, `Cache-Control: no-store`, and generic error messages.

## Verification Evidence

```text
python -m pytest modules/runmux/tests/llm_monitor_integration_test.py modules/runmux/tests/web_llm_monitor_api_test.py -v
-> 17 passed in 0.64s

python -m pytest modules/runmux/tests/web_test.py -q
-> 15 passed in 7.92s

python -m ruff check modules/runmux/src/runmux/llm_monitor_integration.py modules/runmux/src/runmux/web.py modules/runmux/tests/llm_monitor_integration_test.py modules/runmux/tests/web_llm_monitor_api_test.py
-> All checks passed!
```
