---
plan_index: 0009
origin: ai
status: planned
source_file: user_request_20260509_clean_start_flags
---

# Future Plan: Clean-start Runtime Flags

## Requests

- Add a manager flag near `-M/--rebuild-domain-index` that deletes the current
  run log directory before startup.
- Running `-M` without the log-reset flag must remain safe.
- Running the log-reset flag without `-M` must remain safe.
- Running both together must remain safe.
- Neither flag may delete or invalidate `_partial/` resume state or other
  downloader temp state under the configured download/proxy roots.
- The flag must be explicit and clearly named, for example
  `--reset-log-dir` with a short form chosen after checking for conflicts.
- It must not delete `_partial/` resume directories.
- It must not delete archive files unless a separate archive-specific reset
  flag is added and documented.

## Safety Requirements

- Resolve the target log directory before deletion and verify it is the same
  directory ytaedl would write logs to for this run.
- Refuse dangerous targets such as drive roots, user home, repository root, or
  missing/empty path values.
- Add tests proving the flag deletes only the log directory contents and leaves
  archive and `_partial/` trees untouched.
