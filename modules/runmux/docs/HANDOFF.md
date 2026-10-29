# Runmux Current Handoff

## Runmux Web UI — Server Lifecycle Management (Integrated)

Server Lifecycle Management is fully implemented and verified on branch `codex/runmux-web-server-lifecycle-integrated-20261029`.
It provides:
- Existing-server automatic discovery on `runmux web`, verifying running instances via zero-knowledge challenge-response, printing `Status: Already running` with verified URL, original access code (without regeneration), and PID, returning exit code 0 without duplicate server launch.
- Post-bind startup reporting: the server banner (`Status: Started`) is printed only after successful loopback socket binding and application initialization.
- Inspection via `runmux web -S` / `--status`: reports running / not running / unverifiable status, verified URL, access code, PID, and state directory without mutating any state or creating credentials.
- Graceful shutdown via `runmux web -x` / `--stop`: requests authenticated shutdown using signed challenge-response, safely disconnects WebSockets, stops background telemetry workers, removes instance descriptors, and terminates the Web UI server process. Repeated stop commands are idempotent.
- **Supervisor Independence Invariant**: Stopping the Web UI server leaves all supervised Runmux processes alive and running without interruption.
- Owner-scoped filesystem security: descriptors (`server_<port>.json`) use Windows ACL restriction (`icacls` removing inheritance, granting user `(F)`) and POSIX `0600` mode, and strictly reject attacker symbolic links. Zero-knowledge challenge-response ensures secrets are never transmitted to unverified endpoints.
- Verified with unit, lifecycle, and CLI tests (`web_server_lifecycle_test.py`, `web_cli_test.py`, `web_test.py`).
- See `plans/20261029-0030_runmux-web-server-lifecycle/00_implementation-plan.md`, `STATUS.md`, and `checklist.md`.

## Runmux Web UI — LLM Monitor Frontend Workspace (Stages 4–5 Integrated)

The LLM Monitor browser workspace and lifetime management (Stages 4 & 5) are complete, validated, and merged into `main` at commit `ee4fcb19`.
It provides:
- Top-level workspace switcher tabs ("Processes" and "LLM Monitor") in the authenticated header.
- `window.RunmuxLLMMonitor` lifecycle interface (`mount`, `destroy`, `startPolling`, `stopPolling`, `getStatus`, `getSelectedSession`, `selectSession`).
- Sessions sidebar listing active and historical sessions identified by composite identity `(provider_instance_id, session_id)`.
- Main detail view displaying:
  - Session summary, model identification, status badge, context utilization ratio, and token breakdown.
  - Hardware metrics card (GPU utilization %, VRAM used/total GB, temperature °C).
  - Persisted alerts list with severity categorization (`warning`, `error`, `critical`).
  - Chronological event timeline with cursor-based forward/backward pagination.
- Complete XSS immunity via native DOM text nodes and element construction.
- Non-misleading error handling distinguishing 404 Session Missing from 503 Provider Offline.
- Lifetime management & polling:
  - Shared ~5.0s snapshot cadence without client-controlled cache bypass.
  - Active tab / visibility gating: pauses when tab is hidden or "Processes" workspace is selected.
  - Monotonic request generation tracking to prevent async race conditions.
  - Complete lock/logout cleanup canceling in-flight AbortControllers and wiping state.
- Responsive mobile layout bounded across all viewports (390px, 768px, 1366px, 1920px) with 0 page overflow.
- Phase 6C History Explorer (`a03b4fa6` / `382c0608`) integrated and validated without regressions.
- Validation:
  - `llm_monitor_view_test.js`: All 6 test suites passed.
  - `browser_e2e_test.js`: Passed full Chrome E2E suite across 5 responsive widths.
  - `llm_monitor_browser_e2e_test.js`: Passed full Chrome E2E suite and captured responsive screenshots.
  - Backend/API tests: 39/39 passed.
  - Ruff lint clean on all modified files.

## Runmux Web UI — LLM Monitor Host Integration (Stages 0–3 Integrated)

The host-side LLM Monitor integration (Stages 0–3) is fully implemented, review-corrected, verified, and merged into `main` at `39603daa`.
It provides:
- Optional, lazily imported host integration factory (`llm_monitor_integration.py`) preserving Python 3.10 compatibility for ordinary Runmux.
- Explicit server-side opt-in via `RUNMUX_LLM_MONITOR_ENABLED` (disabled by default).
- Safe provider endpoint validation rejecting userinfo, query, or fragment inputs, with IPv6 bracket preservation and port range validation.
- Read-only database access verifying the database is an existing file before opening; never creates a database or initializes recording.
- Model metadata caching (300s TTL) matching exact loaded model IDs without fabricating capacity limits.
- Point-in-time hardware metric sampling via `resource_metrics.gpu`.
- Authenticated read-only REST endpoints under `/api/llm-monitor/v1/`:
  - `GET /status`: capability availability without provider I/O; raw provider endpoint omitted for privacy.
  - `GET /snapshot`: cached system and session snapshot envelope without client-controlled cache bypass.
  - `GET /sessions/detail`: snapshot-seeded detail lookup by `provider_instance_id` and `session_id`; preserves 503 vs 404 distinction.
  - `GET /sessions/timeline`: bounded event page with opaque session-bound cursor.
  - `GET /alerts`: persisted alert queries filterable by status (`active`, `acknowledged`, `resolved`).
  - `GET /hardware`: point-in-time hardware projection.
