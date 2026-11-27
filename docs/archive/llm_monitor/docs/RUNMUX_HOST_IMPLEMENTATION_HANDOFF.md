# Runmux Host Integration Implementation Handoff

**Audience:** Runmux web implementation owner

**Reviewed baseline:** Runmux `3881681d9248ed7398430e92b33683c9481b18a0`

**LLM Monitor contract:** Phase 3D `fa78c6d2d68b3a66e6237eaaa12ba56f0d07aa95`

**Scope:** Runmux-owned authenticated read-only browser integration

This document is an implementation supplement to [the adapter contract](API.md) and [the original integration handoff](RUNMUX_INTEGRATION_HANDOFF.md). It records verified interfaces and concrete host-side recommendations. It does not change the LLM Monitor API contract.

## Verified adapter contract

The Phase 3D package is version `0.5.0`, requires Python `>=3.11`, and declares no runtime dependencies. Runmux currently requires Python `>=3.10`; therefore LLM Monitor must remain optional and Runmux must continue to work on Python 3.10 when the monitor package is missing or incompatible.

Import `RunmuxMonitoringAdapter` from `llm_monitor.runmux_adapter`. Its public methods are:

```python
RunmuxMonitoringAdapter(
    service: ObservabilityService,
    *,
    database_path: str | Path | None = None,
    refresh_interval_seconds: float = 1.0,
)

snapshot(*, force_refresh: bool = False) -> dict[str, Any]
session_detail(provider_instance_id: str, session_id: str) -> dict[str, Any] | None
timeline(
    provider_instance_id: str,
    session_id: str,
    *,
    limit: int = 100,
    cursor: str | None = None,
) -> dict[str, Any]
alerts(*, status: str | None = None, limit: int = 100) -> dict[str, Any]
```

`timeline` accepts limits 1–500 (larger positive values are clamped to 500) and an opaque cursor bound to the provider/session pair. `alerts` accepts status `None`, `active`, `acknowledged`, or `resolved`, and limits 1–500. Invalid identities, cursors, or values can raise `ValueError`; translate that to a generic client error without echoing cursor or provider input.

Snapshot and detail use Observability schema version 1. Adapter timeline and alert envelopes use adapter schema version 1. `snapshot()` serializes refreshes and returns a deep-copied in-process cached snapshot for its configured interval (one second by default). A cache miss calls `ObservabilityService.refresh()`, which queries OpenCode and optionally model metadata and hardware providers. It does not initiate inference. `session_detail()` reads the current service state, so the host must call `snapshot()` before the detail call, usually through a shared in-process adapter.

`timeline()` and `alerts()` use `TelemetryStore(..., readonly=True)`. They return `availability: unavailable` with a reason code when the telemetry file/session is absent or a read fails. They do not create the database. `ObservabilityService` also checks whether the telemetry path is already a file before opening it read-only; it does not record or create a store. Do not replace these paths with writable `TelemetryStore` use in Runmux.

### Response contents and limits

- `snapshot()` returns `schema_version`, `refreshed_at`, `provider`, `system`, `sessions`, `hardware`, and a database path field. The adapter removes the database path before returning it. System counts and session summaries are from one configured OpenCode service; session identity is the pair `(provider_instance_id, session_id)`.
- Each session summary includes model/agent, state and last-observed state, state confidence/source, freshness, coverage, latest inference, separately scoped cumulative tokens, compaction count, current tool, blockers, diagnostic severity, and optional recent context utilization. Unsupported fields remain `null`, `unknown`, or unavailable.
- `session_detail()` returns schema version 1 with `summary`, `recent_events`, `context_utilization`, `compactions`, `diagnostics`, `hardware_samples`, `mcp_correlations`, `completion`, `coverage`, optional `historical_analysis`, and `monitoring_gaps`.
- `timeline()` returns a provider/session-scoped page with events, `next_cursor`, coverage, and total event count. It is persisted history only; it is not a live-event subscription.
- `alerts()` lists only already persisted alert states. It does not evaluate, acknowledge, or write alerts.
- The adapter strips known private content and database paths, sanitizes provider URLs, and hashes non-hashed `tool_target` values. The browser must still render all strings as text, never HTML.

