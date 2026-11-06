# Checklist

## Stage A — Scan
- [x] SQLite schema version 1, WAL, transaction helpers, indexes, and event journal
- [x] Scene URL/file parsing with per-line invalid reporting and duplicate provenance
- [x] One metadata fetch per unique movie and strict scene-ID resolver reuse
- [x] Bounded root inventory with symlink/reparse escape protection
- [x] Conservative scene/full-movie matching and ambiguous classifications
- [x] Scan summary and JSON/CSV exports

## Stage B — Download and verification
- [x] Resumable per-scene jobs isolated from historical archive skips
- [x] Bounded threaded AEBN scene-ID download execution
- [x] Output identity/duration/video-stream verification
- [x] Interrupted/unknown outcome recovery

## Stage C — Review
- [x] Per-original review display and decisions
- [x] Eligibility gate, scoped approval fingerprint, invalidation on changed evidence
- [x] JSON/CSV export

## Stage D — Removal and consistency
- [x] Approved-only removal planning and apply confirmation
- [x] Allowed-root, reparse, active-use, stat/fingerprint, replacement checks
- [x] Reversible quarantine default; separately confirmed permanent delete
- [x] Intent/result journaling and idempotent recovery
- [x] Targeted archive sync without scan-time mutation

## Stage E — Validation and docs
- [x] Synthetic tests for scan, download, verification, approval, removal safety, and recovery
- [x] Relevant existing ytaedl regressions (210 passed)
- [x] Diff review, documentation, final status
- [ ] Feature branch commit
- [ ] Explicit user merge approval (separate from this implementation)
