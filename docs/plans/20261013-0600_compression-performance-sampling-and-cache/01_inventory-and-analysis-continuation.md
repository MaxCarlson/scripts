# Approved inventory and analysis continuation

Approved in conversation 2026-10-16. Planning baseline c3db8b4 on main;
execution branch compression-inventory-and-analysis-20261016.
This extends the existing plan, not a competing roadmap. P1-P3 and seven-strategy
comparison/seeded gallery sampling already exist. Preserve their safety/tests.

## Goal and boundaries

Make repeated library analyses efficient, reproducible, and honest about coverage
and uncertainty. Work in independently usable checkpoints, updating status,
checklist, module versions, CLI help, READMEs and handoffs. Existing user authority
for scoped commits/pushes remains separate from stage completion; record actual
local/published state. No broad live benchmarks, source writes, merges, or automatic
production compression are inferred from this plan. Use isolated fixtures first.

## I1 - persistent inventory and incremental scans (first)

- Separate durable inventory from evictable trial cache, using SQLite with JSON
  export. Store root identity, policy/schema versions, scan time/status, per-file
  relative paths, sizes, timestamps, extension, known format/dimensions, gallery
  ownership, and exclusions/unreadable records. Distinguish file bytes from allocated
  filesystem space, and candidate files from verified image headers.
- Inventory-only CLI and normal compression share one implementation. Ordinary
  compression automatically creates/refreshes inventory; explicit location override
  stays outside the source tree. Never require a user to run inventory first.
- Validated refresh enumerates membership and inspects changed/new files only.
  Remove deleted records only after successful enumeration. Incomplete/interrupted
  scans must not become complete snapshots. Inventory is not an integrity audit.
- Reuse gallery discovery results instead of recursively scanning each gallery twice.
- Report per-gallery/per-extension counts, total bytes, count/byte shares and size
  distributions; separately retain detected format and scan errors. Nested chapters
  stay with their owning MangaDL gallery, and existing control/cover/partial/link
  exclusions remain authoritative.
- Deliver in slices: I1a inventory persistence + inventory-only CLI + automatic
  validated refresh; I1b single-pass MangaDL discovery and richer fast inventory.
  First slice can inspect headers; lightweight filesystem-only mode is explicit
  later and must label unverified metadata, not invent valid image counts.
- Trusted snapshot is an explicit later policy, showing age and stale-population
  warning. Validate selected files before processing; no silent trust based on age
  or directory timestamps. Inventory mismatch causes rescan or clear refusal.

Acceptance: unchanged headers reused; additions/deletions/changes refreshed;
failed/aborted scan not published as current; extension/format mismatch visible;
source mutation and path escape refused; no source images/associations modified;
inventory survives trial eviction. Focused fixtures and full compression/integration
regressions before claiming the usable slice complete.

## I2 - cache and redundant work elimination

- Separate inventory and trial retention. Reuse database connections, coordinate
  readers/writer, use bounded transactions and less frequent eviction. Consider WAL
  only for supported local storage; it does not create multiple concurrent writers.
- Completed results are immediately reusable in memory. Report pending versus
  durably persisted results if writes become buffered; clean stop flushes bounded
  work, crash recovery never treats uncommitted entries as available.
- Cache effective encoder candidates, independent of display labels. AUTO reuses
  compatible explicit trials. Include source identity, encoder options/runtime,
  fidelity/metadata policy and metric revision; never reuse incompatible trials.
- Automatic per-library trial cache with explicit use/refresh/off and existing -K
  override. Show path, timestamps, hits/misses/invalidation causes. Normal validated
  reuse can be automatic; ask only when explicitly trusting an old snapshot.
  No prompts in JSON/unattended runs. Preserve old cache until safe migration.

Acceptance: matching cold/warm results; interrupted-run reuse; active-run cache
reader sees committed results; bounded flush/eviction; changed sources/settings
invalidate; AUTO avoids duplicate encodes and matches reference output. Cached
analysis summaries alone never authorize source publication.

## I3 - progressive sampling and advisor

- Save population identity, seed, selection weights and sample plan. Stable random
  ranking and monotone quota extension preserve earlier samples when budget grows.
- Distinguish gallery/type/size coverage minimum from accuracy recommendations.
  Inventory alone cannot establish a statistically sufficient sample size.
