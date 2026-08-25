# Stage S5 — Generic Gallery-DL Output Integrity

## Trigger

The first full `urls20.txt` acceptance run exposed a pre-existing generic
worker defect. Mangadl forced every gallery-dl extractor to use the nhentai
fields `{gallery_id}`, `{title}`, and `{num}`. Mangakakalot does not provide
those fields, so all pages in a chapter resolved to `None.webp`; only one file
was written while gallery-dl rapidly traversed the remaining chapters.

Four simultaneous series then received HTTP 520 for chapter pages. Gallery-dl
retried each chapter five times with cumulative backoff, creating the observed
near-zero throughput. The worker could also accept a zero exit after individual
child-extractor errors and report the manga as successful.

## Confirmed Baseline

After refreshing the exact-target Chrome session, a direct gallery-dl run with
the same managed cookie file and matching User-Agent, native extractor naming,
and `--child-range 1` downloaded 42 distinct images (1,300,372 bytes) in 9.2
seconds with exit code 0.

## Scope

1. Preserve gallery-dl's native extractor naming by default. Keep any legacy
   naming override narrowly limited to the extractor for which its metadata
   contract is known and tested.
2. Add regression coverage proving Mangakakalot commands do not receive the
   incompatible generic override while nhentai compatibility remains intact.
3. Treat child-extractor HTTP errors in otherwise-zero gallery-dl output as an
   incomplete/failed job rather than successful completion.
4. Classify HTTP 520 as an HTTP failure with actionable output; do not treat it
   as a Cloudflare credential refresh signal without challenge evidence.
5. Validate one authenticated Mangakakalot URL through mangadl with multiple
   distinct output images before retrying a multi-URL run.
6. Evaluate and document a conservative same-domain concurrency policy using
   the live evidence; do not globally reduce concurrency for unrelated hosts.

## Completion Gate

- Focused worker tests cover extractor-compatible naming and zero-exit embedded
  errors.
- The full mangadl suite passes.
- A mangadl single-URL acceptance run downloads multiple uniquely named images
  using the managed profile.
- Plan/handoff documents record the exact commands and results.

## Result

Complete. Generic gallery-dl jobs now retain native extractor formats; the
legacy mangadl naming override is applied only to nhentai. Zero exits with
child-extractor errors fail safely, HTTP 520 and contextual HTTP 429 output are
retryable, and recursive partial merges no longer double-remove source
directories when concurrent jobs share a series destination.

Live checks passed:

- one direct series child: 42 images, 1,300,372 bytes, 9.2 seconds;
- one chapter through mangadl: 42 distinct images, 1,300,372 bytes, 3.7
  seconds;
- four concurrent chapters with one bounded retry: 4/4 jobs succeeded, 702
  images, 22,438,146 bytes, 11.9 seconds.

The concurrent check shows no fixed same-domain cap is necessary. Correct
naming prevents the prior chapter-request storm, the merge is race-safe, and
the existing bounded retry handles a transient image-CDN 429 without reducing
unrelated concurrency.
