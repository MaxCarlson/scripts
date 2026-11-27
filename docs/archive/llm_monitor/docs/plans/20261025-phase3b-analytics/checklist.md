# Phase 3B Checklist

## Stage A — Baseline

- [x] Verify published Phase 3A branch, commit, and clean feature worktree.
- [x] Run Phase 3A test suite and inspect query/event/report/diagnostic contracts.
- [x] Inspect sanitized 2A/2B fixtures and identify missing historical evidence.
- [x] Record architecture choices and limits in `plan.md`.

## Stage B — Analytics

- [x] Add bounded store context and streaming record APIs.
- [x] Persist privacy-safe state observations in existing schema v1.
- [x] Add session metrics, percentiles, context/token trends, and provenance.
- [x] Reconstruct interval timeline and duration unions without double counting.
- [x] Add historical inefficiency findings and large-history tests.

## Stage C — Comparison

- [x] Compare two or more sessions, with deltas and denominator handling.
- [x] Add comparability/coverage/configuration warnings and endpoint ambiguity handling.
- [x] Add text/JSON CLI and tests.

## Stage D — Evidence export

- [x] Add sanitized ZIP contents, manifest, and checksums.
- [x] Add preview-only default, explicit write, verifier, and CSV injection safety.
- [x] Test empty/partial/tampered/missing-file/privacy cases.

## Stage E — Reports and visualization

- [x] Integrate structured analytics/findings into persisted reports.
- [x] Add static SVG timeline, token/context points, and multi-session duration comparison.
- [x] Test escaping, downsampling, missing data, and rendering cost.

## Stage F — Delivery

- [x] Update README, module version, and Scripts Help registry.
- [x] Run full tests, packaging/installed CLI, compile/help, and diff checks.
- [x] Measure large synthetic compare/analysis/export/visualization workload.
- [ ] Commit and push Phase 3B branch; do not merge.