- Pilot trials estimate variability/cost, informing further allocation for a stated
  precision/runtime budget. Correct unequal inclusion probabilities. Outcome-driven
  allocation/stopping needs a defensible estimator/interval, or an independent fixed
  confirmation sample; ordinary repeatedly inspected95% intervals are insufficient.
- Expose rare-format/large-image gaps and partial projections; never treat failures
  as zero savings or use one average sample percentage to scale all library bytes.

Acceptance: heterogeneous populations, stable extension/reuse, exact weighting,
insufficient coverage, census and failures; synthetic repeated-sampling checks for
estimator/interval behavior. Document remaining small-sample/skew limitations.

## I4 - measured scheduling and optional SSD scratch

- Bounded phase benchmark before changing pool model/default budgets. Measure scan,
  cache, decode/encode/verification/similarity, admission waits, utilization and RSS.
- Benchmark bounded parallel headers, cache-hit handling before memory admission,
  queue scaling, and threads versus processes. Retain only measured improvements;
  no promise of100% CPU, removal of image limits, or default process-pool rewrite.
- Optional short/long scratch flag: stage selected inputs only, bounded prefetch,
  owned temporary directory/manifests, copy verification and source-change checks.
  Cache identities remain original-file identities. Track copy time separately.
  Preserve stable source association paths; scratch is not persistent cache.
- Cancellation cleans only verified owned scratch artifacts, never arbitrary paths.
  Benchmark with/without scratch; do not auto-enable it. Analysis-only first; write
  support requires separate publication/recovery acceptance and must not bypass
  library ownership or verified atomic publication.

Acceptance: identical results, bounded resources, fair scheduling, cancellation,
scratch failure/full disk, source changes, cleanup/path safety; report actual gains
and regressions. Live benchmarks require explicit scoped approval.

## I5 - richer comparisons and MangaDL acceptance

### I5a - user-requested visual previews (added2026-10-16)

Small seeded base-image selection, external unique run folder, original copies and
full-resolution lossless/multiple fixed-quality lossy candidates. Accept integer
and decimal quality notation, documenting that quality is not fidelity percentage.
Keep larger candidates for inspection. Manifest source paths/checksums, settings,
actual sizes, similarity and failures; no source writes or summary-cache publication.
Preserve partial output/cancelled status. Initially serial with existing memory,
pixel, source-change, decoded-sample and metadata verification. MangaDL exclusions
and exact gallery filters remain authoritative. Multi-format UI/contact sheets and
parallel preview/scratch are follow-ups, not acceptance claims for the first slice.

Acceptance: full-res files decode, lossless pixels match, original bytes unchanged,
external output enforced, repeat runs do not overwrite, cancellation/failures explicit,
MangaDL nested pages/cover exclusions tested, JSON stdout clean.

### Remaining I5 work

- Multiple quality levels in one run; share lossless baseline/candidates/inventory.
- Show measured savings, projected totals/percent, uncertainty, failures, coverage,
  runtime, cache and scratch overhead. Recommend best savings separately from a
  practical speed/fidelity/reader-compatible trade-off, not SSIM as a visual guarantee.
- Preserve page/chapter names, source associations, covers, archives and partial
  exclusions. Compression does not repair or prove gallery completeness.
- Finish Windows terminal and isolated reader acceptance from original P6 before
  expanding production-write readiness. GPU encoding, global upfront content hashing,
  forced termination during writes and automatic memory increases are deferred.

## Documentation and delivery

Current READMEs match c3db8b4; old main plan had stale P1-P3 implementation claims.
Freshness before reconciliation: README20/100, plan60/100 for both target modules;
shared termdash unchanged. Reconcile in this checkpoint and keep each new CLI/API
slice documented/tested before moving on. No separate docs backlog is necessary.

## Task 1: I1b1 filesystem-only inventory checkpoint

Interfaces: standalone/MangaDL shared analysis arguments consume the new fast
inventory scanner; durable inventory owns a distinct file-snapshot table. Existing
header scans, preview selection, trial cache and estimators must remain unchanged.

1. Write CLI tests for `-l -D files`: literal candidate counts/bytes/extensions,
   no image opens, durable snapshot, updated membership and policy rejection.
   Expected: RED because -D is not recognized, not because of fixture problems.
2. Implement explicit filesystem depth for inventory-only mode, sharing the scanner
   between both CLIs. Enumerate image extensions without claiming verified formats;
   preserve nested-gallery ownership and cover/control/partial/link exclusions.
   First slice refuses -u filters rather than silently ignoring them. Header-based
   inventory remains the default. No trust mode or lazy compression consumption yet.
