# Checklist - Runmux Phase 6C Historical Explorer Frontend

**Branch:** `codex/runmux-6c-history-frontend-local-pilot-20261024`
**Baseline:** `4591b3247bdfafe82f0b8d1a73f40002152a6c2b`

## Requirements and contracts

- [x] Establish clean isolated worktree at pinned baseline.
- [x] Verify local-agent readiness and actual Codex MCP `opencode_setup` invocation.
- [x] Complete genuine local-worker fixture edit and independent verification.
- [x] Inspect historical API filters, sort keys, page bounds, auth, allowlists, event provenance, and lineage identity.
- [x] Inspect and preserve Phase 5C chart integration and existing workspace architecture.
- [x] D0: record exact API filter semantics, filter-state invariants, source locations, test harness, and cursor mutation semantics.

## Frontend

- [x] History workspace view with loading, empty, unauthorized, and error states.
- [x] API-backed filters and supported sort, no full-registry fetch or exact count by default.
- [x] Expose all useful backend history filters, including state, exact name, exit code, restart/duplicate parent, and `has_restarts` through server-side query parameters.
- [x] Validate integer exit filters against signed 64-bit bounds, avoid redundant normalized requests, and reset cursor/request state on effective changes.
- [x] D4 actual authenticated route coverage over 10,000 synthetic rows, including cursor mutation semantics.
- [x] D5 expired-auth and repeated Details request behavior covered for events and lineage.
- [x] Cursor pagination and request cancellation/stale-response guards.
- [x] D3 canonical preset/manual filter reconciliation, including hidden boolean clearing and active-button state.
- [x] Recent completion/failure/LOST discovery.
- [x] Distinct full Run IDs for duplicate process names.
- [x] Events shown with recorded-versus-registry provenance and honest missing state.
- [x] Restart/duplicate navigation uses explicit related Run IDs only.
- [x] Preserve process tabs, Output, Terminal, Details, lifecycle controls, and Phase 5C charts.
- [x] No display of withheld arguments, cwd, environment data, or credentials.

## Validation and handoff

- [x] Frontend unit tests and JavaScript syntax checks.
- [x] Focused API/adapter tests using worktree source.
- [x] Real headless Chrome E2E with disposable state and dedicated ports 8791/9444.
- [x] Existing application responsive checks at 390, 768, 1366, 1920, and 2560 pixels; desktop History screenshots captured.
- [x] D6: keep History open during the viewport loop, validate History controls/table, and capture/inspect a narrow screenshot.
- [x] Malformed filters, missing runs, unauthorized sessions, API failures, empty events/lineage, stale page response, and bounded DOM/request behavior covered in focused tests.
- [x] Inspect History screenshots and restore baseline screenshots overwritten by the E2E harness.
- [ ] Final status, ledger, exact diff review, final clean Git status, commit, and push.
- [ ] Leave feature branch unmerged for independent audit.

Previously paused at a safe checkpoint. Resumed per the approved D0–D7 allocation. D1, D2, and D5 worker attempts produced no changes; coordinator-owned implementations and tests are verified. D0–D6 are complete, with D7 publication still in progress. See `STATUS.md`, `D0-filter-contract.md`, `D5-detail-auth-contract.md`, and `LOCAL_DISPATCH_LEDGER.md` for contracts and routing evidence.
