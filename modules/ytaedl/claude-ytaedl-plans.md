# YTAEDL Manager UI Enhancement Plans

## Overview
This document outlines planned improvements to the ytaedl download manager and MP4 watcher UI.

---

## 1. Interactive Watcher Settings Panel

### Current State
- Watcher displays status information
- Limited keyboard controls (w=switch view, c=cleaner, d=dry-run, q=quit)
- Settings are CLI arguments only, can't be changed at runtime

### Planned Features

#### A. Dynamic Settings Display
Add a settings section to the watcher panel showing current configuration:

```
MP4 Folder Synchroniser (idle)
Manager elapsed: 00:05:30
Total downloaded: 15.3 GB

Current Settings:
  Operation: MOVE              Free Space Trigger: 75.0 GB [ENABLED]
  Total Size Trigger: OFF      Keep Source: NO
  Max Files: UNLIMITED

[Settings and status information...]

-----------------------------------------------------------
Hotkeys: w=back | o=toggle copy/move | f=toggle free-space trigger
         g=toggle size trigger | F=set free-space GB | G=set size GB
         c=run cleaner | d=dry-run | q=quit
```

#### B. Keyboard Controls

**Toggle Hotkeys:**
- `o` - Toggle operation (COPY ↔ MOVE)
- `f` - Toggle free space trigger (ON ↔ OFF)
- `g` - Toggle total size trigger (ON ↔ OFF)
- `k` - Toggle keep source (YES ↔ NO)

**Value Input Hotkeys:**
- `F` (shift+f) - Prompt for new free space threshold (GB)
- `G` (shift+g) - Prompt for new total size threshold (GB)
- `M` (shift+m) - Prompt for max files per run

**Existing:**
- `w` - Back to downloads view
- `c` - Run cleaner now
- `d` - Dry-run analysis
- `q` - Quit

#### C. Input Prompt System
When user presses uppercase keys (F/G/M):
1. Clear screen
2. Display prompt: `Enter free space threshold (GB) [current: 75.0]: `
3. Read user input (with timeout after 30 seconds)
4. Validate input (must be positive number)
5. Update setting and redraw screen
6. ESC cancels and returns to normal view

#### D. Implementation Notes
- All changes apply **only to current session** (not saved)
- Settings changes take effect immediately
- Show visual feedback when settings change (brief highlight/message)
- Multi-row hotkey display at bottom if needed
- Use `WatcherConfig` dataclass but allow runtime modification

---

## 2. Fix Progress Bar >100% Issue

### Current Problem
Progress bars and percentages exceed 100% when download progress updates show:
```
[07] | 99.90%  2.89MiB/s  ETA ?  3.7G/3.7G
     [================================================.     # 99.9%
[0003][00:49:58.196] PROGRESS [4] 134.36% 5.02GiB/3.74GiB  # 134%!
```

### Root Cause Analysis
Located in `manager.py`:
1. **Worker state updates** (`_reader` function) parse NDJSON progress events
2. Raw percentage from downloader can exceed 100% near completion
3. Downloaded bytes can exceed total bytes due to:
   - Compression/decompression discrepancies
   - Download protocol overhead
   - yt-dlp reporting inconsistencies

### Solution

#### A. Clamp Progress Values
In `manager.py` `_reader()` function, after parsing progress event:

```python
elif ev == "progress":
    try:
        dl = evt.get("downloaded")
        tot = evt.get("total")
        sp = evt.get("speed_bps")
        eta = evt.get("eta_s")
        pct = evt.get("percent")

        # CLAMP downloaded to never exceed total
        if isinstance(dl, int) and isinstance(tot, int) and tot > 0:
            show_dl = min(dl, tot)  # ✓ Already doing this
            ws.downloaded_bytes = show_dl
            ws.total_bytes = tot
            # Recalculate percentage from clamped values
            pct_calc = 100.0 * (float(show_dl) / float(tot))
            ws.percent = min(99.9, pct_calc)  # ✓ Already clamping to 99.9
        elif isinstance(pct, (int, float)):
            # Clamp raw percentage too
            ws.percent = min(99.9, max(0.0, float(pct)))
```

