# MangaDL CLI TUI & Side-by-Side Image Comparison Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable, modular CLI TUI package (`modules/cli_tui`) that automatically converts argparse command-line interfaces into interactive terminal TUIs with live streaming process execution dashboards, integrate it into `mangadl` (`mangadl tui` and `--tui`), and build an interactive side-by-side comparison image viewer with keyboard navigation (`Left/Right` for qualities, `Up/Down` for images, `q/Q/Esc` for exit).

**Architecture:**
- `modules/cli_tui`: Standalone reusable TUI module built on `termdash` (curses / windows-curses). Inspects an arbitrary `argparse.ArgumentParser` to extract command hierarchies, choices, defaults, and flags. Provides form editors, input validation, universal key navigation (`q` with confirmation, `Q` immediate quit, `Esc` back), and an execution runner that streams process stdout/stderr into a scrollable ANSI viewport.
- `modules/mangadl`: MangaDL integration adding `mangadl tui` and `--tui`, providing tailored shortcuts for common workflows (`run`, `compress`, `covers`, `repair`, `archive`) and connecting directly to preview outputs.
- `modules/cli_tui/image_viewer.py`: Interactive side-by-side image comparison viewer using Python's standard library `tkinter` + `PIL.ImageTk` (zero external C dependencies). Displays original image on the left and compressed candidate on the right. Supports keyboard cycling: `Left/Right` arrows cycle through quality levels of the same image, `Up/Down` arrows cycle through different sample images, `Space` toggles 1:1 zoom / fit, and `Esc`/`q` closes the viewer returning immediately to the TUI.

**Tech Stack:** Python 3.12, `termdash` (curses / windows-curses), `argparse`, `tkinter` (built-in standard library), `Pillow` (PIL), `subprocess`, `pytest`.

**Spec:** User request:
1. Reusable TUI module for programs with existing argparse formatting (subparsers, options, choices, defaults).
2. TUI menu selection, argument editing, and real-time streaming process output.
3. Universal navigation: `q` exit after confirmation from anywhere, `Q` exit immediately without confirmation, `Esc` go back.
4. MangaDL integration using termdash.
5. Side-by-side comparison image viewer: left = unchanged, right = changed, `Left/Right` cycle quality levels, `Up/Down` cycle images.

---

## Global Constraints

- Standalone modular design: `modules/cli_tui` must have no hard dependency on `mangadl` or `compresser`, making it reusable for any tool in the repository (`file_utils`, `ytaedl`, `vdedup`, etc.).
- Universal keybindings:
  - `q`: Exit confirmation prompt (`"Quit? (y/n)"`). If process is running: `"Process is running. Stop and quit? (y/n)"`.
  - `Q`: Unconditional immediate exit (kills running process if active, restores terminal, exits code 0).
  - `Esc`: Back navigation up the hierarchy (runner -> form -> parent menu -> exit prompt).
- Terminal safety: Clean terminal restore on all exit paths (curses `endwin()` and screen buffer restoration in `finally` blocks).
- Image viewer compatibility: Uses standard library `tkinter` + `Pillow` for native Windows/Linux GUI window rendering; handles missing GUI gracefully with informative terminal fallback.
- Testability: All schema parsing, state transitions, runner buffer handling, and keybinding actions must be unit-testable without requiring an interactive terminal device.

---

## Review Focus

1. **Parser introspection edge cases**: Subparser hierarchies with multiple levels (`mangadl` -> `compress` -> `estimate`), `BooleanOptionalAction` flags (`--sort/--no-sort`), repeatable arguments (`action="append"`, `nargs="+"`), and suppressed/hidden arguments (`help=argparse.SUPPRESS`).
2. **Subprocess lifecycle & stream buffering**: Unbuffered line streaming from Python children on Windows (`PYTHONUNBUFFERED=1`), avoiding pipe deadlocks, handling high line volumes without UI stutter (circular deque buffer), and clean cancellation (`SIGTERM`/`TerminateProcess`).
3. **Terminal resize & layout bounds**: Terminal resize events (`KEY_RESIZE`), bounded widths (`80`, `120`, `160` columns), ANSI escape code stripping in width calculations (`termdash.table._visible_len`), and preventing curses line overflow crashes.
4. **Image viewer indexing & missing files**: Previews where some quality levels failed or produced missing files; gracefully displaying "Unavailable" or skipping missing variants without crashing; handling different image aspect ratios side-by-side.
5. **Keybinding collisions**: Text inputs (where typing 'q' should enter the letter 'q' rather than triggering quit confirmation) vs navigation mode (where 'q' triggers exit confirmation). Explicit navigation vs edit modes.

---

## Stage Breakdown

1. **Stage 1 (`01_clitui-reusable-engine.md`)**:
   - `modules/cli_tui` module setup and package configuration (`pyproject.toml`).
   - `cli_tui.schema`: Argparse introspection and AST extraction.
   - `cli_tui.state`: Navigation and form state models.
   - `cli_tui.widgets`: Form fields (boolean, choices, text, path, multi-choice).
   - `cli_tui.process_runner`: Background process execution and thread-safe streaming output buffer.
   - `cli_tui.app`: Main curses TUI controller with `q`/`Q`/`Esc` key handling and screen transitions.
   - Stage 1 verification: Unit test suite for parser introspection, widgets, state navigation, and mock process running.

2. **Stage 2 (`02_mangadl-tui-integration.md`)**:
   - `modules/mangadl/mangadl/tui.py`: MangaDL TUI launcher and tailored menu definitions.
   - CLI integration: Add `mangadl tui` subcommand and `mangadl --tui` flag in `cli_core.py` and `cli.py`.
   - Wiring execution: MangaDL operations (`run`, `compress estimate`, `compress preview`, `compress apply`, etc.) launch into real-time runner.
   - Stage 2 verification: End-to-end testing of `mangadl tui` invocation, command generation, and execution dashboard.

3. **Stage 3 (`03_comparison-image-viewer.md`)**:
   - `modules/cli_tui/image_viewer.py`: Native Tkinter side-by-side image viewer.
   - Image loading, scaling, aspect ratio preservation, side-by-side canvas rendering.
   - Keybindings: `Left/Right` quality level cycling, `Up/Down` image cycling, `Space` zoom toggle, `q/Esc` close.
   - Scanner & Parser: Discover and group preview outputs from `.mangadl/<target>/previews/` and `.compresser/<target>/previews/`.
   - Integration: Seamless launch from TUI preview completion screen (`[ Press 'v' to View Previews ]`) and standalone CLI (`mangadl compress preview --view`).
   - Stage 3 verification: Unit tests for preview grouping, sample indexing, and key event callbacks; manual verification on real samples.