## Runmux baseline and compatibility

Runmux commit `3881681d9248ed7398430e92b33683c9481b18a0` is the current integration base. It adds web-server lifecycle support, CLI controls, tests, and plan/docs updates. It does not change `src/runmux/web.py`, the static browser UI, or the web API contract. The LLM Monitor routes and workspace can be added without conflict with those lifecycle changes. Keep any new arguments to `create_runmux_web_app` optional so existing CLI and test call sites remain valid.

Runmux's web app creates a single `APIRouter(prefix="/api")`, then passes it to `web_ui_tools.create_app`. The shared middleware already provides trusted-host checks, same-origin checks, login-code session authentication, eight-hour HttpOnly/SameSite cookies, CSP/security headers, and `Cache-Control: no-store` on API responses. Keep every new endpoint on this router; do not add a second app, middleware, CORS policy, or public route.

The server binds to loopback through `web_ui_tools.create_server`. The lifecycle commit preserves this path. Monitoring must not use Runmux lifecycle operations or alter any process state.

The current browser is a single static SPA:

- `src/runmux/web_static/index.html` declares the login/dashboard shell and process workspace.
- `src/runmux/web_static/assets/dashboard.js` owns login/logout, the authenticated `api(path, options)` helper, process views, and a four-second process refresh timer.
- `src/runmux/web_static/assets/dashboard.css` owns the dark Runmux theme and responsive workspace styling.
- `tests/web_test.py` covers backend API/auth behavior; `tests/dashboard_test.js` runs the frontend script in a deterministic DOM harness; `tests/browser_e2e_test.js` is available for browser-level coverage where its prerequisites are installed.

The page's existing main workspace is `#workspace`; its main detail area is `.workspace-shell`, with tabs in `#workspace-tabs`. A separate hidden monitoring workspace is preferable to reusing process tabs or process selection state. Preserve existing process behavior and storage keys.

## Recommended backend integration

### Ownership and dependency

Keep the implementation in Runmux only. Do not add an import-time dependency on `llm_monitor`. Import it lazily inside an opt-in integration factory so a missing package, an older package without `runmux_adapter`, or an unsupported Python version cannot prevent Runmux startup. Do not add a mandatory dependency. If Runmux later publishes an optional extra, it must be Python-version guarded and point at an actually published compatible distribution; the Phase 3D feature branch itself is not a package index release.

Use server-side configuration only. Suggested environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `RUNMUX_LLM_MONITOR_ENABLED` | Explicit integration opt-in; only `1`/`true` enables | disabled |
| `RUNMUX_LLM_MONITOR_OPENCODE_URL` | Configured OpenCode HTTP endpoint | `http://127.0.0.1:4096` |
| `RUNMUX_LLM_MONITOR_LMSTUDIO_URL` | Read-only LM Studio metadata endpoint | `http://127.0.0.1:1234` |
| `RUNMUX_LLM_MONITOR_DATABASE` | Optional existing LLM Monitor telemetry DB | LLM Monitor's platform default |
| `RUNMUX_LLM_MONITOR_DIRECTORY` | Optional OpenCode project-directory scope | unset |

These are host administrator settings, never request parameters. Accept only HTTP(S) endpoints with valid host/port and without user-info, query, or fragment; do not return configured endpoint credentials or internal values to the browser. The browser must not provide a provider URL, filesystem path, database path, OpenCode directory, or LM Studio token.

When a database path is supplied, require it to refer to an existing file before passing it to the service. An absent database is a valid live-only configuration. When omitted, the service's platform default is read only if it already exists. Opening the monitoring page must not create a database, initialize a recorder, run a writable migration, or persist alert state.

### Lazy service construction

Add a Runmux-owned integration wrapper (suggested: `src/runmux/llm_monitor_integration.py`) responsible for environment parsing, capability detection, lazy construction, and stable unavailable status. Do not parse provider payloads or duplicate diagnostics in this wrapper.

When enabled and compatible, construct one shared `OpenCodeClient`, optional `LMStudioClient`, one `ObservabilityService`, and one `RunmuxMonitoringAdapter` per configured OpenCode endpoint. Use a bounded service `max_sessions`; expose its configured ceiling in the Runmux integration status because the service currently has no field indicating that session discovery was truncated. The adapter refresh lock and cache provide cross-request sharing within that adapter. Set its `refresh_interval_seconds` to align with the browser cadence (recommended 5 seconds); do not construct an adapter per request.

