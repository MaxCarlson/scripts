# Phase 5A+ Overview Modes and Live Telemetry Checklist

## Task 1: Overview Mode State, Controls, and Persistence (Phase 5A)
- [x] Implement Mode A (Minimal), Mode B (Inline), Mode C (Dashboard), Mode D (Expanded)
- [x] Implement direct mode selection (A/B/C/D buttons/group)
- [x] Implement mode cycling (A -> B -> C -> D -> A) and keyboard shortcut (Alt+M)
- [x] Implement global mode persistence in localStorage (`runmux-overview-mode-v1`)
- [x] Preserve run selection, workspace tabs, output buffer, and terminal state on mode changes
- [x] Unit tests for mode initialization, cycling, selection, and persistence in `dashboard_test.js`

## Task 2: Live Telemetry Frontend Integration & Metric Provenance (Phase 5B)
- [x] Integrate `/api/runs/{run_id}/telemetry` and `/api/telemetry` endpoints
- [x] Implement process-tree CPU metrics (single-core `cpu_percent` + multicore normalized)
- [x] Implement RSS memory metrics (`formatBytes`)
- [x] Implement process and thread counts (`process_count`, `thread_count`)
- [x] Implement disk I/O throughput rates (`read_bytes_per_second`, `write_bytes_per_second`)
- [x] Implement process GPU memory when attributed (`gpu_memory_bytes`)
- [x] Implement host CPU and RAM metrics
- [x] Implement host network throughput, explicitly labeled host-wide (`HOST NETWORK (SYSTEM-WIDE)`)
- [x] Implement GPU device status and temperature, explicitly labeled hardware scope (`GPU DEVICE (HARDWARE)`)
- [x] Enforce zero vs unavailable distinctions (`null` -> `—` or `Baseline`, not `0.0%`)
- [x] Handle first-sample baselines where rates are null
- [x] Handle finished/failed/killed/lost terminal processes (`unavailable` reason display)
- [x] Unit tests for metric formatting, provenance tags, and edge cases in `dashboard_test.js`

## Task 3: Bounded Polling Engine, Visibility Management, and Lifecycle Cleanup
- [x] Implement bounded 1800ms polling cadence
- [x] Prevent overlapping/concurrent in-flight telemetry requests
- [x] Abort obsolete requests on run switch or view close (`AbortController`)
- [x] Avoid polling in Mode A (Minimal)
- [x] Suspend polling when document is hidden; resume when visible
- [x] Clean up timers on deselect, lock, tab close, or terminal process status
- [x] Handle 404 / 503 errors gracefully without tight-loop retries
- [x] Unit tests for polling lifecycle and concurrency in `dashboard_test.js`

## Task 4: Responsive Styling and Visual Polish
- [x] Mode A minimal header CSS (~34px)
- [x] Mode B inline header CSS with stat badges (~48px)
- [x] Mode C dashboard cards grid CSS
- [x] Mode D expanded diagnostic panels CSS
- [x] Responsive layouts for 390px (mobile), 768px (tablet), 1366px (laptop), 1920px (desktop), 2560px (ultrawide)

## Task 5: End-to-End Native Browser Verification & Screenshot Capture
- [x] Native Chrome CDP E2E tests in `browser_e2e_test.js`
- [x] Verify live metric updates against real server
- [x] Verify run switching and tab switching during polling
- [x] Verify responsive viewports (390px, 768px, 1366px, 1920px, 2560px)
- [x] Capture representative screenshots for Mode A, Mode B, Mode C, Mode D
- [x] Run backend regression test suites (`web_test.py`, `telemetry_test.py`, `web_adapter_test.py`)

## Task 6: Documentation, Status Ledger, and Git Branch Push
- [x] Document polling behavior and trade-offs
- [x] Update `HANDOFF.md`, `STATUS.md`, `modules/runmux/docs/plans/HANDOFF.md`, and roadmap
- [x] Verify `git status` clean and push branch `codex/runmux-web-overview-telemetry-20261024`