- Invariants strictly preserved: No inference, recording, mutation, or process lifecycle actions are triggered.
- Stage 3 coordination: Confirmed Phase 6C History Explorer (`a03b4fa6`) audited and integrated into the frontend workspace baseline.
- Verified with 18 unit and API tests (`llm_monitor_integration_test.py`, `web_llm_monitor_api_test.py`) and 15 existing web tests (`web_test.py`).
- See `plans/20261029-0135_runmux-llm-monitor-host-integration/00_implementation-plan.md`, `STATUS.md`, `checklist.md`, and `FRONTEND_INTEGRATION_SPEC.md`.

Last updated: 2026-10-29

## Runmux Web UI — Phase 6C historical explorer frontend (Integrated)

The historical explorer frontend is complete on branch `codex/runmux-6c-history-frontend-local-pilot-20261024` and incorporated into `main`. It uses the integrated history API with bounded cursor pages and supported filters/sorts, and presents recorded events separately from registry-derived markers plus explicit Run ID lineage. The UI exposes the supported state, exact name, exit code, restart/duplicate parent, and `has_restarts` filters. Focused Node/Python tests and the full real headless Chrome suite pass, including History-open responsive checks at five widths.
## Runmux Web UI — Phase 4A integrated (Backend and Frontend)

Phase 4A (Lifecycle Controls Backend and Frontend) is fully integrated and merged into `main` from `codex/runmux-lifecycle-backend-20261024` and `codex/runmux-web-lifecycle-frontend-20261024` with no conflicts.
It provides authenticated, same-origin REST lifecycle endpoints (`POST /api/runs/{run_id}/stop`, `POST /api/runs/{run_id}/kill`, `POST /api/runs/{run_id}/restart`, `POST /api/runs/{run_id}/duplicate`, `POST /api/runs/{run_id}/pause`, `POST /api/runs/{run_id}/resume`, `GET /api/capabilities`) with state machine validation, supervisor PID reuse protection, and inconclusive process identity fallback safety.
In the browser, it provides selected-process controls for graceful Stop (`force: false`), forced Kill (`force: true`), Restart (creating a new immutable Run ID, reconciling tabs), Duplicate, and capability-aware Pause/Resume (disabled on Windows with descriptive tooltip; dynamic Resume action for paused processes). Destructive actions require modal confirmation displaying the process name and full immutable 22-character Run ID.
Verified with Python test suites (`lifecycle_test.py`, `lifecycle_api_test.py`, `web_test.py`), Node unit suite (`dashboard_test.js`), and headless Chrome CDP E2E testing (`browser_e2e_test.js`).
See `plans/20261024-1315_runmux-web-lifecycle-frontend/HANDOFF.md`, `STATUS.md`, and `plans/20261024-runmux-lifecycle-backend/HANDOFF.md`.

## Runmux Web UI — Phase 5A+ integrated

Phase 5A+ (Overview Modes & Live Telemetry Frontend) was merged into `main` from `codex/runmux-web-overview-telemetry-20261024` with no conflicts.
It provides four selectable overview densities (Mode A Minimal, Mode B Inline, Mode C Dashboard, Mode D Expanded) with keyboard/button cycling and browser persistence, consumes Phase 5B live telemetry endpoints, correctly handles stale ISO 8601 timestamps, separates hardware vs per-process GPU attribution, and respects request cancellation and background throttling.
Verified with headless Chrome CDP, Node unit tests, and Python test suites.
See `plans/20261024-runmux-web-overview-telemetry/HANDOFF.md` and `STATUS.md`.

## Runmux Web UI — Phase 4B integrated

Phase 4B (Enhanced Output Search and Filtering) was merged into `main` from `codex/runmux-web-phase4b-20261024` with no conflicts.
It provides bounded Output search, highlighted matches, safe literal search with ReDoS protection, DOM element bounding (`MAX_RENDER_LINES = 2000`, `MAX_RENDER_MATCHES = 500`), next/previous navigation, conservative severity filtering (`all`, `error`, `warn`, `info`, `debug`, `other`), and accurate count/scope labeling.
Verified with headless Chrome CDP, Node unit tests, and Python test suites.
See `plans/20261024-runmux-web-enhanced-logs/HANDOFF.md` and `STATUS.md`.

## Runmux Web UI — Phase 3 integrated

Phase 1 browser launching, Phase 2 terminal/log correctness, and the Phase 5B
telemetry backend are present in the `main` baseline. Phase 3 was merged from
`codex/runmux-web-phase3-20261024` into main at `54502666b5724596ee3d21c1e694b8522d5a5151` with no conflicts.
The feature branch and its worktree remain available for reference. Read
`plans/20261024-runmux-web-explorer-workspace/STATUS.md` for validation,
privacy boundaries, and remaining limitations.

