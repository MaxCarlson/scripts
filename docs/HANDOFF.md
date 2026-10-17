# Scripts Repository Handoff

I2d2 compresser0.23.0/MangaDL1.49.0 indexes `(path_hash, strategy_hash)` metadata in
`AnalysisCache` (`trial_index`) to classify cache misses and `invalidation_causes`
into `never_measured`, `source_changed`, `settings_changed`, `runtime_changed`,
`evicted`, `refresh_policy`, and `invalid_record`. 141 compression (1 skip)/307 MangaDL/55 help pass.

I3b compresser0.22.0/MangaDL1.48.0 adds rare-format/top-decile-large/tall-WebP
coverage-gap diagnostics, pilot-informed variance & runtime sample-size advisor
(`advise_sample_size`), two-stage Bonferroni-adjusted 95% intervals, disjoint
`confirmation_sample()`, and repeated-sampling unbiasedness/coverage simulations.
140 compression (1 skip)/307 MangaDL/55 help pass.

cross_platform0.7.0/compresser0.21.0/MangaDL1.47.0 adds reusable per-folder read/write
locking (`cross_platform.locks`) with PID+create_time verification, `mangadl lock -s|-u -d TARGET [-j]`,
and live in-place `InventoryProgress` (`termdash.live.LiveBlock` on `stderr`) for
inventory/header scans. 6 lock/137 compression (1 skip)/307 MangaDL/55 help pass.

Task 6 compresser0.20.1/MangaDL1.46.2 avoids population-wide Path.resolve() during
snapshot sampling and refuses noncanonical '..' metadata paths. 136 compression
(1 skip)/306 MangaDL/55 help pass.

MangaDL1.46.1 validates shared compression mode before acquiring writer ownership;
rejected trust/write combination leaves target unchanged.306 MangaDL/55 help pass.
Inventory footer010bc54 pushed. Background live index still needs final stats posted.

Inventory stats0.20.0/1.46.0: readable footer for both CLIs/depths; JSON redirects
preserved, explicit -J clean.134 compression/305 MangaDL/55 help pass,1 privilege
skip. Snapshot1689ffb pushed. User-authorized background header index in B:\Hent\
hent1imageperpage: E:\Temp\mangadl-library-inventory.sqlite3 and timestamped JSON;
paste final statistics to user when complete. Broader plan not complete.

I1b2 compresser0.19.0/MangaDL1.45.0: -U trust explicitly reuses complete header
selection without walks, with selected-file validation and old-population warnings.
128 compression/303 MangaDL/55 help passed;1 symlinkprivilege skip. No production
run. Next user-requested inventory stats summary; broader plan stays open.

Current0.18.0/1.44.0 cache dates/lookup diagnostics checkpoint follows pushed573aa11
fast filesystem inventory.113 compression/302 MangaDL/55 help pass. Same feature
branch, no production library changes. Remaining plan work is not marked complete.

I1b1 current checkpoint: compresser0.17.0/MangaDL1.43.0 on existing compression
feature branch. -l -D files provides filesystem-only extension/size inventory,
clearly unverified and persisted separately.109 compression/302 MangaDL/55 help
pass; default verified-header compression unchanged. Exact -u filters are rejected
in this first fast slice; direct gallery targeting works. Trusted snapshots,
advisor, scratch and reader acceptance remain open; no production library run.

Latest I5b: compresser0.16.0/MangaDL1.42.0 compares lossless plus multiple lossy
qualities using -b -Q90 80 (space between flag and values recommended), sharing the
sample/inventory/lossless baseline/cache.105 compression/19 integration/55 help pass.
Preview I5a df3535f pushed; remaining plan stages are still open. No production runs.

Latest visual preview checkpoint: compresser0.15.0/MangaDL1.41.0 on existing
compression-inventory-and-analysis-20261016. -O external run directory,-n base
image count,-Q qualities produce originals/lossless/lossy candidates with manifest.
103 compression/18 focused MangaDL/55 help pass; no production images changed.
I5a added to existing official continuation; remaining advisor/scratch/reader gates
are not complete. User asks continued per-feature tested commits/pushes.

Current compression continuation branch: compression-inventory-and-analysis-20261016.
User requested commit existing work before branching, then test/commit/push each
major feature. I1a83b6735, I2a7e0e8a9, I2bd097138, I2c1f51b92 published on feature
branch, not main. I3a stable expanding samples tested as0.14.0/1.40.0,98 compression/
full MangaDL/55 help pass, installs refreshed. Persistent inventory and automatic
trial caching ready; advisor/fast snapshots/SSD scratch/multi-quality remain open.

2026-10-16 inventory continuation: official existing compression plan reconciled;
approved I1-I5 continuation includes opt-in SSD scratch at I4. I1a implemented as
compresser0.10.0/MangaDL1.38.0: -l inventory-only, -I durable external inventory,
automatic header reuse and atomic completed scans, gallery discovery reuse.
90 compression/17 integration/55 help tests pass; local installs refreshed. User
requests current checkpoint commit followed by a new branch and per-feature tested
commits/pushes. No production scan or image writes. Next I2 cache improvements.

Last updated: 2026-10-16

## Compression merge checkpoint

