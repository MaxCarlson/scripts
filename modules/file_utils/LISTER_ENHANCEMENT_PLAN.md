# File Lister Enhancement Plan

> **Status**: In Planning
> **Last Updated**: 2025-11-19
> **Related**: `lister.py`, `termdash/interactive_list.py`

## Overview

Enhancing the file lister with deep recursive search, smart path collapse, multiple filters, file operations, and intelligent caching for efficient file finding and management.

> **Portability note:** UI/interaction improvements should be implemented as reusable termdash widgets/helpers wherever possible so other modules (vdedup, ytaedl) can adopt them without duplication.

---

## Current State Analysis

### Existing Features (lister.py)
- ✅ Recursive directory listing with depth control (default: 0)
- ✅ Interactive TUI with folder expansion/collapse
- ✅ Glob filtering (single pattern)
- ✅ Multiple sort modes (created, modified, accessed, size, name)
- ✅ JSON output mode
- ✅ Folder size calculation (background threads)
- ✅ Clipboard integration (y key)
- ✅ Hierarchical sorting with dirs-first
- ✅ Horizontal scrolling
- ✅ Detail view

### Existing Architecture
```python
Entry dataclass:
  - path, name, is_dir, size, created, modified, accessed
  - depth, expanded, parent_path
  - calculated_size, item_count, size_calculating

ListerManager:
  - Manages expanded_folders, hidden_entries
  - get_visible_entries() - hierarchical sorting
  - toggle_folder() - dynamic loading
  - expand_all_at_depth()

Key bindings:
  - Enter: expand/collapse folder
  - ESC: collapse parent
  - e: expand all at depth
  - o: open in new window
  - y: copy path to clipboard
  - S: calculate folder sizes
  - c/m/a/s/n: sort keys
  - f: filter, x: exclude
  - d/t: toggle date/time
  - F: dirs-first toggle
```

---

## New Features Implementation Plan

### Phase 1: Deep Recursive Search & File Type Filtering

**Goal**: Enable unlimited depth search with file type filtering

#### Tasks
- [x] Analysis complete
- [ ] Add `-e/--extension` argument (e.g., `-e pdf`, `-e "*.pdf"`)
- [ ] Add `-t/--type` argument (alias for extension, e.g., `-t pdf`)
- [ ] Change default depth to 999999 when extension filter is used
- [ ] Add `--max-depth` argument (overrides default)
- [ ] Implement progress display during initial scan
- [ ] Show real-time count during scan: "Scanning... found 42 PDFs"
- [ ] Optimize scan to skip non-matching files early

#### CLI Changes
```bash
# Old: only show current directory
file-util ls

# New: deep search for PDFs
file-util ls -e pdf
file-util ls -e "*.pdf" --max-depth 8192

# New: search from specific path
file-util ls /path/to/search -e pdf

# Current directory (.) should be default
file-util ls -e pdf  # searches ./ recursively
```

#### Implementation Notes
- Modify `read_entries_recursive()` to accept extension filter
- Add progress callback to report scan progress
- Add entry counter in UI footer: "1,234 files matched"

**Estimated Time**: 4-6 hours

---

### Phase 2: Smart Path Collapse

**Goal**: Hide irrelevant intermediate folders when searching for specific files

#### Concept
```
Before (standard view):
  folder1/
    subfolder_irrelevant/
      another_irrelevant/
        target.pdf
  folder2/
    also_irrelevant/
      target2.pdf

After (collapsed view):
  folder1/.../target.pdf
  folder2/.../target2.pdf
```

#### Tasks
- [ ] Implement `collapse_paths` flag in ListerManager
- [ ] Create `get_collapsed_entries()` method
- [ ] Add logic to identify "intermediate" folders (no siblings, no matches)
- [ ] Render collapsed paths as "parent/.../child"
- [ ] Add `P` key to toggle path collapse in TUI
- [ ] Add `--collapse-paths` / `--no-collapse-paths` CLI flags
- [ ] Store original depth for uncollapsing

#### Implementation Notes
- Only collapse when extension filter is active
- Keep track of hidden intermediate folders for expansion
- Show full path in detail view
- Add indicator: "📁 Collapsed: 3 levels"

