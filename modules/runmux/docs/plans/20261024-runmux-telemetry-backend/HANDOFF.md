# Handoff — Runmux Live Telemetry Backend (Phase 5B)

**Branch:** `codex/runmux-telemetry-backend-20261024`  
**Worktree:** `.worktrees/runmux-telemetry-backend`  
**Base Commit:** `97515f0905aa2cdc194cabd9c06a250d503256a3` (`main`)  
**Assignment:** Backend-only subset of `PHASE_05B_LIVE_TELEMETRY.md`.  

## Scope & Non-Goals
- **Scope:** Backend resource telemetry collector, `runmux/stats.py`, `modules/resource_metrics/`, verified read API adapter in `web_adapter.py` and `web.py`, focused unit tests in `telemetry_test.py`, and comprehensive documentation in `docs/plans/20261024-runmux-telemetry-backend/`.
- **Non-Goals:** Zero Web UI frontend edits (`dashboard.js`, CSS, HTML), no WebSocket handler modifications, no terminal attachment modifications, no supervisor input-lock modifications, no historical charting or telemetry database.

## Key Technical Decisions & Refinements
1. **Sampler Distinction & Unavailable-vs-Zero:**
   - Web `TelemetrySampler` is non-blocking with monotonic deltas and zero `time.sleep()`.
   - CLI `sample_active_stats` preserves fixed-interval `time.sleep(interval_seconds)` for interactive and one-shot terminal output.
   - For both collectors, unmeasured/failed metrics are strictly `None` (JSON `null`, CLI `--`), while `0.0` is reserved strictly for live processes that consumed zero resources.
2. **PID Creation Tolerance:**
   - Tightened from 60.0s to 5.0s (`PID_CREATION_TOLERANCE_SECONDS = 5.0`).
   - Two-sided bounds protect against both recycled PIDs (spawned after run started) and older pre-existing PIDs (spawned before run was created).
3. **Latency & Concurrency:**
   - `ReadOnlyRunmux.get_overview_telemetry` executes supervisor status checks in parallel via `ThreadPoolExecutor(max_workers=min(16, len(active)))`.
   - 25 disconnected runs complete in < 30ms (verified by test).
   - NVIDIA GPU device queries are cached with a 1.5s TTL to avoid process execution bottlenecks.

## Coordination with Phase 2
- Phase 2 is being developed simultaneously in `.worktrees/runmux-web-launch-20261024` on branch `codex/runmux-web-phase2-20261024`.
- Phase 2 modifies `web_static/assets/dashboard.js`, `tests/dashboard_test.js`, and terminal/launch docs.
- This backend telemetry work touches **zero files modified by Phase 2**, ensuring clean parallel execution and zero merge conflicts.
