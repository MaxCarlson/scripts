# mangadl Immediate Project Handoff

I2d1 1.44.0/compresser0.18.0: cache dates/lookup diagnostics at startup and in text/
JSON summaries. Probe counts not image counts; legacy age not fabricated.113
compression/302 MangaDL/55 help pass. Remaining trust/advisor/scratch/reader gates open.

I1b1 1.43.0/compresser0.17.0: -l -D files shared fast extension/size inventory,
preserving manga ownership/exclusions without image opens. Explicit unverified
totals and separate snapshots. First slice rejects -u (direct gallery targets work).
109 compression/302 MangaDL pass; default header-based compression unchanged.

I5b1.42.0/compresser0.16.0: `-b -Q 90 80` quality sweeps,
shared baseline/sample/inventory/cache.105 compression/19 integration pass. Preview
via -O remains external and serial; no whole-plan completion implied.

I5a1.41.0/compresser0.15.0: shared preview -O/-n/-Q, exact gallery filters and nested
page/cover exclusions preserved. External candidate copies only, serial; full-res
manifest/checksums/failure/cancellation evidence.103 compression/18 integration pass.

Current1.40.0/compresser0.14.0 on compression-inventory-and-analysis-20261016.
Inventory -l/-I, automatic trial -k use/refresh/off, compatible AUTO reuse and stable
growing sample plans implemented.98 compression/full MangaDL/55 help pass; local
installs refreshed. Check authoritative continuation STATUS for remaining stages.

I1a:1.38.0/compresser0.10.0 adds -l inventory-only/-I external inventory SQLite.
Normal compression auto-refreshes inventory; nested pages preserve owning gallery,
covers remain excluded, and discovery results are reused instead of rescanning
each discovered gallery. JSON includes per-gallery totals/shares/extension types
and scan-scope unreadable diagnostics. No production run or source-image writes.

2026-10-16:1.37.0/compresser0.9.0: -b compares full lossless/lossy sets using -q;
-P percentage and -z seed sample across all discovered galleries, preserving
nested-chapter ownership. Counts and bytes jointly weight quotas; projections
correct unequal sampling rates. Reports expose coverage/uncertainty and persistent
-K cache hits. Sampled writes rejected. User library untouched; commands in README.

Current P3: MangaDL1.36.0/compresser0.8.0. Shared per-job memory reservations,
preflight exclusions and aggregate -B allowance64..4096MiB, default512 unchanged.
Per-image decode limit still512MiB. Full83 compression,15 integration,55 help pass.
Actual read-only two-image test shows native threading gain3.735s->1.968s when
budget permits two jobs. No production writes. Publish checkpoint before P4/P5.

Current P2 phase slice: MangaDL1.35.0/compresser0.7.0. Shared active phase labels,
exclusive aggregate phase timings in summary/JSON, narrow stacked comparisons.
Compression75 and integration15 tests pass; setup refreshed. Source benchmark
confirmed native WebP effort6 encoding dominates, about one core, not disk/lock.
Scheduler/budget unchanged; next publish checkpoint then P3 reservations/preflight.

Latest P2 worker-visibility slice: MangaDL1.34.0 / compresser0.6.0. Shared UI and
JSON expose requested/effective/active workers, limiter and active image details.
Full compression71 and integration/ownership15 tests pass. Scheduler/memory budget
unchanged; phase timers, readable narrow summaries and automatic cache are pending.

Active performance/cache continuation: MangaDL1.33.0 / compresser0.5.0.
Cooperative cancellation/STOPPING and exit130 implemented, lock errors explicitly
fail fast. Plan at ../../../docs/plans/20261013-0600_compression-performance-sampling-and-cache/;
plan pushed c76df28. Actual worker/phase diagnosis, memory-aware scheduler, percentage
sampling/projections, automatic cache prompt and integrity acceptance remain planned.

Current compression UI continuation: MangaDL1.32.0 / compresser0.4.0.
Comparison shares one staged dashboard and continuous overall timer/counts;
retained-size report distinguishes rejected larger candidates and encoder failures.
Comparison JSON includes candidate/original bytes and grouped errors. Full
compresser66/MangaDL compression integration10 pass. Terminal/reader and manual
mapping acceptance remain pending; source trials only read user images.

## Current compression continuation — 2026-10-13