3. Persist only completed enumerations; record stat errors as unknown totals, never
   zero-byte success. Failed enumeration preserves prior completed snapshot. Keep
   fast snapshots independent of verified headers and compressed trial retention.
4. Run focused tests, full compression suite, full MangaDL suite and help registry.
   Expected: all pass. Update versions/help/docs/status, refresh installs, commit
   and push this feature branch only. Expected: clean synchronized branch.

## Task 2: I2d1 cache dates and lookup diagnostics

Interfaces: AnalysisCache supplies a JSON-safe diagnostic snapshot consumed by
both CLI report paths; optional cache metadata table remains outside trial eviction.
No encoder keys, source validation, sample selection or persistence policy changes.

1. Write failing tests for creation/last-result timestamps across cache reopen,
   unknown creation time on legacy DB, and actual lookup hit/miss/refresh counters.
   Expected: RED because diagnostic API and dates are absent.
2. Store trustworthy dates in a separate tiny metadata table. Track run lookup
   counters in memory; distinguish refresh-policy misses from no matching entry,
   without claiming to know changed-source/settings/eviction causes from opaque keys.
   Dates commit with saved trials. Never fabricate age for pretracking caches.
3. Expose dates at CLI startup and run lookup summaries in text/JSON, clearly
   separate from processed-image/cache-hit trial counts. Preserve file/policy fields.
4. Run full compression, MangaDL, help and lint/format/whitespace checks; refresh
   installs, commit/push feature branch. Expected: all green and branch synchronized.

## Task 3: I1b2 explicit trusted completed header snapshots

Interfaces: shared snapshot storage publishes a whole-selection header snapshot only
after successful discovery; both CLIs consume the same saved metadata, policy and
gallery ownership. Add -U/--inventory-policy refresh|trust, default refresh.

1. Write RED tests for refresh then trust without directory/header enumeration,
   missing/incompatible/file-only snapshots, changed selected files, nested MangaDL
   ownership, and trusted-mode write/recovery/preview/inventory-only rejection.
   Expected: missing flag/API failures, not fixture failures.
2. Atomically store root/policy/runtime/schema, completed date, metadata and source
   fingerprints separately from per-folder and file-only snapshots. Refuse partial
   or mismatched snapshots. Preserve previous snapshot on discovery failure.
3. Trust is analysis-only explicit consent: no prompt. Validate selected files and
   linked ancestors before any trial lookup, refuse changes with refresh guidance.
   Report snapshot age and stale-population caveat in text/JSON and estimates; no
   claim that unselected files or current library membership were verified.
4. Run full compression/MangaDL/help suites and lint/format/whitespace checks;
   update docs/versions/install, commit and push this feature branch only.
   Expected: all green and branch synchronized. No production library scan.

## Task 4: readable inventory statistics footer (user request2026-10-16)

Interfaces: one shared inventory report emitter for standalone/MangaDL header and
file-only modes. Existing JSON payloads stay intact; -J produces only JSON. Terminal
inventory-only runs show a concise summary, not an unbounded JSON dump. Redirected
stdout retains JSON with the human summary on stderr unless -J is specified.

1. Add RED real-CLI tests for header/file summaries and error/null-size semantics,
   empty library, per-extension totals/shares and clean explicit JSON. A terminal
   stream fixture must prove the report is concise and contains no JSON file list.
2. Reuse termdash tables/byte formatting. Report eligible gallery folders, image or
   candidate counts, bytes, header reuse/inspection, unreadable/stat errors, available
   exclusions, inventory location and extension breakdown. Do not call headers a
   decode audit or candidate bytes verified content. Never print every gallery.
3. Run full compression/MangaDL/help suites and lint/format checks, update versions/
   documentation/status/install, commit and push feature branch. Expected: all pass,
   clean synchronized branch; no production scan.

## Task 5: reject invalid analysis policies before acquiring writer ownership

Follow-up discovered while reviewing I1b2: MangaDL validates shared arguments inside
the writer guard, so rejected -U trust -w may create library controls unnecessarily.
1. Add a real CLI regression asserting rejected trusted/write mode leaves the target
   unchanged. Expected: RED because the lock/control directory is created.
2. Validate shared mode policy before entering writer ownership; do not weaken any
   valid write guard. Expected: focused test GREEN, full MangaDL/help suites GREEN.
3. Patch version/docs/status, commit/push this bounded fix; no production writes.
