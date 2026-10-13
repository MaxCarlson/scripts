# Compresser handoff

Current0.7.0 / MangaDL1.35.0: exclusive per-image phases/current active labels,
aggregate wall-time phase seconds and readable narrow comparison records.
Cache hits never replay old encoder timings; nested AUTO/perceptual phases exclusive.
Full75 tests and MangaDL integration15 pass. Read-only screenshot-image profile:
effort6 wall45.625s/CPU45.484s, encoding45.344s; effort0 wall1.797s but larger
output retained original. No budget/scheduler change or production writes.
Next publish P2, then memory-aware reservations/preflight/wait metrics (P3).

Latest worker diagnostics slice:0.6.0 (MangaDL1.34.0), full71 tests and MangaDL
integration/ownership15 pass. UI/summary/JSON report requested/effective/active
workers, limiter, budget/largest estimate and active image dimensions/time.
No scheduling or budget change; rejected oversized images still affect cap and
are explicitly flagged. Next: publish slice, then P2 phase timers/narrow report.

Active performance/cache plan: ../../../docs/plans/20261013-0600_compression-performance-sampling-and-cache/.
P1 source0.5.0: cooperative Ctrl+C between encodes and before publication,
STOPPING notice/active count, no new jobs, exit130, explicit nonblocking lock error.
Native calls already underway must return; no forced kill. Full69 tests pass,
MangaDL compression/ownership15. Next publish P1, then actual worker/phase diagnostics.

Current UI checkpoint: source0.4.0, MangaDL1.32.0. Persistent comparison stages,
aligned gallery/stage/overall bars, whole-run timer and total image-strategy trials.
Retained-size table distinguishes larger candidates, non-error kept originals and
encoder failures. Raw candidate totals/reasons also exposed in comparison JSON;
cache schema3 invalidates stale trial details. Full66 tests and MangaDL integration10
pass. Read-only two-page user JPEG trial confirmed PNG/WebP lossless outputs larger
than originals; jpegtran absent. Remaining: real terminal/reader acceptance and
manual repair mapping. No production compression or merge.

Branch: compression-module-mangadl-20261013-0151. Plans pushed as f1baeab.
Source checkpoint0.2.0 pushed as7181e4f; nested MangaDL/guard checkpoint2f0dd8b.
Current source0.3.1 shares established-library ownership with MangaDL1.31.1
for batch/single-image writes and recovery apply. Batch holds ownership through
worker completion. Analysis stays mutation-free; external tools remain uncoordinated.

Implemented: read-only analysis, verified JPEG/WebP/PNG dispatch, explicit lossy
AVIF, measured auto selection, encoder/effort controls, persistent separate
inventory/trial cache, stratified measured/projected reporting, sampled RGB/detail
SSIM, resource bounds, OS writer ownership and explicit token-bound recovery.
Actual process-death tests cover prepared/published/source-removed/same-extension
states. Shared termdash transient progress replaces handwritten cursor output.

Verification: full compresser61, MangaDL290, termdash75 passed/1 skipped,
scripts-help55. Focused audit/index/compression78 passed. Compresser/MangaDL
dispatcher targets PASS; installed CLI sample JSON and unchanged fixture hashes
verified. Ruff/compile/help/version checks pass.

Continuation verification: full compresser63 and MangaDL296 pass separately;
MangaDL nested-gallery/operation guard implemented and fixture-tested. Next:
terminal/reader acceptance, then manual repair
mapping. No production compression or merge.

