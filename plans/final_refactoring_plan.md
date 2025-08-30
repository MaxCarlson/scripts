downloads_dlpn/manga-mgmt/model_manager/model_manager.py
downloads_dlpn/manga-mgmt/quantize-manga.py
downloads_dlpn/manga-mgmt/scrape-nhentai-tags.py
downloads_dlpn/manga-mgmt/summarize-manga.py
downloads_dlpn/scripts/ProcessManager.py
downloads_dlpn/scripts/aebndl_dlpn.py
downloads_dlpn/scripts/proc_stats.py
downloads_dlpn/scripts/randomize_urls.py
downloads_dlpn/scripts/roundrr.py
downloads_dlpn/scripts/roundrr2.py
downloads_dlpn/scripts/roundrobin_ytdlp.py
downloads_dlpn/scripts/runytdlp-multi.py
downloads_dlpn/scripts/runytdlp.py
downloads_dlpn/scripts/scan_by_date.py
downloads_dlpn/scripts/shortest.py
downloads_dlpn/scripts/urlsize_test.py
downloads_dlpn/scripts/video_cleaner.py
downloads_dlpn/scripts/video_processor.py
downloads_dlpn/tests/aebndl_dlpn_test.py
downloads_dlpn/tests/scan_by_date_test.py
modules/code_tools/func_replacer.py
modules/code_tools/rgcodeblock_cli.py
modules/code_tools/tests/test_func_replacer.py
modules/code_tools/tests/test_rgcodeblock_cli.py
modules/code_tools/tests/test_rgcodeblock_lib_extractors.py
modules/cross_platform/clipboard_utils.py
modules/cross_platform/debug_utils.py
modules/cross_platform/file_system_manager.py
modules/cross_platform/history_utils.py
modules/cross_platform/network_utils.py
modules/cross_platform/privileges_manager.py
modules/cross_platform/process_manager.py
modules/cross_platform/service_manager.py
modules/cross_platform/system_utils.py
modules/cross_platform/tmux_utils.py
modules/cross_platform/tests/clipboard_utils_test.py
modules/cross_platform/tests/debug_utils_test.py
modules/cross_platform/tests/history_utils_test.py
modules/cross_platform/tests/network_utils_test.py
modules/cross_platform/tests/privleges_manager_test.py
modules/cross_platform/tests/process_manager_test.py
modules/cross_platform/tests/system_utils_test.py
modules/cross_platform/tests/tmux_utils_test.py
modules/file_utils/duplicate_finder.py
modules/file_utils/file_manager.py
modules/file_utils/file_organizer.py
modules/file_utils/file_utils.py
modules/file_utils/utils.py
modules/knowledge_manager/cli.py
modules/knowledge_manager/db.py
modules/knowledge_manager/models.py
modules/knowledge_manager/project_ops.py
modules/knowledge_manager/task_ops.py
modules/knowledge_manager/utils.py
modules/knowledge_manager/tests/db_test.py
modules/knowledge_manager/tests/project_ops_test.py
modules/knowledge_manager/tests/task_ops_test.py
modules/knowledge_manager/tests/utils_test.py
modules/script_manager/env_setup.py
modules/script_manager/modules.py
modules/script_manager/requirements.py
modules/script_manager/scripts.py
modules/script_manager/tests.py
modules/script_manager/utils.py
modules/standard_ui/standard_ui.py
modules/system_tools/cli.py
modules/system_tools/core/clipboard_utils.py
modules/system_tools/core/debug_utils.py
modules/system_tools/core/system_utils.py
modules/system_tools/file_system/file_system_manager.py
modules/system_tools/network/network_utils.py
modules/system_tools/privileges/privileges_manager.py
modules/system_tools/process/process_manager.py
modules/system_tools/process/service_manager.py
modules/system_tools/system_info/cli.py
modules/system_tools/system_info/linux_info.py
modules/system_tools/system_info/mac_info.py
modules/system_tools/system_info/termux_info.py
modules/system_tools/system_info/windows_info.py
modules/system_tools/tests/test_cross_platform.py
modules/termdash/components.py
modules/termdash/dashboard.py
modules/termdash/utils.py
modules/termdash/ytdlp_parser.py
pyscripts/append_clipboard.py
pyscripts/clipboard_diff.py
pyscripts/clipboard_replace.py
pyscripts/copy_buffer_to_clipboard.py
pyscripts/copy_log_to_clipboard.py
pyscripts/copy_to_clipboard.py
pyscripts/edit_video_file.py
pyscripts/file_kit.py
pyscripts/folder_stats.py
pyscripts/git_sync.py
pyscripts/output_to_clipboard.py
pyscripts/replace_with_clipboard.py
pyscripts/rgcode.py
pyscripts/tests/append_clipboard_test.py
pyscripts/tests/clipboard_replace_test.py
pyscripts/tests/copy_buffer_to_clipboard_test.py
pyscripts/tests/copy_to_clipboard_test.py
pyscripts/tests/edit_video_file_test.py
pyscripts/tests/file_kit_test.py
pyscripts/tests/folder_stats_test.py
pyscripts/tests/git_sync_test.py
pyscripts/tests/output_to_clipboard_test.py
pyscripts/tests/replace_with_clipboard_test.py
pyscripts/tests/video_processory_test.py
pscripts/images/dl-mangadex-old.py
pscripts/images/dl-mangadex.py
pscripts/images/hentdl.py
pscripts/phonetopc/rsynctransfer-test.py
pscripts/phonetopc/rsynctransfer.py
pscripts/video/downloadAllPageURLs.py
pscripts/video/duplicates.py
pscripts/video/expand_urls.py
pscripts/video/FileMerger.py
pscripts/video/m3u8_extractor2.py
pscripts/video/m3u8_v2.py
pscripts/video/parallel_runner_generic2.py
pscripts/video/paralleldl.py
pscripts/video/pyppeteer_m3u8_2.py
pscripts/video/RemainingDownloads.py
pscripts/video/roundrobin_ytdlp.py
pscripts/video/roundrr.py
pscripts/video/test/expand_urls_test.py
pscripts/video/urlsize.py

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