# Runmux Historical Telemetry — API Proposal (Phase 5C)

**Document ID:** RUNMUX-5C-API | **Status:** REST API Specification | **Date:** 2026-10-24  
**Scope:** `modules/runmux/src/runmux/web.py`, `web_adapter.py` | **Author:** Antigravity (AI Systems Architect)

---

## 1. Overview & Security Contract

This document specifies the authenticated REST API endpoints for querying historical process and host telemetry.

### Security & Invariants
1. **Authentication:** Inherits existing `modules/web_ui_tools/` session authentication. Unauthenticated requests receive HTTP 401.
2. **Origin & CSRF:** Read-only `GET` endpoints enforce same-origin verification.
3. **Bounded Responses:** Queries default to returning $\le 300$ data points and are hard-capped to a maximum of **1,000 points**. Server-side downsampling is applied when the raw sample count exceeds the budget.
4. **No Secret Disclosure:** Responses contain strictly resource metrics and timing metadata. No command line arguments, environment variables, working directories, or process secrets are returned.

---

## 2. Process Telemetry History Endpoint

### `GET /api/runs/{run_id}/telemetry/history`

Retrieves historical resource time-series for a single managed process tree.

#### Request Parameters (Query String)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `since` | ISO 8601 string or float epoch | No | `now - 1h` | Start boundary of the requested time window. |
| `until` | ISO 8601 string or float epoch | No | `now` | End boundary of the requested time window. |
| `max_points` | integer (10–1000) | No | `300` | Target number of downsampled points to return. |
| `fields` | comma-separated string | No | `all` | Optional field filter (e.g. `cpu,rss,io`). |
| `include_lineage` | boolean | No | `false` | When true, traverses `restart_of` parents with explicit gap markers. |
| `include_events` | boolean | No | `true` | Include discrete lifecycle events (`pause`, `resume`, `exit`). |

#### Response Schema (JSON) — HTTP 200 OK

```json
{
  "run_id": "20261024-080000-f3a1b2",
  "numeric_id": 3,
  "status": "running",
  "provenance": {
    "cpu_scope": "process_tree",
    "cpu_unit": "percent (100% = 1 core)",
    "cpu_count": 8,
    "rss_unit": "bytes",
    "io_unit": "bytes_per_second",
    "gpu_unit": "bytes",
    "time_range": {
      "start": "2026-10-24T08:00:00.000000Z",
      "end": "2026-10-24T09:00:00.000000Z",
      "duration_seconds": 3600.0
    },
    "resolution": "downsampled_bucketed_min_avg_max",
    "raw_sample_count": 720,
    "returned_points": 300
  },
  "series": [
    {
      "timestamp": "2026-10-24T08:00:00.000000Z",
      "epoch": 1729782000.0,
      "sample_interval_seconds": 5.002134,
      "cpu_percent": 12.5,
      "cpu_percent_normalized": 1.56,
      "cpu_percent_min": 10.2,
      "cpu_percent_max": 24.8,
      "rss_bytes": 104857600,
      "rss_bytes_max": 108003328,
      "read_bytes_per_second": 51200.0,
      "write_bytes_per_second": 12800.0,
      "process_count": 2,
      "thread_count": 16,
      "gpu_memory_bytes": null
    },
    {
      "timestamp": "2026-10-24T08:15:30.000000Z",
      "epoch": 1729782930.0,
      "sample_interval_seconds": 15.004218,
      "is_gap": true,
      "gap_reason": "process paused",
      "cpu_percent": null,
      "cpu_percent_normalized": null,
      "rss_bytes": null,
      "read_bytes_per_second": null,
      "write_bytes_per_second": null,
      "process_count": 2,
      "thread_count": 16,
      "gpu_memory_bytes": null
    }
  ],
  "events": [
    {
      "timestamp": "2026-10-24T08:15:30.000000Z",
      "epoch": 1729782930.0,
      "event": "paused",
      "reason": "user action via web UI"
    },
    {
      "timestamp": "2026-10-24T08:20:00.000000Z",
      "epoch": 1729783200.0,
      "event": "resumed",
      "reason": "user action via web UI"
    }
  ]
}
```

#### Status Codes & Error Handling
- `200 OK`: Telemetry history returned successfully.
- `400 Bad Request`: Invalid parameter formats (e.g. `since > until`, `max_points > 1000`).
- `401 Unauthorized`: Session not authenticated.
- `404 Not Found`: Run ID does not exist in registry.
- `503 Service Unavailable`: Telemetry database is locked or disabled.

---

## 3. Host Overview Telemetry History Endpoint

### `GET /api/telemetry/history`

Retrieves system-wide host telemetry (CPU, RAM, network, GPU device summaries).

#### Request Parameters (Query String)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `since` | ISO 8601 string or float epoch | No | `now - 1h` | Start boundary of the requested time window. |
| `until` | ISO 8601 string or float epoch | No | `now` | End boundary of the requested time window. |
| `max_points` | integer (10–1000) | No | `300` | Target number of downsampled points. |

#### Response Schema (JSON) — HTTP 200 OK

```json
{
  "provenance": {
    "scope": "host",
    "cpu_unit": "percent (0.0 - 100.0%)",
    "memory_unit": "bytes",
    "net_unit": "bytes_per_second (host-wide aggregate)"
  },
  "series": [
    {
      "timestamp": "2026-10-24T08:00:00.000000Z",
      "epoch": 1729782000.0,
      "sample_interval_seconds": 5.001842,
      "cpu_percent": 18.2,
      "memory_used_bytes": 17179869184,
      "memory_available_bytes": 17179869184,
      "memory_percent": 50.0,
      "net_read_bytes_per_second": 1048576.0,
      "net_write_bytes_per_second": 262144.0
    }
  ]
}
```

---

## 4. Lineage Traversal & Restart Boundaries

When a process is restarted (`POST /api/runs/{run_id}/restart`), Runmux creates a **new immutable Run ID** with `restart_of = old_run_id`.

- **Default Behavior:** Queries strictly return data for the requested `run_id`.
- **Lineage Traversal (`include_lineage=true`):**
  - The server recursively resolves `restart_of` parent records.
  - Telemetry series points are tagged with their respective `run_id`.
  - An explicit event `{ "event": "restart", "old_run_id": "20261024-073000-a1b2c3", "new_run_id": "20261024-080000-f3a1b2" }` marks the transition.
  - The series injects an explicit `is_gap: true` point between the old process termination and the new process start, ensuring frontend charts render a visible line break rather than an inaccurate diagonal slope.
