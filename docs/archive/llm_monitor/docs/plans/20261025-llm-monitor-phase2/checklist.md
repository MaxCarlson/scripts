# Phase 2 Checklist

## Stage A — Collection (complete)

- [x] Normalized event model and privacy-safe projection
- [x] Cursor API feature detection and bounded page traversal
- [x] Legacy bounded overlap polling with ID deduplication
- [x] Retry/backoff, stale state preservation, and history gap coverage
- [x] Session lifecycle normalization and Stage A tests

## Stage B — Diagnostics

- [x] Per-inference token accounting and capacity metadata
- [x] Compaction operation timeline and measured durations
- [x] Structured tool/edit results and conservative read extraction
- [x] Evidence-classified diagnostic rules
- [x] `diagnose` command and fixture tests

## Stage C — Optional integration and metrics

- [x] Explicit MCP snapshot correlation and qualified orphan handling (no live MCP transport)
- [x] Inference/tool/compaction timing and approximate message elapsed throughput
- [x] LM Studio model metadata with safe context semantics; GPU remains point-in-time `gpu` command only

## Stage D — Reporting and release checks

- [x] `report` command with partial-history caveats
- [x] Watch state transitions, blockers, and freshness (diagnostics derived by `diagnose`/`report`)
- [x] JSON schema versions and docs/help registration
- [x] Full module tests, packaging/CLI checks, final branch/status review