For context/model metadata, use the public `extract_opencode_model_limits` and `LMStudioClient.list_models` APIs through `ObservabilityService.model_metadata_provider`. The callback receives `(session_id, provider_snapshot)` and returns `(limits, loaded_model)`; use `session_info.model` and `session_info.provider`, match the LM Studio model ID exactly, and cache provider metadata (the CLI's five-minute cache is a reasonable precedent). Never substitute `max_context_length` or model-card capacity for a loaded instance's effective context. Do not import the CLI's private `_model_metadata` helper.

If hardware is available, pass a callback using the public `resource_metrics.gpu.gpu_devices` and `gpu_process_memory` functions. Keep the data marked point-in-time and device/process scoped. Unsupported hardware returns an unavailable/empty result and does not disable monitoring. Do not attribute device utilization to an LLM session.

An integration status object should be host-owned because the adapter has no `status()` method. Report only stable fields such as `schema_version`, `availability` (`disabled`, `unavailable`, or `available`), capability names, and safe reason codes (`disabled`, `package_missing`, `adapter_unsupported`, `database_unavailable`, `provider_unavailable`). Do not expose exception messages, local paths, tokens, or raw endpoint strings. Status inspection must not call `snapshot()` or contact a provider.

### Route contract

Add these read-only routes under the existing `/api` router. Suggested paths are versioned; all responses should be private/no-store through the existing middleware.

| Route | Behavior |
|---|---|
| `GET /api/llm-monitor/v1/status` | Host configuration/capability status only; no provider refresh |
| `GET /api/llm-monitor/v1/snapshot` | Return an envelope `{schema_version: 1, availability: "available", snapshot: adapter_snapshot}` |
| `GET /api/llm-monitor/v1/sessions/detail?provider_instance_id=…&session_id=…` | Call shared `snapshot()` first to seed/currentize service state, then `session_detail`; return 404 if absent |
| `GET /api/llm-monitor/v1/sessions/timeline?provider_instance_id=…&session_id=…&limit=100&cursor=…` | Pass IDs, limit, and opaque cursor unchanged to `timeline`; limit 1–500; return adapter envelope |
| `GET /api/llm-monitor/v1/alerts?status=active&limit=100` | Call `alerts`; allowed status values are active/acknowledged/resolved or omitted |
| `GET /api/llm-monitor/v1/hardware` | Project `snapshot.hardware` from the shared cached snapshot; report unavailable when null |

Provider instance IDs are sanitized endpoint URLs, and session IDs are provider-defined. Prefer query parameters for both identities instead of `{provider}/{session}` path segments: endpoint URLs contain slashes/colons and encoded slashes are routing-sensitive. Bound them (`provider_instance_id` max 2048, `session_id` max 512); they must never be interpreted as paths. Bound cursors to 1024 characters. Use FastAPI `Query` validation (timeline/alerts `limit` 1–500) so oversized values fail before reaching the adapter. Do not decode, inspect, regenerate, or rebind cursors; the adapter enforces provider/session binding.

Run blocking adapter and SQLite/provider calls through `run_in_threadpool`, as existing `web.py` does. Map malformed identities/cursors to a generic 400, unknown detail to 404, and missing/failed integration to generic 503 or a status envelope. Do not return exception text. Adapter `timeline`/`alerts` may express unavailability inside a successful envelope; preserve its schema and reason code while avoiding disclosure of exception details. Do not return 200 with empty lists when data is unknown.

`historical_analysis` is already available in `SessionDetail` for persisted, non-live sessions. No separate analyzer or SQL query in Runmux is needed. Historical `timeline` is persisted-only. The adapter exposes no process-correlation method; do not invent a Runmux process/session match. Existing session `job_id` and detail `mcp_correlations` may be shown as monitor-provided evidence, but they do not establish a Runmux process mapping.

## Recommended frontend integration

Keep the host UI changes limited to `index.html`, `assets/dashboard.js`, `assets/dashboard.css`, and optionally a new `assets/llm-monitor.js`. Preserve the current dark theme and make the feature a modular view. Load the new script after `dashboard.js`; expose a narrow integration from the existing script (for example, `RunmuxLLMMonitor.start(api)` and `.stop()`) so the new module reuses the authenticated, same-origin, no-store API helper rather than copying login behavior.

Add a top-level `Processes` / `LLM Monitor` view switch to the dashboard header. Keep `#workspace` unchanged and add a separate `#llm-monitor-workspace` section. Show the monitor status as a clear disabled/unavailable state when its optional package/configuration is absent. Only start the monitor's one shared refresh loop after the authenticated dashboard is shown; stop/abort it in `showLogin` and logout. Use one snapshot request at a time (suggested five-second interval), and fetch details/timeline/alerts on selection/view changes rather than creating a polling loop per panel. A selected session's timeline should request bounded pages and fetch the next page only on user scroll/load-more.

Overview should distinguish current state from `last_observed_state`, use `freshness`/age and `coverage`, and display unknown as an em dash or labeled `Unknown`, never as zero. Keep latest inference tokens visually separate from `cumulative_tokens` and its `cumulative_token_scope`. Mark hardware as device-level or process-level exactly as supplied. Inspector sections can render `summary`, `latest_inference`, `context_utilization`, `compactions`, `recent_events`, `diagnostics`, blockers, `completion`, `mcp_correlations`, `historical_analysis`, and `monitoring_gaps` directly from adapter output.

Render all provider-controlled content with `textContent`/text nodes and DOM APIs. Do not interpolate provider values into `innerHTML`, attributes containing executable content, URLs, or CSS. Do not persist telemetry, session IDs, paths, or provider data in localStorage/sessionStorage. Browser-side sorting/filtering may apply only to the bounded currently returned session list.

## Adapter limitations and explicit blockers

These are constraints of the published Phase 3D API; do not work around them by reaching into provider internals or SQLite from Runmux:

1. **No explicit integration status API.** Runmux must report its own enablement/dependency status without causing provider access.
2. **One adapter is scoped to one `ObservabilityService`/OpenCode endpoint.** Multi-endpoint overview would require multiple configured adapters and a host merge with endpoint-scoped identities; first integration should support one endpoint.
3. **No push stream or subscription.** Use bounded polling and the adapter's shared cache. Do not add WebSocket/SSE unless separately justified.
4. **Snapshot refresh is synchronous provider collection.** A cache miss discovers sessions and polls them serially (default `max_sessions=200`). Configure a bounded session ceiling and a refresh cadence. The service does not flag that the ceiling truncated discovery; host status should disclose the configured ceiling, and the UI should avoid claiming an exhaustive session list.
5. **Detail depends on the service's last refresh.** Call the shared adapter snapshot before detail, while respecting the cache, or a freshly discovered live session can appear absent.
6. **Timeline and alert history require an existing telemetry database.** No DB is valid for live summary/detail; history/alerts should show unavailable rather than fabricate emptiness.
7. **Historical timeline only.** Live normalized events are in the snapshot/detail view, not appended to timeline pages until recorded.
8. **Alerts are persisted states only.** Alerts may be unavailable or empty because `tui --persist-alerts`/alert commands are opt-in. The adapter does not evaluate alerts, acknowledge them, or write state. Keep this web view read-only.
9. **No direct LM Studio inventory method.** Loaded model/context data enters through the service's optional metadata callback and appears in session-level context/model fields. `system.loaded_models` is derived from observed sessions, not a complete independent LM Studio inventory.
10. **No Runmux-process correlation API.** The adapter cannot provide verified Runmux process IDs; show LLM sessions independently unless a separately verified explicit identifier is later added.
11. **Optional hardware only.** `snapshot.hardware` is null unless Runmux wires a hardware callback. It is point-in-time and cannot be treated as a model-attributed inference peak.
12. **Runtime mismatch.** Runmux supports Python 3.10; LLM Monitor requires 3.11+. On Python 3.10, keep Runmux operational and report the integration as unavailable. Do not raise Runmux's minimum Python requirement for this feature.

No change to the published LLM Monitor adapter is required for the initial one-endpoint integration. If product requirements later require live MCP, Runmux-process correlation, a separate loaded-model inventory, push updates, or alert evaluation, request an explicit additive LLM Monitor API proposal instead of duplicating those functions in Runmux.

## Recommended implementation sequence

1. **Backend wrapper and tests:** Add an optional lazy factory with injected-adapter support for tests. Verify disabled default, missing/incompatible package handling, existing-only DB path, and no writable store behavior.
2. **Authenticated routes:** Add status, snapshot, detail, timeline, alerts, and hardware routes to `create_runmux_web_app`'s existing router. Test authentication, same-origin behavior, bounds, query identity, cursor isolation, generic errors, no-store, and provider/database outages.
3. **Frontend shell:** Add the top-level view switch and modular workspace. Reuse the current API helper and auth lifecycle. Test disabled/empty/stale states before adding detailed views.
4. **Session overview and inspector:** Render model/state/freshness, latest inference versus cumulative tokens, context, blockers, compactions, diagnostics, coverage, and completion semantics from adapter response objects.
5. **Paged timeline and alerts:** Add bounded load-more, visible gaps, persisted alerts only, and DOM-safe rendering. Do not introduce mutations.
6. **Integration hardening:** Exercise concurrent clients and recorder reads against a temporary telemetry database. Confirm no database creation when absent and no Runmux registry/process-state changes from monitoring GETs.
7. **Delivery:** Run the Runmux web API/frontend tests and `ruff check .`, inspect changed paths, and document that no live OpenCode/LM Studio endpoint was contacted if none was available.

## Validation checklist for Runmux

### Backend and security

- Run `tests/web_test.py`, existing CLI/lifecycle tests, and new monitor route tests using an injected fake adapter or disposable temporary DB.
- Every monitor route without a cookie returns 401 and `Cache-Control: no-store`; hostile Host/Origin and expired cookies retain current middleware behavior.
- Status is safe while disabled/missing/incompatible and does not import or contact providers.
- Snapshot/detail provider failures become stale/unknown or generic unavailable status; stored history remains queryable offline.
- Query-provided endpoint, path, DB path, auth token, and arbitrary provider URL are rejected/unsupported because no such parameters exist.
- Oversized/invalid page size, cursor, and identities fail without echoing sensitive input. A cursor copied to another provider/session is rejected by the adapter.
- Missing database remains missing after overview/detail/timeline/alerts requests; existing DB is opened only through read-only adapter calls.
- Malformed provider-controlled labels never leak local paths, raw tool output, credentials, or raw arguments.

### Browser

- Run `node tests/dashboard_test.js` with the monitor shell/module registered in its DOM harness.
- Run `node tests/browser_e2e_test.js` if its synthetic registry/browser prerequisites are available.
- Verify monitor polling starts only after login, is shared and bounded, stops on lock/logout, and does not start a recorder.
- Verify unknown/stale status, partial coverage, absent model capacity, unknown completion, and missing hardware/alerts are visibly labeled.
- Verify latest per-inference counts and cumulative totals are separate; tool-target hashes are not rendered as paths.
- Verify session IDs, model labels, diagnostics, and event text containing HTML/script strings render literally.

### Compatibility and concurrency

- Keep all existing `create_runmux_web_app` callers valid; commit `3881681d`'s CLI lifecycle arguments and tests remain unchanged.
- Test Runmux with no `llm_monitor` importable, with Phase 3D `0.5.0`, and (if feasible) under Python 3.10 where the optional integration is unavailable.
- Test concurrent snapshot requests share one adapter/service refresh; do not assert one HTTP request equals one provider request when the adapter cache is warm.
- Test a recorder writing to a disposable DB while Runmux timeline/alert readers use read-only connections; no browser route may start or duplicate recording.
- No live inference, session mutation, model load/unload, Runmux process control, or real registry/database writes are part of these tests.

## Review boundary

This handoff is based on read-only inspection of the Phase 3D source and Runmux source at commit `3881681d`. The lifecycle commit does not overlap the web router or static workspace files. No live OpenCode, LM Studio, or MCP endpoint was exercised for this review, and no Runmux host route/browser integration has yet been implemented or validated.
