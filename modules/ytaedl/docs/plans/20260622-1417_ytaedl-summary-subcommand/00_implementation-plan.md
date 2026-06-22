# Implementation Plan: Real-Time Summary and Instance Stats

## Objective

Add a new subcommand `ytaedl summary` that displays real-time statistics and active locks held across all currently running `ytaedl` manager instances.

To achieve this:
1. Each active `ytaedl` manager writes a status file (`active_manager_<pid>.json`) under `archive/instance_stats/` every ~1 second.
2. Upon shutdown (normal or abnormal), the manager moves its stats file to `archive/instance_stats/stats_archive/` and renames it to `ended_YYYYMMDD_HHMMSS_started_YYYYMMDD_HHMMSS_<pid>.json`.
3. Total files (archived + active) are capped at 50. Oldest archived files are deleted on boot.
4. The `summary` command displays running stats in a neat, color-coded, aligned format. It groups and formats active locks grouped by parent directory.
5. If `summary` detects a stale active manager file (no update for >10s or process PID is dead), it automatically moves it to the archive directory.

---

## Detailed Design

### 1. File Structure and Locations
* Directory for active stats: `<archive_dir>/instance_stats/`
* Directory for archived stats: `<archive_dir>/instance_stats/stats_archive/`
* Active filename format: `active_manager_<pid>.json`
* Archived filename format: `ended_YYYYMMDD_HHMMSS_started_YYYYMMDD_HHMMSS_<pid>.json`

### 2. Pruning on Startup
On boot of `ytaedl` manager:
1. Count the number of active stats files (`active_manager_*.json`) + archived files (`stats_archive/ended_*.json`).
2. If total count is > 50:
   - List all archived files.
   - Sort archived files alphabetically (which corresponds to sorting oldest to newest based on the `ended_` prefix).
   - Delete the oldest archived files one by one until the total count of archived + active files is exactly 50.

### 3. Background Stats Writing
Within the manager run loop (in `manager.py`), spawn a background writer (either in a background thread or at the end of each tick of the main loop).
Since the manager runs in a loop with ticks, writing the file at the end of the tick (or every 1.0 second) is clean and avoids thread coordination issues.
Every tick, if `time.time() - last_stats_write_t >= 1.0`:
* Collect stats:
  - `pid`: Process ID.
  - `start_time`: ISO formatted string of manager start time.
  - `last_updated`: ISO formatted string of current tick time.
  - `runtime_seconds`: Total run time of manager.
  - `workers_count`: Total worker slots (`len(workers)`).
  - `active_workers_count`: Workers with `ws.proc is not None` and not paused/waiting.
  - `finished_count`: Count of completed downloads (or files).
  - `avg_speed_bps`: Average download speed in bytes/sec.
  - `avg_url_speed_bps`: Average URL download speed in bytes/sec.
  - `current_speed_bps`: Current instantaneous download speed in bytes/sec.
  - `locks_held`: List of dicts:
    * `file_path`: Path to locked URL file.
    * `time_held_seconds`: Time elapsed since the lock was acquired.
* Write to `archive/instance_stats/active_manager_<pid>.json`.

### 4. Lifecycle Clean Up
When `run_main` exits:
1. Stop the stats writer.
2. Determine `start_time` and current time `ended_time`.
3. Rename the file to `ended_YYYYMMDD_HHMMSS_started_YYYYMMDD_HHMMSS_<pid>.json` and move it to `archive/instance_stats/stats_archive/`.
If the program crashes unexpectedly, the file remains in `instance_stats/`.

### 5. `ytaedl summary` Command
When user runs `ytaedl summary`:
1. Scan all `active_manager_<pid>.json` files in `<archive_dir>/instance_stats/`.
2. For each file, check if it is stale:
   - Check if the process `<pid>` is still running (using a cross-platform helper).
   - Check if `time.time() - file_mtime > 10.0`.
   - If stale, parse the JSON, determine its start time and end time (from `last_updated`), move it to `stats_archive/`, and do not display it as active.
3. For each active instance:
   - Print a header row (color-coded, e.g. blue header and value alignment).
   - Columns:
     - `instances`: e.g. `ytaedl_instance_<pid>`
     - `workers`: count of active workers
     - `instance runtimes`: formatted as `HH:MM:SS`
     - `finished downloads`: count of finished files
     - `average download speed`: e.g. `13.25 MiB/s`
     - `avg url dl speed`: e.g. `1.62 MiB/s`
     - `current dl speed`: e.g. `25 MiB/s`
   - Print held locks:
     - For each lock, print the relative path from the star/aebn directory, grouped under their parent directory, showing time held in `HH:MM:SS`.
     - Output layout:
       ```text
       ytaedl_instance_1 - 8 - 05:04:01 - 29 - 13.25MiB/s - 1.62MiB/s - 25MiB/s
           locks and times held:
               stars/
                   urlfile1.txt / 03:02:01
                   urlfile2.txt / 00:00:14
               ae-stars/
                   urlfilen.txt / 00:15:01
       ```

---

## Code Changes Outline

### 1. `modules/ytaedl/ytaedl/manager.py`
* Implement stats collection and periodic JSON serialization.
* Implement cleanup and archiving on exit.
* Implement startup pruning.

### 2. `modules/ytaedl/ytaedl/cli.py`
* Add `summary` parser subcommand.
* Implement `handle_summary` which displays the real-time active managers.

### 3. `modules/ytaedl/tests/test_summary.py`
* Write test cases to verify active manager stats writing, archiving, pruning, and summary display output.

### 4. Version Bump
* Bump to `2.13.0` in:
  - `modules/ytaedl/pyproject.toml`
  - `modules/ytaedl/ytaedl/__init__.py`
  - `modules/ytaedl/README.md`
