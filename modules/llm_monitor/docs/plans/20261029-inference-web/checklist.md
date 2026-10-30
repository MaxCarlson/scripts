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
- [x] Run final focused validation; commit `00b44a844f5844485a0e81666b84976ecb353a5e` is pushed to the feature branch. No merge, backend collector, or gateway work was performed.

## Phase D — explicitly enabled gateway

- [x] Implement opt-in loopback OpenAI-compatible chat-completions proxy and authenticated browser event stream.
- [x] Validate real streaming/nonstreaming requests, structured input, reasoning/output, usage, lifecycle, and concurrent-request isolation.
- [x] Keep default web startup passive and database-free; do not redirect client configuration.
- [x] Commit/push Phase D baseline; no merge.

## Phase D.1 — performance and transport hardening

- [x] Add optional metadata-only monotonic timing instrumentation and explicit live benchmark harness.
- [x] Compare identical requests across direct, minimal-forwarder, and observed gateway paths with counterbalanced ordering (40 groups, then a separate 20-group repeat).
- [x] Forward upstream stream bytes incrementally across fragmented LF/CRLF frames; preserve success bytes and mark parse/upstream gaps.
- [x] Harden gateway Origin/content-type checks and pin validated loopback `localhost` resolution.
- [x] Validate partial upstream failures, client iterator cancellation, bounded observer queues, malformed/large SSE and concurrent request isolation.
- [x] Exercise authenticated browser observer disconnect/reconnect during real reasoning and output generation; confirm inference continues and snapshots reconcile.
- [x] Update provider capability matrix, status, validation report and benchmark artifacts.
- [ ] Close performance acceptance: repeat-to-repeat variance and upstream-header stalls remain unexplained; CPU counter resolution is insufficient for per-request attribution.
- [ ] Do not merge until the performance gate and user review are complete.
