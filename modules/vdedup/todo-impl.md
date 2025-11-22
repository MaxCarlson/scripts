# vdedup – Implementation Checklist

This document translates backlog items into trackable execution units. Each top-level checkbox represents a major feature. Nested checkboxes enumerate the tangible sub-tasks, algorithms, or decisions required to finish that feature.

---

## [ ] 1. Promote the Rich Dashboard into `termdash`
- [ ] Extract dashboard layout primitives into reusable classes under `modules/termdash`.
- [ ] Publish a public-facing API that accepts a declarative “pipeline state” object.
- [ ] Mirror existing ProgressReporter features (logs, stats, stage timeline) inside termdash components.
- [ ] Add integration tests that render the dashboard with mocked data.
- [ ] Document how other tools can adopt the dashboard (README + code samples).

## [ ] 2. Stage Timeline, Counters, and ETA
- [x] Track total number of stages selected for each run.
- [x] Emit `Stage X/Y` with name, elapsed time, and ETA derived from current throughput.
- [x] Maintain a stage history table: completed (green + duration), active (yellow), queued (purple).
- [x] Render a stacked bullet list that records each stage's runtime once it completes.
- [x] Persist stage start/stop timestamps for post-run reporting.

## [ ] 3. Full Progress Coverage
- [ ] Provide progress bars for discovery, scanning, hashing, metadata, pHash, scene, audio, timeline.
- [ ] Auto-resize progress totals when the workload expands mid-stage.
- [ ] Combine numerical counters (files/bytes) with graphical bars to keep both CLI/log users informed.
- [ ] Add regression tests that verify bars advance correctly with simulated workloads.

## [ ] 4. Log Streaming Panel
- [x] Replace the static "Recent Activity" list with a scrolling log sink that consumes the main logger.
- [ ] Support log-level filters (INFO/DEBUG/WARN/ERROR) without restarting the pipeline.
- [ ] Stream logs to disk and UI simultaneously, with back-pressure safeguards.
- [ ] Provide quick controls (e.g., `f` to change filter) that update the panel instantly.
- [x] Ensure the widget refreshes at ≥5 FPS so log entries appear smoothly.

## [ ] 5. Runtime Controls
- [ ] Create a non-blocking input listener that captures pause/resume/stop/restart/quit commands.
- [ ] Wire controls to `ProgressReporter` so workers respect pause and shutdown signals.
- [ ] Display control state (e.g., “Paused”) and next steps (press key to resume).
- [ ] Ensure stop/restart gracefully drain thread pools and update caches before exiting.
- [ ] Allow queue/parameter changes while paused (thread counts, limits) and surface the updates instantly in the UI.
- [ ] Add hotkeys to switch between dashboard and per-scan detail screens without restarting the pipeline.

## [ ] 6. Precision Metrics & Live Signals
- [ ] Increase byte formatting precision for TiB+ datasets (two decimals minimum).
- [ ] Emit at least three live-changing stats (files/s, GiB/s, duplicates found, stage ETA) at all times.
- [ ] Track “artifact skips” separately and render them alongside normal skip counts.
- [ ] Validate rate calculations against synthetic workloads.
- [ ] Target a refresh cadence of ~5 Hz so stats never appear frozen.

## [ ] 7. Artifact Modes & Cleanup
- [ ] Keep partial downloads excluded by default with explicit reason codes.
- [ ] Implement an "artifact cleanup" scan mode: inventory, report, optionally delete/quarantine.
- [ ] When artifacts are included (CLI flag), visually tag them in the dashboard and reports.
- [ ] Add unit tests covering inclusion/exclusion logic.

## [ ] 8. Documentation & Knowledge Transfer
- [ ] Update `README`/FAQ sections describing the dashboard, controls, and telemetry.
- [ ] Write developer docs for extending `termdash` components.
- [ ] Keep `the_journal_of_an_llm.md` current with design rationales and research links.
- [ ] Record algorithm choices (accepted/rejected) for future contributors.

## [ ] 9. Duplicate Detail Explorer & Interactive List
- [ ] Create an interactive list component that surfaces master videos sorted by their duplicate/subset counts (leaders only by default).
- [ ] Allow expanding a master entry to view all subordinate files with metadata, detection reason, and similarity metrics.
- [ ] Build a dedicated detail pane that highlights resolution, bitrate, duration, codecs, chosen keep-policy, and rationale for each group.
- [ ] Add filters/toggles to switch between detection types (exact hash vs. subset vs. visual similarity).
- [ ] Integrate keyboard navigation (enter/back) so the dashboard and list share the same controls.
- [ ] Rebase the interactive list on termdash widgets so it can be reused across modules (avoid Rich-only paths).

## [ ] 10. Missing Footage Detection & Export
- [ ] Detect cases where a subset file contains segments not present in its master using timeline fingerprints.
- [ ] Record the additional segments (start/end timestamps, duration) so they surface in the detail pane.
- [ ] Provide CLI/UI options to export those extra segments to files (non-destructive defaults).
- [ ] Persist operator decisions (ignore/extract) so reports indicate which masters need manual editing.
- [ ] Add tests covering detection of >2 minute extra footage blocks.

## [ ] 11. Worker Parallelism Visibility
- [ ] For multi-worker scans, render per-worker progress/throughput and an at-a-glance summary.
- [ ] Show worker rows in parallel and update when pausing/stopping a single worker.
- [ ] Keep the dashboard responsive while workers stream updates (no blocking on shared locks).

---

Please tick off sub-tasks as they get implemented. Top-level items should only be marked complete once every nested box is checked.***
