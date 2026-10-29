# LLM Monitor application API (v1)

`llm_monitor.observability.ObservabilityService` is the shared, read-only application layer for terminal and future browser consumers. It calls the existing OpenCode adapter once per refresh, reuses normalized events and diagnostics, and optionally reads historical telemetry through `TelemetryStore`. It does not start a recorder. Consumers should share one service instance per provider endpoint instead of creating a collector for every view.

## Contract

The current Python API is:

```python
service = ObservabilityService(
    OpenCodeClient("http://127.0.0.1:4096"),
    database_path="/path/to/telemetry.sqlite3",  # optional, read-only
    session_filter=None,                         # optional exact session ID
    max_sessions=200,
    stale_after_seconds=15,
)
snapshot = service.refresh()
detail = service.get_detail(provider_instance_id, session_id)
```

`SystemSnapshot.to_dict()` and `SessionDetail.to_dict()` return envelope objects with `schema_version: 1`. The fields are defined by the dataclasses in `observability.py`; additive optional fields may be introduced within v1. A breaking rename, semantic change, or incompatible shape requires a new schema version.

`provider_instance_id` plus `session_id` is the session key. Session IDs alone are not globally unique. Summaries carry current state, last provider-observed state, confidence/source, freshness, coverage, latest completed inference, cumulative-token scope, blockers, and diagnostic summaries. Unsupported values are `null` or explicitly `unknown`/`unavailable`; they are never silently represented as zero. A stale provider snapshot reports normalized `state="unknown"` and retains `last_observed_state`.

Live detail is bounded by the OpenCode adapter's current observation window. Historical detail reads at most the last 100 event records for its timeline pane and uses the existing historical analyzer for aggregate results. Large consumers should use `TelemetryStore` paginated/streaming methods rather than repeatedly requesting full event histories.

The initial service supports bounded refresh polling; it does not expose a push subscription. `refresh()` discovers up to `max_sessions`, polls each discovered session, then includes stored sessions absent from the live result when a telemetry database exists. A provider failure is represented in `provider.status` and does not erase already persisted history. No state-changing provider operation is exposed.

## Future HTTP mapping

This is a contract for an authenticated host, not an HTTP server implemented by this module. `llm_monitor.runmux_adapter.RunmuxMonitoringAdapter` provides a framework-neutral read-only adapter over the existing `ObservabilityService` and `TelemetryStore`. It does not create a collector, recorder, database, route, or authentication boundary. A Runmux host may map its methods to bounded, versioned routes such as:

| Method/path | Result |
|---|---|
| `GET /api/llm-monitor/v1/snapshot` | System snapshot and session summaries |
| `GET /api/llm-monitor/v1/sessions/detail?provider_instance_id=…&session_id=…` | One session detail |
| `GET /api/llm-monitor/v1/sessions/timeline?provider_instance_id=…&session_id=…&limit=100&cursor=…` | Bounded chronological events |
| `GET /api/llm-monitor/v1/alerts` | Bounded persisted alert states |

The adapter methods are `snapshot(force_refresh=False)`, `session_detail(provider_instance_id, session_id)`, `timeline(provider_instance_id, session_id, limit=100, cursor=None)`, and `alerts(status=None, limit=100)`. A snapshot refresh is shared and serialized within the adapter, with a one-second in-process cache by default. Hosts should call the shared snapshot before requesting detail so the service's current session state is populated. Timeline cursors are opaque provider/session-bound keyset positions over the stored chronological event order. Pages are capped at 500 records. Stored tool targets are hashed at ingestion and remain hashed in responses. Provider URLs are reduced to scheme, host, and port; local database paths and known sensitive payload fields are omitted. Non-empty `error` details are replaced by the stable marker `provider_error` so transport exception text cannot disclose credentials or private URL components. Timeline and alerts return explicit `availability` values when the store or session is unavailable. Snapshot/detail objects retain ObservabilityService schema version 1; adapter-owned timeline/alerts envelopes use schema version 1.

Runmux should construct one adapter and one `ObservabilityService` per configured OpenCode endpoint and share them across browser clients. Refresh the service from a single bounded host update loop, then serve cached snapshots to requests; do not create a service or poll providers for every browser component. The adapter's `snapshot()` performs a refresh, so the host must coordinate calls to avoid duplicated polling. Persisted timeline and alert queries are read-only. Alert states are listed only when already stored; the adapter does not evaluate, acknowledge, or save alerts.

The host must apply the same authentication/session, origin, local-bind, and cache-control boundaries as its existing protected UI APIs. Responses must be private/no-store. Provider-instance identities are sanitized URLs and contain path delimiters; query parameters are preferable to route path segments for identity pairs. Route parameters must be bounded and validated, errors must not reveal filesystem paths or credentials, and untrusted strings must be escaped by the browser renderer. Do not add permissive CORS or direct browser access to OpenCode or telemetry SQLite files. See [the verified Runmux host implementation handoff](RUNMUX_HOST_IMPLEMENTATION_HANDOFF.md) and [the original scope handoff](RUNMUX_INTEGRATION_HANDOFF.md).

The Python contract contains no process start/stop, inference, model configuration, job recovery, or provider mutation method. Runmux process/session/job associations require explicit identifiers; directory/time matches remain qualified hypotheses. This phase does not add a Runmux backend route because its UI/backend work is concurrently active; the integration can implement this mapping after its owners review the contract.

## Alerts

`AlertEngine.evaluate(snapshot, previous=..., now=...)` is a pure evaluator shared by consumers. It returns active alerts, transitions, and serializable states. It performs no notifications and no storage writes. `TelemetryStore` stores optional local alert state only when explicitly opened writable by `tui --persist-alerts` or an alert-management command. Alert findings retain severity and confidence separately. Device-level utilization alone does not trigger a session-attributed hardware alert. Sustained hardware-pressure and recorder/database-error alerts are not emitted in this release because the current consumer API does not expose the required sampled alert stream.
