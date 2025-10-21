# Knowledge Manager - Feature Roadmap & TODO List

## Overview
This document tracks all planned features for the Knowledge Manager (km) module, including both immediate priorities and future enhancements.

---

## PRIORITY 1: Critical UX Fixes

### ✅ COMPLETED
- [x] Fix 'e' key in TasksScreen to edit task title (not open nvim)
- [x] Fix 'e' key in ProjectsScreen to open project (not crash)

### 🔨 IN PROGRESS
- [ ] Fix 'e' key behavior when viewing tasks IN the project overview page
  - Currently: 'e' opens the project
  - Desired: 'e' should edit the highlighted task name (if task is selected)
  - Location: `ProjectsScreen` when detail_view_mode shows tasks

---

## PRIORITY 2: Cross-Project Task Linking (Bidirectional)

### Core Concept
Tasks can be linked to multiple projects using `@project-name` syntax in the task title. Changes to the task propagate to ALL linked projects (one task, multiple views).

### 2.1 Database Schema
- [ ] Create `task_links` table:
  ```sql
  CREATE TABLE task_links (
      task_id TEXT,
      project_id TEXT,
      is_origin BOOLEAN,  -- TRUE for project where task was created
      created_at TEXT,
      modified_at TEXT,
      FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
      FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
      PRIMARY KEY (task_id, project_id)
  )
  ```
- [ ] Add migration logic to initialize table in existing databases
- [ ] Update `db.py` with CRUD operations for task_links

### 2.2 Link Creation & Auto-Detection
- [ ] **Auto-link on save**: When task title contains `@project-name`, automatically create link
  - Parse title for all `@mentions` when creating/updating tasks
  - Create `task_links` entry for each mentioned project
  - Verify project exists (or show error)
- [ ] **Link deletion on edit**: If user removes `@project` from title, delete that link
  - Detect removed links by comparing old vs new title
  - Only allow deletion if not the origin project
- [ ] **Visual feedback**: Color `@project` mentions blue in TUI (like hyperlinks)
  - Render links with different color in task list
  - Maybe surround with delimiters like `<@project>` or `{@project}` for clarity

### 2.3 Link Display & Indicators
- [ ] Show tag indicators based on origin:
  - **Origin project**: Display `@linked-project` (blue)
  - **Linked project**: Display `%origin-project` (different color, e.g., yellow)
- [ ] Update `TaskList` rendering to inject these indicators
- [ ] Handle multiple links: `@todo @modules @security` → shows all in origin, `%modules` in others

### 2.4 Bidirectional Sync
- [ ] Update `task_ops.update_task_details_and_status()`:
  - When ANY field changes (title, status, priority, details, etc.), it updates the SAME task record
  - Since all projects reference the same `task.id`, changes are automatically visible everywhere
  - Re-parse title for `@mentions` on every update to add/remove links
- [ ] Test edge cases:
  - Changing status in one project updates all
  - Editing details in one project updates all
  - Deleting origin task deletes all links (CASCADE)

### 2.5 Link Navigation (Enter Key)
- [ ] **Current behavior**: Enter on task selects it
- [ ] **New behavior**: Enter on task WITH `@link` or `%link` jumps to that project
  - If task has exactly one link: jump immediately
  - If task has multiple links: show dialog to choose destination
  - Jump to destination project and highlight the same task
- [ ] Make `Ctrl+Enter` still available for "Follow Link" (existing behavior)

### 2.6 Link Navigation History (Breadcrumbs)
- [ ] Track navigation history as a stack: `[projectA, projectB, projectC]`
- [ ] `Ctrl+Left`: Go back one step in history (C→B→A)
- [ ] `Ctrl+Right`: Go forward one step (A→B→C)
- [ ] Store in `KmApp` as `navigation_history: List[uuid.UUID]` and `history_index: int`
- [ ] Update footer to show navigation breadcrumbs when history exists
- [ ] Clear forward history when user manually navigates to new project

---

## PRIORITY 3: Autocomplete Dialog for @Mentions

### 3.1 Autocomplete for Projects
- [ ] Detect when user types `@` in task title input
- [ ] Show dialog listing all matching projects (fuzzy search)
- [ ] Allow arrow keys + Enter to select
- [ ] Insert `@project-name` at cursor position
- [ ] Support quoted names: `@"Project Name With Spaces"`

