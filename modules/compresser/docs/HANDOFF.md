# Compresser handoff

Plan03 P7 implemented: compresser0.34.0/MangaDL1.60.0 uses bounded memory-admitted
source workers, serial variants/local decoded image, immutable sequenced events and
one manifest owner. Numbered outputs/order stable under reverse completion; atomic
exclusive artifact publication, source checks, cancellation/draining, in-place UI.
276 compression/1 skip,315 MangaDL/55 help pass plus final13 preview regressions;
publication gate follows. P8 canonical CLI migration and whole-branch review next.


Plan03 P6 implemented: compresser0.33.0/MangaDL1.59.0 adds opt-in -B auto,
20% available floor/cap4096MiB, clear low/unknown telemetry failures, fixed512MiB
omitted default and unchanged image/pixel caps. Existing per-job scheduler pauses
new admissions under pressure, reports waiting reason and supports cancellation;
no cross-process/OS reservation promise.269 compression/1 skip, focused pressure
checks and55 help pass; final MangaDL/task gate follows. P7 parallel previews next.


Plan03 P5 completed: compresser0.32.0/MangaDL1.58.0 caches each successfully
verified AUTO format candidate during analysis, with normalized PNG-lossless keys,
retained-original policy and candidate-only elapsed time. Preview/write paths still
require bytes; failed candidates never fabricated.249 compression/1 skip,315
MangaDL/55 help pass. P6 explicit available-memory auto policy next.


Plan03 P4 implemented: compresser0.31.0/MangaDL1.57.0, atomic versioned metadata
profiles with input-size variance proxy, explicit -s auto starter coverage, stable
uniform-within-gallery prefixes and design-weighted estimates. Numeric -s/-P stay
balanced until P8; census unchanged. File-only profiles remain unverified, no pilot.
Full gate/publication follows; P5 verified AUTO candidate reuse next.


Plan03 P3 completed: compresser0.30.0/MangaDL1.56.0, incremental pre-admission
cache probes overlap encodes; bounded preparation, source checks and cancellation
retained. Bulk validated library lookup preserves scalar legacy/diagnostic behavior.
No speculative stat pool; first dispatch keeps scalar probing. P4 metadata-only
profiles next; final gate/publication follows. No production writes or main push.


Plan03 P3a compresser0.29.2/MangaDL1.55.2: deduplicate shared ancestor lstat work
per256-page validation batch, compare directory IDs before/after and between batches,
no trust retained across comparison stages. Leaf lstat/fingerprint remains mandatory;
ancestor replacement during validation now rejected. RED checks8->2 shared-parent
visits and missed replacement -> GREEN;227 compression/1 skip,314 MangaDL/55 help
pass. Task4 NOT complete: bounded scalar-equivalent cache probes, overlapping
preparation/encoding, thread measurement/cancellation/startup-latency tests remain.

Plan03 P2b compresser0.29.1/MangaDL1.55.1 reuses coordinator-only root discovery
entries through classification/scanning; regression counts each relevant directory
once for library/single-gallery paths. MangaDL rejects reparse-point roots before
resolution/locking. Task3 final gate follows; P3 trust/cache preparation next.

Plan03 P2a compresser0.29.0/MangaDL1.55.0: bounded SQL-free header workers,
<=2*workers pending, ready-result collection, one selection connection/pool,
<=256-key lookups/cache flushes and short write transactions. No-follow scandir
classification, before/after source identity and only visited-directory pruning.
Fingerprint/policy2 requires refresh of older trusted snapshots; no DB deletion.
224 compression/1 platform skip,311 MangaDL/55 help pass. Generated worker matrix
keeps equal results; MangaDL connection count10->1. Tiny scopes<=64 stay serial
after measured pool overhead; file-only serial unchanged. Editable installs verified.
P2 remains in progress: root discovery still probes/re-enumerates separately;
finish that reuse and failure/admission review before task3 gate, then P3 trust/cache.

