# Refactoring Plan: Video Tools

**Goal:** Consolidate all video post-processing scripts into a single, coherent CLI tool named `video-tools` under `pyprjs`.

### Source Files to Merge:

- `downloads_dlpn/scripts/video_processor.py`
- `downloads_dlpn/scripts/video_cleaner.py`
- `pyscripts/edit_video_file.py`
- `pyscripts/video_dedupe.py`
- `downloads_dlpn/scripts/shortest.py`

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/video-tools`.
2.  **Build CLI:** Create a main CLI entry point using `argparse` or `typer`.
3.  **Implement Subcommands:**
    -   `process`: Port the powerful re-encoding and filtering logic from `video_processor.py`. The `termdash` UI should be preserved for this command.
    -   `clean-names`: Port the logic for fixing bracketed filenames from `video_cleaner.py`.
    -   `edit`: Port the clipping and merging functionality from `edit_video_file.py`. This will require adding `moviepy` as a dependency for this project.
    -   `find-shortest`: Port the logic from `shortest.py` to find the shortest videos in a directory.
4.  **Standardize UI:** While `process` will use `termdash`, ensure all other commands use the `rich` library for consistency with other tools in the ecosystem.

### Files to Delete Post-Refactoring:

- `downloads_dlpn/scripts/video_processor.py`
- `downloads_dlpn/scripts/video_cleaner.py`
- `pyscripts/edit_video_file.py`
- `downloads_dlpn/scripts/shortest.py`
