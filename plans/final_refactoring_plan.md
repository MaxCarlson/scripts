# Final Refactoring and Consolidation Plan

This document synthesizes all previous analyses into a final, actionable plan for reorganizing the entire scripts project. The goal is to eliminate redundancy, improve maintainability, and establish a clear, project-based structure.

## Target Project Structure

The final structure should consolidate the scattered scripts and modules into a set of well-defined projects and shared libraries.

### Core Shared Modules (`modules/`)

This directory will house the foundational, reusable libraries that all other projects can depend on.

1.  **`system_tools`**: The single source of truth for cross-platform utilities. This will be the result of merging `cross_platform` into the better-structured `system_tools` module.
2.  **`termdash`**: A solid, reusable UI component for terminal dashboards.
3.  **`standard_ui`**: The primary tool for consistent, rich CLI output using the `rich` library.
4.  **`script_manager`**: The meta-utility for managing other scripts and modules.
5.  **`llm_manager` (Future)**: The `model_manager.py` from `manga-mgmt` is a strong candidate to be promoted to this new shared module if other projects need it.

### Standalone Applications (`pyprjs/`)

This directory will house all the major, self-contained applications and tools.

1.  **`pyprjs/file-toolkit`**: A comprehensive file system utility.
    -   **Merges:** `pyscripts/file_kit.py`, `pyscripts/folder_stats.py`, `downloads_dlpn/scripts/scan_by_date.py`, and the `modules/file_utils` module.
    -   **Functionality:** File finding, statistics, duplicate detection, organization, and analysis with a unified CLI.

2.  **`pyprjs/media-dl`**: A unified media downloading framework.
    -   **Merges:** All downloader scripts from `pscripts/video`, `pscripts/images`, `downloads_dlpn/scripts`, and the entire `downloads_dlpn/nhentai-dl` directory.
    -   **Functionality:** A core parallel runner with a plugin/config system for different sources (yt-dlp, aebndl, nhentai, etc.) and manifest extraction.

3.  **`pyprjs/video-tools`**: A dedicated suite for post-download video processing.
    -   **Merges:** `downloads_dlpn/scripts/video_processor.py`, `downloads_dlpn/scripts/video_cleaner.py`, and `pyscripts/edit_video_file.py`.
    -   **Functionality:** Re-encoding, cleaning filenames, clipping, and merging videos.

4.  **`pyprjs/manga-analyzer`**: An AI-powered manga management and analysis tool.
    -   **Merges:** The core logic from `downloads_dlpn/manga-mgmt` (`summarize-manga.py`, `quantize-manga.py`, `model_manager.py`).
    -   **Functionality:** OCR, summarization, and tagging of manga collections.

5.  **`pyprjs/sync-tool`**: A single, robust tool for file synchronization.
    -   **Merges:** All `rsynctransfer` scripts from `pscripts/phonetopc` and `pyscripts/git_sync.py`.
    -   **Functionality:** A portable Python tool for `rsync` and `git`-based synchronization.

6.  **`pyprjs/clip-tools`**: The central CLI for all clipboard operations.
    -   **Merges:** All clipboard-related scripts from `pyscripts/`.
    -   **Functionality:** A subcommand-based interface for copying, pasting, diffing, and replacing clipboard content, using `system_tools` as the backend.

7.  **`pyprjs/code-tools`**: A project for developer-focused code manipulation.
    -   **Merges:** The `modules/code_tools` module and related scripts like `pyscripts/rgcode.py`.
    -   **Functionality:** Code block extraction, function replacement, and other AST-based tooling.

8.  **`pyprjs/knowledge-manager`**: The existing personal knowledge management application.
    -   **Action:** Promote from `modules/` to `pyprjs/`.

9.  **`pyprjs/proc-manager`**: A tool for managing detached processes.
    -   **Merges:** The `downloads_dlpn/scripts/ProcessManager.py` script.

## Proposed Refactoring Plan

1.  **Stabilize the Foundation:**
    -   Fix the 12 failing tests in `modules/code_tools` to ensure its logic is sound before moving it.
    -   Complete the refactoring of `modules/cross_platform` into `modules/system_tools`. Update all dependencies and remove `cross_platform`.

2.  **Create New Project Skeletons:**
    -   Create the new directories within `pyprjs/` for each of the projects listed above (`file-toolkit`, `media-dl`, etc.).

3.  **Migrate and Consolidate:**
    -   Systematically move the logic from the identified scripts and modules into their new project homes.
    -   Refactor standalone scripts into subcommands of their respective new CLI tools.
    -   Standardize on using the core shared modules (`system_tools`, `termdash`, `standard_ui`) across all projects.

4.  **Deprecate and Delete:**
    -   Once functionality has been successfully migrated and tested, remove the old scripts from `pyscripts/`, `pscripts/`, and the now-empty module directories from `modules/`.
    -   Remove all `.bak` files and other temporary artifacts.