#### B. Fix in Downloader NDJSON Output
In `downloader.py`, ensure emitted progress never exceeds 100%:

```python
def emit_json(...):
    # When emitting progress event
    if downloaded_bytes and total_bytes:
        clamped_dl = min(downloaded_bytes, total_bytes)
        percent = (clamped_dl / total_bytes) * 100.0
        percent = min(99.9, percent)  # Never report 100%
```

#### C. Display Logic
In `manager.py` render functions:
- Always show `min(99.9, percent)` in UI
- Display "?" for ETA when progress ≥ 99.5%
- Show file as "completing..." state at 99.9%

---

## 3. Fixed Header with Scrollable Workers

### Current Problem
- Status header can scroll off screen with many workers
- User can't see all workers at once
- No way to navigate to workers off-screen

### Planned Architecture

#### A. Viewport System

```python
class UIViewport:
    """Manages screen layout and scrolling."""
    def __init__(self, total_rows: int, total_cols: int):
        self.rows = total_rows
        self.cols = total_cols
        self.header_rows = 2  # Fixed header size
        self.footer_rows = 2  # Fixed footer (hotkeys)
        self.content_start = self.header_rows
        self.content_rows = self.rows - self.header_rows - self.footer_rows
        self.scroll_offset = 0  # Which worker to show first

    def visible_worker_range(self, total_workers: int) -> tuple[int, int]:
        """Returns (start_idx, end_idx) of visible workers."""
        lines_per_worker = 3  # Worker takes 3 lines
        visible_count = self.content_rows // lines_per_worker
        start = self.scroll_offset
        end = min(start + visible_count, total_workers)
        return (start, end)
```

#### B. Screen Layout

```
┌─────────────────────────────────────────────┐
│ Header: DL Manager | stats (FIXED, 2 rows) │ ← Always visible
├─────────────────────────────────────────────┤
│                                             │
│  [Worker 3]  ← scroll_offset = 2 (0-based) │
│  Stats/bars                                 │
│                                             │
│  [Worker 4]                                 │ ← Content area
│  Stats/bars                                 │    (scrollable)
│                                             │
│  [Worker 5]                                 │
│  Stats/bars                                 │
│                                             │
│  (Workers 6-7 off screen, scroll to view)  │
├─────────────────────────────────────────────┤
│ Keys: ↑/↓=scroll w=watcher q=quit (FIXED)  │ ← Always visible
└─────────────────────────────────────────────┘
```

#### C. Keyboard Navigation

**New Controls:**
- `↑` (Up Arrow) - Scroll up (decrease `scroll_offset`)
- `↓` (Down Arrow) - Scroll down (increase `scroll_offset`)
- `Home` - Jump to first worker
- `End` - Jump to last worker
- `PgUp` - Scroll up by visible count
- `PgDn` - Scroll down by visible count

**Visual Indicators:**
- Show "↑ More workers above" when scrolled down
- Show "↓ More workers below" when not at end
- Display "Worker 3-5 of 7" in header

#### D. Implementation Files

**New file: `ytaedl/ui_viewport.py`**
```python
@dataclass
class ViewportState:
    scroll_offset: int = 0
    selected_worker: int = 1
    verbose_mode: int = 0
    verbose_scroll: int = 0  # For scrolling verbose output

class WorkerViewport:
    """Manages scrolling and viewport for worker display."""
    # Calculate visible range, handle scroll bounds, etc.
```

**Modify: `manager.py`**
- Create `ViewportState` instance in main loop
- Update keyboard handling for arrow keys
- Pass viewport to render functions
- Render only visible workers

---

## 4. Verbose Output with Worker Context

### Current Problem
When viewing worker verbose output (JSON/LOG):
- Worker UI disappears completely
- Can't see which worker you're viewing
- Can't see worker stats alongside output
- No scrolling through long output

### Planned Solution

#### A. Split-Screen Layout

