# Checklist

## Phase A — audit

- [x] Verify current branch, worktree, clean baseline and relation to supplied SHA.
- [x] Inspect current LLM Monitor API/provider/storage boundaries and active handoff.
- [x] Inspect `web_ui_tools` HTTP/WebSocket protections, lifecycle, tests and Python floor.
- [x] Review current official LM Studio REST and CLI documentation.
- [x] Inspect installed LM Studio CLI help without running inference or streaming log content.
- [x] Audit and record Runmux data-shape and Python 3.10 compatibility assumptions.
- [x] Complete provider capability matrix and source evidence fixtures.

## Phase B — standalone MVP

- [x] Add request-oriented typed contracts and bounded in-memory inventory store.
- [x] Add optional app-scoped cookie name while preserving the existing default.
- [x] Add a single cached LM Studio inventory service and authenticated versioned GET API.
- [x] Add `llm-monitor web` with loopback default and no telemetry database access.
- [x] Add packaged standalone overview assets and optional web dependency extra.
- [x] Correct verified compatibility mismatches and add regression tests.
- [x] Validate focused module suites, CLI help, wheel assets, auth, hostile labels, and no DB creation.
- [x] Stop at the Phase B acceptance gate; do not start Phase C or D.

## Approved frontend workstream

- [x] Commit/push the validated Phase A/B checkpoint before UI work.
- [x] Read `docs/APPROVED_VISUAL_OUTLINE.md` and audit current HTML, CSS, API contracts, and tests.
- [x] Record the three-category frontend gap analysis in `FRONTEND_GAP_ANALYSIS.md`.
- [x] UI-1: implement visual shell, six KPIs, two-column explorer/inspector, GPU and capture panels; inspect desktop screenshots.
- [x] UI-2: implement navigation, filtering, model/server selection, inspector tabs, history/alerts states, responsive and keyboard interactions.
- [x] UI-3: implement fixture-only incremental request-event state contract and verify selection stability, incremental segment updates, deduplication and stream-gap behavior.
- [x] UI-4/5: inspect required viewport screenshots, transcript readability, accessibility structure, packaged assets, and document differences/dependencies.
- [ ] Run final focused validation, then commit and push this accepted major frontend milestone; do not merge or implement backend collectors/gateway.
