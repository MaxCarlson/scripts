# Refactoring Plan: Sync Tool

**Goal:** Unify all file synchronization scripts into a single, portable Python-based tool named `sync-tool` under `pyprjs`.

### Source Files to Merge:

- **Python Foundation:**
  - `pscripts/phonetopc/rsynctransfer.py`
  - `pyscripts/git_sync.py`
  - `pscripts/termux/rsyncInternal.py`
  - `pscripts/termux/rsync_final.py`
- **Shell Scripts to be Replaced:**
  - `pscripts/phonetopc/rsynctransfer.sh`
  - `pscripts/phonetopc/rsynctransfer2.sh`
  - `pscripts/phonetopc/rsynctransfer3.sh`
  - `pscripts/phonetopc/rsynctransfer4.sh`
  - `shell-scripts/copyrsync.sh`
  - `pscripts/termux/rsyncAndroidToSlice.sh`
  - `pscripts/termux/rsyncInternal.sh`

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/sync-tool`.
2.  **Establish Base:** Use the logic from `pscripts/phonetopc/rsynctransfer.py` as the foundation for the new tool's CLI and core rsync logic.
3.  **Add Git Sync Mode:** Integrate the functionality of `pyscripts/git_sync.py` as a separate mode, selectable with a flag like `--mode git` (vs. the default `--mode rsync`).
4.  **Use Core Modules:** Ensure the new tool uses the unified `modules/system_tools` for any platform-specific checks or command execution, enhancing its portability.
5.  **Create `pyproject.toml`:** Define the project's metadata and any dependencies.

### Files to Delete Post-Refactoring:

- All source files listed above from `pscripts/phonetopc/` and `pyscripts/`.