```
┌─────────────────────────────────────────────┐
│ Header: DL Manager | stats                 │
├─────────────────────────────────────────────┤
│ >[07] | mia_evans.txt          [A] | URL 3/4│ ← Selected worker
│  [07] | 99.90% 2.89MiB/s  3.7G/3.7G        │    (always visible)
│      [=================================...   │
├─────────────────────────────────────────────┤
│ Verbose Output (NDJSON):     [lines 5-15/50]│ ← Scrollable
│ {"event":"progress","percent":45.2,...}     │    content
│ {"event":"progress","percent":46.1,...}     │
│ ...                                          │
├─────────────────────────────────────────────┤
│ ↑/↓=scroll output  v=cycle mode  Esc=close │
└─────────────────────────────────────────────┘
```

#### B. Verbose Mode States

```python
class VerboseMode:
    OFF = 0      # No verbose output
    NDJSON = 1   # Show JSON events
    LOG = 2      # Show program log

class VerboseState:
    mode: VerboseMode = VerboseMode.OFF
    selected_slot: int = 1
    scroll_offset: int = 0  # Line offset in output
    max_visible: int = 10   # Lines to show
```

#### C. Keyboard Controls in Verbose Mode

- `↑/↓` - Scroll through output lines
- `PgUp/PgDn` - Scroll by page
- `v` - Cycle verbose mode (NDJSON → LOG → OFF)
- `Esc` or `v` (when OFF) - Close verbose view
- `1-9` - Switch to different worker (keep verbose mode)

#### D. Implementation Strategy

**In `manager.py` render logic:**

1. **Always reserve space for selected worker** (3-4 lines)
2. **Calculate remaining rows for verbose output**
3. **Slice output buffer** based on `scroll_offset`
4. **Show scroll indicators** (↑↓) and position (line X-Y of Z)

**Modifications needed:**
```python
def _render_downloads_with_verbose(
    workers: List[WorkerState],
    viewport: ViewportState,
    verbose: VerboseState,
    rows: int,
    cols: int
) -> List[str]:
    lines = []

    # 1. Header (2 rows, fixed)
    lines.extend(render_header(...))

    # 2. Selected worker (3 rows, fixed)
    selected_worker = workers[verbose.selected_slot - 1]
    lines.extend(render_single_worker(selected_worker, cols))

    # 3. Separator
    lines.append("-" * cols)

    # 4. Verbose output (remaining rows, scrollable)
    available_rows = rows - len(lines) - 2  # -2 for footer
    output_lines = get_worker_output(selected_worker, verbose.mode)
    visible_output = output_lines[
        verbose.scroll_offset:
        verbose.scroll_offset + available_rows
    ]
    lines.extend(visible_output)

    # 5. Footer with scroll info
    if len(output_lines) > available_rows:
        line_range = f"[lines {verbose.scroll_offset+1}-{verbose.scroll_offset+len(visible_output)} of {len(output_lines)}]"
        lines.append(f"Verbose Output {line_range}")

    return lines
```

---

## 5. Watcher Operation Mode Fix (COMPLETED)

**Issue**: Files were being copied but not deleted from proxy location, even with `-o move`.

**Root Cause**: The `-o <operation>` flag and `-K/--mp4-keep-source` flag were independent. The code always checked `keep_source` to decide whether to delete, but `keep_source` wasn't tied to the operation mode.

**Fix Applied** (manager.py:523-529):
```python
# Determine keep_source based on operation mode
# move = delete source (keep_source=False), copy = keep source (keep_source=True)
# But -K flag can override to always keep source
if args.mp4_keep_source:
    keep_source = True  # -K flag overrides
else:
    keep_source = (args.mp4_operation == "copy")  # copy mode keeps source, move mode deletes
```

**New Behavior**:
- `-o move` → Deletes source files after copying (frees space at proxy location)
- `-o copy` → Keeps source files after copying (duplicates files)
- `-o move -K` → Keeps source files (force override with -K flag)

**Files Modified**: `manager.py`
**Lines Changed**: ~15 lines
**Tests**: All 74 tests passing ✅

---

## 6. Implementation Order

### Phase 1: Progress Bar Fixes (COMPLETED)
1. Add clamping in `_reader()` function (manager.py:~line 900)
2. Add clamping in `emit_json()` (downloader.py)
3. Test with active downloads
4. Verify no progress >100% in UI or logs

