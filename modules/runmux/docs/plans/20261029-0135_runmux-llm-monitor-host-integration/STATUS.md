# Runmux + LLM Monitor Host-Side Integration Status

**Branch:** `runmux-llm-monitor-host-integration-20261029`  
**Worktree:** `.worktrees/runmux-llm-monitor-host-integration-20261029`  
**Baseline:** `c34739c5b3fe41f9cd3c63a19c4991e7da519fec` (`origin/main`)  
**Verified Remote Branch HEAD:** `e7a0fd825f4542c9cf3e247985b542201c289939`  
**State:** Backend implementation and review corrections completed, verified with 33 passing tests (18 integration/API tests + 15 web tests). Frontend workspace deferred per Stage 3 specification (`FRONTEND_INTEGRATION_SPEC.md`) awaiting Phase 6C merge.  
**Next:** Stage intended files, commit review corrections, and await Phase 6C frontend unblock.

## Concurrency Ledger & Implementation Evidence

- **Baseline SHA:** `c34739c5b3fe41f9cd3c63a19c4991e7da519fec`.
- **Remote Branch Baseline:** `e7a0fd825f4542c9cf3e247985b542201c289939`.
- **LLM Monitor Baseline:** Merged on `main` at `c34739c5`. Provides `llm_monitor.runmux_adapter.RunmuxMonitoringAdapter`, `ObservabilityService`, `TelemetryStore`.
- **Phase 6C Status:** Unmerged on `codex/runmux-6c-history-frontend-local-pilot-20261024` (`a03b4fa65d49bde59287dc4a246603f13a91b974`), holding `web_static/`. Per Stage 3 instructions, `web_static/` was kept untouched to avoid conflicts. Stages 1 and 2 and review corrections are delivered independently along with `FRONTEND_INTEGRATION_SPEC.md`.
- **Runmux Server Lifecycle:** Commit `3881681d` is unmerged into `main`. Changes in `create_runmux_web_app` add optional `llm_monitor_integration` and `default_cwd` parameters, remaining backwards-compatible with all existing call sites.

## Review Corrections Completed

1. **Snapshot Cache Bypass Prevention:** Removed `force_refresh` query parameter from `/api/llm-monitor/v1/snapshot`. Browser callers share the scheduled background refresh cadence and cannot flood the OpenCode provider with serial requests.
2. **Inert Disabled Integration:** `LLMMonitorConfig.from_env()` performs no validation or import of `llm_monitor.storage` when monitoring is disabled (`RUNMUX_LLM_MONITOR_ENABLED` not truthy). Malformed environment variables or missing dependencies do not hinder ordinary Runmux startup.
3. **Provider URL Validation:** Rigorous URL parsing preserves IPv6 square brackets (`[::1]`), rejects absent hostnames, enforces port range (1–65535), and strips userinfo/credentials without leaking secrets.
4. **Status Privacy:** Removed raw configured provider endpoints and private URL paths from `/api/llm-monitor/v1/status`. The response envelope is restricted to capabilities, status, and safe reason codes.
5. **App-Scoped Integration Instances:** `create_runmux_web_app` binds an isolated `LLMMonitorIntegration` per application instance rather than relying on a shared global singleton, ensuring test and multi-instance isolation.
6. **Unavailable vs. Missing Sessions:** Differentiates provider offline errors (`MonitoringServiceUnavailableError` -> HTTP 503) from genuinely absent session records (`MonitoringSessionNotFoundError` -> HTTP 404), preserving historical session availability.
7. **Explicit Database Isolation:** Specifying a nonexistent database file marks the database configuration invalid instead of silently falling back to the platform-default database.

## Stage 1 & 2 Completed Capabilities

1. **`llm_monitor_integration.py`:**
   - Lazy loading, preserving Python 3.10 compatibility.
   - Explicit opt-in via `RUNMUX_LLM_MONITOR_ENABLED` (disabled by default).
   - Validates server-side URLs (rejects userinfo, queries, fragments, invalid ports).
   - Only accepts existing database files; never creates a database or initializes a recorder.
   - Cached model metadata provider (300s TTL) matching exact loaded model IDs.
   - Point-in-time hardware metrics via `resource_metrics.gpu`.
   - Safe status method that never triggers provider I/O.
2. **`web.py` API Endpoints:**
   - `GET /api/llm-monitor/v1/status`: non-blocking capability status.
   - `GET /api/llm-monitor/v1/snapshot`: cached snapshot envelope without cache bypass.
   - `GET /api/llm-monitor/v1/sessions/detail`: snapshot-seeded detail lookup by `provider_instance_id` and `session_id`.
   - `GET /api/llm-monitor/v1/sessions/timeline`: bounded event pagination with opaque cursors.
   - `GET /api/llm-monitor/v1/alerts`: read-only persisted alert query with validated status enum.
   - `GET /api/llm-monitor/v1/hardware`: point-in-time hardware projection.
   - Enforces session cookie authentication, trusted host/origin validation, `Cache-Control: no-store`, and generic error messages.

## Verification Evidence

```text
python -m pytest modules/runmux/tests/llm_monitor_integration_test.py modules/runmux/tests/web_llm_monitor_api_test.py modules/runmux/tests/web_test.py -v
-> 33 passed in 10.63s

python -m ruff check modules/runmux/src/runmux/llm_monitor_integration.py modules/runmux/src/runmux/web.py modules/runmux/tests/llm_monitor_integration_test.py modules/runmux/tests/web_llm_monitor_api_test.py
-> All checks passed!

python -m compileall modules/runmux/src/ modules/runmux/tests/
-> 0 errors
```
