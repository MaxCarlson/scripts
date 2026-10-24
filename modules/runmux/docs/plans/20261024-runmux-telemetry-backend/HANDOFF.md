# Handoff — Runmux Live Telemetry Backend (Phase 5B)

**Branch:** `codex/runmux-telemetry-backend-20261024`  
**Worktree:** `.worktrees/runmux-telemetry-backend`  
**Base Commit:** `97515f0905aa2cdc194cabd9c06a250d503256a3` (`main`)  
**Assignment:** Backend-only subset of `PHASE_05B_LIVE_TELEMETRY.md`.  

## Scope & Non-Goals
- Scope: Backend resource telemetry collector, `runmux/stats.py`, `modules/resource_metrics/`, verified read API adapter in `web_adapter.py` and `web.py`, focused unit tests, and telemetry provenance documentation.
- Non-Goals: No Web UI frontend edits (`dashboard.js`, CSS, HTML), no WebSocket handler modifications, no terminal attachment modifications, no supervisor input-lock modifications, no historical charting or telemetry database.

## Coordination with Phase 2
- Phase 2 is being developed simultaneously in `.worktrees/runmux-web-launch-20261024` on branch `codex/runmux-web-phase2-20261024`.
- Phase 2 modifies `web_static/assets/dashboard.js`, `tests/dashboard_test.js`, and terminal/launch docs.
- This backend telemetry work touches zero files modified by Phase 2, ensuring clean parallel execution and zero merge conflicts.
