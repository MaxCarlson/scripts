# Runtime TUI submissions status

- Branch: `codex/ytaedl-runtime-submissions-20261106`
- Base: `fcc95eac657463d4b9bd731e6b759d38bc3887b1` (AEBN integration on local main).
- Goal: accept durable URL and URL-file submissions without interrupting workers, with queue or additional-worker scheduling.
- State: implemented, focused validation passed; feature branch committed, merge approval pending.
- Constraints: preserve domain and bandwidth limits, existing exact-file scheduling, archives, fragments, and active worker lifecycle; use mocked worker tests and no media downloads.
- Implementation: `i` opens a nonblocking multiline dialog with validation, queue/additional-worker scheduling, worker-slot cap, and `j`/`k` worker-list scrolling. Submitted URLs become durable one-URL files; submitted files retain their original paths. Pending and in-progress submissions are atomically stored in `<log-dir>/pending_manual_submissions.json`, with interrupted claims restored on restart.
- Scheduling: runtime work enters the priority pool in file mode, the existing domain index in `-D` mode, and the exact-file runtime queue in `-i/--priority-files-only` mode. Existing worker start, archive, file-lock, domain, and global bandwidth controls remain in use.
- Validation: focused suite (runtime submission, domain index, manager, pause, CLI dispatch, summary) passed: 145 tests. Ruff and compileall passed for changed Python files. Mocked subprocesses only; no media downloads or live services.
- Next: feature commit is ready; keep worktree and branch. Ask the user before merging into local `main`.
