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
the view is locked, or the poller closes. Suspend polling while hidden and
resume with one immediate request when visible again. Stop after a sample whose
`status` is `finished`, `failed`, `killed`, or `lost`, or whose `unavailable`
value is `run is finished` or `process exited`. Transient errors must be passed
to `onError` when supplied and polling must continue after the normal interval.

Only edit `src/telemetry_polling.js`. Run `node tests/polling_public_test.js`.
