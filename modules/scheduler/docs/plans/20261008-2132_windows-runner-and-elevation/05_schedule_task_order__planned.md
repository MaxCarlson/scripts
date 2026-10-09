# Stage 5: Preserve Schedule Assignment Order

## Objective

Tasks attached to the same schedule execute sequentially in the order they were attached. A task begins only after the previous task's execution and logging complete.

## Plan

- Persist a per-schedule `schedule_order` on tasks while remaining compatible with existing JSON records.
- Migrate legacy schedules deterministically from the task order already present in the JSON file; new or reattached tasks append to the end of their target schedule.
- Return attached tasks ordered by this field. Keep the service's synchronous task loop, which already waits for each result before continuing.
- Add storage and service tests for initial order, reattachment order, and sequential execution order.
- Update docs and package version, then run scheduler validation, Ruff, and diff checks.

## Acceptance Criteria

1. Existing configurations load without errors and receive a stable order for tasks already attached to schedules.
2. New tasks and tasks linked to another schedule append after existing tasks in the target schedule.
3. Schedule execution uses that persisted assignment order and never overlaps its tasks.
