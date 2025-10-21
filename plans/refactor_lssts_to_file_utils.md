# Refactoring Plan: `lssts.py` to `file-util ls`

**Goal:** Consolidate the standalone `pyscripts/lssts.py` script into the `file_utils` module as a new `ls` subcommand. This involves creating a reusable, interactive TUI component in the `termdash` module and enhancing the listing functionality with recursion and indentation.

---

### Execution Plan

- [x] **Part 1: Create Reusable TUI Framework in `termdash`**
    - [x] Create a new file: `modules/termdash/interactive_list.py`.
    - [x] Generalize the `curses`-based TUI logic (main loop, screen drawing, keyboard handling, state management) from `lssts.py` and move it into `interactive_list.py` to create a generic, reusable component for displaying lists of items.

- [x] **Part 2: Upgrade `file_utils` to a CLI Tool**
    - [x] Create a new command-line entry point file: `modules/file_utils/cli.py`.
    - [x] Modify `modules/file_utils/pyproject.toml` to add `[project.scripts]` entry points for a main `file-util` command and a short `fu` alias.
    - [x] Add a dependency on the `termdash` module in the `file_utils` `pyproject.toml`.

- [x] **Part 3: Implement the `ls` Subcommand**
    - [x] Create a new file for the core logic: `modules/file_utils/lister.py`.
    - [x] Move the file-gathering logic from `lssts.py` into `lister.py`.
    - [x] The `cli.py` will define the `ls` subcommand, which will call the function in `lister.py` to get file data and then pass it to the new TUI component in `termdash`.

- [x] **Part 4: Add New Features**
    - [x] In `lister.py`, update the file-gathering logic to support recursive directory walking.
    - [x] In `cli.py`, add a `--depth`/`-d` argument to control the recursion depth.
    - [x] In the `Entry` data class and the TUI's line formatting function, add support for tracking and displaying indentation to represent directory depth.
    - [x] Ensure all existing sorting features (by name, size, modified date, etc.) are preserved.
    - [x] Verify cross-platform support, especially for the `curses` library (`windows-curses` on Windows).

- [x] **Part 5: Cleanup**
    - [x] Once the new `file-util ls` command is fully implemented and tested, delete the original `pyscripts/lssts.py` file.