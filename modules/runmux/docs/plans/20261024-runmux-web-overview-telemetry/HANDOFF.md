# Runmux Web UI — Phase 5A+ Overview Modes and Live Telemetry Handoff

**Phase:** RUNMUX-WEB-P5A+  
**Branch:** `codex/runmux-web-overview-telemetry-20261024`  
**Base:** `origin/main` at `6fa307f3bd84761f6fe21f3700dceb9889fe090b docs(runmux): reconcile phase 4a integration status`  
**Status:** Completed and Verified with Native Windows Chrome CDP  

---

## 1. Overview and Scope

Phase 5A+ implements four selectable process overview density modes (**Mode A: Minimal**, **Mode B: Inline**, **Mode C: Dashboard**, **Mode D: Expanded**) and completes the full frontend integration of Phase 5B's live telemetry endpoints (`GET /api/runs/{run_id}/telemetry` and `GET /api/telemetry`).

The implementation maintains the IDE-like developer desktop workspace, prioritizes log and terminal space, rigorously distinguishes unavailable measurements from valid zeros, explicitly tags process-tree versus host-wide scopes, enforces bounded non-blocking polling, and survives page reloads and viewport resizing without state corruption.

---

## 2. Implemented Overview Modes

| Mode | Header Height | Intended Usage | Displayed Elements | Polling Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Mode A — Minimal** | ~36px | Maximum space for Output/Terminal logs | Process name, status badge, compact command/ID inline. Symbol, eyebrow, and all telemetry hidden. | Polling suspended (0 network/CPU overhead). |
| **Mode B — Inline** | ~48px (Default) | Compact live monitoring without losing log space | Essential process identity plus inline live CPU %, RSS memory, and process/thread count badges. | Polls `/api/runs/{id}/telemetry` at 1.8s interval. |
| **Mode C — Dashboard** | ~130px | Balanced live process inspection | Full process header + 5 resource cards: Process CPU (including multicore normalization), Resident RAM (RSS), Process Tree (procs/threads), Disk I/O Rate (read/write throughput), Process GPU RAM. | Polls `/api/runs/{id}/telemetry` at 1.8s interval. |
| **Mode D — Expanded** | ~240px | Full diagnostic presentation | All Mode C process-tree cards + 4 host/hardware cards: Host CPU Total, Host RAM (used/total), Host Network (System-wide), GPU Device (Hardware load, VRAM, temp). | Decoupled dual-cadence: polls selected run at 1.8s and host overview (`/api/telemetry`) at 5.4s. |

---

## 3. Mode Switching and Persistence

- **Cycle Shortcut & Button:** Cycle `A → B → C → D → A` using the `⟳` cycle button or global keyboard shortcut `Alt+M`.
- **Direct Selection:** Individual `A`, `B`, `C`, `D` buttons with accessible `aria-pressed` and tooltips.
- **Global Setting:** One global preference across all process tabs; changing tabs retains the selected mode.
- **Safe Persistence:** Persisted in browser `localStorage` under `runmux-overview-mode-v1`. No secrets, tokens, logs, or command arguments are stored.
- **Non-Disruption Guarantee:** Changing modes does not reset or reload:
  - Selected process or tab list.
  - Active view tab (Output / Terminal / Details).
  - Terminal WebSocket connection, PTY input lock, or focus.
  - Output search query, case toggle, severity filter, or loaded buffer.
  - Output auto-follow state or scroll position.

---

## 4. Telemetry Provenance and Correctness

In accordance with `modules/runmux/docs/plans/20261024-runmux-telemetry-backend/TELEMETRY_PROVENANCE.md`:

1. **Zero vs. Unavailable Distinction:**
   - Valid zero work (`cpu_percent === 0.0`, `read_bytes_per_second === 0`) renders as `0.0%` and `0 B/s`.
   - Missing or unestablished data (`null` / `undefined`) renders as `—` (with informative subtext such as `Baseline pending (first sample)` or `I/O rate unavailable`), never masked as `0.0%` or `0 B/s`.
2. **GPU Memory Attribution Distinction:**
   - `gpu_memory_bytes == null`: Renders as `Unavailable` with subtext `No GPU attribution data` (never masked as zero).
   - `gpu_memory_bytes === 0`: Renders as `0 B` with subtext `Verified zero GPU memory`.
   - `gpu_memory_bytes > 0`: Formatted bytes with subtext `Attributed compute VRAM`.
