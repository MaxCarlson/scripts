# Runmux Web UI — Phase 5B: Verified Live Resource Telemetry

**Status:** Future separately assignable feature | **Priority:** P2 | **Backlog:** M07–M09, M12–M13

## Objective

Expose **verified current** resource measurements for selected Runmux processes, reusing existing `modules/runmux/src/runmux/stats.py` and `modules/resource_metrics/` wherever appropriate. Do not build a second collector before inspecting the first.

## Mandatory correctness audit

- Verify CPU denominator/sample interval; process-tree aggregation; RSS semantics; IO counter/rate units; GPU per-process versus device scope; missing permissions and process exit handling.
- **Known source-code caveat:** Current `runmux.stats.sample_active_stats` computes a **host-wide network delta** and `build_process_stats` places that value on each process stats record. Do not present that as process-specific network throughput. Label host-level stats as host-level or omit them from a per-process card until defensible attribution exists.
- Existing `sample_active_stats` sleeps while obtaining delta samples; inspect latency and concurrency before calling it in an HTTP route. Don't block the event loop or poll unsafely at dashboard refresh speed.
- Define source, process/host scope, units, freshness, unavailable/stale states, and sampling overhead for every exposed metric. Unavailable is not zero; process PIDs can be reused, so bind attribution to verified run identity and valid current status.

## Work and acceptance

Provide minimal bounded, authenticated read API/adapter for current metrics and integrate into overview modes only where genuine values exist. Test source attribution, stale/unavailable states, ended/lost runs, permission denial, CPU multi-core semantics, process-tree aggregation, and cross-platform limitations using disposable processes/mocks. No speculative historical chart series, privileged polling services or external uploads.

Deliver focused tests, telemetry provenance table, docs, pushed branch and performance/latency notes; **do not merge**.
