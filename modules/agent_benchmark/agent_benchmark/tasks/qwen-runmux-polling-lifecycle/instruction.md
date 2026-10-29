# Implement bounded telemetry polling with lifecycle controls

Implement `createTelemetryPoller(options)` in `src/telemetry_polling.js`.
The `options` object contains `fetchTelemetry(runId, { signal })`,
`onSample(sample)`, optional `onError(error)`, optional `intervalMs`,
optional `setTimer(callback, delay)`, and optional `clearTimer(timer)`.
Return an object with `selectRun(runId)`, `setMode(mode)`,
`setVisible(visible)`, `setLocked(locked)`, `deselectRun()`, and `close()`.

Poll only while a run is selected, mode is not `minimal`, the page is visible,
the view is unlocked, and the run has not reached a terminal state. Start an
eligible selection immediately, then poll after each request finishes using
`intervalMs` (default 1800 ms). Never overlap requests. Ignore results from a
superseded run. Abort the prior request when the run changes, is deselected,
the view is locked, or the poller closes. Keep a request marked in flight until
its promise settles, even if an abort has been requested; do not start a second
request before then. Suspend polling while hidden. If visibility returns while
a request is still in flight, queue exactly one immediate follow-up for after
that request settles, provided polling is still eligible. Stop after a sample whose
`status` is `finished`, `failed`, `killed`, or `lost`, or whose `unavailable`
value is `run is finished` or `process exited`. Transient errors must be passed
to `onError` when supplied and polling must continue after the normal interval.

Only edit `src/telemetry_polling.js`. The benchmark harness runs the public and
acceptance tests after you finish. This worker profile has no shell, so do not
attempt to run terminal commands.
