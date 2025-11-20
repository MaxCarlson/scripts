# vdedup - Planning & Documentation Backlog

This document aggregates every feature, enhancement, and investigation task we have discussed so far. Treat it as a living backlog: new ideas go here first, then migrate down into the implementation checklist once they are sufficiently specified.

---

## 1. Modularize the Rich Dashboard into `termdash`
- Generalize the new Rich-based dashboard into reusable building blocks.
- Expose layout primitives (stage timeline, stat blocks, log panels, progress bars) as composable termdash components.
- Provide a thin adapter so other scripts can drive the UI using a declarative state object rather than imperative printing.
- Publish reference documentation and quick-start snippets in the termdash repo.

## 2. Stage Awareness & Telemetry
- Show "Stage X/Y" prominently with current stage name, elapsed time, and ETA (update every refresh tick, not just on state change).
- Keep a rolling timeline of every stage: completed ones in green (with duration), current in yellow, queued in magenta/purple.
- Maintain a stacked bullet list that records each stage's runtime the moment it completes, so operators can audit historical performance mid-run.
- Capture per-stage metrics (files, bytes, hit rates, subset counts) so the UI can surface stage-specific dashboards.
- Emit stage boundaries as structured events so reports/logs can reconstruct the full lifecycle.

## 3. Progress Bars Everywhere
- Drive progress indicators for every stage that has a countable workload (discovery, scan, hashing, metadata, pHash, scene, audio, timeline).
- Offer both linear bars and textual counters so terminal and non-terminal renderers stay in sync.
- Support dynamic rescaling when the total changes mid-stage (e.g., when new collisions are queued).

## 4. Log Streaming & Diagnostics
- Convert the "Recent Activity" panel into a continuously scrolling, high-verbosity log stream fed by the logger (INFO by default, DEBUG optional).
- Allow filtering (INFO/DEBUG/WARN/ERROR) without restarting the pipeline.
- Persist log history to disk while also emitting to the dashboard for forensic auditing.
- Refresh the log widget frequently (e.g., >=5 FPS) so users see constant movement.

## 5. User Controls (Hotkeys & CLI Hooks)
- Implement pause/resume/stop/quit controls via non-blocking key listeners.
- Provide a restart command that replays the current stage from the latest checkpoint.
- Surface control status (e.g., "Paused at Q3 metadata - waiting for resume") inside the UI banner.
- Ensure controls gracefully unwind worker pools and flush caches before stopping.

## 6. High-Fidelity Metrics
- Increase precision for large byte counters (>= 1 TiB) by showing at least two decimals and an explicit delta/second.
- Always keep multiple "live" stats moving (files/s, GiB/s, duplicates found, stage ETA) so the operator knows the pipeline is active.
- Track artifact/partial skip counts separately from ordinary skips.
- Target a smooth refresh cadence (e.g., 5 Hz) so changes feel continuous, not jumpy.

## 7. Artifact Handling & Modes
- Continue skipping partial downloads (`.part`, `.crdownload`, etc.) by default.
- Add a "artifact cleanup" mode that scans for these files and offers deletion/quarantine options.
- When artifacts are included (via CLI flag), tag them in the UI so they can be triaged quickly.

## 8. Documentation & Knowledge Sharing
- Document the new UI architecture, controls, and telemetry fields inside `termdash` and `vdedup`.
- Maintain a public FAQ (or README section) covering performance implications, recommended thread counts, GPU support, etc.
- Capture lessons learned (algorithms evaluated, rejected approaches) inside `the_journal_of_an_llm.md`.

## 9. Duplicate Detail Explorer & Interactive List Integration
- Build an interactive list that surfaces master videos sorted by number of subset/duplicate files (leaders only by default).
- Allow operators to expand a master entry (keyboard enter/click) to see all subordinate files with metadata, detection reason, and similarity metrics.
- Show a dedicated detail page highlighting comparisons: resolution, bitrate, duration, codec, detection stage (hash, metadata, subset), and why the winner was chosen.
- Provide quick toggles to filter by detection type (exact duplicate vs. subset vs. visual similarity) and to jump between master groups without leaving the dashboard.

## 10. Missing Footage Detection & Export
- Detect cases where a supposed subset contains footage not present in the master (e.g., >2 minutes of extra content) by leveraging timeline fingerprints.
- Surface these extra segments in the detail pane, with timestamps and duration, so users can decide what to do.
- Offer CLI/UI controls to export the extra footage to separate files and (later) to assist in splicing, but default to non-destructive operations.
- Record the decision (keep/remove/extract) so reports know which masters require follow-up editing.

---

Feel free to append new feature ideas here before they are fully specced. Once an item is ready to execute, translate it into the implementation checklist (`todo-impl.md`).