2026-10-16 follow-up: compresser0.9.0/MangaDL1.37.0 implement combined -b comparison,
gallery-weighted random -s/-P sampling with -z seed, coverage/inventory and weighted
projections/approximate uncertainty in text/JSON. Explicit -K persists trials during
analysis (tested from a fresh reader before batch completion). Full compresser87,
full MangaDL suite, help55 and final report subset6 pass; local editable installs
refreshed. No production image writes or broad library benchmark. Automatic cache
policy and reader acceptance remain open; see active P4/P5 plan.

- User authorized merging `compression-module-mangadl-20261013-0151` into `main` after verification. Fresh origin refs, ancestry, patch equivalence, tracked files, and CLI checks confirmed it was not already integrated. Merge applied without conflicts, preserving newer main commits.
- Validation: compresser 83 tests passed; full MangaDL suite passed; termdash live/table/horizontal-bar 17 tests passed; scripts_help 55 tests passed. File-publication tests required running outside the sandbox because hardlinks were denied there. Both compression CLI smoke checks passed. Source-path staged whitespace check passed; imported historical test artifacts and some docs retain existing whitespace warnings.
- No production images changed. `-s N` is still a global format/size-stratified sample, not guaranteed per-gallery coverage. Pending user requests: per-gallery byte-weighted sampling and full lossless/lossy comparison at selected quality. Broader remaining work: `docs/plans/20261013-0600_compression-performance-sampling-and-cache/`.
- Earlier checkpoint notes below are historical; the current branch is `main`.

## Current cross-repository work

Current P3 checkpoint: compresser0.8.0/MangaDL1.36.0. Per-job memory reservations,
preflight exclusions, bounded fairness and -B aggregate budget.83/15/55 tests pass,
setup refreshed. Read-only native threading test~1.9x speedup for two eligible jobs
when1024MiB permits overlap; default512MiB and per-image safety unchanged.
Publish before P4 inventory/projections and P5 automatic-cache features.

Current P2 checkpoint: compresser0.7.0/MangaDL1.35.0, exclusive phase timings and
readable narrow reports, compresser75/integration15 pass. Bounded screenshot-image
read-only benchmark:45.6s wall/45.5s CPU,45.3s encoding; effort0 takes1.8s but
produces larger output. Native encoding + conservative one-worker cap explain
low aggregate CPU. No budget/scheduler change. Publish checkpoint, then P3.

Current checkpoint: P2 worker-visibility slice, compresser0.6.0/MangaDL1.34.0.
Full compression71 and integration/ownership15 pass; setup refreshed. Plan remains
docs/plans/20261013-0600_compression-performance-sampling-and-cache/; requested/
effective/active workers and image details are usable. No scheduler/budget change.
Next: publish slice, then phase timings/narrow reports, memory-aware scheduling,
sampling projections and automatic cache, committing each usable feature.

Active follow-up: docs/plans/20261013-0600_compression-performance-sampling-and-cache/.
Plan pushed c76df28; P1 stopping/lock feedback implemented, compresser0.5.0 and
MangaDL1.33.0, compresser69 and MangaDL compression/ownership15 tests pass.
Native-call cancellation is cooperative; no global budget change. Next: publish P1,
then measured phase/actual worker diagnostics before changing scheduling/budgets.
Percent sampling, population estimates and automatic MangaDL cache are planned,
not implemented. Publish each usable feature before starting the next.

Latest UI continuation: compresser0.4.0/MangaDL1.32.0; continuous comparison stages
and whole-run progress, retained-vs-encoded sizes/failure reasons. Full compresser66,
MangaDL compression integration10 pass. No production compression; manual terminal/
reader acceptance and A3/A4 remain pending. Current module handoffs/STATUS own details.

- Branch: `compression-module-mangadl-20261013-0151`
- Plan: `docs/plans/20261013-0151_compression-module-and-mangadl-integration/`
- Scope: Standalone image compression module (`modules/compresser`), `mangadl compress` subcommand, termdash table and horizontal comparison bar extensions, perceptual SSIM optimization, crash recovery journaling, and library audit preservation.
- State: S5/S6 safety/analysis and audit A1/A2 pushed as7181e4f; nested-gallery/MangaDL guard pushed as2f0dd8b. Current shared standalone guard checkpoint: compresser0.3.1/MangaDL1.31.1, compresser63/MangaDL296 full tests. Production-write acceptance remains gated by terminal/reader checks; external tools must not write concurrently.
- Next action: S7/S8 terminal/reader acceptance, then A3/A4 manual mapped repairs. No merge/live compression. Audit follow-up lives at `modules/mangadl/docs/plans/20261013-0300_audit-ux-and-manual-folder-repair/`.

This pointer describes the current branch. Earlier plans may still have their own validation or acceptance work; consult their `STATUS.md` and Git evidence when a task targets them. Do not infer that the newest plan supersedes another plan's incomplete acceptance checks.

## Previous cross-repository plans

- `docs/plans/20261012-2039_codex-agent-instructions/`
- `docs/plans/20261009-0349_kavita-module-mangadl-collections/`
- `docs/plans/20261009-0941_scheduler-log-explorer-and-shared-logging/`
- `docs/plans/20260926-0107_missing-only-bootstrap/`
- `docs/plans/20260729-0900_validation-evidence-context-history/`

Module-owned work has its own handoff under `modules/<module>/docs/` when present.
