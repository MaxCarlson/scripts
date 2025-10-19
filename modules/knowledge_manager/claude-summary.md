# Knowledge Manager — Work Summary & Handoff (2025-10-19)

## Purpose
Bring another LLM up to speed on recent changes, current behavior, and the next tasks for the **knowledge_manager** module (CLI + Textual TUI). Focus areas: fixing tests, adding local `.kmproj` support tied to the master DB, and implementing inline `@project` / `&task` link navigation.

---

## High-Level Overview
- **Core idea:** A centralized project/task system with a master SQLite DB, plus optional **local link files** (`*.kmproj`) that refer back to master records.  
- **Interfaces:**
  - **CLI:** `km` (project and task management, link file creation, printing trees, opening TUI by reference).
  - **TUI:** `kmtui` (Textual-based UI to browse/edit projects and tasks).

---

## What Was Fixed / Added

### 1) Test Failures Resolved
- Root cause of many errors: missing `mocker` fixture.
- **Fix:** Added dev dependencies → `pytest-mock`, `pytest-asyncio`.  
- Result: **All original tests pass** (92/92). New link tests added (10) → **Total: 102 passing**.

### 2) CSS & TUI Stability
- **`tui/km_tui.css`:** Replaced invalid `$text-accent` with valid `$accent`.  
- **`tui/screens/tasks.py`:**
  - Removed invalid `await` on `pop_screen()` (not async).  
  - Introduced `update_detail_view()` and integrated it when selection changes/reselects.  
  - Added **Ctrl+G** binding to follow inline links found in details.

### 3) CLI Correctness & Quality-of-Life
- **Task subcommands** were attached to the wrong parser. Fixed to use `task_subparsers` for `list`, `view`, `done`, `getpath`, `update`.
- **Local project files:** `km project add -n "Name" -l` creates the DB project **and** a local `Name.kmproj` in CWD (via `linkfile.create_link_for_project`).
- **Shorthand open:** `km <file.kmproj>` now rewrites args internally to act like `km -o <file.kmproj>` (open/target project quickly).

### 4) New Linking System
- **`links.py` (new):**  
  - Parses inline references:
    - `@project-name` or `@"Project Name"`
    - `&task-title` or `&"Task Title"`
  - Resolves by UUID → exact name → case-insensitive prefix (optionally scoped to current project for task lookups).
  - Exposed helpers: `extract_links(text)`, `resolve_project_link()`, `resolve_task_link()`.
- **TUI integration:**
  - On **Ctrl+G**, extracts links from the **task details markdown** and navigates:
    - `@project` → switches to that project’s task screen.
    - `&task` → selects that task; switches project first if necessary.
  - If multiple links found, it currently **auto-follows the first** and shows a toast with the count.

### 5) Tests Added
- **`tests/links_test.py`** (10 tests) cover parsing and resolution flows (projects & tasks, quoted/unquoted, UUIDs, prefix matching, not-found behavior).  
- All tests pass with dev deps: `pytest-mock`, `pytest-asyncio`.

---

## Current Behavior (Quick Demos)

### Create a project that’s also linked locally
```bash
km project add -n "My Project" -l
```

### Create a `.kmproj` for an existing project in CWD
```bash
km -c "Existing Project Name"
```

### Open by link file (shorthand)
```bash
km My-Project.kmproj
```

### Launch TUI
```bash
kmtui
```

### Print a project’s tree
```bash
km print My-Project.kmproj
# or
km print "Project Name"
# or, if only one *.kmproj in CWD
km print
```

### Filter/list tasks
```bash
km task list -p "Project Name" -s todo
```

**Note (Termux):** Avoid putting `.kmproj` into `/tmp` (permission denied on some devices). Use `$HOME` or another writeable directory.

---

## Where Changes Landed (Key Files)
- **New:** `knowledge_manager/links.py`
- **Updated:**  
  - `knowledge_manager/tui/screens/tasks.py` (detail panel, Ctrl+G link follow, reselect logic)  
  - `knowledge_manager/tui/app.py` (selection updates detail view)  
  - `knowledge_manager/cli.py` (task subparsers, `--local/-l`, `.kmproj` shorthand)  
  - `knowledge_manager/tui/km_tui.css` (`$accent` fix)  
  - `pyproject.toml` (`textual>=0.47.0`, `pytest-mock`, `pytest-asyncio` in `dev` extras)

---

## Known Gaps / Next Tasks (Please implement)

1) **Follow links in task titles (list items), not only in details**  
   - **Problem:** User wants to navigate when a link appears **in the task title** (e.g., a task named `Get @syncmux working`).  
   - **Proposed behavior for Ctrl+G:**
     1. If a task is selected, **parse its title first** for `@...` / `&...`.  
     2. If none, fallback to **details markdown** (current behavior).  
     3. If multiple, present a **modal selection** list (instead of auto-following first).  
   - **TUI changes:** In `TasksScreen`, add a helper to gather links from **selected title + details**, then route to `_navigate_to_link`.  
   - **Tests:** Unit test for `links.extract_links(title)`. If feasible, a light TUI test that simulates selection + action route.

2) **Multi-link modal selection**  
   - Replace “follow the first link” with a minimal modal (`ListView` in a `Screen`/`ModalScreen`) so the user can pick which `@...`/`&...` to open.

3) **Ensure `km print <file.kmproj>` always prints**  
   - There was one run with no output. Double-check the print command path resolution and ensure it loads from either the `.kmproj` or project name if provided.

4) **Keybinding finalization**  
   - The original request considered **Ctrl+Enter** if free. Confirm conflicts. Keep **Ctrl+G** or move to **Ctrl+Enter** consistently across views. Update footer help.

5) **Robust `.kmproj` safety**  
   - When creating `.kmproj`, ensure **idempotency** in directories with existing link files; conflict policy: overwrite vs. prompt vs. `--force/-f`.

6) **Add tests for title-link resolution**  
   - New test cases for titles containing `@project` and `&task` (quoted/unquoted, UUID, cross-project).

---

## Acceptance Criteria

- **Title Links:** Pressing Ctrl+G while a task is selected:
  - If its **title** contains any `@...` or `&...` → show a modal if >1, otherwise navigate to the single target.
  - If **no title link**, fallback to details text links (existing behavior).
- **Modal UX:** A simple chooser listing discovered links (e.g., `@syncmux`, `&"Setup environment"`). **Enter** follows, **Esc** cancels.
- **Backward Compatibility:** Existing Ctrl+G flow for details still works. No regressions in selection/detail updates and reselect behavior after navigation.
- **CLI Print:** `km print <.kmproj>` reliably prints the project tree; `km print` without args prints the single `*.kmproj` in CWD; with multiple, prints an error prompting an explicit target.
- **Tests:**  
  - All existing tests remain green.  
  - New tests for `extract_links` on **titles** + resolution paths.  
  - If possible, a small TUI test verifying the action method chooses title links first (can be a unit-style test of the link-gathering function if a full TUI pilot is too heavy).

---

## Quick Dev Setup

```bash
# from knowledge_manager module root
pip install -e ".[dev]" && pytest -q
# run TUI
kmtui
# sanity
km project list && km task list -p "Some Project"
```

---

## Notes / Behaviors to Preserve
- Creating a local `.kmproj` also ensures the project exists in the **master DB** (“single source of truth”), thanks to `linkfile` plumbing.  
- Link resolution order (task): **UUID → exact title → case-insensitive prefix**; if `project_context` is supplied, search within project first, then globally.  
- After navigating to a `&task` in another project, the TUI **switches projects** and **reselects** the target task.

---