### 3.2 Autocomplete for Tasks (Future - Lower Priority)
- [ ] Syntax: `@project->taskID` or `@project->task-title-prefix`
- [ ] After typing `@project->`, show tasks from that project
- [ ] Each task needs a human-readable short ID (e.g., first 8 chars of UUID, or auto-increment per-project)
- [ ] Insert full link: `@todo->fix-auth` or `@todo->abc12345`

---

## PRIORITY 4: Task Copies (Independent, Non-Syncing)

### Core Concept
Create independent task copies in multiple projects. Changes to one copy DO NOT affect others.

### 4.1 Syntax
- [ ] Use `&project-name` for task copies (NOT `#`, saving that for tags)
- [ ] Example: `Setup environment &dev &prod &staging` creates 3 independent tasks

### 4.2 Implementation
- [ ] On task creation, detect `&mentions` in title
- [ ] Create NEW task records (different UUIDs) for each `&project`
- [ ] Remove `&mention` from title in destination projects (or prefix with source?)
- [ ] Store metadata linking copies (new `task_copies` table?)
  ```sql
  CREATE TABLE task_copies (
      original_task_id TEXT,
      copy_task_id TEXT,
      copied_to_project_id TEXT,
      created_at TEXT,
      FOREIGN KEY (original_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
      FOREIGN KEY (copy_task_id) REFERENCES tasks(id) ON DELETE CASCADE
  )
  ```

---

## PRIORITY 5: Configuration System

### 5.1 Config File (`config.json`)
- [ ] Create `.local/share/knowledge_manager_data/config.json`
- [ ] Store customizable settings:
  ```json
  {
    "version": 1,
    "symbols": {
      "project_link": "@",           // Bidirectional link symbol
      "task_copy": "&",              // Independent copy symbol
      "tag": "#",                    // Future tag system
      "origin_indicator": "%",       // Shows task came from another project
      "task_link_separator": "->"    // For @project->taskID syntax
    },
    "link_display": {
      "surround_with": "<>",         // <@project> or {@project}
      "color_links": true,
      "link_color": "blue",
      "origin_color": "yellow"
    },
    "keybindings": {
      "follow_link": "ctrl+enter",
      "nav_back": "ctrl+left",
      "nav_forward": "ctrl+right",
      "edit_title": "e",
      "edit_details": "ctrl+e"
    },
    "behavior": {
      "auto_link_on_mention": true,
      "confirm_link_deletion": true,
      "show_link_candidates_dialog": false
    }
  }
  ```
- [ ] Create `config.py` module to load/save config
- [ ] Add validation and defaults
- [ ] Expose config via CLI: `km config set symbols.project_link "#"`

---

## PRIORITY 6: Tag System (Future)

### 6.1 Tags vs Links
- **Links** (`@project`): Task appears in multiple projects, stays synced
- **Tags** (`#keyword`): Categorization/filtering, no project association
- Examples:
  - `Fix auth bug @modules #urgent #security`
  - `Write docs @website #documentation #public`

### 6.2 Tag Features
- [ ] Parse `#tag` syntax from task titles
- [ ] Store in `task_tags` table (many-to-many)
- [ ] Filter tasks by tag: `km task list --tag urgent`
- [ ] Tag viewer in TUI (sidebar or separate screen)
- [ ] Tag autocomplete dialog (like `@mentions`)

### 6.3 Project-Tag Statistics (TUI Enhancement)
- [ ] In ProjectsScreen, add "Tag Stats" view showing:
  - Tasks from other projects tagged with this project name
  - Total tasks tagged with project (active vs completed)
  - Oldest/newest tagged tasks
  - Tag cloud visualization
- [ ] Hotkey to toggle between "Description", "Tasks", and "Tag Stats" views

---

## PRIORITY 7: TUI Enhancements

### 7.1 Link Visualization
- [ ] Syntax highlighting in task titles:
  - `@project` in blue (clickable)
  - `%origin` in yellow (indicator only)
  - `#tag` in green (future)
- [ ] Hover tooltip showing link destination
- [ ] Underline or bold for linked tasks

### 7.2 Task Details Panel Improvements
- [ ] Show all linked projects in detail view
- [ ] Show task creation/modification timestamps
- [ ] Show link creation dates
- [ ] Button to "unlink from this project" (if not origin)