Plan03 P1 compresser0.28.0/MangaDL1.54.0: logical-gallery completion events,
per-gallery file counts, independent overall progress, thread-safe render snapshots,
recent completed-gallery ETA (estimated, unknown until sufficient history).
Nested chapters do not reset parent progress; empty/error galleries finish once.
TTY-stream redraw/narrow-CJK/double-close and redirected JSON/no-UI tests cover
renderer contracts, not real Windows visual acceptance (still manual). P2 next.

Plan03 P0 compresser0.27.0/MangaDL1.53.0: response-only current-run coordinator/
worker phase measurements, high-resolution clock, inventory SQL/header/candidate
counts, cache hits and worker/reservation high-water marks. Worker contexts isolate
trace stacks; nested traces remain exclusive; warm hits never replay old encode time.
Generated benchmark matrix covers standalone/MangaDL1/2/4/8 workers with3 repetitions;
same verified results, no blanket more-threads improvement. P1 progress is next.

Inventory UI regression fix0.26.4: use actual termdash ProgressBar.set_total/str
and LiveBlock.close APIs. Nonexistent render_bar raised first; nonexistent clear
masked that error during finally cleanup. Real renderer TTY-stream regressions
cover headers/files,50% progress, double close and stopped timer. Task6 untouched.

Repair Task5 0.26.3/MangaDL1.52.3 ranks complete design-weighted target projections,
no failed/unestimated/nonpositive fallback winners. Practical lossy eligibility
requires measured SSIM>=0.98 and observed retained JPEG/PNG/WebP (AUTO conditional).
Warm/mixed cache disables speed term across comparison. JSON includes retained
formats/ranking scope; text says when unavailable. User STOP after this checkpoint;
Task6 not started. Real Windows terminal/reader acceptance remains manual.

Repair Task4 0.26.2: diagnostic RAM LRU bounded across paths/settings, persistent
exact-key/existence queries without materializing all settings. SQLite history
survives result eviction (disk growth explicit); legacy/forgotten memory history
reports unknown.185 compression/1 skip,308 MangaDL/55 help pass. Next Task5 ranking.

Repair Task3 0.26.1/MangaDL1.52.1: byte reservations precede source opens;64KiB
streaming/hash verification, cancellable capacity wait, atomic pre-write manifest,
tracked partial writes, run-identity/link checks, retryable cleanup with evidence.
Unlink failure aborts waiting stagers; engine/context-manager normal exit fails if
cleanup incomplete (does not mask original cancellation).17 scratch failure fixtures
cover oversized inputs, chunk bounds, exact concurrent reservation, manifest/disk/
delete failures, replacement, source growth/checksum/cancel, invalid budgets.
Local generated4-image benchmark identical: median0.125s direct/0.156s staged;
no B: or SSD speedup claim. Next bounded diagnostic cache memory.

Repair Task2 0.26.0/MangaDL1.52.0/cross_platform0.8.0: coordinated external reader/
writer gate and overlapping-tree registry. Standalone owns target through discovery
and all trials; writes before discovery, read-only target untouched. Managed writes
preserve legacy locks and thread-covering reentrancy.161 compression pass/1 skip;
129 cross_platform pass/4 skips. Stop old binaries before upgrade, shared local user
state required. Next bounded streaming scratch, cache bounds, recommendations, CLI plans.

Review Task1 compresser0.25.1/MangaDL1.51.1: confirmation_sample requires measured
pilot_results, stores known pilot observations, and estimate adds pilot totals plus
residual-population estimate/FPC. Missing/failed/duplicate/mismatched pilot refused;
unknown residuals remain unknown. Deprecated two-stage interval null, unsupported
pooling advice removed; ordinary -s no longer advertised as implementing advice.
158 compression passed/1 symlink skip. Remaining repairs in repo plan02_review-repairs:
locks, scratch, diagnostic bounds, recommendations and exact CLI plan consumption.

Inventory footer0.20.0/MangaDL1.46.0: shared emitter keeps redirected JSON while
showing stats on stderr (terminal gets summary only); -J suppresses footer. Header/
file modes report eligible gallery counts, bytes, extension shares and error/scan
diagnostics, never full integrity claims or fabricated zero for unknown bytes.
134 compression/305 MangaDL/55 help pass,1 symlinkprivilege skip. Snapshot1689ffb
pushed; remaining advisor/performance/scratch/reader gates open. One user-requested
read-only production header scan is running externally; inspect artifacts before
reporting final counts (see repo active STATUS). Source images unchanged.

