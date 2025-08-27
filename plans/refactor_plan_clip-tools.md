# Refactoring Plan: Clip Tools

**Goal:** Consolidate all standalone clipboard utility scripts into a single, robust CLI tool named `clip-tools` under `pyprjs`.

### Source Files to Merge:

- `pyscripts/append_clipboard.py`
- `pyscripts/clipboard_diff.py`
- `pyscripts/clipboard_replace.py`
- `pyscripts/copy_buffer_to_clipboard.py`
- `pyscripts/copy_log_to_clipboard.py`
- `pyscripts/copy_to_clipboard.py`
- `pyscripts/output_to_clipboard.py`
- `pyscripts/replace_with_clipboard.py`

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/clip-tools`.
2.  **Build CLI:** Create a main CLI entry point (e.g., `cli.py`) using `argparse` or `typer`.
3.  **Implement Subcommands:** Refactor the logic from each source script into a dedicated subcommand:
    -   `append` (from `append_clipboard.py`)
    -   `diff` (from `clipboard_diff.py`)
    -   `replace-block` (from `clipboard_replace.py`)
    -   `copy-buffer` (from `copy_buffer_to_clipboard.py`)
    -   `copy-log` (from `copy_log_to_clipboard.py`)
    -   `copy` (from `copy_to_clipboard.py`)
    -   `paste` (from `replace_with_clipboard.py`)
    -   `run` (from `output_to_clipboard.py`)
4.  **Centralize Backend:** All clipboard get/set operations within the new tool **must** be performed by calling the unified `modules/system_tools` (the successor to `cross_platform`). No direct calls to `subprocess` for clipboard access should exist in this project.
5.  **Create `pyproject.toml`:** Define the project and its dependencies (e.g., `rich`, and a local path dependency on `system_tools` if applicable).

### Files to Delete Post-Refactoring:

- All the source scripts listed above from `pyscripts/`.
