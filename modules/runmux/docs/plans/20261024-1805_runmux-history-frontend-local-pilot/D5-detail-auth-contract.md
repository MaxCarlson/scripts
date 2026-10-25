# D5 — Details authentication and request-cache contract

Coordinator-confirmed behavior for the bounded event/lineage test task.

- Event and lineage data are keyed by the immutable selected Run ID. Changing the selected Run ID invalidates the previous request generations, aborts outstanding requests, and resets both caches before loading the new run.
- The first Details visit for a selected run loads events and lineage. Successful event history (`runEventsLoaded`) and lineage (`runLineageRunId`) are reused on repeated Details-tab visits for that same Run ID; toggling between Details, Output, and Terminal must not duplicate those requests.
- Concurrent duplicate loads are suppressed while each request is busy.
- The global Refresh button refreshes the process list. There is no separate force-refresh control for historical events or lineage; repeated Details visits remain cache hits. Event pagination is an intentional new request.
- A 401 is translated by `api()` to the `locked` error and shows the login view. `showLogin()` calls `invalidateSelection()`, which aborts both detail requests and clears both cached Run ID keys. After authentication is restored, reopening Details for the same run must load events and lineage again; cached data must not cross the authentication boundary.
- A 404/503 error remains an honest visible unavailable state. Repeated tab visits must not fabricate data or create request loops. Existing explicit selection change or authentication reset is the reload boundary; do not invent new retry policy or a new refresh control.

Test with `dashboardHarness()` in `tests/dashboard_test.js`, using deferred responses. The production contract and API are unchanged.
