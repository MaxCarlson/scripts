# Stage 1: Windows Path Handling & TextWidget Cursor/Navigation/Mouse

## Objectives
1. Fix `_split_arg_tokens` so backslashes in Windows file paths are never stripped.
2. Fix `TextWidget.render_line` to display the cursor at `self.cursor_pos` instead of at the end of the text.
3. Enhance `TextWidget.handle_key` to support Home, End, Ctrl+A, Ctrl+E, Ctrl+U, Ctrl+K.
4. Support mouse clicking on widgets in `cli_tui` forms: click on a text widget focuses it, enters edit mode, and moves cursor to the clicked column.
5. Provide hardware cursor positioning in `_curses_loop` while editing.

## Target Files
- `modules/cli_tui/cli_tui/state.py`
- `modules/cli_tui/cli_tui/widgets.py`
- `modules/cli_tui/cli_tui/app.py`
- `modules/cli_tui/tests/test_state.py`
- `modules/cli_tui/tests/test_widgets.py`
- `modules/cli_tui/tests/test_app.py`

## Verification
- `pytest modules/cli_tui/tests/test_state.py`
- `pytest modules/cli_tui/tests/test_widgets.py`
- `pytest modules/cli_tui/tests/test_app.py`
