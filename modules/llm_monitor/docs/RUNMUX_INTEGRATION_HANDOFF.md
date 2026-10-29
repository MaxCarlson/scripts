# Runmux LLM Monitor Integration Handoff

**Owner:** Runmux implementation agent  
**Consumer module:** `llm_monitor`  
**Boundary:** Read-only integration. This document was prepared without changing Runmux source.

## Available LLM Monitor interface

Import `RunmuxMonitoringAdapter` from `llm_monitor.runmux_adapter`. Construct it around one shared `ObservabilityService`; optionally pass the same telemetry database path. It exposes:

- `snapshot()` — refreshes and returns the shared system/session snapshot (Observability schema v1).
- `session_detail(provider_instance_id, session_id)` — provider-scoped detail or `None`.
- `timeline(provider_instance_id, session_id, limit=100, cursor=None)` — bounded persisted event page; maximum 500 rows, opaque keyset cursor bound to provider and session.
- `alerts(status=None, limit=100)` — bounded read of persisted alert state only.

The adapter does not create a server, authenticate users, record telemetry, write alert state, or operate providers. Its snapshot call performs provider polling through the existing service. Runmux should coordinate a single refresh cadence and serve a cached snapshot to concurrent browser requests. Timeline and alert queries use SQLite read-only mode and remain available without OpenCode when the telemetry store exists.

Data is privacy-projected: provider endpoint URLs lose credentials, paths, query, and fragment; stored `tool_target` identifiers remain hashes; local database paths and known raw-content fields are omitted. Do not add raw arguments or source/tool output to the web layer.

## Read-only host compatibility review

The inspected Runmux implementation builds an `/api` `APIRouter`, mounts it through `web_ui_tools.create_app`, and its host documentation/source establish loopback-only binding, startup access-code login, short-lived HttpOnly/SameSite session cookies, trusted host/origin checks, no-store API responses, and disabled access logs. New monitoring GET routes should be added to that existing router and inherit the shared middleware. Do not add a second app/server, permissive CORS, static unauthenticated endpoints, or direct browser access to provider/database resources.

Runmux already uses bounded history/event APIs with cursor parameters. The monitor adapter's cursor is opaque and session-bound; pass it through unchanged, validate the requested `limit`, and map `ValueError` to a generic client error without echoing cursor contents. Adapter results are already bounded. Use threadpool execution for SQLite/provider work in async route handlers, following existing Runmux route patterns.

## Suggested route mapping

Keep endpoints read-only and versioned under the existing `/api` router:

| Route | Adapter call |
|---|---|
| `GET /api/llm-monitor/v1/snapshot` | `snapshot()` |
| `GET /api/llm-monitor/v1/sessions/{provider_instance_id}/{session_id}` | `session_detail(...)` |
| `GET /api/llm-monitor/v1/sessions/{provider_instance_id}/{session_id}/timeline?limit=100&cursor=...` | `timeline(...)` |
| `GET /api/llm-monitor/v1/alerts?status=active&limit=100` | `alerts(...)` |

URL-decode path components once and avoid using either value as a filesystem path. Provider IDs are endpoint identities, not arbitrary paths. Use `Cache-Control: no-store` through the host middleware. Return generic 404/503 responses for missing session/store/provider cases; do not return exception text containing local paths or credentials. Escape provider-controlled labels in HTML. Keep alert routes read-only; acknowledgment requires a separately reviewed authenticated mutation route.

## Session/process correlation

The monitor provides OpenCode provider/session identity and persisted MCP snapshot relationships, but no verified Runmux process ID mapping. Do not infer a one-to-one relation. If Runmux has an explicit process/session/job identifier, expose that as a separately sourced correlation with its confidence. Directory/time similarities remain hypotheses and must not claim ownership.

## Browser workspace scope

Implement the requested overview, detail, timeline, and alerts as modular views in the existing Runmux application. Reuse its current navigation, stylesheet, API request helper, authentication, and theme. Keep polling bounded (one shared client refresh; no request loop per panel), preserve offline historical views, and show provider freshness/coverage. Do not add lifecycle controls to the monitor views.

## Suggested host-side verification

- No cookie, expired cookie, hostile Origin/Host, and cross-site fetch are rejected by existing host middleware.
- Authenticated same-origin GET responses are no-store.
- Malformed/oversized cursors and limits are rejected without leaking exception details.
- Provider offline leaves stored timeline/report accessible.
- Concurrent browser requests share one service refresh and do not write to telemetry.
- Automated tests use a temporary SQLite database and synthetic provider client; never use the user's Runmux registry.
