# Runmux Web UI — Phase 5C: Historical Metrics, Charts, and Optional Drawer

**Status:** Optional; **requires separate approval of history storage/retention policy** | **Priority:** P2 | **Backlog:** M10–M11

## Objective

Add real metric time series and optional expanded monitoring views **only after** Phase 5B verifies live source provenance. Phase 5A's A/B/C/D modes remain usable without chart history.

## Decisions required before implementation

Propose sampling cadence, retention duration and storage location/volume, downsampling and query bounds, per-run/host attribution, startup/shutdown behavior, cost/performance, and whether histories survive server restarts. The user must approve substantive new retention/background collection policy before it is implemented.

## Once approved

- Implement bounded history collection/query if not already present. Verify gaps, stale samples, missed intervals, process exits and time axes.
- Add labeled charts for supported series only, with correct units and selectable genuine time ranges. Never synthesize previous points from a single current observation.
- Optionally add a compact resizable metrics drawer if justified, without replacing the terminal workspace or introducing a generalized docking framework.
- Test memory/storage/query caps, process reuse/identity, retention expiry, absent sources, UI responsiveness and real-vs-host metric labels using disposable state.

**Out of scope:** Alerts, remote monitoring, telemetry uploads, arbitrary resource-limit configuration, automatic scheduling. Deliver tests, provenance/retention documentation, pushed feature branch and verification; **do not merge**.