Branch `compression-module-mangadl-20261013-0151`. Reviewed plans pushed as
`f1baeab`; S5/S6 and audit A1/A2 checkpoint pushed as7181e4f. Continuation source,
shim and registry synchronized at1.31.1 (compresser0.3.1). Nested chapter pages
and a whole-operation OS guard now coordinate run/page repair/batch repair/compression.
Same-thread reentrancy supports normal repair workers; separate-process contention
and process-death release are tested. Consistent established library roots required;
standalone compresser engine/CLI/recovery now share ownership. External tools
that ignore the lock must not run concurrently.
Compression defaults lossless and JSON suppresses progress stdout; explicit
lossy/perceptual writes require -L. Production compression not accepted.
Audit A1/A2 now implement bottom summaries, visible inferred gaps even for
ambiguous sources, explicit source fields (not cover/artist links), association
inventories with -x, and shared3-row URL/folder progress. A3/A4 manual worksheet
and mapped repair are still planned. Full290 MangaDL tests pass; compresser61,
termdash75/1 skipped, scripts-help55, dispatcher, Ruff/compile/help/version and
installed read-only CLI acceptance pass. Continuation full MangaDL296/compresser63
pass. Terminal/reader gates remain; manual mapping has not started.

## Current branch planning handoff — 2026-10-12

Branch: `codex/mangadl-generalized-audit-repair`.

The active plan is [generalized audit and batch repair](plans/20261012-2300_generalized-audit-and-batch-repair/00_implementation-plan.md).
MangaDL 1.28.0 accepts repeatable URL files/globs plus top-level `url*.txt`
directory discovery, records cross-file duplicate provenance, writes a
versioned audit report automatically with input-based names and numbered
collisions, prints per-URL page findings and separate duplicate/invalid counts,
and builds a visible batch repair plan directly from
that report. `repair -p` is optional output only; `repair -r REPORT` always
creates and displays the plan. Apply remains token-guarded and limited to
proven individual nhentai page repair plus normal downloads for wholly missing
non-collection galleries. Successful actions re-audit and backfill exact source
identity. Unsupported or ambiguous items remain report-only. Repository
validation passed (268 MangaDL tests and 42 focused scripts-help tests). The
user confirmed the live audit findings and authorized committing this usable
1.26.0 state. Live progress and colored summaries are deferred at the user's
request. Live repair acceptance is pending; no live library repair, push, or
merge has been performed.

The first live missing-only repair failed before downloads because its manifest
directory was not created. Archive backups and current archive were confirmed
identical. The 1.26.1 fix creates a short repair directory unconditionally and
writes its manifest before archive-key deletion. Focused repair/CLI regression
validation passed (44 tests); retry of the live apply remains pending.

The live retry exposed placeholder `None` archive keys in print-only
enumeration. Version 1.26.2 generates and validates distinct real keys, and the
agent's authorized repair restored all 260 missing pages in galleries 633374,
268015, and 592786. Independent destination checks found 192/192, 160/160, and
76/76 valid pages, respectively. See the active plan's LIVE_REPAIR.md.
The user now authorizes commit/push after the repair fix, then summary/color
improvements, then shared normal downloader UI and available-worker scheduling.

The live repair fix was pushed as `55d02b2`. Summary/color changes now use
readable wrapped fields, terminal-only ANSI status colors, clean JSON/plain
redirected output, and termdash audit metadata/image progress. Validation:
271 MangaDL tests passed. Next is the shared normal repair worker pool/UI.

Completed on 2026-10-13: summary stage pushed as `a49c655`; repair apply now
uses one normal manager queue per destination, per-URL exact page ranges,
normal dashboard and worker controls, and `-w/-m/-N/-L`. One batch lock/backup
protects the archive. Production galleries remain complete. Isolated live UI
acceptance dispatched three workers in one run and verified nine downloaded
pages; available-worker reassignment and failed scratch resume are covered by
integration tests. Final validation: 276 MangaDL tests, Ruff, compilation,
CLI help/version, and editable install at 1.28.0. No merge is authorized.

---

## Prior branch planning handoff — 2026-10-09

Branch: `codex/kavita-module-mangadl-collections-20261009-0349`.

The active multi-feature plan is
[library identity, audit, and Kavita operations](plans/20261009-1204_library-identity-audit-and-kavita-operations/00_implementation-plan.md).
The URL-file audit stages 1–3 were implemented in `b58b308`; the Kavita library
and download-time collection integration were implemented in `0ed97c5`. The
feature branch, including the subsequent shared identity, audit, assignment,
and safe repair workflows, was merged into main on 2026-10-12. Paradise's
recorded audit result is 192 expected pages, pages 1–158 missing, and page 175
corrupt; no repair or archive mutation has been performed.

