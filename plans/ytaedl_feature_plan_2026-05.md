# ytaedl Feature Plan — May 2026

## Overview

Four features to implement in priority order. Features 1 and 4 are quick
surgical fixes; Feature 2 is a moderate rendering change; Feature 3 is the
largest (new interactive subsystem).

---

## Feature 1 — Proxy Duplicate Check

**Problem:** When `-P <proxy_root>` is active `_simulate_check()` only looks
in `canonical_out_dir`. If the file already exists in the proxy dir (because
a previous run downloaded it there) the downloader re-downloads it
unnecessarily.

**Affected files:** `downloader.py`

### Changes

#### `_simulate_check(url, canonical_out_dir, *, extra_check_dir=None)`

Add an optional `extra_check_dir: Optional[Path]` kwarg.

After the existing canonical scan loop, add a second scan if
`extra_check_dir is not None` and `extra_check_dir.resolve() !=
canonical_out_dir.resolve()`:

```python
if extra_check_dir and extra_check_dir.resolve() != canonical_out_dir.resolve():
    if extra_check_dir.exists():
        for existing in extra_check_dir.iterdir():
            if existing.is_file():
                if existing.name == predicted_name or existing.stem == stem:
                    return _SimulateResult(True, existing, predicted_name)
```

Return `_SimulateResult(True, ...)` on match (same semantics as canonical hit).

#### Call site in `_run_one` (~line 916)

```python
# Before:
sim = _simulate_check(url, _canonical_resolved)

# After:
sim = _simulate_check(
    url,
    _canonical_resolved,
    extra_check_dir=out_dir if (out_dir and out_dir.resolve() != _canonical_resolved.resolve()) else None,
)
```

Here `out_dir` is the proxy destination (already resolved to
`proxy_root / canonical_out_dir.name`). When `-P` is not set `out_dir ==
canonical_out_dir` so the branch is skipped.

#### `canonical_duplicate` block in `_run_one` (~line 1010-1040)

This block fires when a `destination` event arrives mid-download.  It already
resolves the proxy path back to canonical to check there.  Also check whether
the proxy `candidate` itself exists directly:

```python
# After existing canonical check, before yielding DUPLICATE:
if not dup_path and candidate.exists():
    dup_path = candidate
```

### Tests to add

`test_downloader.py`:
- `test_simulate_check_finds_dup_in_proxy_dir` — proxy dir has matching stem; should return `is_duplicate=True`
- `test_simulate_check_skips_proxy_when_same_as_canonical` — `extra_check_dir == canonical_out_dir`; no double scan

---

## Feature 2 — Watcher Log Reordering + Scan Summary

**Problem:**
1. SKIP-only entries dominate the log; important (MOVE/DELETE/ERROR) lines
   scroll off the top.
2. After a scan there's no at-a-glance summary (files scanned / skipped /
   deleted / moved per disk).

**Affected files:** `manager.py`

### 2a — Reorder log entries (SKIP last → non-SKIP last)

User's intent: non-SKIP entries should appear *last* (bottom of the visible
window) so they're always visible without scrolling.

In `_render_watcher_panel`, after `log_entries = _read_watcher_log_lines(...)`:

```python
# Partition: skip-only lines first, action lines last
def _is_skip_line(line: str) -> bool:
    clean = ANSI_ESCAPE_RE.sub("", line)
    return "[SKIP]" in clean

skip_lines    = [l for l in log_entries if _is_skip_line(l)]
noskip_lines  = [l for l in log_entries if not _is_skip_line(l)]
log_entries   = skip_lines + noskip_lines
```

This keeps the tail (most-recently-shown portion) populated by action lines.

### 2b — Scan summary table after Recent Activity

`WatcherRunSummary.summary_rows` is a `Dict[str, SummaryRow]` keyed by action
string (`"move"`, `"skip"`, `"delete"`, etc.). `SummaryRow` has `.count`,
`.transfer_size`, `.source_deleted_size`, `.destination_added_size`.

Build a compact 1-line summary after the log window:

```
Last scan (dry-run  12:34:56): scanned 120 | skip 98 | move→D1 15 | move→D2 7 | delete 3
```

Steps:
1. After displaying the Recent Activity block, check
   `snapshot.last_result is not None`.
2. Extract from `last_result.summary_rows`:
   - `scanned  = sum(row.count for row in rows.values())`
   - `skipped  = rows.get("skip").count`
   - `deleted  = rows.get("delete").count`
   - `moved    = rows.get("move").count + rows.get("copy", SummaryRow()).count`
3. For per-disk breakdown: the existing `summary_rows` rows have destination
   info aggregated (not per-disk). The plan-level per-disk breakdown exists in
   `mp4_watcher.py`'s `folder_totals` dict (set via `progress.set_folder_totals`).
   That data is NOT currently stored on `WatcherRunSummary`.

**To get per-disk counts:**

Option A (simpler, no struct change): parse the watcher log file itself.
Log events like `[HH:MM:SS] MOVE /staging/foo.mp4 → /disk1/videos/foo.mp4`
can be tallied per destination root.

Option B (cleaner): add `folder_summary: Dict[str, int]` to
`WatcherRunSummary` (count of moves per destination root). Populate it in
`mp4_watcher._run_inner` after `execute_plan` from `processed_actions`:

```python
folder_moves: Dict[str, int] = {}
for a in processed_actions:
    if a.action in {ACTION_MOVE, ACTION_COPY}:
        dest_root = Path(a.destination).parts[1]  # or drive/mount
        folder_moves[dest_root] = folder_moves.get(dest_root, 0) + 1
```

