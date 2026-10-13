# Status

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