Implementation stages 1–6 of the active plan are present in the working tree:
shared source identity/manifests, folder-only and URL-file audit, historical
Kavita file/name/pattern assignment, and exact-page nhentai repair. URL-file
audit and `kavita assign-file` opportunistically backfill missing source
manifests only for unique, populated matches, with a `--no-index-backfill`
opt-out. SSD destination OR SSD scratch uses the aggregate logical-CPU budget
without an extra fixed cap; when neither is SSD, the cap is four. On 2026-10-09,
the dispatcher passed MangaDL (254 tests) and Kavita (16 tests), including
compile, Ruff, and MangaDL CLI help. Live audit/repair preview, TUI, and Kavita
server acceptance remain unverified. The branch was merged into main on 2026-10-12;
no live repair or Kavita collection write has been performed.

---

Historical handoff snapshot: branch `main` (the following run-specific notes
predate the current feature branch and should not be read as its current Git
state).

Current version: `mangadl 1.20.0`.

Current task: graceful interactive shutdown and runtime worker scaling cleanup.
The active plan is
[20261009-0325 graceful quit and worker scaling](plans/20261009-0325_graceful-quit-and-worker-scaling/00_implementation-plan.md).
Read-only inspection of the first real scratch run confirmed that the three
cleaned B: partial URLs were downloaded again rather than skipped. The run
finished successfully with 33 successes and 5 archive skips. Graceful quit,
runtime worker controls, and SSD-aware worker defaults are implemented and
validated; see the active plan for current verification.

Previous task: opt-in `-S/--scratch` staging for payloads and active control
files, with destination-aware duplicate checks and guarded serialized
promotion to the B: library. The user confirmed B: is a mirrored
SATA-HDD Storage Spaces volume and E: is a separate NVMe SSD. The four-worker
ceiling is unchanged. Unit tests cover promotion failure and resume, but no
production B:/E: download has been run; bounded manual validation is the next
gate. Archive, state, and logs retain B: as canonical paths but are active on
E: during a scratch run and sync at the end. New archive rows remain on E:
while scratch partials exist. No commit, push, or merge approval was given
for this task.

The current B: destination has eight existing `_partial` owners (read-only
preview on 2026-09-26). Scratch mode fails closed on that library until they
are resolved; no migration or cleanup was performed.

Active scratch records:

- [Plan](plans/20260926-1224_ssd-scratch-staging/00_implementation-plan.md)
- [Status](plans/20260926-1224_ssd-scratch-staging/STATUS.md)
- [Checklist](plans/20260926-1224_ssd-scratch-staging/checklist.md)

The remaining notes below describe prior partial-safety and managed-auth
feature work. Their old branch/test counts are historical, not the state of
this branch.

Current cross-module work: [Kavita collection assignment plan](../../../docs/plans/20261009-0349_kavita-module-mangadl-collections/00_implementation-plan.md).

The Kavita collection-assignment work is underway on
`codex/kavita-module-mangadl-collections-20261009-0349`. It adds a reusable
`modules/kavita` package and preserves the existing `-c/--config` behavior;
the collection option is `-M/--collections`. Assignment mutations require
`-E/--apply-kavita`, while pending assignments can be previewed and later
applied with `mangadl kavita reconcile`.

Active planning records:

- [Partial safety and merge-readiness plan](plans/20260921-0943_partial-safety-and-merge-readiness/00_implementation-plan.md)
- [Partial safety status](plans/20260921-0943_partial-safety-and-merge-readiness/STATUS.md)
- [Partial safety checklist](plans/20260921-0943_partial-safety-and-merge-readiness/checklist.md)
- [Managed gallery-dl auth plan](plans/20260825-0540_gallery-dl-managed-auth/00_implementation-plan.md)
- [Managed gallery-dl auth stage 1](plans/20260825-0540_gallery-dl-managed-auth/01_profile-and-ua-foundation__planned.md)
- [Managed gallery-dl auth stage 2](plans/20260825-0540_gallery-dl-managed-auth/02_browser-refresh-and-probe__implemented.md)
- [Managed gallery-dl auth stage 3](plans/20260825-0540_gallery-dl-managed-auth/03_managed-runtime-retry__in-progress.md)
- [Managed gallery-dl auth stage 4](plans/20260825-0540_gallery-dl-managed-auth/04_target-catalog-and-progress__planned.md)
- [Managed gallery-dl auth stage 5](plans/20260825-0540_gallery-dl-managed-auth/05_gallery-dl-output-integrity__planned.md)
- [Managed gallery-dl auth stage 6](plans/20260825-0540_gallery-dl-managed-auth/06_destination-root-series-layout__planned.md)
- [Managed gallery-dl auth stage 7](plans/20260825-0540_gallery-dl-managed-auth/07_input-wide-auth-preflight__planned.md)
- [Managed gallery-dl auth status](plans/20260825-0540_gallery-dl-managed-auth/STATUS.md)
- [Managed gallery-dl auth checklist](plans/20260825-0540_gallery-dl-managed-auth/checklist.md)

