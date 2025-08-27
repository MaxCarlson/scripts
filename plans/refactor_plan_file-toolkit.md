# Refactoring Plan: File Toolkit

**Goal:** Consolidate all file/folder scanning, analysis, and manipulation scripts into a single, powerful CLI tool named `file-toolkit` under `pyprjs`.

### Source Files to Merge:

- **Foundation:** `pyscripts/file_kit.py`
- **Features to Integrate:**
  - `pyscripts/folder_stats.py`
  - `downloads_dlpn/scripts/scan_by_date.py`
  - `pyscripts/deduplicator.py`
  - `pyscripts/delete_files.py`
  - `pyscripts/folder_matcher.py`
  - `pyscripts/folder_similarity.py`
  - `pyscripts/zip_for_llms.py` / `pyscripts/repo_processor.py`
- **Core Library:** `modules/file_utils/` (entire module)

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/file-toolkit`.
2.  **Relocate Library:** Move the contents of `modules/file_utils` into a library subdirectory, e.g., `pyprjs/file-toolkit/lib/`.
3.  **Establish CLI:** Use `pyscripts/file_kit.py` as the foundation for the main CLI entry point (e.g., `pyprjs/file-toolkit/cli.py`). Use `argparse` or `typer` to create a subcommand structure.
4.  **Integrate Subcommands:**
    -   `find`: Merge the core listing logic from `file_kit.py` with the advanced date-based filtering (`--older-than`, `--newer-than`) from `scan_by_date.py`.
    -   `stats`: Port the directory statistics and hotspot analysis features from `folder_stats.py`.
    -   `dedupe`: Integrate the logic from `deduplicator.py`.
    -   `delete`: Use the logic from `delete_files.py`.
    -   `match`: Combine the functionality of `folder_matcher.py` and `folder_similarity.py`.
    -   `package`: Add the repository packaging logic from `zip_for_llms.py` and `repo_processor.py`.
5.  **Standardize UI:** Ensure all output uses the `rich` library for a consistent user experience. Remove all dependencies on `curses` and `tabulate`.

### Files to Delete Post-Refactoring:

- All source scripts listed above from `pyscripts/` and `downloads_dlpn/scripts/`.
- The entire `modules/file_utils/` directory.