Last updated: 2026-10-24

## Historical notes — completed earlier phases

The Runmux Web UI UX refinement was merged into `main` on 2026-10-24
from `codex/runmux-web-ux-20261024`, based on `origin/main` at
`3e84e8c9a5de3c83b268c7988944e34da716fb2b`. See
`plans/20261024-runmux-web-ux-refinement/00-implementation-plan.md` for the
gap assessment and validation. It adds status-grouped process navigation and
browser-only process tabs, and gives the process workspace more screen space.
It preserves the existing authenticated terminal and supervisor input-lock
flow. The merge is published on `origin/main`.

The preceding interactive-terminal feature was merged into `origin/main` and
its completed record remains in `plans/20261023-runmux-web-interactive-terminal/`.

### UX refinement validation

- Desktop screenshot and interaction smoke used only the synthetic registry
  under `.pytest_tmp_root/web-ux-visual`.
- Verified status grouping, selecting two views, switching between them,
  closing one view while its process remained listed, and the Details labels.
- Browser access required an elevated local loopback server because the default
  sandbox could not bind the port; no production state was opened.
- Automated test results are recorded in the UX refinement plan.

An earlier branch added an authenticated browser terminal to the Web UI. Its
archived plan and validation are in
`plans/20261023-runmux-web-interactive-terminal/`. That historical branch was
published for review without merging.

The earlier native TUI integration remains recorded below as project history;
the branch named in that historical section differs from this feature branch.

For that historical integration, the original read order was:

1. Applicable global and repository-level LLM instructions
2. `README.md`
3. `plans/HANDOFF.md`
4. `plans/20261023-runmux-web-interactive-terminal/HANDOFF.md`
5. `plans/20261023-runmux-web-interactive-terminal/STATUS.md`
6. `plans/20261023-runmux-web-interactive-terminal/checklist.md`
7. `plans/20261023-runmux-web-interactive-terminal/00-implementation-plan.md`

## Current State

- Cycle 1 was committed as `f697615`.
- Stage 2 was committed as `1cb73e4` and manually approved on 2026-07-19.
- Integration branch is `codex/runmux-native-tui-final-integration`, based on
  `f6bf043bee4cf9a694f52ce7c2845510f3cde5d0`.
- Runmux source version is `0.11.0` on this branch.
- The read-only browser UI is available as `runmux web`; its login code is
  printed at startup and remains valid until server exit.
- The native process workspace is available as `runmux tui`; it is being
  integrated using the consolidated `cli_tui` package.
- Stage 2 automated verification passed and the user confirmed concurrent
  terminals can interact with or view the same managed run.
- Stage 4 history display, filtering, common-command, replay, interactive, and
  fzf code is implemented but awaiting user-run tests and manual validation.
- Documentation now includes a detailed project README, reusable AGENTS policy,
  and HANDOFF files in every created documentation directory.
- Current acceptance checks and remaining work are tracked in the final
  integration plan linked above.

## Cycle 2 Implementation

- SQLite attachment-session schema and lifetime counters.
- View and interact registration with heartbeat leases.
- Concurrent interact clients.
- Supervisor-owned FIFO input lock.
- First interactor receives initial ownership.
- Lowercase `l` requests ownership from Ctrl-X command mode.
- Ten-second minimum tenure and 250 ms input-idle transfer.
- Immediate holder-disconnect handoff.
- Stale-session expiration.
- Input from non-holders is discarded rather than replayed.
- `runmux ls/list` and JSON expose attachment and lock counts.

## Verification Evidence

```text
pytest --tb=short -q .\modules\runmux\  -> 72 passed
ruff check ...                         -> passed
black --check --line-length 120 ...    -> passed
python -m compileall ...               -> passed
coverage                               -> 54% overall, store 89%
real IPC smoke                         -> I:2 V:1 T:3 L:1 Q:1
```

## Manual Validation

The user confirmed on 2026-07-19 that multiple terminals can interact with or
view the same managed run. The original validation procedure was:

1. Start an indefinitely interactive managed program.
2. Open two `runmux interact` clients for the same run.
3. Verify Ctrl-X works independently in both clients.
4. Verify only the first client initially controls program input.
5. In the second client press Ctrl-X, then lowercase `l`.
6. Verify it reports queue position 1.
7. After minimum tenure and holder inactivity, verify control transfers.
8. Add a view client and check live output.
9. Check `runmux ls` current/lifetime and lock counts.
10. Detach clients and confirm current counts drop while lifetime totals remain.

## Known Risks

- Stage 3 persistent configuration remains incomplete even though attachment
  status rendering exists in the current code.
- Stage 4 storage migration/retention remains unfinished.
- Existing overall coverage remains modest because older CLI/supervisor paths
  have limited tests, though new state/store logic has direct coverage.

## Next Action

Complete the focused TUI, web UI, lifecycle, package import-boundary,
concurrency, Ruff, and diff checks. Record any remaining Windows terminal
acceptance check in the plan. The authorized deliverable is a review branch;
do not merge it into `main`.
