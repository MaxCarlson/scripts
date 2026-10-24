# Runmux Web Interactive Terminal Status

Last updated: 2026-10-23

## Current State

Implementation and focused validation are complete on `codex/runmux-web-terminal-20261023`, based on `origin/main` at `9e64c56977bb1db6469d77feaa2733130ce61023`.

- `web_ui_tools` now provides authenticated same-origin WebSocket admission for every `/api` socket and configures Uvicorn with the declared `wsproto` transport.
- Runmux exposes a terminal socket that reads bounded raw ANSI bytes, registers and heartbeats supervisor view attachments, and opens an interact channel only through supervisor IPC.
- Completed runs replay saved ANSI output without trying to reopen a supervisor attachment; input controls remain disabled and the browser does not retry the finished run.
- Binary input is sent only while the supervisor reports that attachment holds the FIFO input lock. Resize requests now carry the attachment ID and are revalidated by the supervisor under its session lock.
- Vendored xterm.js and fit assets are local, versioned, licensed, and included in the Runmux wheel.
- Closing or reconnecting a browser view releases its attachments without stopping the supervised process.

## Verification

- Combined focused shared WebSocket, Runmux web/adapter/supervisor, web CLI, and TUI compatibility tests: 63 passed.
- Frontend Node harness and `node --check`: passed.
- Ruff on changed Python code: passed.
- Both package wheels built. The Runmux wheel contains xterm.js, xterm.css, addon-fit, and both license files; the web-ui-tools wheel metadata declares `wsproto>=1.2`.
- `python -m runmux --help` succeeds with workspace module paths, and importing `runmux.cli` does not import `web_ui_tools`.
- Manual desktop browser smoke displayed a running synthetic process, terminal output, ANSI color class, supervisor lock state, and control-release action. The synthetic process completed naturally; that smoke exposed and led to a fix for finished-run reconnect behavior. The browser server was stopped and the exact temporary state directory was removed after confirming the recorded PID no longer existed.

An earlier broader run including `modules/runmux/tests/cli_test.py` produced four known unrelated failures: `test_history_browser_renders_global_ids_and_bottom_hotkeys`, `test_list_rows_show_numeric_id_and_selected_actions`, `test_list_rows_can_colorize_status_and_selection`, and `test_handle_run_save_command_marks_saved`. Their expected output/record shape predates this feature; the existing read-only Web UI plan records related CLI baseline failures. They should be assessed separately from the interactive terminal change.

## Delivery

- Feature implementation commit: `25d3393abb042edd91d289cd2080f57ae22e03bf` (`feat(runmux): add authenticated browser terminal`).
- Pushed to `origin/codex/runmux-web-terminal-20261023` and verified against the remote ref.
- Not merged.
