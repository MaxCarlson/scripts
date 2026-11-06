# Checklist

## P0 — Root cause and evidence
- [x] Verify branch/worktree and preserve dirty main and scheduler branch.
- [x] Correlate single-URL manager, worker, raw, output, and archive records.
- [x] Probe fresh output and three historical outputs for stream duration and packet timing.
- [x] Compare healthy and collapsed-timeline synthetic fragmented MP4 before/after current metadata rewrite.
- [x] Complete 68-file CSV classification and archive correlation.
- [x] Inspect available retained fragment box/timestamp structure and report missing fresh fragments.

## P1 — Finalization and validation
- [x] Validate video and audio independently against expected duration and bounded packet timestamps.
- [x] Stage mux and metadata outputs; preserve the assembled intermediate on metadata validation failure.
- [x] Emit `complete` only after final promoted output passes validation; report actual final size.
- [x] Add realistic fragmented-MP4 regressions for metadata and timeline preservation.

## P2 — Segments, resume, interruption
- [x] Propagate required segment failures and keep optional final-segment behavior explicit.
- [x] Validate fragment structure and representation identity on reuse.
- [x] Use atomic fragment and `.part` writes with recomputed resume counters.
- [x] Make retry/task and progress-thread cleanup exception-safe.
- [x] Return nonzero for SIGTERM; preserve recoverable state.

## P3 — ytaedl and reconciliation
- [x] Reject corrupted AEBN existing outputs and prevent archive success.
- [x] Re-run AEBN URLs through the AEBN validator instead of trusting prior archive success.
- [x] Require independent stream coverage in reconciliation and invalidate stale verification results.
- [x] Keep original-media approval/deletion gates explicit and unchanged in authority.

## P4 — Validation and delivery
- [x] Offline synthetic end-to-end healthy and corrupted cases.
- [ ] Focused AEBN, ytaedl, reconciliation, and procparsers regressions (procparsers checkout is absent in this worktree).
- [ ] Ruff, compile checks, `git diff --check`, and final diff review.
- [x] Document no-live-test limit and safe recovery procedure.
- [ ] Run the separately authorized controlled live smoke test after offline checks pass; preserve staged artifacts.
- [ ] Commit validated changes; request explicit merge approval, do not merge.
