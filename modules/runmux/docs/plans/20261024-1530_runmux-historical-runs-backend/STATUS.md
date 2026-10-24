# Status - Runmux Phase 6C: Historical Run Discovery & Events Backend

**Date:** 2026-10-24
**Branch:** `codex/runmux-historical-runs-backend-20261024`
**Base:** `origin/main` (`8befeae3375740e21cdfe17a081387f0e3cf8f54`)
**Current Stage:** Complete (backend-only)
**Approval State:** Implemented and verified on the authorized feature branch; not merged.

---

### Progress & Operational Ledger

1. **Worktree & Isolation Established:**
   - Dedicated worktree `.worktrees/runmux-historical-runs-backend` created from `origin/main`.
   - Feature branch `codex/runmux-historical-runs-backend-20261024` active.
   - Verified native Windows environment. Disposable test state only.

2. **Architecture Research & Matrix Complete:**
   - Evaluated 3 distinct data categories: Run History (`registry.sqlite3`), Metric History (`telemetry.sqlite3`), and Lifecycle Events (`telemetry_events` / `runs` transitions).
   - Produced `01_existing_capabilities_matrix.md` and `00_implementation-plan.md`.

3. **Completed implementation:**
   - Added indexed SQL-side filters and stable keyset pagination with a 1–200 page bound, opaque filter-bound cursors, and an initial-created-time watermark. Later pages exclude runs with a creation timestamp later than the first-page watermark; a same-second insertion with a lower Run ID may still appear. Status changes are reflected per request and can move a record into or out of a filter; this is not a database snapshot.
   - Added a SQLite VM-step budget for history and lineage queries. Exact `total_count` is optional (`include_total=true`) because counting can require a full filtered scan.
   - Added bounded restart/duplicate lineage, allowlisted history serialization, recorded telemetry-event access with chronological keyset cursors, and registry timestamp markers with explicit provenance.
   - Added authenticated `GET /api/runs/history`, `/api/runs/{run_id}/events`, and `/api/runs/{run_id}/lineage`. Existing `GET /api/runs` remains an array response.
   - No frontend, telemetry collection, retention policy, or event-capture changes were made.

4. **Validation:**
   - `python -m pytest tests/historical_runs_api_test.py tests/store_test.py tests/web_adapter_test.py -q -s`: 28 passed; 10,000 synthetic run registry benchmark most recently measured first page 19.26 ms, next page 14.54 ms, and status/name-filtered page 3.22 ms.
   - `python -m ruff check src/runmux/store.py src/runmux/models.py src/runmux/web_adapter.py src/runmux/web.py tests/historical_runs_api_test.py`: passed.
   - `python -m compileall -q src/runmux/store.py src/runmux/models.py src/runmux/web_adapter.py src/runmux/web.py`: passed.
   - The ordinary `python -m runmux --version` resolves the environment's already-installed 0.13.0 package. The feature branch updates module metadata to 0.14.0; verify the local source with `PYTHONPATH=src python -m runmux --version`.
   - Direct HTTP TestClient execution was not completed: Windows asyncio loop initialization blocked in the sandbox while creating its internal socket pair. Adapter behavior and route registration were tested; HTTP auth is inherited from the existing authenticated `/api` router and existing auth middleware.

5. **Remaining limitations:**
   - The registry stores current lifecycle state, not a transition log. Registry events therefore represent only recorded timestamps and explicit relationship fields; telemetry events are separately tagged `telemetry_store`.
   - Telemetry event free-text reasons and arbitrary details are withheld because their payloads have no safe disclosure allowlist.
   - Lineage page totals count direct restart/duplicate relationships for the selected run; returned ancestor/descendant nodes are capped and indicate truncation.
   - The legacy duplicate roadmap at `modules/runmux/docs/RUNMUX_WEB_UI_MASTER_ROADMAP.md` is older than the revised canonical handoff roadmap. Both trackers were updated to show this branch as complete but unmerged.
