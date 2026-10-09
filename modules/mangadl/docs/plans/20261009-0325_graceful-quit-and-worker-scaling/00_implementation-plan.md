# Graceful quit and worker scaling

## Objective

Make interactive shutdown and runtime worker scaling predictable during downloads.

## Stage 1

- Make `q` stop new assignments, allow every active worker to finish its current
  gallery, then exit with the remaining queue preserved.
- Make `Ctrl+Q` (and the existing `Ctrl+C` interrupt path) terminate active
  workers immediately.
- Retain `+`/`-` runtime worker scaling, clarify it in the dashboard, and remove
  retired worker rows and stale selection after their current job completes.
- Keep the conservative default ceiling at four for rotational or unknown
  destinations without scratch. Use the existing hard ceiling of eight when
  scratch is enabled or the destination is detected as solid-state, and expose
  `-m/--max-workers` for an explicit ceiling in normal runs.
- Add focused UI, manager, integration, and regression tests; update user docs
  and synchronized package versions.

## Invariants

- Graceful quit never leases another job after it is requested.
- Graceful quit does not terminate a worker that is already processing a job.
- Immediate quit preserves the current resumable-partial behavior.
- Reducing worker count does not terminate an active worker.
- Increasing workers remains bounded by the existing concurrency budget.
- Storage classification comes from the reusable `cross_platform` API; unknown
  media fails conservatively to four workers.
- Unrelated repository work is not modified or staged.

## Acceptance criteria

- Unit tests distinguish `q`, `Ctrl+Q`, and `Ctrl+C`.
- An integration test proves graceful quit completes active work and leaves the
  next job queued.
- Tests prove a retired active worker stays visible until completion and then
  disappears, with selection clamped to a visible worker.
- CLI tests prove the scratch-aware default ceiling and explicit override.
- The MangaDL dispatcher target passes.