I1b2 0.19.0/MangaDL1.45.0: -U refresh|trust, defaultrefresh. Whole-selection
snapshot table scoped by root/scanner/Pillow/exactfilter policy; trust skips walks,
checks selected source fingerprints/links before cache/encoding and between stages.
Text/JSON show UTC age and stale-population caveat; old membership never claimed
current. No trust for writes/recovery/previews/inventory-only.128 compression passed,
1 symlinkprivilege skip;303 MangaDL/55 help passed. No production runs. Next readable
inventory summary, then advisor/benchmark/scratch/reader gates in existing plan.

I2d1 0.18.0/MangaDL1.44.0: durable cache dates and run-scoped trial lookup counters,
shared text/JSON diagnostics. Legacy creation date unknown, refresh/no-match/invalid
record categories only (no invented source/settings cause). Dates commit with results,
separate from eviction.113 compression/302 MangaDL/55 help pass; RED->GREEN API/CLI.

I1b1 0.17.0/MangaDL1.43.0: shared file_inventory scanner via -l -D files, no image
opens/encodes. Explicit candidate/unknown totals, gallery/extension sizes/shares,
durable separate completed file snapshots; aborted walk preserves prior snapshot.
109 full compression/302 full MangaDL tests pass; RED->GREEN observed for main
behavior and stat-error guard. Header compression/preview logic unchanged. Existing
plan-scoped ledger records execution; remaining trust/advisor/scratch stages open.

I5b0.16.0/MangaDL1.42.0: -Q/--qualities now also works in combined/lossy comparison;
--preview-qualities alias retained. One shared lossless baseline and sample; stages
named per quality, duplicate values removed, per-row estimates/cache reuse.105
compression/19 integration tests pass. I5a preview df3535f pushed previously.

I5a0.15.0/MangaDL1.41.0 preview: -O external unique run,-n base count,-Q integer/
decimal quality list (defaults90/80), lossless always included. Full-resolution
verified candidate bytes + checksum original copy; actual sizes even if larger.
Atomic manifest tracks sources/settings/errors/cancellation. Serial safety-bounded
execution; summary caches not reused as image bytes. Existing inventory reused.
103 full compression/18 focused MangaDL tests pass. No production images changed.

I3a0.14.0/MangaDL1.40.0: stable seeded file ranking + monotone gallery quotas;
larger samples retain earlier selections on unchanged population/seed. Persisted
sample plans/population identity in separate inventory_samples table. Revision2
changes old selection order.98 compression/full MangaDL/55 help pass; installs
refreshed. Pilot-based advisor, trusted snapshots/fast inventory, diagnostics,
scratch and multi-quality/reader acceptance remain open. No production writes.

I2c:0.13.0/MangaDL1.39.0 automatic per-library trial cache, -k use/refresh/off,
-K override. Refresh ignores old disk trials but reuses this run's work; off keeps
memory only. Inventory-only opens no trial DB. Text/JSON report path/policy; CLI
finally closes handles.96 compression/17 integration/55 help tests pass. Next I3a
stable expanding samples. Miss-cause detail, cache timestamps/advisor still open.

I2b:0.12.0 effective candidate keys/legacy fallback, read-only AUTO candidate reuse.
Complete compatible candidates required; unavailable lossless JPEG optimizer excluded.
Missing candidates fall back; summary caches never publish image bytes.95 compression
and17 integration pass. Label changes/unused lossless quality no longer force encodes.

I2a:0.11.0 on compression-inventory-and-analysis-20261016. Reused lock-coordinated
SQLite handle, disk-hit promotion, periodic eviction bounded by capacity+255,
immediate per-result commits preserved. close()/context manager release handles.
92 compression/17 integration/55 help pass; lint/format/whitespace checks pass.
I1a83b6735 pushed on new branch; no push of main. Next candidate/AUTO reuse.

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