### 7.3 Keyboard Shortcuts
- [ ] `Ctrl+L`: Show all links for selected task
- [ ] `Ctrl+Shift+L`: Manage links (add/remove)
- [ ] `/`: Quick search/filter (like vim)
- [ ] `?`: Show help overlay with all keybindings

---

## PRIORITY 8: CLI Enhancements

### 8.1 Link Management
- [ ] `km task link <task-id> <project-name>`: Manually add link
- [ ] `km task unlink <task-id> <project-name>`: Remove link
- [ ] `km task links <task-id>`: List all linked projects
- [ ] `km task copy <task-id> <project-name>`: Create independent copy

### 8.2 Search & Query
- [ ] `km task search <query>`: Full-text search across all tasks
- [ ] `km task find --linked-to <project>`: Find all tasks linked to project
- [ ] `km task orphans`: Find tasks not linked to any project

---

## PRIORITY 9: Testing & Documentation

### 9.1 Tests
- [ ] Unit tests for link detection (`links.py`)
- [ ] Unit tests for `task_links` CRUD operations
- [ ] Integration tests for bidirectional sync
- [ ] TUI tests for link navigation
- [ ] Test edge cases:
  - Circular links
  - Deleting linked tasks
  - Renaming projects with existing links
  - Multiple simultaneous edits

### 9.2 Documentation
- [ ] Update README.md with linking examples
- [ ] Create LINKING_GUIDE.md with detailed workflows
- [ ] Add docstrings to all new functions
- [ ] Create migration guide for existing users

---

## PRIORITY 10: Performance & Optimization

### 10.1 Database Optimization
- [ ] Add indexes on `task_links(project_id)` and `task_links(task_id)`
- [ ] Optimize task listing queries to join `task_links` efficiently
- [ ] Cache project lookups for link validation

### 10.2 TUI Performance
- [ ] Lazy-load tasks in large projects
- [ ] Virtualize task lists for projects with 1000+ tasks
- [ ] Debounce link autocomplete queries

---

## Future Ideas (Brainstorm)

### Integrations
- [ ] Export project as markdown/JSON
- [ ] Import from GitHub Issues, Jira, Trello
- [ ] Sync with external task managers (Todoist, etc.)
- [ ] Git hooks to auto-create tasks from commit messages

### AI/LLM Features
- [ ] Auto-suggest links based on task content
- [ ] Generate task summaries from details
- [ ] Smart tag suggestions
- [ ] Natural language task creation: `km task add "remind me to fix auth bug in modules project due next friday"`

### Collaboration
- [ ] Multi-user support (shared database)
- [ ] Task assignment
- [ ] Comments/discussion threads
- [ ] Activity feed

### Visualizations
- [ ] Gantt chart view for tasks with due dates
- [ ] Dependency graph (if we add task dependencies)
- [ ] Burn-down charts
- [ ] Project timeline

---

## Implementation Notes

### Link Deletion Behavior
When user edits task title and removes `@project`:
1. Detect which links were removed (compare old vs new)
2. If removing origin link: ERROR (cannot unlink from origin)
3. If removing non-origin link: Delete from `task_links` table
4. Update task display in all affected projects

### Link Symbol Conflicts
- Ensure symbols don't conflict: `@` (link), `&` (copy), `#` (tag)
- Parse in order: links first, then copies, then tags
- Handle escaping: `\@` to type literal @ without linking

### Migration Strategy
- Existing tasks with `project_id` still work (backward compatible)
- Gradually migrate to `task_links` table
- Provide CLI command: `km migrate --tasks-to-links`

---

## Questions for Future Consideration

1. **Link Permissions**: Should some projects be "read-only" for linked tasks?
2. **Link Notifications**: Notify when linked task is updated in another project?
3. **Link Expiration**: Auto-unlink tasks marked done for X days?
4. **Smart Links**: `@parent` to link to parent project, `@all` to link everywhere?
5. **Link Templates**: Predefined link patterns, e.g., "bug report" → auto-link to QA project?

---

## Version History
- 2025-10-21: Initial roadmap created based on user requirements
- Future: Update as features are implemented

---

**Note**: This document is the source of truth for km feature development. Update regularly as priorities shift.