**Recommendation: go with Option B.** Requires:
- Add `folder_summary: Dict[str, int] = field(default_factory=dict)` to
  `WatcherRunSummary`.
- Populate in `mp4_watcher.py` after execute_plan.
- In `manager.py` summary line: iterate `last_result.folder_summary` for
  `move→X N` columns.

### Display format

```
─── Last Scan ──────────────────────────────────────────────────────
  dry-run  12:34:56  scanned 120  skip 98  delete 3  →/mnt/D1 15  →/mnt/D2 7
```

Rendered as one or two colourized lines immediately below the Recent Activity
section (before the hotkey line).

### Tests to add

`test_manager.py`:
- `test_watcher_log_skip_lines_sorted_first`
- `test_watcher_scan_summary_rendered` (mock `WatcherRunSummary`)

---

## Feature 3 — URL Panel: Force Queue + Priority Keybind

**Problem:** The URL panel is read-only. There is no way to force a specific
URL file (or N URLs from it) to be the next thing downloaded, without
restarting with `-P` priority flags.

### 3a — Data structure

Add to the main loop closure (near `url_order_paths`):

```python
# List of (resolved_path, remaining_count) — checked first in _assign
force_queue: List[Tuple[Path, int]] = []
```

### 3b — `_assign` honours force queue

At the top of `_assign`, before the normal priority/regular pool selection:

```python
# Check force queue first
for i, (fq_path, fq_count) in enumerate(force_queue):
    if str(fq_path) not in active and fq_path.exists():
        if fq_count <= 1:
            force_queue.pop(i)
        else:
            force_queue[i] = (fq_path, fq_count - 1)
        urlfile = fq_path
        # proceed with normal _start_worker call
        break
```

Domain-index mode: force queue is ignored (domain_index picks URLs, not
files); enqueue UI key is disabled when domain-index mode is active.

### 3c — URL panel display changes

New layout for the URLs panel:

```
URL Stats Panel | ...header...
─────────────────────────────────────────────────────────────────────
Force Queue (0 entries):
  (empty — press Enter/f to queue selected file)

─────────────────────────────────────────────────────────────────────
  Name            Total  AEBN   Stars  MP4    Rem    Ratio  GiB
► foo-bar.txt     1000   200    800    300    700    70%    12.50   ← selected row (highlighted)
  baz-qux.txt     500    0      500    400    100    80%    5.20
...

Auto refresh: ON | Keys: ... Enter=queue selected, N=set count, A=apply order, ...
```

The `►` cursor (stored as `url_panel_top`) already exists; repurpose it as the
active selection for queuing.

### 3d — New keybinds in URLs panel

| Key | Action |
|-----|--------|
| `j` / `k` | Move cursor down / up (already scroll; now also "selects") |
| `Enter` or `f` | Enqueue selected file with current force-count (default 1). Prompt for count if none set. |
| `n` | Prompt "Force N URLs from [selected file] (default 1):" — sets per-file count for the *next* enqueue. |
| `A` (capital) | Snapshot current sort order into force_queue: for each file in `ordered_entries` (top → bottom) that is not already in force_queue, append `(path, 1)`. Effectively applies the displayed rank as a one-shot priority override. |
| `D` (capital) | Remove selected entry from force_queue (if present). |
| `C` (capital) | Clear entire force_queue. |

### 3e — Display the force queue

At the top of the URLs panel content block (above the table), print:

```
Force Queue (N entries):
  [1] filename.txt  (×3 remaining)
  [2] other.txt     (×1 remaining)
```

Cap display at 5 entries; show `... and N more` if longer. Skip section when
queue is empty (show single greyed-out placeholder line).

### Implementation order

1. Add `force_queue` variable.
2. Add force-queue check at top of `_assign`.
3. Add `url_panel_cursor` (int, separate from `url_panel_top` which is scroll
   offset) to track the highlighted row.
4. Update URL panel render to show force queue block + cursor highlight.
5. Wire keybinds: `f`/Enter, `n`, `A`, `D`, `C`.
6. Test manually (no automated tests for TUI keybinds — add unit tests for
   force-queue logic in `_assign` if logic is extracted into a helper).

---

## Feature 4 — One Worker Per URL File

**Status: Already implemented.**

### File mode

`_assign` builds `avail = [p for p in pool if str(p.resolve()) not in active]`.
The `active` set is populated at assignment and cleared at `_requeue`. One
worker per file is strictly enforced.

### Domain-index mode

Each assignment creates a unique temp file
`logs/tmp_urls/w{slot:02d}_{file_id}_{line_num}.txt`. The URL inside is marked
`in_progress` by `DomainIndex.pick_url` before the temp file is created, so
the same URL cannot be picked by a second worker. Effectively one-worker-per-URL
(finer-grained than per-file, which is what matters here).

**No code changes required.** Add a comment in `_assign` near the `active`
set filter to document this guarantee.

---

## Implementation Schedule

| # | Feature                         | Effort | Files changed                                  |
|---|---------------------------------|--------|------------------------------------------------|
| 1 | Proxy duplicate check           | S      | `downloader.py`, `test_downloader.py`          |
| 4 | Confirm one-worker-per-file     | XS     | `manager.py` (comment only)                    |
| 2 | Watcher log reorder + summary   | M      | `manager.py`, `mp4_watcher.py`, `mp4_sync.py` |
| 3 | URL panel force queue           | L      | `manager.py`                                   |

Run full test suite (`pytest --tb=short -q modules/ytaedl/`) after each
feature. Target: 124+ pass, 1 skip throughout.
