# Stage 5: Navigation

Escape returns one view; `H` returns to the main menu. Shift+Escape is recognized when curses reports a distinct extended key sequence. `H` is the reliable fallback. Existing nested menus continue to return to their immediate caller. Key paths are covered in `tests/test_tui.py`.
