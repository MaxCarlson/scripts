# Stage 4 Plan: Controlled Encoder & Measurement Backend

**Stage:** 4  
**Plan ID:** `20261024-0920_video-compression`  
**Date:** 2026-10-24  
**Status:** In Progress  

---

## 1. Goal & Architectural Boundaries

Implement a safe, controlled sample-encoding and empirical measurement backend that evaluates short video clips without ever modifying or endangering source media:
1. **Source Immutability Contract**: Source media is strictly read-only. Stat fingerprints (mtime_ns and size) are verified before and after every operation.
2. **Isolated Scratch Execution**: All intermediate encodes occur within path-hashed workspace scratch directories (`<workspace>/scratch/<trial_id>/`). Never write to the source directory.
3. **Subprocess Management & Cancellation**: FFmpeg execution via `-nostdin`, `-hide_banner`, `-nostats`. Enforce per-trial timeouts and clean Windows process-tree cancellation (`taskkill /T /PID`) preventing orphan processes.
4. **Deterministic Sampling Windows**: Bounded temporal window generation (`S3`, `S5`, `S8`) spaced across playable duration, robust to short files and boundary conditions.
5. **Output Validation & Trial Caching**: Every sample clip is probed with FFprobe to verify codec, duration, and elementary stream size. Results are cached in `<workspace>/trials.sqlite3`.
6. **Quota & Resource Schedulers**: Enforce `--max-trials` and `--max-time` budgets to ensure bounded execution.
7. **Sample-Based Estimation**: Aggregate measured sample bitrates with Stage 3 container decomposition to produce empirical predictions (`estimate --tier sampled`).
8. **Zero Full-File Encoding**: Stage 4 strictly forbids full-file encoding and source replacement.

---

## 2. Modules to Implement

| Module | Purpose |
|---|---|
| `videocompress.adapters.ffmpeg` | Subprocess wrapper for FFmpeg with timeout, process tree termination, and output parsing. |
| `videocompress.sampling` | Deterministic temporal window generator (`S3`, `S5`, `S8`) with boundary guards. |
| `videocompress.trials` | Trial job execution, output validation, SQLite trial caching (`trials.sqlite3`), and quota budgeting. |
| `videocompress.cli` | Integration into `vcompress estimate --tier sampled` and `vcompress trial`. |

---

## 3. Verification Criteria

1. **Source Immutability**: Tests confirm error is raised if source file stat changes during encode, and source is never modified.
2. **Subprocess Cancellation**: Tests confirm process tree is cleanly killed on timeout without orphan processes.
3. **Isolated Scratch**: All test outputs are restricted to temp scratch folders and cleaned up.
4. **Trial Cache Idempotency**: Running the same trial twice reuses cached measurements from SQLite without re-encoding.
5. **Quota Enforcement**: Schedulers stop immediately when `--max-trials` or `--max-time` is reached.
6. **Regression Suite**: All existing tests in `videocompress`, `cli_tui`, `compresser`, and `scripts_help` pass cleanly.
