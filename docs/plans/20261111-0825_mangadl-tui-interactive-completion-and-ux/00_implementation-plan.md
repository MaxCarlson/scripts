# Implementation Plan: MangaDL / CLI-TUI Interactive, Completion UX, and Windows Path Fixes

## Problem Summary
1. **Windows Paths / Backslashes Stripped**:
   `cli_tui.state._split_arg_tokens` calls `shlex.split` with default POSIX mode (`posix=True`), which treats backslashes as escape characters. As a result, Windows paths like `B:\hent1imageperpage\urls37.txt` have their backslashes stripped into `B:hent1imageperpageurls37.txt`, causing download runs to fail.
2. **TextWidget Cursor Visibility, Navigation, and Mouse Clicking**:
   - Cursor indicator `▏` is unconditionally appended to the end of the text in `TextWidget.render_line`, ignoring `self.cursor_pos`.
   - Cursor navigation is limited to basic left/right arrows; Home/End, word jumps, and deletion shortcuts are missing.
   - Mouse clicks are not handled by the curses event loop or dispatched to form widgets to position the cursor.
3. **Subprocess Freeze & Deadlock on Key Input**:
   `ProcessRunner` does not isolate `stdin` with `subprocess.PIPE`. On Windows, the subprocess inherits `STD_INPUT_HANDLE` (CONIN$). Both parent (`cli_tui` PDCurses) and child (`mangadl` `msvcrt`) race to read from the console input buffer. When two-byte key sequences (like arrow keys) arrive, `mangadl` reads the prefix byte and calls `msvcrt.getwch()`, which blocks indefinitely because PDCurses consumed the second byte. Furthermore, unhandled keys in `cli_tui` are not forwarded to the subprocess.
4. **Vague Completion UX**:
   When `mangadl run` finishes, `cli_tui` only displays a subtle status string `FINISHED (Success) | Elapsed: ...` in the top header. The body keeps displaying the frozen dashboard output, making it ambiguous whether the run is done and what key to press to return.

## Proposed Architecture & Changes

### Stage 1: Windows Path Handling & TextWidget Cursor/Navigation/Mouse
- **`cli_tui/state.py`**:
  - Update `_split_arg_tokens` to use `posix=False` on Windows or whenever backslashes are present.
  - Correctly strip outer quotes from tokens while preserving all backslashes in Windows file paths.
- **`cli_tui/widgets.py`**:
  - Render cursor at `cursor_pos` in `TextWidget.render_line`, using highlighted/standout character styling and horizontal scrolling that follows `cursor_pos`.
  - Add navigation keys to `TextWidget.handle_key`: `KEY_HOME` / Ctrl+A, `KEY_END` / Ctrl+E, Ctrl+U (clear), Ctrl+K (kill to end).
  - Add `set_cursor_from_click(char_offset: int)`.
- **`cli_tui/app.py`**:
  - Enable mouse reporting with `curses.mousemask`.
  - Handle `curses.KEY_MOUSE` in `_curses_loop` and `process_key`: map clicks on form widgets to focus the widget, enter edit mode, and set cursor position.
  - Toggle `curses.curs_set(1)` when actively editing text and position the terminal cursor at the active cell.
- **Unit Tests**:
  - `cli_tui/tests/test_state.py`: Test Windows path splitting and `build_argv` preserving backslashes.
  - `cli_tui/tests/test_widgets.py`: Test cursor rendering, navigation, and click positioning.

### Stage 2: Subprocess Stdin Isolation & Key Forwarding
- **`cli_tui/process_runner.py`**:
  - Set `stdin=subprocess.PIPE` in `ProcessRunner.start()`.
  - Add `write_input(data: str)` to stream keystrokes/commands into the subprocess stdin pipe without blocking.
- **`mangadl/manager.py`**:
  - In `_keyboard()`: Protect Windows console reading by ensuring `msvcrt.getwch()` is only called when `msvcrt.kbhit()` confirms a character is waiting.
  - In `_keyboard()`: When `not sys.stdin.isatty()`, poll `sys.stdin` non-blockingly (via `ctypes.windll.kernel32.PeekNamedPipe` on Windows, or `select` on POSIX) and process received hotkeys.
- **`mangadl/ui.py`**:
  - Support `v` alongside `l` to toggle worker logs in `ConsoleDashboard.handle_key`.
- **`cli_tui/app.py`**:
  - In `_handle_running_key`: Forward unhandled keys (and UP/DOWN when output is not scrollable) to `self.runner.write_input(...)`.
  - In global shortcuts: Only cycle panes on `[` and `]` when `len(self.workspace.panes) > 1`.
- **Unit Tests**:
  - Tests in `cli_tui/tests/test_process_runner.py` for `write_input` and `stdin=subprocess.PIPE`.
  - Tests in `mangadl/tests/ui_test.py` for hotkey handling including `v` and piped input.

### Stage 3: Abundantly Clear Completion UX & Return Banner
- **`cli_tui/app.py`**:
  - In `render_virtual_screen` for `TuiScreenMode.RUNNING`:
    - Display prominent color-coded status badges: `✔ FINISHED (Success)` or `✖ FAILED (exit code {code})`.
    - Append an eye-catching, bordered completion box at the bottom of the viewport content lines clearly instructing:
      `▶ Press [Enter] to conclude and return to form`
      `▶ Press [Esc] to return to menu`
      `▶ Press [r] to re-run`
    - Elevate `[Enter] Return` as the first highlighted badge in the bottom hotkey footer when execution is finished.
- **`mangadl/manager.py`**:
  - Print a clear terminal completion summary header before emitting JSON output.
- **Unit Tests & Regression**:
  - `cli_tui/tests/test_app.py`: Test completed runner screen rendering for success and failure states.
  - Full test suite runs for both `cli_tui` and `mangadl`.
