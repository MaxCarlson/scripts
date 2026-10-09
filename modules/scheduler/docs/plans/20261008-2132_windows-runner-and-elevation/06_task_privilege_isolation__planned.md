# Stage 6: Honor Per-Task Privilege Flags

## Objective

Scheduled `admin=False` tasks must run with a limited user token, while only `admin=True` tasks run elevated. The existing highest-privilege daemon cannot safely execute both classes itself.

## Plan

- Register two per-user interactive logon tasks in the one-time setup: a limited-privilege schedule daemon and a highest-privilege Admin worker.
- Route Admin tasks from the limited schedule daemon to the worker over the existing one-shot request queue; wait for Admin scheduled task results so schedule ordering remains sequential.
- Keep non-Admin schedule executions in the limited daemon process.
- Make the Admin worker return results to the limited daemon, which remains the sole writer of task/config metadata and run logs.
- Route the delayed TUI runner test to the Admin worker and keep visible-console behavior.
- Update readiness/status/start/remove/setup flows to manage and validate both runner tasks. Existing one-task installations must show setup required until `scheduler setup windows` updates them.
- Add mocked tests for registration principals, worker routing, limited execution, sequential result handling, status gating, and no per-run UAC fallback.
- Update docs/version and run the scheduler validation target, Ruff, and diff checks. Never modify the live scheduled task during tests.

## Acceptance Criteria

1. Both per-user tasks use the same interactive logon and config file; schedule daemon is Limited and Admin worker is Highest.
2. Scheduled `admin=False` tasks execute in the limited daemon context.
3. Scheduled `admin=True` tasks execute in the worker's elevated context without a per-run UAC prompt.
4. Schedule execution waits for each Admin task result before starting the next attached task.
5. The setup gate rejects an older/incomplete one-task registration and directs the user to update setup once.
