# Stage 2: Scheduler history

Add stable schedule/task IDs, migrate existing JSON records on first read, import only unambiguous retained text logs, and capture linked schedule/task runs in SQLite. Preserve readable text logs. Verify collision handling, rename identity, output retention, and coverage reset with isolated tests. Implementation: `scheduler/history.py`, `storage.py`, `service.py`, and `tests/test_history.py`.
