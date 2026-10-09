# Stage 4: Delayed Elevated Runner Test from the TUI

## Objective

Let a user select a task in the TUI and either run it immediately using the existing manual path or queue a one-time test run for about ten seconds later through the registered Windows daemon. The delayed test must not block the TUI; when it runs, open a visible console window so the user can watch its output.

## Plan

- Add a small, file-backed one-shot request queue consumed by the scheduler daemon independently of normal schedule ticks.
- Poll the request queue at a short interval while preserving the configured interval for normal schedule evaluation.
- Execute queued tasks inside the already elevated daemon context. For `admin=True`, fail with a clear diagnostic instead of opening a second UAC prompt if the daemon is not elevated.
- Add a visible-console execution mode for Windows and keep the normal immediate manual run behavior unchanged.
- Add a TUI choice after task selection: run now, or queue a runner test for approximately ten seconds later. Return to the TUI immediately after queuing.
- Require the daemon runner to be active before queueing so requests are not silently delayed until a future login. Explain that starting a stopped runner may trigger existing catch-up tasks.
- Add tests for queue timing, daemon request processing, visible process launch, privilege guard, and TUI routing. Tests must not launch a live task or alter the machine Task Scheduler.
- Update module and plan documentation, then validate with the repository scheduler target, Ruff, and diff checks.

## Acceptance Criteria

1. The delayed test is executed by the registered daemon, not by the unelevated TUI process.
2. The TUI does not wait for the task result; it reports that the run is queued.
3. When due, the task opens in a visible console window and writes its normal task log/result.
4. An `admin=True` queued task never starts a per-run UAC prompt; it fails safely if the daemon lacks an elevated token.
5. The regular schedule check interval and existing manual-run path remain unchanged.
