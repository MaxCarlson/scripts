# Runmux Web Terminal and Log Correctness

**Phase:** RUNMUX-WEB-P2
**Branch:** `codex/runmux-web-phase2-20261024`
**Base:** merged Phase 1 at `97515f0905aa2cdc194cabd9c06a250d503256a3`
**Specification:** [`web-ui-handoff/PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md`](../web-ui-handoff/PHASE_02_TERMINAL_AND_LOG_CORRECTNESS.md)

## Goal and boundaries

Make the existing Output and Terminal views trustworthy for ordinary logs and
supported TUI output by first locating where fidelity is lost. Keep the two
views distinct, preserve the xterm.js WebSocket and supervisor input-lock
architecture, and make only changes backed by a reproducible defect. Do not
add lifecycle controls, advanced log search, metrics, or a replacement PTY.

The supplied Phase 2 handoff is the approved product and execution brief. The
implementation starts with diagnosis; no renderer or storage rewrite is
presumed.

## Verified current flow

`create_managed_run` starts a detached supervisor. The supervisor attaches the
child to ConPTY/pywinpty on Windows when available (otherwise pipes), or a PTY
on POSIX, and writes captured output to `output.ansi`. The Output API reads
bounded chunks, decodes UTF-8, removes terminal control sequences using
`TerminalTextSanitizer`, and returns a signed-by-fingerprint cursor. The browser
appends the returned text as `textContent`, caps its in-memory view at 512 KiB,
and polls while following. The Terminal WebSocket reads bounded raw bytes from
the same file, initially tails up to 128 KiB, sends an output reset followed by
binary frames, and waits for browser acknowledgements. xterm.js renders the
bytes. Resize reaches the supervisor only from the current input-lock holder.

Relevant code is in `src/runmux/supervisor.py`, `src/runmux/web_adapter.py`,
`src/runmux/web.py`, `src/runmux/web_static/assets/dashboard.js`,
`src/runmux/web_static/assets/dashboard.css`, and
`../../../../web_ui_tools/src/web_ui_tools/terminal.py` (shared sanitizer).
Existing focused tests are `tests/supervisor_test.py`,
`tests/web_adapter_test.py`, `tests/web_test.py`,
`tests/dashboard_test.js`, and `modules/web_ui_tools/tests/terminal_test.py`.

## Work sequence

### 1. Capture a reproducible baseline

- Add or use disposable synthetic programs for multiline text, carriage-return
  progress updates, ANSI cursor/erase/color output, Unicode width, long lines,
  and sustained output.
- On the Windows host, launch through Runmux with a temporary registry; capture
  the raw `output.ansi` bytes, API chunks, browser Output view, and browser
  Terminal view at recorded dimensions.
- Compare producer output, PTY/pipe capture, storage, transport, and rendering.
  Record exact evidence before choosing a fix. Do not touch real registries or
  user processes.

### 2. Pin diagnosed defects with tests

- Put byte and cursor/replay assertions in `tests/web_adapter_test.py` or
  `tests/web_test.py`; put pure sanitizer behavior in the shared terminal tests
  only when that layer is proven responsible.
- Put browser state, bounded-memory, follow-tail, and rendering-adapter
  assertions in `tests/dashboard_test.js`.
- Cover chunk-split ANSI/control sequences, truncation/reconnect, safe malicious
  text, and completed/lost runs where relevant to each demonstrated cause.
- Confirm each regression test fails for the observed defect before changing
  implementation.

### 3. Apply minimal fixes at the owning layer

- Fix only the layer identified by the baseline: supervisor capture, bounded
  adapter/replay, Output policy, browser terminal fitting/rendering, or follow
  state.
- Keep Output history-oriented and Terminal emulator-oriented. State any
  unsupported reconstruction when a bounded tail lacks the earlier terminal
  state required to rebuild a screen.
- Retain bounded server chunks, browser output size, terminal scrollback,
  inert text rendering, WebSocket authentication, reconnect behavior, and
  supervisor FIFO input-lock checks.

### 4. Verify and document

- Run `python -m pytest tests/web_adapter_test.py tests/web_test.py tests/supervisor_test.py -q`
  from `modules/runmux/` with `PYTHONPATH=src` as needed.
- Run `python -m pytest` from `modules/web_ui_tools/` if the shared sanitizer
  changes, plus `node tests/dashboard_test.js`, `node --check` on the dashboard,
  and Ruff on changed Python files.
- Repeat the synthetic browser flow with a disposable state directory and
  record screenshots only for meaningful viewport/rendering changes.
- Update the status, checklist, handoff, and Runmux Web master phase tracker
  with exact evidence, platform limits, and the resulting commit SHA.

## Review focus

- Whether the anomalous carriage-return and multi-column text is already
  present in `output.ansi` or introduced by the API/browser Output policy.
- Whether a truncated Terminal tail begins without the control history needed
  to reconstruct the current TUI screen.
- Whether requested terminal dimensions are applied to the active PTY and kept
  consistent with xterm.js at the tested viewport.
- Whether follow mode, truncation notices, reconnect and final output work
  without unbounded memory or affecting the underlying process.

## Initial status and completion

The Windows synthetic baseline confirmed that Output merged carriage-return
progress updates while Terminal interpreted the same raw stream. Subsequent
clean headless Chromium validation found a separate xterm styling CSP defect,
and a dimension-sensitive POSIX fixture proved resize ioctl did not notify the
detached child. Output normalization, scoped CSP opt-in, and POSIX SIGWINCH
delivery are implemented with regressions. Final WSL validation passed 39
Runmux tests and 8 web_ui_tools tests; Ruff and dashboard checks passed. The
headless browser visually verified synthetic Manga-style progress and
file-util-like multi-column output, safe markup, and resize/redraw. See
`STATUS.md` for acceptance coverage and limitations, including Windows
Proactor/ConPTY and Linux font constraints. Phase 2 is ready for commit/push;
do not merge or begin Phase 3.
