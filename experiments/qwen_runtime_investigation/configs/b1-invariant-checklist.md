Before editing, check each requirement in the task instruction against the implementation plan:

- Polling is eligible only when a run is selected, mode is not `minimal`, the page is visible, the view is unlocked, and the run is not terminal.
- An eligible run starts one request immediately; after each request settles, schedule the next request after `intervalMs`.
- At most one request promise may be unsettled. Calling abort does not count as settlement and must not clear the in-flight marker.
- If visibility returns while a request is unsettled, remember one follow-up request. After settlement, start exactly one immediately if polling is still eligible; otherwise do not start it.
- Ignore results from a superseded run. Abort on run change, deselection, lock, or close.
- Stop after the specified terminal status or unavailable value. Transient errors call `onError` when supplied and continue after the normal interval.

Use this checklist to inspect the task requirements and verify that the state transitions preserve them. Do not broaden the task or edit paths outside the allowed file.
