# Plan Handoff: MangaDL CLI TUI & Side-by-Side Image Comparison Viewer

**Active Plan Directory:** `docs/plans/20261019-0358_mangadl-cli-tui-and-preview-viewer/`
**Branch:** `mangadl-cli-tui-20261019-0358`
**Worktree:** `C:\Users\mcarls\src\scripts-mangadl-cli-tui`
**Status:** Planning complete; awaiting user approval to begin Stage 1.

## Scope Overview
1. Standalone `modules/cli_tui` module for converting arbitrary argparse parsers into termdash-based interactive TUIs.
2. Universal navigation: `q` with confirmation, `Q` immediate quit, `Esc` back.
3. Real-time process streaming into scrollable ANSI terminal viewport.
4. MangaDL integration with `mangadl tui` and `--tui`.
5. Native Tkinter side-by-side comparison image viewer:
   - Left = unchanged original, Right = compressed candidate.
   - `Left/Right` arrow keys cycle through quality levels of the same image.
   - `Up/Down` arrow keys cycle through different images.
   - `Space` toggles 1:1 zoom vs fit.
   - `q` / `Esc` closes viewer.

## Verification Baseline
- Worktree clean.
- `python -m pytest modules/mangadl/tests/cli_test.py`: 38 passed.
- `python -m pytest modules/termdash/tests/`: 76 passed, 1 skipped.
- Ruff and Black checks clean.