Historical planning records:

- [Manga18FX plan](plans/20260729-1307_manga18fx-backend/00_implementation-plan.md)
- [Manga18FX status](plans/20260729-1307_manga18fx-backend/STATUS.md)
- [Manga18FX checklist](plans/20260729-1307_manga18fx-backend/checklist.md)
- [Manga18FX handoff](plans/20260729-1307_manga18fx-backend/HANDOFF.md)
- [CLI/optimizer/archive plan](plans/20260729-1630_cli-optimizer-archive/PLAN.md)
- [CLI/optimizer/archive status](plans/20260729-1630_cli-optimizer-archive/STATUS.md)

Implemented scope includes the native Manga18FX backend; destination-aware resume; bounded inner image concurrency; safe/staggered outer workers; runtime concurrency controls; cumulative native progress; aligned two-row dashboard output; concise `run`, `optimize`, `benchmark`, and nested `config` command surfaces; online adaptive optimization and systematic benchmarking; and an interactive archive browser.

The user confirmed live Manga18FX downloads and approximately 15-17 MiB/s aggregate throughput with four outer workers. A fifth outer worker saturates the current destination disk and remains outside the safe default ceiling.

The pre-existing Manga18FX local validation notes remain historical. Managed
gallery-dl authentication S1-S5 is implemented and validated on this feature
branch. S6 removes gallery-dl's category wrapper during successful merge,
places control paths under the destination by default, provides human-readable
dry-run output, and coordinates auth refresh without blocking the dashboard.
The bounded S6 live layout and TUI acceptance now passes. S7 remains planned
behind its stricter complete-series and current multi-worker gates.

Version 1.16 added a default refusal for broad gallery-dl collection URLs with
an explicit `-G/--allow-collection` opt-in. New partials contain versioned
ownership metadata and exact archive-key/path manifests. `mangadl partials
clean` previews archive-aware cleanup and applies it only with `--apply`, with
archive deletion ordered before filesystem deletion. Legacy partials require
URL recovery or an explicit URL override for archive reconciliation, or an
explicit files-only cleanup. The dashboard's
raw-log view now reads a bounded file suffix rather than rereading the entire
log every refresh, addressing the concrete full-UI freeze path found in the
September 21 run.

`mangadl partials clean` now owns its interactive TermDash tree rather than
delegating deletion to `file_utils`. With no explicit target it supports
expand/collapse, hierarchical sorting, URL/ownership details, and multi-select
of top-level partial owners. Explicit repeatable `-t` targets remain available.

For legacy owners without manifests, the command can recover URLs from local
state (or validated URL overrides), enumerate exact archive keys through a
no-download gallery-dl metadata pass, and delete matching rows from an explicit
archive before deleting files. It refuses active/recently changing trees and
rechecks the preview fingerprint immediately before archive mutation.

The live `fc7c3b753cc0` investigation originally found gallery-dl PIDs
30028/14992 still running the broad collection after the manager had been
interrupted. Those processes have since stopped. A final read-only files-only
preview reported 41,957 files and 17,073,852,121 bytes; no `B:` archive, state,
or partial data was changed. Version 1.17 can now recover this legacy owner's
URL and reconstruct exact archive keys when an explicit archive is supplied,
so files-only cleanup is no longer the only available path.

The 1.17 merge-readiness baseline is green at 182 tests plus compile and Ruff.
Live acceptance on 2026-09-21 downloaded chapter 0 as 42 distinct images
(1,300,372 bytes) directly under `Like No Other\c000`, with no category
wrapper. A second live TTY run proved activity-log, raw-log, and worker-view
switching remained responsive while downloading. The repository `mangadl`
dispatcher target also passes at 182 tests. Staging, commit,
push, continued integration work, and the final merge were approved on
2026-09-21. A current four-URL/four-worker acceptance also completed 4/4
chapters (702 images, 22,438,146 bytes) without a retry. The user explicitly
deferred S7 and its potentially large complete-series gate to a follow-up
branch.
