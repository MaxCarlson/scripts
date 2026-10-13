# compresser 0.6.0

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

Samples are stratified by format, size and WebP dimension eligibility. Reports
separate sample bytes/savings, population inventory and projected covered savings.
Unrepresented/failed strata remain unestimated; projections are not confidence
intervals. Comparison rows retain failure, skipped and cache-hit counts.
Comparison uses one persistent dashboard across PNG, WebP, JPEG and AUTO stages.
The dashboard reports requested/effective/active workers and the CPU/memory/requested
limiter, with up to two active image names, dimensions, conservative memory estimate
and elapsed time. JSON and summaries expose worker_diagnostics too. These are actual
worker activity counters, not OS CPU utilization. The current largest-image cap still
includes oversized images; this is shown explicitly, pending scheduler correction.
Codec/verification/similarity phase timers are not implemented yet.
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

