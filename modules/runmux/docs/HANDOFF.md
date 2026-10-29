# Runmux Current Handoff

Last updated: 2026-10-29

## Current Repository State

Runmux has completed and integrated all planned Web UI and native TUI core milestones into `main`. The baseline includes:

1. **Server Lifecycle Management (`runmux web`)**:
   - Automatic discovery of existing servers: `runmux web` verifies running instances via zero-knowledge challenge-response, printing `Status: Already running` with verified URL, original access code (without regeneration), and PID, returning exit code 0 without duplicate server launch.
   - Post-bind startup reporting: the server banner (`Status: Started`) is printed only after successful loopback socket binding and ASGI application initialization.
   - Inspection via `runmux web -S` / `--status`: reports running / not running / unverifiable status, verified URL, access code, PID, and state directory without mutating state or creating credentials.
   - Graceful shutdown via `runmux web -x` / `--stop`: requests authenticated shutdown using signed challenge-response, safely disconnects WebSockets, stops background telemetry workers, removes instance descriptors, and terminates the Web UI server process. Repeated stop commands are idempotent.
   - **Timeout Descriptor Preservation**: If the server process does not terminate within the shutdown timeout, the descriptor is preserved so the instance remains discoverable, inspectable via `-S`, and retryable via `-x`.
   - **Unmanaged Port Collision Detection**: Probes port collisions on startup and warns if an unmanaged or legacy Runmux server occupies the port, without killing unverified processes.
   - **Supervisor Independence Invariant**: Stopping the Web UI server leaves all supervised Runmux processes alive and running without interruption.
   - **Owner-Scoped Filesystem Security**: Descriptors (`server_{host}_{port}.json`) use Windows ACL restriction (`icacls` removing inheritance, granting user `(F)`) and POSIX `0600` mode, and strictly reject symlinks/reparse points.
   - **Documented Exit Codes**:
     - `0`: Success (server started/discovered running; status reported running or not running; stop completed or already not running).
     - `1`: Operational error, timeout, port collision, or unverifiable instance.
     - `2`: Missing optional dependencies (`runmux[web]` or `web-ui-tools`).

2. **LLM Monitor Integration (Stages 0–5)**:
   - Host-side backend (`llm_monitor_integration.py` & `/api/llm-monitor/v1/` routes) merged at `39603daa`.
   - Browser workspace (`assets/llm-monitor.js`) merged at `ee4fcb19`.
   - Workspace switcher tabs ("Processes" and "LLM Monitor") in authenticated header.
   - Composite session identity `(provider_instance_id, session_id)`.
   - Hardware metrics card, alerts list, cursor-based event timeline.
   - Bounded ~5.0s snapshot cadence with active tab / visibility gating.
   - Out-of-order response rejection and complete lock/logout cleanup.

3. **Phase 6C Historical Explorer Frontend and Backend**:
   - Integrated into `main` at commit `ee4fcb19`.
   - Historical workspace view, supported filters/sorting, keyset cursor pagination, bounded DOM rendering, event provenance, and explicit Run ID lineage navigation.

4. **Phase 5A/B/C Telemetry Systems**:
   - 4 overview modes (Minimal, Inline, Dashboard, Expanded).
   - Live telemetry and SQLite ring-buffer historical telemetry charts.

5. **Phase 4A/B Process Lifecycle Controls & Output Search**:
   - Browser controls for graceful Stop, forced Kill, Restart, Duplicate, and Pause/Resume.
   - Bounded ANSI log search and severity filtering.

6. **Native TUI (`runmux tui`) & Process Manager Core**:
   - Full-screen terminal UI via `cli_tui`.
   - Detached ConPTY/PTY supervisors with supervisor-owned FIFO input lock.
   - Command history, saved commands, and JSONL persistence.

## Verification Evidence

All 307 tests in the Runmux test suite pass:

```text
python -m pytest modules/runmux/tests -q
-> 307 passed, 2 skipped (100% pass)

node modules/runmux/tests/llm_monitor_view_test.js
-> ALL 6 llm_monitor_view_test.js TEST SUITES PASSED!

node modules/runmux/tests/dashboard_test.js
-> Passed (exit 0)

node modules/runmux/tests/history_view_test.js
-> history_view_test.js passed

node modules/runmux/tests/llm_monitor_browser_e2e_test.js
-> ALL REAL BROWSER LLM MONITOR E2E TESTS PASSED!

ruff check modules/runmux/src/runmux modules/runmux/tests
-> All checks passed!
```

## Known Risks & Operational Guidance

- When testing web commands, prefer isolated test directories (`--state-dir`) and custom ports (`-p/--port`) to prevent interfering with any live server running on the default port 8787.
- Windows ConPTY handles ANSI escape sequences; ensure terminal clients maintain raw byte fidelity when inspecting output files.
