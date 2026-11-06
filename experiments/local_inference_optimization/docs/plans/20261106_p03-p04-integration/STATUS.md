# P03/P04 Integration Status

- **Branch:** `integrate/local-inference-p03-p04-20261106`
- **Worktree:** `.worktrees/integrate-local-inference-p03-p04-20261106`
- **Base:** `603842728f966e270e8a6bb0572f233c62052b35` (P04)
- **Integrated P03:** `3a9e51d145f923d8cb0a2b71ab6685eb1fc93491`
- **Purpose:** Offline interface reconciliation only; no real inference or baseline work.

## Status

P03 and P04 are present in one merge-history checkpoint. An additive LIO adapter
now joins verified P04 execution/request records to existing LIO trial/evidence
schemas. A synthetic fixture traverses SQLite v4 history, P03 frozen-design
matching and paired analysis, and offline HTML reporting. Infrastructure-invalid
matched blocks are now reported as excluded from paired effects while remaining
visible in scored-denominator diagnostics.

`benchmark_core` is version 0.5.0; `agent_benchmark` is version 1.28.0 with its
dependency bound updated to the compatible core range. Existing protocol
schemas remain unchanged.

## Remaining acceptance boundary

- Mocked Harbor runner → child environment → OpenCode config → gateway propagation
  now passes; Docker container inheritance and actual OpenCode parsing remain
  unverified and require separately authorized live acceptance.
- P04 history persists correlation metadata, not request parameters; the LIO
  adapter accepts separately captured sanitized parameter evidence and does not
  infer settings from correlation.
- P02 remains unsealed unless independently established; synthetic readiness is
  not evidence about the real baseline.
- Effective settings still require independent backend-runtime evidence.
- Full `llm_monitor` passed (277 passed, 2 skipped). The full Agent Benchmark
  directory completed (643 passed, 10 skipped, 5 failed); the failures are
  classified in `OFFLINE_REGRESSION_CLOSURE.md`. Two verifier path failures
  passed with a short temp root; two tests require Docker; one test probes the
  default local Monitor endpoint and must be isolated before future offline
  suite runs.

## Offline validation

The original combined command ran 273 tests with 1 existing skip and exit code 0.
It covered all LIO tests, all `benchmark_core` tests, all
`interactive_reports` tests, P04 correlation/storage plus the schema migration
regression, and the agent correlation/config and Monitor-preflight suites.
Imports were printed and verified to resolve from this integration worktree.
The follow-up full Monitor run and bounded Agent Benchmark diagnostics, including
the Windows event-loop stack trace and exact failure classification, are in
`OFFLINE_REGRESSION_CLOSURE.md`. The targeted P04 propagation, gateway,
correlation, and P03/P04 LIO integration tests passed from this worktree.

See `../../P03_P04_INTEGRATION.md` for protocol details and validation scope.
