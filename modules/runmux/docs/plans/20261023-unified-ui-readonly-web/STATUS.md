# Unified UI Read-Only Web Status

Updated: 2026-10-23

## Architecture and ownership

- `web_ui_tools` owns a reusable FastAPI service, explicit app-owned `/api` router integration, static delivery, loopback server factory, and local browser session security. A separate `web_ui_tools.examples.hello_app` runs without importing runmux.
- Runmux owns its process registry, supervisors, and output. The browser adapter opens `registry.sqlite3` in SQLite read-only mode and uses only the existing authenticated `status` IPC operation for transient detail projection.
- A terminal startup code is exchanged for an opaque in-memory `HttpOnly; SameSite=Strict` cookie. API requests require a live session and either an exact same-origin header or (for safe GET/HEAD requests with omitted Origin) the browser-controlled `Sec-Fetch-Site: same-origin` marker. Host checks, no-store API responses, CSP/security headers, loopback-only binding, and disabled access logs are applied by the shared service.
- Authentication tests generate per-test codes at runtime; no static test or browser startup code is committed.
- Browser metadata is an explicit allowlist: stable full ID, user-provided name, executable basename, status/connection, PID, exit code, runtime and timestamps. Names and executable basenames may disclose project/tool identity; arguments, cwd, environment, log path, IPC port and credentials are omitted.
- Output is read from the selected run's owned `output.ansi` path, at most 64 KiB per response. The cursor detects truncation/replacement and carries decoder/parser state; incomplete UTF-8 bytes are reread on the next poll, invalid UTF-8 uses replacement characters, and ANSI/control sequences are stripped across chunk boundaries. The view caps retained text at 512 Ki characters and writes output with `textContent`.
- The frontend is an application-specific, packaged plain-JavaScript dashboard. `runmux web` loads optional web dependencies only when invoked; existing CLI/native terminal behavior remains in place.

## Implemented

- [x] Inspected the isolated worktree, repository instructions, current Runmux registry/IPC/CLI behavior, tests, and relevant Branch A adapter/log-follow code.
- [x] Added reusable `web_ui_tools` service, static hosting, authenticated API integration, shutdown-capable Uvicorn server factory, security headers, and executable independent hello-app example/test.
- [x] Added read-only Runmux listing/detail/output adapter, exact-ID validation, explicit metadata serialization, bounded UTF-8/terminal-control handling, rotation/truncation detection, and graceful missing/disconnected/inaccessible states.
- [x] Added the `runmux web` optional CLI command and application-specific process list, inspector, tabs, search, status states, and incremental output view.
- [x] Added tests for auth/origin/host restrictions, no-cache responses, independent sample app, read-only registry access, stable IDs, safe serialization, transient status IPC, output bounds/UTF-8/rotation/path ownership, route behavior, shutdown and managed-process persistence.
- [x] Visually smoke-tested the login, three synthetic process rows, details panel and an output line containing literal `<script>alert(1)</script>` in Chrome. The line appeared as text; no process from the user registry was read or controlled.
- [x] Corrected two issues found during browser verification: same-origin GET fetches that omit `Origin` now require `Sec-Fetch-Site: same-origin`, and logout removes the session from the backing dictionary correctly.
- [x] Clarified that the startup code remains valid until server exit and documented that user names/executable basenames may identify private projects or tools.

## Verification evidence

- `modules/web_ui_tools`: `python -m pytest -p no:cacheprovider tests -q` — 9 passed.
- `modules/runmux`: focused web tests with `PYTHONPATH=src;..\web_ui_tools\src` — 12 passed. The test group includes temporary registries/processes, authenticated requests and server shutdown with the managed process still alive afterward.
- Ruff focused checks for both modules' new service/adapter/tests — passed.
- `node --check src/runmux/web_static/assets/dashboard.js` — passed.
- `runmux.cli` imported and `runmux --help` rendered with `web_ui_tools` unavailable from `PYTHONPATH`; ordinary Runmux CLI use does not need web dependencies.
- Full Runmux module suite — five failures among the existing tests, and all five reproduced on clean repository `main`: `test_history_browser_renders_global_ids_and_bottom_hotkeys`, `test_list_rows_show_numeric_id_and_selected_actions`, `test_list_rows_can_colorize_status_and_selection`, `test_handle_run_save_command_marks_saved`, and `test_stats_table_cells_share_header_columns_without_ansi_padding`. No new web test failed.
- Wheel build was attempted for both packages, but local packaging could not run: pip's build tracker could not write under the machine temp directory, and `hatchling` is not installed in the available environment. Neither package produced a wheel.
- Chrome was used for visual interaction; Windows/WSL2 manual validation against a user's ordinary Runmux state directory remains outstanding.

## Branch A review and reuse

- Reviewed pushed `codex/runmux-tui-integration` commit `45b0bbd2`, including `tui_adapter.py` and `log_follow.py`.
- Kept browser code independent of the native TUI. The adapter follows the same read-only/transient-status separation, while its bounded output reader handles file identity, truncation, cursor state and UTF-8 boundaries for this browser contract. No Branch A runtime import or shared `cli_tui` edit was made.
- History locking and SQLite allocation changes were not adopted. No dependency on the other `cli_tui` worktree was identified.

## Deferred and remaining integration

- Interactive PTY, input locks, lifecycle controls, metrics, additional dashboard views, plugin discovery, and shared UI schemas remain deferred.
- The dashboard has not been installed from built wheels or manually tested against the user's regular registry. Current test and visual data are disposable and stored under the worktree's `.pytest_tmp_root`.
- Review packaging in an environment with the declared build backend available, then perform an explicitly selected local validation against a user-approved state directory if desired.