**Estimated Time**: 6-8 hours

---

### Phase 3: Multiple Filters (Filter Stacking)

**Goal**: Apply multiple filters progressively to narrow down results

#### Concept
```
All files (1000)
  → Filter 1: *.pdf (500)
    → Filter 2: *report* (50)
      → Filter 3: *2024* (12)
```

#### Tasks
- [ ] Create `FilterStack` class to manage multiple filters
- [ ] Modify UI to show filter stack in header
- [ ] Add `f` key to add new filter (current behavior)
- [ ] Add `F` key to remove last filter
- [ ] Add `Ctrl+F` to clear all filters
- [ ] Add numbered filter removal: `1f`, `2f`, `3f` removes filter 1, 2, 3
- [ ] Update filter display: "Filters: [*.pdf] [*report*] [*2024*] (12 items)"
- [ ] Implement progressive filtering logic
- [ ] Store original unfiltered entries for restoration

#### UI Design
```
┌─────────────────────────────────────────────────────┐
│ Path: /home/user/documents                          │
│ Filters: [*.pdf] [*report*] [*2024*]  (12 items)   │
│ f:add F:remove ^F:clear                             │
├─────────────────────────────────────────────────────┤
│ 2024-11-15  ../reports/report_2024_Q1.pdf  2.5 MB  │
│ 2024-11-16  ../reports/report_2024_Q2.pdf  2.8 MB  │
│ ...                                                  │
└─────────────────────────────────────────────────────┘
```

**Estimated Time**: 8-10 hours

---

### Phase 4: File Operations (Copy, Move, Delete)

**Goal**: Perform file operations on filtered items

#### Operations
1. **Copy**: `c` (single), `C` (bulk)
2. **Move**: `m` (single), `M` (bulk)
3. **Delete**: `D` (single/bulk with confirmation)

#### Tasks
- [ ] Create `FileOperations` class
- [ ] Implement copy operation (single file)
- [ ] Implement bulk copy (all visible filtered items)
- [ ] Implement move operation (single/bulk)
- [ ] Implement delete operation with confirmation
- [ ] Add destination folder selection
- [ ] Add progress bar for bulk operations
- [ ] Add error handling and rollback
- [ ] Add dry-run preview before bulk operations
- [ ] Log all operations to operation history

#### Destination Folder Selection
- Via CLI: `-D/--dest-folder /path/to/dest`
- Via TUI: `:` command to enter dest path
- Via TUI: `b` key to browse with tree picker

#### Confirmation Dialog
```
┌──────────────────────────────────────┐
│ Bulk Copy Operation                  │
│                                      │
│ Copy 12 files to:                    │
│ /home/user/backup/                   │
│                                      │
│ Total size: 45.2 MB                  │
│                                      │
│ [Y] Proceed  [N] Cancel  [P] Preview │
└──────────────────────────────────────┘
```

**Estimated Time**: 12-16 hours

---

### Phase 5: Operation Preview Panel

**Goal**: Show copied/moved items in a mini interactive list

#### Concept
```
┌─────────────────────────────────────────────────────┐
│ Path: /home/user/documents  [Main View]            │
│ Filters: [*.pdf]  (500 items)                      │
├─────────────────────────────────────────────────────┤
│ 2024-11-15  ../reports/report1.pdf  2.5 MB    [c]  │
│ 2024-11-16  ../reports/report2.pdf  2.8 MB         │
│ ...                                                  │
├─────────────────────────────────────────────────────┤
│ Operations (3 pending)  [O:toggle full view]       │
│ ✓ Copy: report1.pdf → /backup/  (2.5 MB)          │
│ ⧗ Copy: report2.pdf → /backup/  (2.8 MB)          │
│ ✗ Copy: report3.pdf → /backup/  (failed)          │
└─────────────────────────────────────────────────────┘
```

#### Tasks
- [ ] Create `OperationPanel` class (split view)
- [ ] Implement 3-way split: main list (2/3) + operations (1/3)
- [ ] Add `O` key to toggle operations panel size (1/3 ↔ full ↔ hidden)
- [ ] Show operation status: pending (⧗), complete (✓), failed (✗)
- [ ] Make operations panel interactive (navigate with arrow keys)
- [ ] Add `Tab` key to switch focus between panels
- [ ] Show operation details in operations panel detail view
- [ ] Add retry option for failed operations
- [ ] Add undo option for recent operations
- [ ] Persist operations to log file

