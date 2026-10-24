# Runmux Web Interactive Terminal Implementation Plan

> **For agentic workers:** Implement this plan task-by-task in this session. Keep changes on `codex/runmux-web-terminal-20261023` and validate each boundary before continuing.

**Goal:** Add a browser xterm terminal that can view live ANSI output and send input only through Runmux's authenticated supervisor and input-lock mechanisms.

**Architecture:** Extend `web_ui_tools` with authenticated, same-origin WebSocket admission and enable WebSocket transport in its Uvicorn server. Runmux will expose one terminal WebSocket that registers a normal view lease, streams a bounded tail of raw ANSI log bytes, heartbeats the lease, and opens a separate supervisor-owned interact attachment only after the user requests control. Disconnecting closes those attachments only; it never changes process lifecycle.

**Tech Stack:** Python 3.10+, FastAPI/Starlette WebSockets, Uvicorn with WebSocket support, existing Runmux IPC/supervisor, xterm.js vendored static distribution.

**Spec:** This assignment's “Runmux Web UI — Interactive Terminal Implementation”; supporting UX reference archived at `docs/web-ui-visual-design-ux-implementation-specification.md`.

## Global Constraints

- Preserve existing CLI, native TUI, and read-only Web UI behavior.
- Authenticate browser WebSockets with the existing opaque session cookie and exact same-origin/loopback-host rules.
- Keep supervisor authoritative for process lifecycle and input ownership.
- Use disposable synthetic process state for tests.
- Keep xterm assets local and included in the Runmux wheel; no runtime CDN dependency.
- Do not implement deferred UI features or unrelated visual redesigns.
- Do not merge; commit and push only this dedicated feature branch.

## Review Focus

- Cross-site, expired-session, or unauthenticated WebSocket attempts are rejected before attachment or log access.
- A read-only view cannot write input, and an interact client cannot write until the supervisor reports it owns the lock.
- Disconnect/reconnect removes only the browser attachment and keeps the supervised process running.
- Run IDs, log paths, supervisor credentials, and attachment tokens are not accepted from browser input or returned to the browser.
- ANSI/UTF-8 output chunk boundaries, log truncation/rotation, and terminal status do not cause unbounded buffering or invalid file access.

---

### Task 1: Shared WebSocket authentication and transport

**Files:**
- Modify: `modules/web_ui_tools/src/web_ui_tools/app.py`
- Modify: `modules/web_ui_tools/pyproject.toml`
- Test: `modules/web_ui_tools/tests/test_app.py`

**Interfaces:** Add reusable WebSocket admission to `create_app` that validates trusted Host, exact HTTP(S) Origin matching the WS(S) request host, and a live `SESSION_COOKIE` value from `app.state.sessions`. Configure Uvicorn to use an installed WebSocket implementation and declare that implementation in the package dependencies.

- [x] Add tests for same-origin authenticated acceptance and rejection of missing/expired cookie, bad Origin, and untrusted Host.
- [x] Run those tests and confirm they fail for the missing authorization/transport behavior.
- [x] Implement shared WebSocket admission in `create_app` and enable WebSocket transport without changing HTTP middleware behavior.
- [x] Run the focused shared tests and lint the changed Python files.

### Task 2: Runmux supervisor terminal bridge

**Files:**
- Modify: `modules/runmux/src/runmux/web.py`
- Modify: `modules/runmux/src/runmux/web_adapter.py`
- Test: `modules/runmux/tests/web_test.py`
- Test: `modules/runmux/tests/web_adapter_test.py`

**Interfaces:** Add bounded raw-output reads restricted to `<state_dir>/runs/<full_run_id>/output.ansi`. Add `/api/runs/{run_id}/terminal` WebSocket, authenticated before resolving run state. Register a view attachment and heartbeat it. Accept typed JSON control messages for `interact`, `release`, `lock`, and `resize`; carry terminal keystrokes only as binary frames. Interact mode uses `open_input_socket` and supervisor lock/status IPC. On every exit path, close input and detach all sessions. Never expose a mutation operation.

- [x] Add tests proving unauthenticated/unauthorized WS requests do not attach, output is raw and bounded, and browser-provided paths/tokens are ignored.
- [x] Add disposable-supervisor tests proving input is accepted only while `session_holds_lock`, lock requests use supervisor FIFO state, and reconnect/disconnect does not stop the process.
- [x] Run the targeted tests and confirm they fail before implementing the bridge.
- [x] Implement output streaming, attachment heartbeat, interact-channel lifecycle, lock status, and cleanup.
- [x] Run focused web tests and Python lint.

### Task 3: Packaged xterm UI and documentation

**Files:**
- Modify: `modules/runmux/src/runmux/web_static/index.html`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.css`
- Modify: `modules/runmux/src/runmux/web_static/assets/dashboard.js`
- Add: `modules/runmux/src/runmux/web_static/assets/vendor/` (xterm.js, CSS, fit addon, license/version notice)
- Modify: `modules/runmux/README.md`
- Test: `modules/runmux/tests/dashboard_test.js`

**Interfaces:** Add a Terminal workspace tab and explicit View/Request control/Release control affordances. The frontend connects with same-origin cookies, writes raw output to xterm, fits/resizes the view, sends keystrokes only while supervisor lock status grants ownership, and reconnects with bounded output replay. Closing/switching selection closes browser sockets only.

- [x] Test frontend control-state handling, reconnect cleanup, and input gating with the existing Node harness.
- [x] Vendor the official xterm distribution locally and include its license/version notice.
- [x] Implement terminal tab, control/lock queue state, input, resize, reconnect/error states, and socket cleanup.
- [x] Document security/loopback model, input-lock behavior, and reconnect/process-lifecycle semantics.
- [x] Run Node syntax and focused frontend tests; visually inspect the desktop layout.

### Task 4: Packaging and compatibility verification

**Files:**
- Verify: `modules/runmux/pyproject.toml`, `modules/web_ui_tools/pyproject.toml`, both package static-file manifests
- Verify: Runmux/web UI tool test suites and CLI import boundary

- [x] Build both wheels and inspect that xterm assets and license are included.
- [x] Run focused Web UI, supervisor/attachment, CLI, and TUI tests using temporary state.
- [x] Run both packages' Ruff checks and `node --check`/dashboard tests.
- [x] Verify ordinary CLI import/help works without optional web dependencies; verify web-ui-tools declares WebSocket transport.
- [x] Review final diff and update `STATUS.md`, `checklist.md`, and Runmux handoffs.
- [ ] Commit the focused change and push `codex/runmux-web-terminal-20261023`; record commit SHA and push result.
