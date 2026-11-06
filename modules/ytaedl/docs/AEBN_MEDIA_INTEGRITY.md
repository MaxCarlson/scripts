# AEBN media integrity and recovery

## What completion means

`aebndl` now validates a scene or movie against its expected duration using
independent audio and video stream durations, packet counts, and bounded packet
timestamp samples. Missing or collapsed video coverage fails closed. The
`complete` event is emitted only after metadata processing, validation, and
promotion, and its `file_size` is read from the final artifact. Existing AEBN
outputs must pass the same checks before they can be reported as `already`.

Metadata rewriting uses a separate candidate MP4 and explicit audio/video
mapping. Scene chapter time is rebased to the selected scene. The assembled
intermediate is retained if metadata validation fails. Segment writes and part
state are atomic; retained fragments are checked against stream and segment
identity before reuse. `SIGTERM` reports an interrupted, nonzero result.

These checks prevent the known two-second-video/long-audio signature from
becoming a new successful archive result. One controlled live test reached AEBN
but was correctly rejected because video fragments repeated after index 22.

## Historical outputs

The read-only incident inventory is at:

`modules/ytaedl/.pytest_tmp_root/aebn-incident/B-stars-last-24-hours.csv`

It covers 68 supplied paths. All show a substantial audio/video duration
mismatch: 67 classify as truncated video and one as suspected timestamp
corruption. Manager/archive correlation linked 67 paths to a URL and found 65
`downloaded` archive statuses and 2 `already` statuses; one chaptered temporary
copy had no matching manager destination. These are diagnostic findings only.
The source media and archive were not changed.

The original reproduction's pre-metadata MP4 and its scene-specific fragments
were not retained. Its logged pre-metadata size was about 485.7 MB, while the
final file was about 60.4 MB. Offline remux fixtures show that the metadata
rewrite preserves both healthy stream coverage and an already-collapsed video
timeline; they do not reproduce that size reduction. The immediate cause of
that historical size reduction therefore remains unconfirmed. A later isolated
live test of scene 1320457 for movie 329413 showed a related upstream symptom:
205 video fragment indices (23–227) were byte-identical to fragment 17 and had
a regressing `tfdt`. Audio fragments advanced normally. The concatenated
video-only stream contained only about 34.8 seconds of timestamp coverage, and
the first muxed stage had 46 seconds of video against 453.9 seconds of audio.
The pipeline rejected it before metadata rewriting, final output promotion, or
archive success. This establishes that metadata rewriting did not cause that
live failure; whether repeated responses came from AEBN/CDN delivery or
request/representation behavior remains unresolved.

## Safe handling of a historical file

Do not treat an old archive success or a matching filename as proof of a valid
scene. The downloader preserves a corrupt existing output and fails closed; it
does not overwrite it. If a replacement is later needed, download into a new,
isolated output directory and validate that new artifact first. Keep the
historical file untouched until the replacement has been independently
verified. Do not approve removal through historical reconciliation unless the
replacement was checked under the current audio/video verification contract;
old verification records are insufficient.

No historical output was repaired, replaced, requeued, or removed as part of
this implementation.

## Controlled live smoke test

The attempted candidate was a short scene resolved from
`https://straight.aebn.com/straight/movies/329413/amersterdam-shower`, using
480p. Use an isolated scratch root such as
`modules/aebndl_module/.pytest_tmp_root/live-smoke-20261106/` with separate
`output`, `archive`, `resume`, and `diagnostics` subdirectories. Reserve up to
1 GiB of scratch space and approximately 15 minutes. Preserve downloaded
fragments and logs, and copy concatenated audio/video streams plus the
pre-metadata and post-metadata MP4s before cleanup. Compare audio/video stream
durations, packet timestamps at both ends, packet/frame counts, final file
size, and completion/archive-success behavior. The metadata request selected
scene 1320457; its download was rejected before metadata remux and finalization.
Captured artifacts and `diagnostics/live-smoke-report.json` remain in the
isolated scratch root. This is a failed live smoke, not a service validation.

## Validation status

Offline synthetic fragmented-MP4 tests cover healthy mux/remux and the
two-second-video/long-audio failure, final completion ordering, final file
size, segment failures, and invalid output rejection. Focused module test
results are recorded in the active plan status. Live validation, Windows user
environment behavior, and whether current AEBN manifests match the fixtures
remain unverified.
