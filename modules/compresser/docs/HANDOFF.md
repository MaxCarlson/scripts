# Compresser handoff

I1a (2026-10-16):0.10.0 durable SQLite inventory independent of trial eviction.
-I path override and -l JSON inventory-only; normal analysis refreshes automatically.
Validated membership/header fingerprints, transactional completed-scope publication,
deleted-record pruning and explicit unreadable scope diagnostics. Initial scan uses
headers, not filesystem-only or trusted snapshots. MangaDL reuses gallery discovery
results; automatic metadata persistence is isolated in test fixtures. No source writes.

2026-10-16:0.9.0 adds CLI -b combined lossless/lossy comparison, -P percent and
-z seed. New sampling.py provides per-gallery coverage, count/byte-weighted quotas,
uniform random selection and design-weighted projections with approximate95%
intervals/explicit gaps. Legacy select_sample API unchanged. Nested gallery IDs
come from MangaDL. One shared inventory/sample, seven trials per selected image.
-K cache commits each finished trial immediately; live reader fixture verifies
durability before batch completion. Automatic cache/default prompt remains open.
README documents limits and ready-to-run commands. No production image writes.
Verification: full compresser87; full MangaDL suite; scripts_help55 passed.
Final report/cache/UI subset6 passed after adding per-gallery JSON inventory.
ruff and source whitespace checks passed; editable installs refreshed successfully.

Current P3:0.8.0/MangaDL1.36.0. Per-job reservations/preflight/fair bounded bypass,
aggregate -B64..4096MiB (default512), per-image512MiB/pixel limits unchanged.
Source dimensions verified against metadata before decoding. Full83 tests,
integration15/help55 pass; setup refreshed. Two real read-only effort0 encodes:
512MiB one active3.735s;1024MiB two active1.968s, zero failures. Peak reservations
bounded; actual RSS not measured. Next publish P3, then P4 inventory/projections,
P5 automatic cache prompts and P6 integrity/reader acceptance.

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

