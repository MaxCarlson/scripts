# compresser 0.8.0

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
default), so large scans may evict old entries. Without `-K`, reuse is in-memory
for this invocation only. Sampling never applies writes.
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