**Files:** `manager.py`, `downloader.py`
**Lines:** ~50 changes
**Risk:** Low

### Phase 2: Viewport System (Medium Priority)
1. Create `ui_viewport.py` module
2. Add `ViewportState` to main loop
3. Implement arrow key handling
4. Update render functions for scrolling
5. Add scroll indicators

**Files:** `ui_viewport.py` (new), `manager.py`
**Lines:** ~200 new, ~100 modified
**Risk:** Medium (major UI change)

### Phase 3: Verbose Output Improvements (Medium Priority)
1. Modify render logic for split-screen
2. Add verbose scroll handling
3. Test with long output buffers
4. Ensure worker UI always visible

**Files:** `manager.py`
**Lines:** ~150 modified
**Risk:** Medium

### Phase 4: Interactive Watcher Settings (Lower Priority)
1. Add settings display to watcher panel
2. Implement toggle hotkeys
3. Add input prompt system
4. Update WatcherConfig at runtime
5. Add multi-row hotkey display

**Files:** `mp4_watcher.py`, `manager.py`
**Lines:** ~200 new
**Risk:** Low (isolated to watcher view)

---

## 6. Testing Strategy

### Unit Tests
- Progress clamping edge cases
- Viewport scroll boundary conditions
- Input validation for settings

### Integration Tests
- Download with many workers, verify scroll
- Switch verbose modes, verify worker visible
- Modify watcher settings, verify persistence in session
- Long verbose output, verify scrolling

### Manual Testing Scenarios
1. Start 7+ workers, verify header fixed, can scroll workers
2. Select worker, enable verbose, verify output scrollable
3. Progress at 99%, verify stays ≤99.9%
4. Switch to watcher, toggle settings, verify immediate effect
5. Press arrow keys in both views, verify behavior

---

## 7. File Structure Changes

```
modules/ytaedl/
├── ytaedl/
│   ├── __init__.py
│   ├── manager.py           # Modified (viewport, verbose, keyboard)
│   ├── downloader.py        # Modified (progress clamping)
│   ├── mp4_watcher.py       # Modified (interactive settings)
│   ├── mp4_sync.py          # No changes
│   ├── ui_viewport.py       # NEW (viewport management)
│   └── ui_input.py          # NEW (input prompt system)
├── tests/
│   ├── test_manager.py      # Modified (new tests)
│   ├── test_viewport.py     # NEW
│   └── test_ui_input.py     # NEW
├── claude-ytaedl-plans.md   # This file
└── README.md
```

---

## 8. Configuration Impact

### Current CLI Arguments
No changes to existing arguments. All interactive features are runtime-only.

### Future Consideration
Could add `--save-watcher-config` flag to persist settings to `.ytaedl.conf` file for next run.

---

## 9. Backward Compatibility

All changes are **backward compatible**:
- Existing CLI arguments unchanged
- Default behavior unchanged
- Tests continue to pass
- Non-interactive mode works as before

---

## 10. Performance Considerations

### Viewport Scrolling
- Only render visible workers (not all 7+)
- Minimal CPU impact (already refreshing at 5 Hz)

### Verbose Output
- Keep output buffers capped (last 1000 lines)
- Lazy slicing of visible portion only

### Watcher Settings
- Runtime changes don't trigger I/O
- Config updates are in-memory only

---

## Implementation Notes

- Use Windows `msvcrt.getwch()` for arrow key detection
- Arrow keys return 2-char sequences: `\x00` + direction code
  - Up: `\x00H`
  - Down: `\x00P`
  - Left: `\x00K`
  - Right: `\x00M`
- For input prompts, use `input()` with thread timeout
- Progress bar width calculation must account for terminal width

---

*Last Updated: 2025-10-26*
*Author: Claude (Sonnet 4.5)*


additional todos
We produce tons od artifacts inside the folder stars/urlfile/_tmp/ of the file type "*.mp4.part" or "*.part.mp4".
 doibt these are used to save tmp file prpgress, but we need tl bot emsjre theid deletiom when a downlload finisjes as well.as ensurimg thay  anh that are somewhat lld are.dleyed as well
