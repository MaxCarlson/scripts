# Checklist — Named Agent Dispatcher

- [x] Verify M2 integrated base and establish isolated feature worktree.
- [x] Extend durable event model, SQLite materialization, replay, and idempotency for GUI aliases, slots, activation history, and pending launches.
- [x] Add service operations for creation, activation, state changes, explicit session attachment, and current-session queries.
- [x] Add `llmd` and `llm-dispatcher` entry points with dry-run mutations, JSON, and interactive mode.
- [x] Add provider command construction and dispatcher-owned pane process supervision.
- [x] Test dispatcher service, CLI, interactive harness, provider wrapper, concurrency, and rebuild behavior.
- [x] Complete regression suites, Ruff, disposable packaging smoke checks, and `git diff --check`.
- [x] Review task-only diff, update this status, and create the authorized dispatcher checkpoint commit.
- [ ] Integrate and validate the separate `terminal_launcher` package; actual layouts are outside this branch's ownership.
