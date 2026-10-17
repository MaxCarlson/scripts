# compresser 0.23.0

## Pilot sample-size advisor, coverage gaps, and confirmation sampling

`GallerySample.summary()` and `GallerySample.estimate()` distinguish the per-gallery
coverage floor (`coverage_minimum_images`) from the within-gallery variance floor
(`variance_minimum_images`) and expose coverage gaps (`unsampled_formats`,
`unsampled_large_images` in the top size decile, `unsampled_tall_webp_images`
exceeding WebP's 16,383px dimension limit, and `singleton_non_census_galleries`).
On sampled runs, `GallerySample.advise_sample_size()` uses observed within-gallery
savings variance and per-image runtime (`elapsed_s`) to recommend total and
additional confirmation sample sizes and Neyman-weighted gallery quotas for a target
margin or runtime budget. Because stopping early based on a pilot interval can
understate uncertainty, `estimate()` reports both `approximate_95_percent_interval_bytes`
and `two_stage_adjusted_95_percent_interval_bytes` (Bonferroni two-look adjustment),
and `confirmation_sample()` draws a strictly disjoint confirmation sample from the
remaining seeded permutation in each gallery.

## Live inventory scan progress and statistics summary

`compresser -i TARGET -l` displays a live in-place `termdash` progress block on
`stderr` while discovering folders and scanning files/headers (folders processed,
files processed, reused vs. inspected headers, total file bytes processed, rolling
files/s and MB/s throughput, elapsed time, and ETA; disable with `-N/--no-ui`), and
ends with a concise, color-aware summary: eligible gallery
folders, image headers/extension candidates, total file bytes, extension counts/sizes
and count/byte shares, plus header reuse/unreadable or stat/exclusion counts as available.
Detected formats are separate from extensions. No per-gallery dump in a terminal.
Unknown sizes/shares stay unknown rather than becoming zero. No encoders run.

Interactive inventory-only runs display just the summary on stderr. Redirected stdout
retains the full JSON inventory, with the summary still visible on stderr. Use `-J`
for JSON only (no human footer), e.g. `compresser -i TARGET -l -J > inventory.json`.
Both header depth and `-D files` have summaries; candidates are not verified content
and header inventory is not a decode/completeness audit. Bytes are file lengths,
not filesystem allocated space. The final line shows where the inventory was saved.

## Explicit snapshot reuse

Normal analysis and header inventory (`-l`) save a completed whole-selection
snapshot, separately from file-only scans and trial caches. Subsequent read-only
analysis can skip discovery and header scans with `-U/--inventory-policy trust`:

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -l
compresser -i 'B:\Hent\hent1imageperpage' -U trust -b -Q 90 80 -P 2 -z 42
```

Use the same root and `-I`/`-K` inventory location. The snapshot records scanner policy,
Pillow version and selection. Missing/incompatible snapshots fail with refresh guidance;
file-only snapshots cannot be trusted for compression. `-U refresh` remains the default
and discovers changes while reusing unchanged headers.

Trust is explicit noninteractive consent to old population membership: reports show
the UTC completion time, age, and a warning that totals/projections describe the saved
population, not today's library. Selected files are checked for size/timestamps and
linked ancestors before trial/cache work and between comparison stages. Changed or
missing selections fail closed; new or changed unselected files are not discovered.
Fingerprints are not content hashes or an integrity audit. Trust cannot be combined
with source writes, recovery, inventory-only or previews. No prompt is required.
JSON includes `inventory_snapshot` and `population_warning` alongside estimates.

## Cache visibility and indexed invalidation causes

Normal analyses show the persistent cache creation date and last result-save date
at startup. Legacy caches without recorded dates explicitly show unknown creation
time; tracking starts when first opened by this version, not retroactively. Cache
dates persist independently of trial eviction. Only successfully committed trial
saves advance the last-result timestamp.

Text summaries and JSON `cache` objects include current-run trial lookup hits/misses,
`miss_reasons`, and `invalidation_causes` indexed via `trial_index`:
`no_matching_entry`/`never_measured` (path never recorded in the trial index),
`source_changed` (file size, mtime, or ctime changed since measurement),
`settings_changed` (different format/mode/quality/effort/encoder for an already-measured
source), `runtime_changed` (codec/Pillow/metric identity changed), `evicted` (previously
recorded in `trial_index` for the exact source, settings, and runtime before `entries`
pruning), `refresh_policy`, and `invalid_record`. Memory-only caches have no persistent
creation date.

## Fast extension/size inventory

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -l -D files -I 'E:\Temp\image-inventory.sqlite3' > 'E:\Temp\file-inventory.json'
```

`-D/--inventory-depth files` is an inventory-only pass using directory entries and
file stats: no image header opens, pixel decodes or encoder work. It counts candidate
images by extension, gallery and bytes, with size summaries and count/byte shares.
Malformed files with image extensions are counted as candidates, not valid images.
Actual formats/dimensions remain unverified/null. Unknown file sizes are null, with
explicit stat errors; known bytes are reported separately. Directory enumeration
failure leaves the last completed snapshot intact. Hidden/partial/linked paths are
excluded. Bytes are file lengths, not filesystem allocated space.

Fast snapshots are saved in a separate inventory_file_snapshots table, never as
verified headers or compression results. Normal compression still refreshes verified
headers; this fast snapshot does not yet bypass that refresh or advise accuracy.
`-D headers` (default) retains the existing header-based inventory workflow. Files
depth requires -l and cannot drive sampled compression or source writes.

## Multi-quality comparison

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -b -Q 90 80 70 -P 2 -z 42 -t 4 -B 1024
```

`-Q/--qualities` also works in comparisons (the existing --preview-qualities spelling
remains an alias). With -b, one lossless set is followed by WebP/JPEG/AUTO lossy rows
for every quality, on the same sample and inventory. Duplicate qualities are removed.
Lossless baselines are not repeated. For only a PNG lossless baseline plus lossy
quality sweeps, use `-c -m lossy -Q 90 80`.
Without -Q, -q continues to select the single lossy quality. Per-quality stage names,
sample projections and cache hits are reported separately. Comparison writes no image
copies; use -O for visual preview output. More qualities mean more encoder trials.

## Full-resolution compression previews

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -O 'E:\Temp\compression-previews' -n 3 -f webp -Q 0.9 0.8 -e 2
```

`-O/--preview-dir` creates a unique run folder outside the source tree. `-n` chooses
how many base images (default3, capped by availability); `-z` controls reproducible
selection. This small preview subset is not a representative savings estimate and
does not require one image per gallery. Each numbered image directory contains a
checksum-verified original copy, lossless candidate and lossy candidates for `-Q`
(default90/80). Integer90 and decimal0.9 both mean encoder quality90, not90% fidelity
or10% storage savings. Previews use -Q, not the analysis-mode -q setting.

Targets are -f auto/webp/jpeg/avif; AUTO can select a different format per variant.
Lossless JPEG needs jpegtran and lossless AVIF is unsupported: failures are explicit
in manifest.json. PNG has no lossy quality setting and is not an explicit preview
target. Full-resolution candidate files are retained even if larger than originals;
manifest sizes/savings describe actual candidates, not normal retained-original rules.
The manifest maps source paths/settings/encoders/SSIM, sizes and failures. SSIM is
not a visual-quality guarantee. Open numbered folders in an image viewer to compare.

No source files, page names, manifests or archives are changed. Repeated runs create
new folders and do not overwrite previous previews. Cancellation preserves partial
output and records cancelled status. Existing safety/metadata checks apply, source
changes are detected, and oversized/unsupported inputs are reported. Preview is
serial (-t is not used), with one source/candidate at a time; native encoder work can
delay Ctrl+C until it returns. Summary-only trial caches cannot supply image bytes,
so variants are regenerated; inventory headers are still reused. Preview cannot be
combined with -w/-c/-b/-s/-P/-l/recovery. Add -J for a JSON-only final report.

## Persistent inventory

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -l -I 'E:\Temp\image-inventory.sqlite3' > 'E:\Temp\image-inventory.json'
```

`-l/--inventory-only` refreshes inventory and emits JSON without encoding. Includes
per-gallery eligible header-image counts/bytes, extensions versus actual formats,
size summaries and shares; scan scopes separately report unreadable candidates.
Headers are not full image-integrity verification. Bytes are file lengths, not
filesystem allocation sizes. `-I/--inventory-file` selects durable SQLite storage
outside the input tree. Without it, a companion inventory is used beside explicit
`-K`, or a per-library file under the user cache directory. Normal compression
automatically refreshes the same inventory. Existing inventory metadata is never
evicted by the trial cache. Membership is enumerated every run; only new/changed
headers are inspected. Successful scope refreshes remove deleted records; aborted
scans do not publish a completed snapshot. Sources are unchanged; only the inventory
is written. Trusted-snapshot/fast filesystem-only modes and sample advice are later
checkpoints; this first implementation inspects headers on the initial pass.

Reusable image analysis, encoder comparison and optional verified compression.
Default operation is read-only, lossless analysis. Bulk production writes are
not yet accepted; see the [reviewed plan](../../docs/plans/20261013-0151_compression-module-and-mangadl-integration/05_reviewed-plan.md).

## Usage

```powershell
compresser -i B:\Hent\hent1imageperpage -s 60 -N
compresser -i B:\Hent\hent1imageperpage -c -m lossless -s 60 -N
compresser -i B:\Hent\hent1imageperpage -f webp -A pillow-webp -e 6 -m perceptual -p 0.990 -s 60 -K E:\Temp\compression-cache.sqlite3 -N
```

Analysis changes no source images, journals or source manifests. An optional
`-K/--cache-file` must be outside the input tree; it stores inventory headers
and measured trials across sessions. Source stat identity, encoder/runtime,
metric revision and all settings invalidate stale entries. Directory membership
is still enumerated to detect new/removed files; unchanged headers aren't reopened.
Cache hits are distinguished from measured encoding throughput.

`-f/--format`: auto, keep, jpeg, webp, png, avif.
`-A/--algorithm`: auto or a verified named encoder. `-e/--effort` controls
PNG/WebP effort (0–6), not JPEG visual quality. `-m/--mode`: lossless,
lossy or perceptual. `-q/--quality` is an encoder setting, not a percentage
of visual degradation. Perceptual mode tests bounded candidates against sampled
RGB/detail SSIM; this is not a guarantee that every detail remains perceptually
identical. Inspect representative pages before choosing a lossy policy.

Auto measures eligible JPEG/WebP/PNG candidates and keeps the smallest verified
output, or the original when no smaller result exists. PNG is always lossless.
JPEG coefficient optimization requires original-file jpegtran; Pillow JPEG is
lossy. AVIF is explicit lossy only. No unverified external wrapper is automatically
selected merely because a binary appears on PATH. Explicit oversized WebP,
animation, unsupported color/bit depth, changed source and metadata/alpha loss
are refused. Estimated aggregate decoded working memory is capped at512MiB;
this is conservative scheduling, not an OS memory reservation.

CLI samples are seeded random samples within each gallery. `-s N` is a total
budget and must cover every eligible gallery; `-P PERCENT` automatically raises
the count to at least one per gallery. If the budget permits, two images per
non-singleton gallery are reserved before allocating the remainder equally by
image-count and byte shares. Within each gallery every image has equal selection
probability. `-z SEED` reproduces selection (default 0). Nested chapters belong
to their manga in MangaDL; standalone input groups by first-level directory.

Sampling revision2 uses stable seeded file priorities and monotone weighted quota
allocation. With the same inventory/seed, increasing -s or -P retains every previous
selection, maximizing trial-cache reuse. A changed population is a different sample
plan. This revision can select different images from revision1 for the same seed.
Plans are saved in the inventory database's `inventory_samples` table, including
population fingerprint, selected relative paths, seed, quotas and creation time.
These are selection records, not proof that any trial finished. Pilot-based sample
size advice and outcome-adaptive sampling are not implemented; existing uncertainty
limits still apply, especially when repeatedly inspecting growing samples.

`-b/--compare-both` compares PNG/WebP/JPEG/AUTO lossless and WebP/JPEG/AUTO lossy
using `-q QUALITY`, one inventory and one shared sample: seven strategy trials per
sampled image, not one encode. No source images are changed.

```powershell
compresser -i 'B:\Hent\hent1imageperpage' -b -q 80 -P 2 -z 42 -t 4 -B 1024 -K 'E:\Temp\compression-cache.sqlite3'
```

Reports separate measured sample savings from projected whole-target savings.
Each gallery's mean saved bytes per sampled image is expanded by its population
count, correcting unequal sampling rates. Approximate 95% normal intervals use
within-gallery sample variance and finite-population correction, not guaranteed
accuracy. Small/skewed samples may understate uncertainty. Non-census galleries
with one sample prevent interval calculation; failed/unmeasured galleries prevent
a full projection. Rare formats may be missed: inspect format coverage, increase
the sample or repeat with another seed. The legacy public `select_sample` API
remains format/size-stratified.

`-K` enables real-time persistent caching: unchanged metadata and completed trials
are committed as they finish, reusable on matching checks and after interruption.
Active encodes have no reusable result yet. Keys include file timestamps/identity,
strategy settings and codec/runtime identity; quality/effort changes need new trials.
The cache must be outside the input tree. Storage is bounded (20,000 entries by
default, with at most 255 temporary extra rows between eviction passes), so large
analyses may evict old trial entries. Durable inventory is separate and not evicted.
Connections are reused; each completed trial is still committed immediately.
Display labels no longer prevent reuse, and lossless keys ignore unused quality
values. Exact old-format keys are still checked for compatibility. Read-only AUTO
can compose its result from a complete compatible set of explicit-format trials,
avoiding repeated encodes; incomplete candidate sets fall back to normal encoding.
An unavailable lossless JPEG optimizer is excluded from that candidate set. Cached
size summaries are never used as replacement image data in write mode.
Library callers can use `AnalysisCache` as a context manager or call `close()`.
CLI trial caching is now automatic per library, beside the inventory. `-K` overrides
the location. `-k/--cache-policy use` (default) validates and reuses persisted trials;
`refresh` bypasses older trial entries but reuses new in-run work and persists it;
`off` disables trial disk caching but retains in-run memory reuse. Inventory remains
independently persistent. No interactive prompt is required for fingerprint-validated
reuse; trusting stale population snapshots is not implemented. CLI paths/policies
appear in text and JSON reports. Inventory-only runs do not open a trial cache.
Direct `AnalysisCache()` API callers remain memory-only unless passed a path.
Sampling never applies writes.
Comparison uses one persistent dashboard across PNG, WebP, JPEG and AUTO stages.
The dashboard reports requested/effective/active workers and the CPU/memory/requested
limiter, with up to two active image names, dimensions, conservative memory estimate
and elapsed time. JSON and summaries expose worker_diagnostics too. These are actual
worker activity counters, not OS CPU utilization. Per-job reservations allow small
images to overlap with large ones when they fit; rejected oversized images never
cap valid jobs. Reserved bytes are estimates, not actual RSS or an OS reservation.
`-B/--memory-budget-mib` sets aggregate batch scheduling allowance64..4096MiB
(default512). It does not raise the512MiB per-image decode allowance or pixel limit.
Use a larger allowance only when sufficient RAM is available; independent batches
have independent budgets. Bounded FIFO-head bypass prevents large-job starvation.
Diagnostics include peak reserved bytes and total dispatch waiting from batch start,
separate from exclusive worker phase seconds. Increasing workers is still CPU/memory
bounded and cannot accelerate one single-core high-effort native encode.
Active images show their current phase. Reports/JSON expose exclusive phase
worker-seconds: source decode, encoding, candidate decode, similarity, verification,
cache and publication when applicable. Parallel worker times add and are not CPU
time or whole-run elapsed time. Cached trials record only current lookup work.
Encoding includes codec preparation/bookkeeping outside separately instrumented
decode/metric calls. Uninstrumented overhead is not fabricated; dispatch wait is
reported separately and includes preflight/admission delay, not codec CPU work.
Narrow terminals use stacked comparison records; wide terminals keep the matrix.
Stage/gallery bars reset for each strategy; the aligned overall bar and elapsed
timer cover all image-strategy trials (60 images x4 strategies =240 trials).
Completed stages are green, active blue, pending yellow, with textual status when
color is disabled. AUTO may encode several candidates within one trial; ETA uses
recent throughput and can change substantially between encoders.
Retained size/savings include originals when candidates are larger or trials fail.
Encoded candidate totals before retention and grouped failure reasons are printed
below the table; totals are unavailable if any image trial failed. "Kept" counts
non-error skips. Cached entries are invalidated for the new candidate-size schema.

## Writes and recovery

Ctrl+C stops new job submission and checks cancellation between encoder candidates
and before publication. A stopping notice shows the active encoder count. A native
encode already in progress must return; cancellation is cooperative, not an unsafe
forced kill. Interrupted CLI runs return130, without a traceback. OS write locks
fail immediately with their path and "Not waiting"; retry after the owner finishes.

Writes need `-w/--write`; lossy/perceptual writes also need `-L/--allow-lossy`.
Valid outputs are fully decoded and checked before publication. Existing target
collisions are preserved. Same-extension replacement uses an atomic rename;
cross-extension changes are journaled and are NOT one atomic operation.
The persistent `.compress.lock` is an OS-owned lock released on process death;
do not remove it. It is harmless when no process holds it.
Established MangaDL libraries additionally share `.mangadl/operation.lock` with
MangaDL run/repair/compression. Unrelated external tools must not write concurrently.
`-s` limits the total images processed, including with `-w`; omit it for a full apply.

Pending journals block new writes; analysis never applies recovery. Preview one
exact gallery (not the whole library), then apply its current token:

```powershell
compresser -i "B:\Hent\hent1imageperpage\GALLERY" -R
compresser -i "B:\Hent\hent1imageperpage\GALLERY" -R -w -C TOKEN
```

Recovery validates containment, hashes and published-image geometry. Legacy,
malformed or externally changed journals are refused. No deletion is authorized
merely because an image opens. Separate-output mode (`-o`) remains explicitly
rejected. Readers and real-terminal behavior still need final acceptance.