3. **Strict Attribution & Scope Separation:**
   - Process tree cards are tagged `PROCESS TREE` (user+sys deltas summed across living descendant tree).
   - Host metrics are explicitly tagged `HOST & SYSTEM (NOT ATTRIBUTED TO PROCESS)`.
   - Host network throughput is explicitly labeled `HOST NETWORK (SYSTEM-WIDE)` to prevent operators from mistaking host-wide traffic for process traffic.
   - GPU device load and temperature are explicitly labeled `GPU DEVICE (HARDWARE)`.
4. **Stale Telemetry and ISO Timestamp Parsing:**
   - `sampled_at` ISO 8601 UTC strings parsed correctly via `parseTelemetryTimestamp()`.
   - When sample age exceeds 6.0 seconds without updates, status banner displays `Stale telemetry (Xs ago)`.
5. **Terminal and Exited Process Handling:**
   - Live polling terminates only when the run is genuinely terminal (`finished`, `failed`, `killed`, `lost`, or `unavailable === "run is finished"` / `"process exited"`).
   - Transient states (e.g. `unassigned pid` or momentary access error) display informational banners but do NOT terminate polling, allowing bounded retry on the regular interval.
6. **No Speculative Historical Series:**
   - Live rates display instantaneous rates and total counters; no historical charts are fabricated from isolated live samples.

---

## 5. Efficient Polling Architecture

- **Dual-Cadence Polling:**
  - Selected Process Telemetry (`/api/runs/{id}/telemetry`): 1.8s (`TELEMETRY_INTERVAL_MS = 1800`). Smooth rate deltas exceeding the 1.5s GPU cache window.
  - Host Overview (`/api/telemetry`): 5.4s (`HOST_TELEMETRY_INTERVAL_MS = 5400`). Decoupling reduces `/api/telemetry` calls (which query all active processes across the fleet) by 66% (from 33 queries/min to 11 queries/min in Mode D) with cached host stats between cycles.
- **Request Cancellation & Generation Guard (`telemetryRequestId` & `telemetryInFlightId`):**
  - Concurrency guard prevents overlapping requests.
  - Aborted/superseded requests cannot reset `telemetryInFlightId` when a newer request is active.
- **Page Visibility & Mode A Suppression:**
  - Listens to `document.visibilitychange`. Polling is suspended when hidden, and immediate requests are suppressed.
  - Polling completely halted when in Mode A (Minimal) or when selection is cleared.

---

## 6. Verification and Evidence

1. **Unit Tests (`tests/dashboard_test.js`):**
   - 30 test suites passed (0 failures).
   - Includes tests for ISO 8601 stale detection, GPU null vs zero attribution, temporary unavailable vs terminal run polling, dual-cadence overhead verification, request cancellation race guards, mode cycling, and rate formatters.
2. **Headless Chrome CDP E2E Verification (`tests/browser_e2e_test.js`):**
   - Real headless Chrome launched via CDP against disposable Runmux web server and active Python worker.
   - Verified live telemetry update across Mode B, Mode A, Mode C, Mode D.
   - Verified real Chrome GPU attribution distinction: `Unavailable (No GPU attribution data)`.
   - Verified mode cycling via UI button and persistence across `Page.reload`.
   - Verified responsive layouts across viewports: `390x844` (mobile), `768x1024` (tablet), `1366x768` (laptop), `1920x1080` (desktop), `2560x1080` (ultrawide). Zero horizontal overflow.
   - Verified run switching and finished run handling.
3. **Representative Screenshots Generated:**
   - `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/screenshots/mode_a_minimal.png`
   - `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/screenshots/mode_b_inline.png`
   - `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/screenshots/mode_c_dashboard.png`
   - `modules/runmux/docs/plans/20261024-runmux-web-overview-telemetry/screenshots/mode_d_expanded.png`
4. **Backend Regressions:**
   - `python -m pytest tests/web_test.py tests/telemetry_test.py tests/web_adapter_test.py -q`: 37 tests passed in 4.7s.
   - `ruff check src/runmux/web.py src/runmux/web_adapter.py src/runmux/stats.py tests/telemetry_test.py tests/web_test.py`: All checks passed.
