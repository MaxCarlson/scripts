downloads_dlpn/scripts/ProcessManager.py

# Refactoring Plan: Process Manager

**Goal:** Establish the process manager script as a standalone, reusable project named `proc-manager` under `pyprjs`.

### Source Files to Migrate:

- `downloads_dlpn/scripts/ProcessManager.py`

### Execution Plan:

1.  **Create Project:** Create a new directory `pyprjs/proc-manager`.
2.  **Relocate and Rename:** Move `ProcessManager.py` into the new project directory. Consider renaming it to `cli.py` to clearly denote it as the command-line entry point.
3.  **Create `pyproject.toml`:**
    -   Create a new `pyproject.toml` file inside `pyprjs/proc-manager`.
    -   Define the project metadata (name, version, description).
    -   List its dependencies, which include `rich`, `psutil`, `filelock`, and `readchar` (or `windows-curses` for Windows).
    -   Define a `[project.scripts]` entry point to make `proc-manager` a runnable command after installation.
4.  **Refine Imports:** If the script has any relative imports, ensure they are updated to work within the new package structure.

### Files to Delete Post-Refactoring:

- `downloads_dlpn/scripts/ProcessManager.py`