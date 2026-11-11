# Stage 2: Subprocess Isolation & Interaction

## Objectives
1. Set `stdin=subprocess.PIPE` in `ProcessRunner` to prevent child processes from inheriting the console input buffer (`CONIN$`) and deadlocking with curses.
2. Add non-blocking `write_input(data: str)` to `ProcessRunner`.
3. In `cli_tui/app.py`, forward unhandled keys in running mode to `self.runner.write_input(...)`, and only cycle panes when multiple panes exist.
4. In `mangadl/manager.py`, guard `_keyboard()` against blocking on missing second escape bytes, and read keys non-blockingly from piped stdin when `not sys.stdin.isatty()`.
5. Support `v` alongside `l` in `ConsoleDashboard.handle_key` to toggle worker logs.

## Target Files
- `modules/cli_tui/cli_tui/process_runner.py`
- `modules/cli_tui/cli_tui/app.py`
- `modules/mangadl/mangadl/manager.py`
- `modules/mangadl/mangadl/ui.py`
- `modules/cli_tui/tests/test_process_runner.py`
- `modules/mangadl/tests/ui_test.py`

## Verification
- `pytest modules/cli_tui/tests/test_process_runner.py`
- `pytest modules/mangadl/tests/ui_test.py`
