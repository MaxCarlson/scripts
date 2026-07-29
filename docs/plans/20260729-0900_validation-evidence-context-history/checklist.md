# Validation Evidence Checklist

## Foundation

- [x] Add root dispatcher
- [x] Add target manifest
- [x] Add fixed authoritative latest report
- [x] Add bounded report history
- [x] Add target-configured context sources
- [x] Add current context snapshot
- [x] Add context progress diff
- [x] Add repository-wide plan tree
- [ ] Validate on Windows
- [ ] Verify first-run legacy-report migration
- [ ] Verify second-run context diff
- [ ] Verify retention limits

## Later Expansion

- [ ] Add machine-readable run metadata
- [ ] Add explicit run IDs across paired artifacts
- [ ] Add commit-range summaries
- [ ] Add changed-file statistics
- [ ] Add checklist transition extraction
- [ ] Add coverage/test-count deltas
- [ ] Add staleness detection
- [ ] Add chronological development-log generation
- [ ] Add cross-platform dispatcher parity
- [ ] Add dedicated dispatcher unit tests

## Later Compact-Report Processing

- [ ] Define the authoritative compact report schema
- [ ] Keep live pytest output colored while normalizing tracked text to plain UTF-8
- [ ] Remove successful installation chatter from the compact handoff
- [ ] Collapse individual passing-test lines into aggregate counts
- [ ] Preserve complete failure/error/traceback and short-summary details
- [ ] Preserve commands, working directories, exact exit codes, warnings, skips, and environment metadata
- [ ] Preserve coverage totals and meaningful regressions
- [ ] Decide whether raw transcripts are tracked, failure-only, or local-only
- [ ] Document the compact-report contract in `AGENTS.md`, `CLAUDE.md`, and `docs/test-results/README.md`
- [ ] Add regression tests proving compaction cannot hide actionable failures
- [ ] Measure token/size reduction before making compact output authoritative
