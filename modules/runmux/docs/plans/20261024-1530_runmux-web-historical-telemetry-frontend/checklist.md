# Phase 5C Historical Telemetry Frontend Checklist

## Task 1: UI Elements and Styling
- [x] Add process CPU, RSS, and disk I/O chart containers.
- [x] Add host CPU, memory, and network chart containers in Expanded mode.
- [x] Add 1h, 6h, 24h, and 7d controls, Expanded lineage toggle, and coverage/resolution text.
- [x] Add responsive SVG chart and legend styling.

## Task 2: SVG Time-Series Rendering
- [x] Render responsive SVG axes, grid, lines, and singleton points.
- [x] Break paths at explicit gaps, null/unavailable values, stale measurements, temporal discontinuities, and Run ID transitions.
- [x] Scale process CPU above 100% without clipping and format bytes/byte rates.
- [x] Show lifecycle and restart event markers with accessible title text.

## Task 3: History Controller
- [x] Generate bounded range queries for 1h/6h/24h/7d with a 300 point cap.
- [x] Gate requests: no history in Minimal/Inline, process only in Dashboard, process plus host in Expanded.
- [x] Cancel old requests and ignore responses from stale selections/ranges.
- [x] Refresh active runs every 30 seconds and fetch terminal runs once.
- [x] Show actual earliest returned sample time and resolution for partial retention.

## Task 4: Frontend Unit Tests
- [x] Test query windows, point limits, mode gating, and lineage parameters.
- [x] Test gaps, nulls, stale samples, and multi-core CPU scaling.
- [x] Test obsolete-request cancellation and active/terminal polling.

## Task 5: Real Chrome E2E and Screenshots
- [x] Seed process and host telemetry in a disposable SQLite database with synthetic parent/child lineage.
- [x] Verify process and host charts, lifecycle event pins, restart boundary, time ranges, and lineage requests in Chrome.
- [x] Verify run, view tab, follow state, and terminal visibility remain unchanged during range/lineage changes.
- [x] Capture `mode_c_dashboard_charts.png`, `mode_d_expanded_charts.png`, and `limited_retention_charts.png`.
- [x] Re-run existing Output and lifecycle E2E checks successfully.

## Task 6: Finalization
- [x] Record implementation, test evidence, and platform limitation in `STATUS.md` and `HANDOFF.md`.
- [x] Review final diff and status; readiness review left the worktree clean.
- [x] Commit and push feature branch (`89d530a8548a139261b3d0cf944d413ffa620426`); do not merge.
