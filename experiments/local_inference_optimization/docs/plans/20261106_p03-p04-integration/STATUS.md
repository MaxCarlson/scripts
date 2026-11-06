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

- Actual Harbor/OpenCode propagation of per-invocation correlation is not tested.
- P04 history persists correlation metadata, not request parameters; the LIO
  adapter accepts separately captured sanitized parameter evidence and does not
  infer settings from correlation.
- P02 remains unsealed unless independently established; synthetic readiness is
  not evidence about the real baseline.
- Effective settings still require independent backend-runtime evidence.
- Full `llm_monitor` and `agent_benchmark` suites did not complete within this
  environment's bounded run; focused suites and the other full offline suites
  are recorded in the integration handoff.

## Offline validation

The final combined command ran 273 tests with 1 existing skip and exit code 0.
It covered all LIO tests, all `benchmark_core` tests, all
`interactive_reports` tests, P04 correlation/storage plus the schema migration
regression, and the agent correlation/config and Monitor-preflight suites.
Imports were printed and verified to resolve from this integration worktree.
Ruff checks, formatting checks for new files, compileall, and `git diff --check`
also completed successfully. The broader Monitor and agent test directories
were attempted but did not return within the bounded environment run; those
attempts are not counted as passing validation.

See `../../P03_P04_INTEGRATION.md` for protocol details and validation scope.
