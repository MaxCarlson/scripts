# cross_platform immediate handoff

0.8.0 adds real external folder_read_lock/folder_write_lock coordination with a
common short acquisition gate and overlapping-tree exclusion. Shared readers,
thread-reentrant covering writers, no read target mutations, death/error release;
legacy inode locks retained.129 full tests pass/4 platform skips (run from package
root; storage_test imports top-level storage). Same-user shared-state scope; stop
older binaries before upgrade, no distributed/nonparticipating-writer guarantee.

The reusable storage-media classifier is implemented in version 0.6.0. It
reports solid-state, rotational, or unknown without requiring administrator
privileges. MangaDL consumes it for its default worker ceiling policy.

Final repository dispatcher passed: compile and Ruff checks succeeded, and the
full suite reported 110 passed, 4 skipped. See the active plan for details.
