# P2a generated inventory checkpoint

Windows11/Python3.12.10/Pillow12.2.0; same generated-only benchmark as P0,
three repetitions at requested1/2/4/8 workers, no production images or source writes.
These development measurements preceded the final fingerprint revision2; unit and
full-suite validation cover that revision. They are not HDD or production predictions.

- Standalone64-file fixture inventory median:1 worker0.0643s,2 workers0.0748s,
  4 workers0.0783s,8 workers0.0913s before selecting the small-scope serial policy.
- The final scheduling rule keeps scopes<=64 candidates serial. Larger scopes may
  use up to the requested limit; pending futures are bounded to twice the limit.
  A barrier-controlled132-image test proves actual simultaneous inspections and
  ready-result collection without waiting for the first, blocked image.
- MangaDL8-gallery fixture after shared connection/small-scope serial policy:
  inventory medians0.1284/0.1220/0.1431/0.1210s at requested1/2/4/8. P0 at1/8 was
  0.1303/0.1557s. Subsecond noise prevents a general speedup claim.
- Representative MangaDL1-worker inventory:1 connection,110 SQL statements,
  18 commits versus P0's10 connections,166 statements,10 commits. More short cache
  commits deliberately replace a write transaction held during filesystem work.
  A real independent SQLite writer succeeds inside the scan callback.
- Both matrices retained equal verified results across repetitions and worker limits.
  Full-target populations/reports still occupy coordinator RAM; only query/cache
  batches and pending worker jobs are bounded by this change.

Windows `DirEntry.stat()` gives zero device/file IDs. Candidate identity lookup
must remain even when cached directory metadata supplies classification and size.
Verified locally and against [Python3.12 os.DirEntry.stat documentation](https://docs.python.org/3.12/library/os.html#os.DirEntry.stat).

Remaining P2: eliminate redundant root discovery/probe work, finish failure/admission
review, and run the task-level post-commit gate. P2a is a usable slice, not task3 completion.
