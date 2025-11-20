# The Journal of an LLM – vdedup

This notebook captures reasoning, research notes, and design decisions while evolving the vdedup pipeline and UI. Treat it as a chronological log; append entries as work progresses.

---

## Entry – Dashboard Refactor Kickoff
- **Context:** The Rich-based dashboard proved popular and should become a reusable asset inside `termdash`.
- **Thoughts:** Rather than hard-coding layout logic inside `vdedup.progress`, abstract the concepts: banner, stage timeline, stat grid, log stream. Each should accept data models instead of direct references to `ProgressReporter`.
- **Questions:** How do we expose keyboard controls without tying the UI to `stdin` (e.g., when running under systemd)? Possibly allow both direct key listening and an API for external event sources.
- **Next Steps:** Define a `PipelineDashboardState` dataclass and have `ProgressReporter` populate it. Then port rendering code into termdash using the same state.

## Entry – Stage Telemetry & Controls Requirements
- **Context:** New operator requests call for richer stage indicators (Stage X/Y, bullet list of durations), smoother log streaming, and interactive controls.
- **Observations:** Most data already exists inside `ProgressReporter` but needs structured storage (per-stage timings, stage order, completion timestamps). Log streaming will require wiring the main logger into an async-safe queue that the UI consumes every refresh tick.
- **Risks:** Introducing key listeners in a multi-threaded CLI risks blocking stdin on Windows; need to evaluate `msvcrt`, `select`, or `prompt_toolkit` for portability.
- **Next Steps:** Extend the planning documents with precise requirements (done), then prototype a `StageTracker` helper inside `vdedup.progress` that records timings and can be surfaced both to the UI and to downstream tools.

## Entry – Stage Timeline Implementation
- **What changed:** Added `set_stage_plan`, persistent `stage_records`, and UI rendering for Stage X/Y plus colored timeline bullets with durations. Pipeline now precomputes the plan and explicitly marks skipped stages so the UI never drifts.
- **Reasoning:** Keeping plan + state in one place lets multiple consumers (UI, reports, future termdash widgets) share the same source of truth. It also makes it easy to show operators exactly where they are (Stage 2/7) and how long each phase took.
- **Open Questions:** Stage ETA currently extrapolates from file-count throughput; later we might refine it using bytes or hashed units per stage. Also need to expose the same plan to the upcoming termdash module so other CLIs can reuse this work.

## Entry – Log Feed Polish
- **Change:** Reworked the “Recent Activity” widget so it prints timestamped entries (up to 12 lines) with severity-aware coloring. This gives the continuous scrolling sensation the operator requested without importing a heavy terminal toolkit.
- **Note:** Real streaming still depends on upstream callers invoking `reporter.add_log`. Later we might wire Python’s logging module into this method via a custom handler so every component automatically lands in the feed.

---

Feel free to append new entries with timestamps, diagrams, links to research papers, or algorithm sketches. This document is meant to preserve the “why” behind each major architectural choice.***
