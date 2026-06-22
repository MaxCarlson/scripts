# Implementation Checklist

- [x] Stage 1: Implement background stats writing in manager.py
  - [x] Initialize stats writing on manager startup
  - [x] Write `active_manager_<pid>.json` to `archive/instance_stats/` every ~1 second
  - [x] Gather runtime, slots, finished counts, speeds, and currently held locks
  - [x] Clean up/archive the stats file on normal or abnormal exit to `archive/instance_stats/stats_archive/` using the format `ended_YYYYMMDD_HHMMSS_started_YYYYMMDD_HHMMSS_<pid>.json`
  - [x] Limit total archive + active files to 50 on boot, deleting the oldest archived files first

- [x] Stage 2: Implement the `ytaedl summary` CLI subcommand
  - [x] Register the `summary` subcommand in cli.py
  - [x] Scan `archive/instance_stats/active_manager_*.json` files
  - [x] Identify stale active files (where process is dead or file has not been updated for >10s) and archive them automatically
  - [x] Color-code columns and align stats correctly
  - [x] Print group indented locks (grouped by parent directory) and display times held
  - [x] Verify execution runs smoothly and tests pass

- [x] Stage 3: Verification and testing
  - [x] Write unit tests for background stats writing, lifecycle cleanup, and archiving logic
  - [x] Write unit tests for the `summary` CLI printout format and stale cleanup
  - [x] Validate and perform manual testing on multiple instances
