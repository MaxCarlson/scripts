# Priority URL-File Scheduling

## Goal

Cap initial workers in `-i/--priority-files-only` mode at `-t`, queue files
beyond that cap, and offer whole-file or rotating one-URL-at-a-time scheduling
for the explicitly selected `-p` files.

## Implementation

- Preserve the default whole-file scheduling behavior while treating `-t` as a
  hard initial-worker ceiling.
- Reuse the existing in-memory domain index, URL-file locks, archive statuses,
  and domain concurrency limit for rotating URL scheduling.
- Keep rotating-mode index state private to the selected files and in memory.
- Add mocked scheduling regressions and document the new option.

## Safety boundaries

- No media downloads, live services, remote Git operations, commits, or merges.
- Work only in `.worktrees/ytaedl-priority-file-queue-20261106`.
