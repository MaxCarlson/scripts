# Plan Handoff: MangaDL CLI TUI & Side-by-Side Image Comparison Viewer

**Active Plan Directory:** `docs/plans/20261019-0358_mangadl-cli-tui-and-preview-viewer/`
**Branch:** `mangadl-cli-tui-20261019-0358`
**Worktree:** `C:\Users\mcarls\src\scripts-mangadl-cli-tui`
**Status:** Complete (All 3 stages implemented, verified, and committed).

## Scope Completed
1. Reusable `modules/cli_tui` module for converting arbitrary argparse parsers into interactive TUIs (`introspect_parser`, `FormState`, interactive widgets, real-time process streaming runner).
2. Universal navigation across all TUI screens:
   - `q`: Exit with confirmation dialog (`"Are you sure you want to exit? (y/n)"`).
   - `Q`: Unconditional immediate quit without confirmation.
   - `Esc`: Go back one level (from runner to form, from form to parent menu).
3. Real-time streaming process execution with circular output buffer, elapsed time tracking, auto-scroll, and manual scrolling (Up/Down/PgUp/PgDn).
4. MangaDL integration with `mangadl tui` and `--tui` / `-T`.
5. Post-run action callbacks (`PostRunAction`), allowing runners to offer contextual actions like `[v] View Previews`.
6. Native side-by-side comparison image viewer (`cli_tui.image_viewer` using standard library Tkinter + Pillow):
   - Left panel: unchanged original image with file size.
   - Right panel: compressed candidate image with recipe, byte size, and savings percentage.
   - `Left/Right` arrow keys cycle through quality levels of the same image.
   - `Up/Down` arrow keys cycle through different sample images in the preview set.
   - `Space` toggles 1:1 zoom vs fit-to-panel.
   - `q` / `Q` / `Esc` closes the viewer.
7. Integrated `--view` / `-V` flag into `compress preview` (`mangadl compress preview --view`), automatically launching the side-by-side viewer when previews finish.

## Verification
- `python -m pytest modules/cli_tui/tests/`: 21 passed.
- `python -m pytest modules/mangadl/tests/tui_test.py`: 6 passed.
- `python -m pytest modules/mangadl/tests/cli_test.py`: 40 passed.
- `python -m pytest modules/compresser/tests/preview_test.py --basetemp=.pytest_tmp`: 13 passed.
- Ruff and Black checks 100% clean across all modules.
