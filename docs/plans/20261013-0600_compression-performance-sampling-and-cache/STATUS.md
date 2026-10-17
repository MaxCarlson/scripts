# Status

Locking & live scan progress cross_platform0.7.0/compresser0.21.0/MangaDL1.47.0:
per-folder OS byte-range write locks with offset-1 holder metadata (PID, create_time,
operation, target) and external shared read locks (no target folder mutation) in
`cross_platform.locks`; `mangadl lock -s|-u -d TARGET [-j]` inspects write/read/repair/
state-run locks and live processes, auto-cleaning harmless stale metadata on status
and requiring explicit `-u` for stale `repair.lock`/`state.sqlite3` running rows;
`InventoryProgress` live `termdash` progress block on `stderr` for `-l` (`-D headers`
and `-D files`) and initial header scans. 6 cross_platform lock tests, 137 compression
(1 skip), 307 MangaDL, 55 help pass; ruff clean.

Snapshot sampling compresser0.20.1/MangaDL1.46.2: gallery_sample uses lexical
absolute paths and rejects noncanonical '..' parts, avoiding population-wide
filesystem resolution on Windows during -U trust sampling. RED->GREEN2 tests;
full136 compression (1 privilege skip)/306 MangaDL/55 help pass.

MangaDL1.46.1: invalid analysis policies rejected before writer guard acquisition;
-U trust -w no longer creates .mangadl controls before returning an error. RED->GREEN
source-preservation regression;306 MangaDL/55 help pass. Compression code unchanged
from0.20.0 checkpoint010bc54, which is committed/pushed with134 tests/1 privilege skip.
Live header inventory is still running; no final counts claimed yet.

Inventory summary compresser0.20.0/MangaDL1.46.0: shared concise terminal footer
for header and file-only -l. Gallery/image counts, file bytes, extension shares,
format/header diagnostics, errors/exclusions and saved path; unknown totals stay
unknown. Redirected stdout remains JSON, summary on stderr; -J is JSON only.
RED->GREEN8 CLI tests; full134 compression/305 MangaDL/55 help pass,1 Windows
symlinkprivilege skip. Prior snapshot1689ffb committed/pushed. Broader advisor/
performance/scratch/reader gates remain open. User authorized one read-only live
header inventory of B:\Hent\hent1imageperpage in background; external artifacts
E:\Temp\mangadl-library-inventory.sqlite3 and timestamped JSON. Check completion
before claiming final counts. No source image/association changes.

I1b2 compresser0.19.0/MangaDL1.45.0: explicit -U refresh|trust. Whole-selection
header snapshots retain root/scanner/Pillow/filter policy, UTC completion and manga
ownership; atomic publication only after completed discovery. Trust skips enumeration,
validates selected files before trial/cache work and between comparison stages, and
labels old population totals/projections/date/age in text/JSON. Missing/incompatible/
changed selections fail closed; file-only snapshots cannot drive compression.
Trust excludes writes/recovery/previews/inventory-only. RED->GREEN for missing flag,
snapshot storage and between-stage change guard.128 compression passed/1 skipped
(Windows symlink privilege),303 MangaDL/55 help passed with required fixture permissions.
No production scan. Next: user-requested readable inventory summary, then advisor/
measured scheduling/scratch and reader acceptance. Docs freshness20/100 both modules.

I2d1 compresser0.18.0/MangaDL1.44.0: persistent creation/tracking/last-result-save
dates, run trial lookup hit/miss counters and refresh/no-match/invalid-record labels.
Text/JSON expose dates/counters without conflating probes with image counts. Legacy
creation remains unknown; successful trial commits advance last-save time. Separate
metadata table is not subject to trial eviction. RED->GREEN observed for missing API
and missing CLI report fields.113 compression/302 MangaDL/55 help pass, lint/format/
whitespace checks pass. Source validation/keys/policies unchanged. Detailed hashed-key
invalidation causes not claimed. I1b1 573aa11 pushed. No production library run.

I1b1 compresser0.17.0/MangaDL1.43.0: -l -D files counts extension candidates/bytes
without opening image content, reports known versus unknown totals, gallery shares/
size distributions and stat errors, and persists completed unverified snapshots in
inventory_file_snapshots. Existing headers/trials untouched. Normal header refresh
still required for compression. Fast -u filters explicitly rejected; direct gallery
targeting supported, nested pages/cover/control/partial/link exclusions retained.
RED observed for absent CLI/guard and denied-stat boundary, then focused5 tests pass;
full compresser109, full MangaDL302 and help55 pass. Lint/format/whitespace checks
pass; editable installs refreshed before publishing. User-requested existing
feature branch retained. No production run.
Docs freshness: compresser/MangaDL20 (same-checkpoint CLI docs); termdash unchanged.