#### Operation States
- `PENDING`: Queued, not started
- `RUNNING`: Currently executing
- `COMPLETE`: Successfully finished
- `FAILED`: Error occurred
- `CANCELLED`: User cancelled

**Estimated Time**: 10-14 hours

---

### Phase 6: Caching System

**Goal**: Intelligent caching with smart invalidation

#### Features
- Cache search results keyed by: `(path, pattern, max_depth)`
- Store: file list, mtimes, total count, total size
- Smart invalidation: only re-scan changed directories
- UI indicators: cache age, size, item count
- Cache management: update, prune, clear

#### Tasks
- [ ] Create `file_cache.py` module
- [ ] Implement `CacheManager` class
- [ ] Design cache schema (JSON or SQLite?)
- [ ] Implement cache save/load
- [ ] Implement smart invalidation (check directory mtimes)
- [ ] Add cache UI indicators in footer
- [ ] Add `U` key to update cache
- [ ] Add `P` key to prune/clean cache
- [ ] Add `--use-cache` / `--no-cache` CLI flags
- [ ] Add `--cache-dir` argument (default: `~/.cache/file-util/`)
- [ ] Add cache size limit with LRU eviction
- [ ] Add cache statistics command

#### Cache Schema (JSON)
```json
{
  "version": "1.0",
  "caches": {
    "key_hash": {
      "search_path": "/home/user/docs",
      "pattern": "*.pdf",
      "max_depth": 999999,
      "created_at": "2025-11-19T10:30:00",
      "last_accessed": "2025-11-19T11:00:00",
      "entry_count": 1234,
      "total_size": 5678901234,
      "entries": [
        {
          "path": "/home/user/docs/file.pdf",
          "size": 12345,
          "mtime": 1700000000.0,
          "is_dir": false
        }
      ],
      "dir_mtimes": {
        "/home/user/docs": 1700000000.0,
        "/home/user/docs/subdir": 1700000100.0
      }
    }
  }
}
```

#### UI Indicators
```
Footer:
┌─────────────────────────────────────────────────────┐
│ Cache: 1,234 items (2.5 GB) | Age: 5m | U:update P:prune | ↑↓:nav ↵:select │
└─────────────────────────────────────────────────────┘
```

**Estimated Time**: 12-16 hours

---

### Phase 7: Progress Indicators

**Goal**: Visual feedback for long-running operations

#### Tasks
- [ ] Add scanning progress bar
- [ ] Show real-time file count during scan
- [ ] Add cache building progress
- [ ] Add bulk operation progress (copy/move/delete)
- [ ] Add percentage and ETA
- [ ] Add cancellation support (ESC key)
- [ ] Use `termdash.progress` module

#### Progress Display
```
┌─────────────────────────────────────────────────────┐
│ Scanning: /home/user/documents                      │
│ ████████████░░░░░░░░░░░░  45%  (1,234 / 2,700)    │
│ ETA: 2m 15s  [ESC to cancel]                        │
└─────────────────────────────────────────────────────┘
```

**Estimated Time**: 4-6 hours

---

### Phase 8: Termdash Enhancements

**Goal**: Create reusable components for other modules

#### New Components
1. **FolderPickerComponent**: Tree-based folder browser
2. **CacheStatusComponent**: Display cache info
3. **MultiPanelLayout**: Split view with resizable panels
4. **OperationQueueComponent**: Show pending operations
5. **ProgressBarComponent**: Enhanced progress bars

#### Tasks
- [ ] Create `termdash/folder_picker.py`
- [ ] Create `termdash/cache_status.py`
- [ ] Create `termdash/multi_panel.py`
- [ ] Create `termdash/operation_queue.py`
- [ ] Enhance `termdash/progress.py`
- [ ] Add component documentation
- [ ] Add component tests
- [ ] Create example usage

**Estimated Time**: 16-20 hours

---

