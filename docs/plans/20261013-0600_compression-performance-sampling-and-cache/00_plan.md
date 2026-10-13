# Compression performance, sampling and MangaDL cache

Branch: compression-module-mangadl-20261013-0151. Baseline: df9e0d4.
Continue the reviewed compression plan; do not replace its unresolved terminal,
reader, fidelity or production-write acceptance gates. Manual repair mapping remains
tracked separately. User authorizes implementation, scoped commits and pushes,
most important first, publishing each usable feature before starting the next.

## Evidence and constraints

- Comparison is read-only: it does not acquire the library writer lock. OS locks
  are nonblocking and fail immediately; there is no existing lock-wait mode.
- Current pool size uses the largest image in the sample, including images that
  exceed the decode allowance and will fail. This can serialize all valid jobs.
- Requested worker limit is displayed, not effective limit or active workers.
- Working allowance is512MiB, estimated48 bytes/pixel. It is conservative scheduling,
  not measured RSS or a hard OS cap. Do not blindly raise it or remove Pillow limits.
- WebP effort6 may spend substantial time in native encoding. Perceptual mode tests
  six quality levels; AUTO may repeat multiple encoders. These need measured phase
  timings, not assumptions from low aggregate CPU or compressed file size.
- First Ctrl+C currently waits silently for executor shutdown. Native calls cannot
  be safely interrupted mid-call by Python threads; no forced process exit during
  image publication. Cancellation must stop future work and explain active work.
- Source JPEG trials showed lossless candidates larger than originals. Preserve
  distinction between encoded candidates, retained size, failures and true savings.

## P1 - stopping and lock feedback (first usable checkpoint)

Cooperative cancellation shared by both CLIs: stop new jobs immediately, cancel
queued jobs, check between candidate encodes/verification/publication, show a
stopping state and active count, cleanly return130. Hold write ownership until
workers finish. Never bypass verification/journal recovery or delete lock files.
Native encode already in progress can delay stop until it returns; document this.
Lock errors identify exact lock and conflicting operation and explicitly say
"not waiting". No invented wait indicator or implicit retry policy.
Tests: cancellation between quality trials, no subsequent jobs/publish, ownership
release, CLI exit130, dashboard cleanup, existing transaction regressions.

## P2 - diagnosis and truthful worker UI

Add requested/effective/active workers, queued/completed counts, active image names,
dimensions/estimated memory and limiter reasons. Stage UI and JSON must share
structured events; stderr progress must not contaminate JSON stdout.
Measure decode, encode, verification, similarity, cache lookup and publication,
plus scheduling wait where real. Codec/metric instrumentation must not double-count
nested AUTO/perceptual trials. Show bounded slow-image diagnostics and aggregate
phase timings; no per-pixel or high-frequency logging overhead. Document actual
limits, timings and unavailable counters. Narrow comparison output should switch
to fewer columns/stacked details, not truncate every field into meaningless cells.
Tests: known fake phase durations, active counters with concurrent jobs, resize,
NO_COLOR, redirects, JSON, cancellation and failures.

## P3 - memory-aware scheduling

Preflight unsupported/oversized images and keep their explicit report-only failures
out of the worker-cap calculation. Schedule eligible images using per-job memory
reservations and bounded futures so small jobs can overlap without exceeding the
configured aggregate allowance. Do not starve large eligible jobs.
Expose a short/long memory-budget option only after conservative defaults and upper
bounds are defined. Distinguish per-image decode safety from concurrency allowance;
increasing concurrency allowance alone must not disable pixel/format protections.
Benchmark bounded user-image read-only trials and deterministic fake workloads.
Validate actual speed/RSS before changing defaults; no broad production writes.

## P4 - inventory and representative estimates

Show counts, total bytes, count share and byte share by actual image format and
file extension (do not conflate mislabeled extensions), with unreadable/skipped
inventory counts. Use cache for unchanged metadata, enumerate membership afresh.
Add percentage sampling with short/long flag, mutually exclusive with -s count.
Sampling is read-only for estimates; do not let a percentage projection imply a
whole-library apply. Deterministic, proportional count allocation within format/
size/tall-image strata, minimum coverage when sample size permits. Use known
population bytes per stratum to weight measured retained-size ratios. Do not
simply scale a sample-wide percent, especially with heterogeneous sizes.
Comparison adds projected whole-target saved bytes and percentage, measured sample
size, population coverage and uncertainty. Failed/unrepresented strata are not zero
savings: incomplete projection must be labeled partial/N/A. Separate sample errors
from inventory errors. No guaranteed accuracy or fabricated confidence interval;
optional uncertainty methods need defensible assumptions and tests.
Tests: imbalanced types/sizes, small percentages, rounding, failed strata, changed
membership, same-count/different-bytes distributions, repeated deterministic samples.

## P5 - automatic MangaDL cache

Per-library cache outside image tree, scoped by resolved library identity. Interactive
startup shows path and created/updated time, asks y/n whether to reuse. "No" bypasses
prior entries for the current run and writes fresh results without deleting unrelated
files. Source/settings/runtime fingerprints always validate entries even after "yes".
Explicit short/long policy ask/use/refresh/off for unattended/JSON runs; never prompt
when stdin is not interactive. Conservative noninteractive ask policy does not reuse
unapproved persistent results. Preserve explicit -K paths and standalone behavior.
Clearly state analysis writes only opted-in/automatic cache, never source images,
manifests, journals or archives. Fail readable on cache errors; define safe fallback.
Cache hits must not masquerade as new encoder throughput or fidelity checks.
Tests: y/n, first use, no terminal, JSON, cache disabled, root selection, timestamps,
changed sources/settings, pending recovery and no image-tree mutations.

## P6 - MangaDL-specific integrity and acceptance

Exact URL/gallery selections and source associations remain authoritative; no fuzzy
matching. Preserve page stems/chapter paths, covers, manifest identities and archive
semantics. Report incomplete/corrupt/unsupported galleries without treating compression
as repair. Count source associations and gallery-level before/after coverage.
Cover/partial/control exclusions, linked paths, active repair/download protection,
source identity conflicts and reader-supported target formats get focused fixtures.
Complete real Windows terminal and isolated reader acceptance, then consider production
write readiness. Live acceptance needs explicit scoped authority; no merge authorized.

## Delivery discipline

For each P stage: implement smallest usable slice, focused tests plus relevant full
suite, sync module versions/help/docs, refresh editable installs, update STATUS and
checklist, stage explicit paths, commit, push, confirm synced checkout. Failure leaves
stage open with evidence. Never publish partial cancellation hooks as completed work.
Do not start next feature with uncommitted changes from the previous usable checkpoint.
Docs freshness baseline20 for compresser/MangaDL (one current continuation); termdash0.
