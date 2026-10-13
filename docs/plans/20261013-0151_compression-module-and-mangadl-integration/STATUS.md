# Reviewed compression status

Branch: compression-module-mangadl-20261013-0151.
Plans committed/pushed as f1baeab; verified source checkpoint pushed as 7181e4f.
Nested-gallery/operation-guard checkpoint pushed as2f0dd8b.
Continuation: MangaDL1.31.1 / compresser0.3.1, shared standalone ownership implemented.
Authoritative: [reviewed plan](05_reviewed-plan.md), [findings](REVIEW.md).

## Implemented and fixture-verified

S5: strict analysis purity; verified codec dispatch and alpha/metadata guards;
bounded decode/futures/metric memory; OS directory ownership; durable source/output
fingerprinted transactions; explicit token-bound recovery CLI; actual child-process
crash and competing-owner tests. Legacy/malformed/changed records remain refused.

S6: PNG, measured auto candidates, explicit algorithm/effort, persistent separate
inventory/trial cache and invalidation, stratified samples and coverage-aware
projections. RGB and native-detail patches guard perceptual candidates. Quality
settings and projections are not percentage-loss or visual guarantees.

S7 implemented portions: shared termdash LiveBlock, bounded Unicode tables,
stderr/plain/NO_COLOR output, gallery/overall progress, rolling ETA, exact source
URL/folder selection, cover/partial/control exclusions and active repair/run
refusal. Nested chapter pages now included beneath selected galleries; an explicit
nested-only gallery requires its valid source manifest, otherwise first-level
folders define gallery ownership. Whole-operation OS ownership coordinates MangaDL
run/page repair/batch repair/compression, with same-thread repair-manager reentrancy.
Cross-process refusal and process-death release are fixture-tested. Use an established
library root consistently. Standalone batch/single-image and recovery writes now
share the same established-library ownership; batch worker lifetime and competing
processes are tested. External tools that ignore this lock must not run concurrently.
Real Windows terminal and reader acceptance remain pending. Not production-write ready.

Related A1/A2 audit work implemented: bottom summaries, concrete-defect prioritization,
ambiguous defects retained, source-confirmed vs inferred labels, read-only
association inventory even with -x, explicit source metadata fields (covers/artists
excluded), per-item three-row progress for both URL and folder modes.

## Verification

- Final full compresser61 passed, MangaDL290 passed, termdash75 passed/1 skipped,
  scripts-help55 passed. Dispatcher compresser/MangaDL targets PASS with retained history.
- Focused audit/index/CLI/compression78 passed after provenance fixes.
- Ruff/compile/help/version checks pass. Installed CLI read-only2-of4-image sample
  produced valid JSON and left all fixture hashes unchanged. Installed versions:
  compresser0.2.0, MangaDL1.30.0, termdash0.7.0.
- Prior validation history retained; don't prune tracked records on dispatcher reruns.
- No images/archive/state changed in production. Only saved report and bounded
  contentV2 metadata were read. No merge is authorized.

## Next

Current UI continuation: compresser0.4.0 / MangaDL1.32.0. One LiveBlock spans
all comparison stages; stage colors/text, aligned local/overall bars and whole-run
timer/trial counts replace full resets. Stage savings remain intentionally local.
Retained-size table exposes non-error kept counts, raw candidate totals before
retention and grouped failure reasons; JSON adds candidate/original bytes and
error_summary. Cache schema3 invalidates older trials missing candidate details.
Full compresser66 and MangaDL compression integration10 pass; Ruff/format and
help55 pass. Installed0.4.0/1.32.0 and read-only sampled lossy table verified;
redirected Unicode capture required PYTHONIOENCODING=utf-8. Actual read-only
source trials on user JPEG folder:01.jpg371797 B
->PNG937393/WebP845742;02.jpg367020->PNG906909/WebP823514. No jpegtran available.
These candidates are larger, so original retention and0% savings are correct.
Terminal/reader manual acceptance still pending; no production images modified.

Shared ownership checkpoint pushed as c78fbf8. Final documentation/help correction:
MangaDL1.31.2 clarifies that -s is a total sample across selected galleries, not
N per gallery. Compresser remains0.3.1; -s also limits write scope, so full applies
must omit it. Root README version and setup are refreshed.

Previous continuation verification: full MangaDL296 and compresser61 pass separately;
focused integration/CLI/ownership52 pass; Ruff passes. Combined collection failed
because both packages have cli_test.py; separate suites are authoritative.

Current checkpoint: compresser63 and MangaDL296 full suites; shared ownership
fixtures cover standalone CLI, batch, single-image, recovery, callback lifetime,
same-thread repair reentrancy and process-death release. Editable installs refreshed;
installed CLIs report compresser0.3.1/MangaDL1.31.1. Help registry55, Ruff and diff
whitespace checks pass. No production compression performed.

Full fixture commands (each has its own module-local temp root):
`python -m pytest modules/compresser/tests -q -o addopts= -p no:cacheprovider --basetemp modules/compresser/.pytest_tmp_root/shared-final`
`python -m pytest modules/mangadl/tests -q -o addopts= -p no:cacheprovider --basetemp modules/mangadl/.pytest_tmp_root/shared-final`
Use fresh temp root names for reruns. Normal Windows filesystem permissions were
needed for the hard-link publication fixtures; sandbox-only writes are insufficient.

Docs freshness: compresser/MangaDL20 (current behavior update), termdash0 (unchanged).
Documentation action completed here: remove stale standalone boundary claims from
README/handoffs while retaining real-terminal/reader acceptance warnings.

S7/S8 remaining terminal/reader acceptance, then
A3 stable manual source worksheet/A4 exact supported mapped repairs.
User authorized continued implementation without another planning approval.