I5b compresser0.16.0/MangaDL1.42.0: -Q/--qualities quality sweep in -b or -c -m
lossy. Existing --preview-qualities alias retained. Unique quality stages share
inventory/sample/lossless baseline and effective candidate cache. Without -Q the
old -q single-quality behavior/names remain.105 full compression/19 integration
tests and55 help tests pass; lint/format/whitespace checks pass. I5a df3535f already pushed. Remaining
advisor, trusted/fast inventory, diagnostics/scratch/reader acceptance not complete.

I5a compresser0.15.0/MangaDL1.41.0: new user-requested full-resolution previews
(-O external output,-n base count,-Q quality list; lossless plus default90/80).
Checksum-verified original copies and verified encoded candidates, unique run
folders/atomic manifest, explicit larger-output sizes, failures and cancellation.
Serial bounded memory/pixels; no source changes or summary-cache image publication.
103 full compression/18 integration/55 help tests pass; lint/format/whitespace pass.
This is a visual subset, not statistical coverage/advisor. Documented in READMEs
and approved continuation. Existing broader plan remains open (advisor/snapshots/
scratch/multi-quality analysis/reader acceptance). No production library run.

I3a compresser0.14.0/MangaDL1.40.0: seeded hash priorities and monotone divisor quota
extension keep earlier selections when -s/-P grows on unchanged inventory/seed.
Sampling revision2 differs from revision1. Selection plans in inventory_samples
include population fingerprint, selected relative files, quotas, seed and timestamp;
they are not completed-trial evidence.98 compression tests pass, including every
budget expansion in a heterogeneous fixture; full MangaDL suite and55 help pass.
Local installs refreshed; final persistence-close focused check recorded in handoff.
I2c1f51b92 pushed. Next: I3 pilot advisor/confirmation design; I1b trusted snapshots/
fast scan, miss-cause timestamps, I4 scratch/benchmarks and I5 multi-quality/reader
acceptance are still open. No production library benchmark or image writes.

I2c compresser0.13.0/MangaDL1.39.0: automatic per-library trial persistence beside
inventory, -k/--cache-policy use/refresh/off, -K override preserved. Refresh ignores
prior disk entries but permits new in-run reuse; off is memory-only for trials and
does not disable inventory. Inventory-only opens no trial cache. Text/JSON report
path/policy; CLI finally closes cache after workers stop.96 compression/17 integration/
55 help tests pass; ruff/whitespace checks pass. No stale snapshots implicitly trusted.
I2b d097138 pushed; next publish I2c, then stable expanding samples (I3a). Detailed
miss reasons/timestamps, pilot advisor and remaining I1b/I4/I5 acceptance stay open.

I2b compresser0.12.0: effective trial keys ignore display labels and unused valid
lossless quality, with exact legacy-key fallback. Analysis AUTO composes from a
complete measured candidate set and excludes unavailable lossless JPEG optimizer;
missing/failed candidate trials fall back to normal encoding. Publication never
uses summary-only cached candidates. Tests compare cached AUTO to uncached results
and prohibit re-encoding in fully cached cases.95 compression/17 integration pass.
I2a7e0e8a9 already pushed. Automatic trial-cache policy/diagnostics remain open;
I3 progressive sampling is next after publishing this usable slice.

Branch compression-inventory-and-analysis-20261016 tracks matching origin branch.
I1a committed83b6735 before branch creation and pushed on new branch, not main.
I2a compresser0.11.0: one lock-coordinated reusable SQLite connection per cache,
disk-hit memory promotion, eviction every min(256,capacity) writes, at most255
temporary excess rows. Every successful set still commits immediately. Explicit
close/context-manager API and final handle cleanup. No WAL assumption or buffered
durability introduced. Full compression92/integration17/help55 pass; lint/whitespace
checks pass. Next I2b reusable encoder candidates; automatic trial cache still open.

I1a implemented/tested: compresser0.10.0/MangaDL1.38.0, durable non-evicting
inventory, automatic validated header reuse, -I/-l inventory-only JSON, transactional
completed scopes, errors/extensions/sizes/coverage diagnostics and discovery reuse.
Full compression90, focused MangaDL17, help55 pass; ruff/format/whitespace checks
pass and editable installs refreshed. Initial scan still inspects headers; trusted
snapshots, lightweight filesystem-only inventory and advisor remain open. User now
explicitly requests: commit current changes, create a new branch, then test/commit/
push each major feature before continuing. Main is not to be pushed by this step.

2026-10-16 approved continuation recorded in01_inventory-and-analysis-continuation.md.
Baseline c3db8b4 on main, clean before this checkpoint. I1a persistent inventory is
next/in progress; no new production runs or source writes. I1-I5 supersede unfinished
P4/P5 design details; existing sampling/comparison and P1-P3 are not being rewritten.
SSD scratch belongs in I4 as opt-in analysis-only staging after measured diagnostics.