### Phase 9: Testing & Documentation

**Goal**: Comprehensive tests and user documentation

#### Testing Tasks
- [ ] Unit tests for file operations
- [ ] Unit tests for cache system
- [ ] Unit tests for filter stacking
- [ ] Integration tests for TUI
- [ ] Performance tests (1000+ files)
- [ ] Cross-platform tests (Windows, Linux, Termux)

#### Documentation Tasks
- [ ] Update CLI help text
- [ ] Create usage examples
- [ ] Create tutorial guide
- [ ] Update README.md
- [ ] Create screencast demos
- [ ] Document keybindings

**Estimated Time**: 8-12 hours

---

## Total Estimated Time

**Total**: ~90-120 hours (11-15 full days)

### Breakdown by Priority

#### Must Have (MVP)
- Phase 1: Deep Recursive Search (4-6h)
- Phase 2: Smart Path Collapse (6-8h)
- Phase 4: Basic File Operations (12-16h)
- Phase 7: Progress Indicators (4-6h)

**MVP Total**: ~26-36 hours (3-5 days)

#### Should Have
- Phase 3: Multiple Filters (8-10h)
- Phase 5: Operation Preview Panel (10-14h)
- Phase 6: Caching System (12-16h)

**Should Have Total**: ~30-40 hours (4-5 days)

#### Nice to Have
- Phase 8: Termdash Enhancements (16-20h)
- Phase 9: Testing & Documentation (8-12h)

**Nice to Have Total**: ~24-32 hours (3-4 days)

---

## Implementation Order

### Sprint 1: Foundation (Days 1-3)
1. Deep recursive search
2. Smart path collapse
3. Progress indicators

### Sprint 2: Operations (Days 4-6)
4. File operations (copy, move, delete)
5. Destination folder picker

### Sprint 3: Advanced (Days 7-9)
6. Multiple filters
7. Operation preview panel

### Sprint 4: Performance (Days 10-12)
8. Caching system
9. Cache UI

### Sprint 5: Polish (Days 13-15)
10. Termdash components
11. Testing & documentation

---

## Success Criteria

### MVP Requirements
- [ ] Can search for files recursively with extension filter
- [ ] Paths collapse smartly to show only relevant folders
- [ ] Can copy/move/delete files from TUI
- [ ] Progress indicators show during long operations
- [ ] Works on Windows, Linux, Termux

### Quality Requirements
- [ ] All tests passing
- [ ] Handles 5,000+ files efficiently
- [ ] No memory leaks
- [ ] Responsive UI (no freezing)
- [ ] Clear error messages

### Documentation Requirements
- [ ] Updated CLI help
- [ ] Usage examples
- [ ] Tutorial guide
- [ ] API documentation for reusable components

---

## Current File Structure

```
modules/file_utils/
├── cli.py                           # CLI entry point
├── lister.py                        # Main lister logic
├── file_cache.py                    # Cache system (NEW)
├── file_operations.py               # File ops (NEW)
├── LISTER_ENHANCEMENT_PLAN.md       # This file
└── tests/
    ├── lister_test.py               # Existing tests
    ├── file_cache_test.py           # Cache tests (NEW)
    └── file_operations_test.py      # Ops tests (NEW)

modules/termdash/
├── interactive_list.py              # Existing interactive list
├── folder_picker.py                 # Folder picker (NEW)
├── cache_status.py                  # Cache display (NEW)
├── multi_panel.py                   # Split view (NEW)
├── operation_queue.py               # Operation panel (NEW)
└── tests/
    ├── folder_picker_test.py        # Picker tests (NEW)
    └── multi_panel_test.py          # Panel tests (NEW)
```

---

## Questions & Open Items

- [ ] Q: Should cache be JSON or SQLite?
  - A: Start with JSON, migrate to SQLite if performance issues

- [ ] Q: Default cache size limit?
  - A: 1 GB or 10,000 cached searches, whichever comes first

- [ ] Q: Should operations be atomic/transactional?
  - A: Yes, implement rollback for failed bulk operations

- [ ] Q: Undo depth for file operations?
  - A: Store last 100 operations, allow undo within session

---

**End of Plan** • Ready to implement!
