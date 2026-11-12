# Implementation Plan: Fix mangadl Run Completion Hang, Preflight Skip, and Zero Stats

## Problem Analysis

1. **Massive HDD Seek Thrashing on Every Worker Start & Finish (`snapshot_top_level`)**:
   - Every worker process runs `snapshot_top_level(destination)` on startup and on completion.
   - `snapshot_top_level` performs a full recursive traversal (`rglob("*")` + `stat()`) over all 1,225 directories and 74,454 files on the destination drive (HDD `B:`).
   - With 2–4 concurrent workers, simultaneous random directory scans cause severe disk head thrashing, stalling workers for minutes before they even emit `worker_ready` or invoke `gallery-dl`.
   - In addition, if a gallery download is skipped because it's already in the archive or complete, running cover installation and full library snapshots is entirely redundant.

2. **No Preflight Fast-Path for Already-Completed Manga**:
   - Input files (such as `urls37.txt` with 18 URLs) often contain galleries that are already downloaded in the destination library (with `.mangadl-source.json` manifests and complete images) and recorded in `archive.sqlite3`.
   - `DownloadManager` dispatches all URLs to heavy worker subprocesses, which launch `gallery-dl` and make network queries over HTTPS to nhentai/etc. When rate limiting, slow networks, or Cloudflare delays occur, workers stall or take minutes per URL.
   - A fast-path preflight check in `DownloadManager` can check the destination library and archive before leasing, immediately resolving already-complete jobs as `skipped_archive` in milliseconds without spawning subprocesses or contacting the network.

3. **`tail` Deque Length Bug causing `gallery_skipped` to be False**:
   - In `modules/mangadl/mangadl/worker_core.py`, `gallery_skipped` checks `any("archive" in line.lower() for line in tail)`.
   - `tail` is `deque(maxlen=100)`. When a skipped gallery has >100 images (such as NH 685702 with 178 images), gallery-dl emits 178 `# <file>` lines. The archive header line is popped off `tail`.
   - `gallery_skipped` evaluates to False, reporting state `"succeeded"` with 0 bytes and 0 images instead of `"skipped_archive"`.
   - Tracking `archive_matched` as a persistent boolean flag fixes this.

4. **Output Buffering & Process Spawning Safety**:
   - `gallery-dl` command in `worker_core.py` lacked Python unbuffered flag `-u` and `PYTHONUNBUFFERED=1`.
   - `raw_log` in `worker_core.py` was not flushed before `Popen`, leaving logs at 0 bytes if output was delayed.
   - Subprocesses inherited the stdin pipe, causing issues when stdin is a pipe under `cli_tui` or background tasks. Passing `stdin=subprocess.DEVNULL` ensures isolated execution.

5. **Transfer and Processing Stats Stuck at Zero**:
   - For `manga18fx`, `output_root` in `worker_core.py` was set to `partial`, but `manga18fx` writes directly to `args.destination`. So `_tree_stats` always returned 0.
   - When items are skipped, `completed_images` and `completed_bytes` were incremented with 0, leaving totals at 0.0 B/s and 0 img across the entire run.

## Proposed Changes

### Stage 1: Fix Output Buffering, Process Spawning, and `gallery_skipped` in `worker_core.py`
- Pass `-u` to `sys.executable -m gallery_dl`.
- Pass `stdin=subprocess.DEVNULL` to `subprocess.Popen`.
- Set `PYTHONUNBUFFERED=1` in `env`.
- Call `raw.flush()` immediately after writing process headers.
- Set `output_root = Path(args.destination) if args.backend in {"hdporncomics", "manga18fx"} else partial`.
- Track `seen_archive_match` persistently across all lines in `capture()`.

### Stage 2: Eliminate Recursive Full-Disk Scanning in `worker.py` and `covers/files.py`
- If a gallery is skipped (`state == "skipped_archive"`), do not run cover installation or snapshots.
- In `worker.py`, if `series_path` is known and already exists, pass it directly to cover installation rather than doing before/after full library snapshots.
- Optimize `snapshot_top_level(root)` to avoid recursive `rglob("*")` across the entire disk; check top-level directory entries and mtimes.

### Stage 3: Implement Preflight Fast-Path for Already-Downloaded Manga in `manager.py`
- In `DownloadManager.run()`, before worker loop, perform a fast preflight check against destination library manifests and `archive.sqlite3`.
- Any queued job whose destination folder already exists with complete images (or whose gallery is complete in archive) is immediately resolved as `skipped_archive` with its existing image count and bytes recorded.
- Set `stdin=subprocess.DEVNULL` and `PYTHONUNBUFFERED=1` when spawning `mangadl.worker`.

### Stage 4: Verify Transfer & Processing Stats in `ui.py`
- Ensure `ui.py` displays accurate transfer rates, averages, and processed/skipped counts when runs complete.

### Stage 5: Verification & End-to-End Testing
- Run test suites in `modules/mangadl` and `modules/cli_tui`.
- Verify with a live test on `urls37.txt`.
