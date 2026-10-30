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
