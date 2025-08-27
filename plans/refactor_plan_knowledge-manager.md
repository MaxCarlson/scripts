# Refactoring Plan: Knowledge Manager

**Goal:** Promote the `knowledge_manager` module to a first-class, standalone application under the `pyprjs` directory.

### Source Files to Migrate:

- `modules/knowledge_manager/` (the entire directory and its contents)

### Execution Plan:

1.  **Move Project:** Relocate the entire `modules/knowledge_manager` directory to `pyprjs/knowledge_manager`.
2.  **Verify Configuration:**
    -   Inspect the `pyproject.toml` file within the new `pyprjs/knowledge_manager` directory.
    -   Ensure that the `[project.scripts]` entry point (e.g., `km = knowledge_manager.cli:main`) is correct and will function from the new location.
    -   Verify that any relative path assumptions within the code (e.g., for accessing its own TUI resources) are still valid or are updated.
3.  **No Code Merging Required:** This is primarily a structural move. The application is already self-contained and does not need to be merged with other scripts.

### Files to Delete Post-Refactoring:

- The original `modules/knowledge_manager/` directory.