2026-10-16 P4 implementation: compresser0.9.0/MangaDL1.37.0 on main after
authorized merge3122931. Shared -b/--compare-both executes seven unique lossless/
lossy strategies on one inventory/sample. -P/--sample-percent and -z/--sample-seed
provide reproducible gallery-stratified random sampling; -s is a strict total
budget requiring gallery coverage. Reserve one per gallery (two if total budget
permits), distribute remaining quotas by equal image-count and byte weighting,
then sample uniformly without replacement within galleries. MangaDL explicitly
assigns nested chapter pages to their gallery. CLI sampled writes are rejected.
Projection uses gallery expansion weights; finite-population variance gives an
approximate normal95% interval only when every non-census gallery has >=2 trials
and no failures. Small/skewed samples remain a limitation, not claimed accuracy.
Inventory/coverage and projection appear in text/JSON; table includes projected
saved bytes. Existing -K persistence writes completed trials during processing;
a fresh cache reader inside a completion callback verifies real-time durability.
Full compression87 and focused MangaDL16 tests passed before final formatting;
final verification recorded in handoffs. P5 automatic cache policy is still open:
use explicit -K outside target; default capacity20000 can evict large inventories.
No production images changed. Historical checkpoint notes below remain context.

Current P3 checkpoint: compresser0.8.0/MangaDL1.36.0. Per-job memory reservations,
bounded FIFO-head bypass, preflight memory/pixel rejections excluded from pool cap,
active/reserved/peak/dispatch-wait diagnostics, and -B/--memory-budget-mib64..4096.
Default aggregate allowance512MiB unchanged; independent512MiB per-image/40M-pixel
decode limits retained, actual source dimensions must match scan metadata before
decode. Larger aggregate budgets do not admit unsupported oversized images.
Full compresser83, integration/ownership15 and help55 pass; lint/format checks pass;
editable installs refreshed. Remaining: publish P3, then P4 inventory/sampling/
projection, P5 automatic cache and P6 gallery/reader acceptance.

Read-only two-image threading check, WebP lossless effort0, same screenshots'
gallery files001 and003:512MiB gives peak active1, wall3.735s/CPU3.719s,
peak reserved467262432 B;1024MiB gives peak active2, wall1.968s/CPU3.516s,
peak reserved899089632 B, zero failures. Native WebP work can run concurrently;
about1.9x speedup for this bounded test. Actual RSS not measured; estimates are
not OS memory reservations. No source image changes or automatic default increase.

Current P2 phase/narrow-report slice: compresser0.7.0/MangaDL1.35.0. Per-image
exclusive wall phases and active phase labels implemented, aggregate phase seconds
in summaries/comparison/JSON. Cached hits measure current lookup work only. AUTO/
perceptual nested phases do not double-count. Below150 columns comparison uses
readable stacked records. Full compresser75 and MangaDL integration/ownership15
pass; setup refreshed. Scheduler/global budget unchanged. Uninstrumented overhead
and queue wait not fabricated; reservation-wait metrics belong with P3 scheduling.

Bounded read-only source benchmark: simplyhentai_232000_001.jpg,2646x3679,
4115764 B. WebP lossless effort6: wall45.625s, CPU45.484s, encoding45.344s,
verification0.140s, source decode0.047s; candidate3958962 B. Effort0: wall1.797s,
encoding1.500s, candidate4906754 B (larger, original retained). Native encoding
dominates and consumes about one core. Conservative estimate ~446MiB means only
one such worker fits the current512MiB allowance. No production images modified.
Next publish P2 checkpoint, then P3 memory-aware scheduling before P4/P5 features.

P1 pushed faf8822. P2 worker-visibility slice implemented and tested: requested,
effective and active worker counts, limiter/budget/largest-image estimates, active
image names/dimensions/estimated bytes and ticking elapsed durations. UI/summary/
JSON share diagnostics. Scheduling and memory budget are unchanged; oversized
images affecting the current cap are explicitly flagged. Full compresser71 and
MangaDL compression/ownership15 pass, lint/format/whitespace checks pass, editable
installs refreshed to0.6.0/1.34.0. Publish this usable slice before further edits.
P2 phase timings and narrow comparison fallback still open. No live image writes.
Docs freshness20 for changed modules,0 for unchanged termdash; current doc changes
explicitly retain scheduler/cache/phase/reader gates rather than imply completion.

Branch: compression-module-mangadl-20261013-0151, baseline df9e0d4.
User approved continuous implementation and scoped commit/push per usable feature.
Plan committed/pushed as c76df28. P1 implemented, fixture-verified and ready to publish:
cooperative cancellation, STOPPING/active encoder notice, no new jobs or candidates,
checks before publication, nonblocking lock feedback and clean CLI exit130.
Native encodes already in progress still need to return; repeated Ctrl+C does not
release ownership before active workers finish. No hard-kill behavior added.
Versions: compresser0.5.0 / MangaDL1.33.0. Full compresser69 and MangaDL
compression/ownership15 pass. Setup refreshed, installed CLI versions confirmed,
lint/whitespace checks pass. P1 is the usable publication checkpoint; P2 is next.
Confirmed global largest-image cap can reduce valid workload to one worker; no
running compression process was available during the latest counter probe.
Next: publish usable P1 checkpoint, then P2 diagnostics/worker visibility.
No budget increase, production image writes, broad live benchmark or merge authorized.
