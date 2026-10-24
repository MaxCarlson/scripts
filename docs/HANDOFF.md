# Scripts Repository Handoff

2026-10-24 active plan: Shared Launchers and Invocation-History Infrastructure
Location: docs/plans/20261024-0925_shared-launchers-and-invocation-history/
Branch: shared-launchers-20261024-0925
Worktree: C:\Users\mcarls\src\scripts\.worktrees\shared-launchers-20261024-0925
Status: Plan created and thoroughly designed; awaiting user review and approval before Stage 1 execution.
Scope: Cross-platform native wrappers, centralized invocation recording, SQLite WAL persistence, stable read-only consumer API in script_logging, manifest generator, and non-destructive migration tooling.

2026-10-19 active plan: MangaDL CLI TUI & Side-by-Side Image Comparison Viewer
Location: docs/plans/20261019-0358_mangadl-cli-tui-and-preview-viewer/
Branch: mangadl-cli-tui-20261019-0358
Worktree: C:\Users\mcarls\src\scripts-mangadl-cli-tui
Status: Plan created and thoroughly designed; awaiting user review and approval before Stage 1 execution.
Scope: Reusable argparse-to-termdash TUI engine (`modules/cli_tui`), real-time streaming process execution dashboard with scrollback, universal key navigation (q with confirmation, Q immediate exit, Esc back), MangaDL integration (`mangadl tui`), and Tkinter native side-by-side image comparison viewer with Left/Right quality cycling and Up/Down image cycling.

2026-10-17 current checkpoint: compresser1.4.1/MangaDL2.4.1, TermDash0.8.0.
Workspace/report plan Tasks1-5 complete and pushed on
`compression-ui-color-and-stats-20261017`. Final gates: 326 compresser/1 skipped,
317 MangaDL, 76 TermDash/1 skipped, 55 help passed; Ruff and Black120 clean.
Workspace boundary review fixes cover hardlink cache aliases, report/previews cache
collisions, report target ownership and early invalid-recovery rejection. No production
images touched. Plan: modules/compresser/docs/plans/20261017-1026_workspace-and-comparison-reports/plan.md.
Manual Windows terminal resize/color and reader quality acceptance remain; paused Plan03 P8 remains excluded.
Historical paragraphs below are not current status.

2026-10-17: Compression workspace/responsive report plan prepared at
`modules/compresser/docs/plans/20261017-1026_workspace-and-comparison-reports/plan.md`.
Source64b33d1 on `compression-ui-color-and-stats-20261017`; no product changes in
this planning step. Await written-plan review. Includes automatic Markdown inventory
and detailed operation summaries; does not resume paused Plan03 P8 or migrate source state.

Plan03 P7 implemented: compresser0.34.0/MangaDL1.60.0 uses bounded memory-admitted
source workers, serial variants/local decoded image, immutable sequenced events and
one manifest owner. Numbered outputs/order stable under reverse completion; atomic
exclusive artifact publication, source checks, cancellation/draining, in-place UI.
276 compression/1 skip,315 MangaDL/55 help pass plus final13 preview regressions;
publication gate follows. P8 canonical CLI migration and whole-branch review next.


Plan03 P6 implemented: compresser0.33.0/MangaDL1.59.0 adds opt-in -B auto,
20% available floor/cap4096MiB, clear low/unknown telemetry failures, fixed512MiB
omitted default and unchanged image/pixel caps. Existing per-job scheduler pauses
new admissions under pressure, reports waiting reason and supports cancellation;
no cross-process/OS reservation promise.269 compression/1 skip, focused pressure
checks and55 help pass; final MangaDL/task gate follows. P7 parallel previews next.


Plan03 P5 completed: compresser0.32.0/MangaDL1.58.0 caches each successfully
verified AUTO format candidate during analysis, with normalized PNG-lossless keys,
retained-original policy and candidate-only elapsed time. Preview/write paths still
require bytes; failed candidates never fabricated.249 compression/1 skip,315
MangaDL/55 help pass. P6 explicit available-memory auto policy next.


Plan03 P4 implemented: compresser0.31.0/MangaDL1.57.0, atomic versioned metadata
profiles with input-size variance proxy, explicit -s auto starter coverage, stable
uniform-within-gallery prefixes and design-weighted estimates. Numeric -s/-P stay
balanced until P8; census unchanged. File-only profiles remain unverified, no pilot.
Full gate/publication follows; P5 verified AUTO candidate reuse next.


Plan03 P3 completed: compresser0.30.0/MangaDL1.56.0, incremental pre-admission
cache probes overlap encodes; bounded preparation, source checks and cancellation
retained. Bulk validated library lookup preserves scalar legacy/diagnostic behavior.
No speculative stat pool; first dispatch keeps scalar probing. P4 metadata-only
profiles next; final gate/publication follows. No production writes or main push.


Plan03 P3a trusted validation checkpoint0.29.2/1.55.2: shared ancestor checks at
bounded batch boundaries, directory identity guard, selected file checks retained.
227 compression/1 skip,314 MangaDL/55 help pass. Task4 remains open for bounded
cache preparation/dispatch overlap and performance/cancellation tests. Main unpushed.

Plan03 P2b root-discovery reuse implemented/tested, compresser0.29.1/MangaDL1.55.1.
Directory-once fixtures preserve library/single-gallery grouping; linked/reparse
roots rejected before resolution. Task3 gate/publication then P3 trust/cache next.

Plan03 P2a inventory pipeline checkpoint: compresser0.29.0/MangaDL1.55.0, bounded
header workers, batched SQL and one run connection, short transactions and no-follow
identity checks.224 compression/1 skip,311 MangaDL/55 help pass. P2 still open for
root discovery reuse/failure review; then P3-P8. No production changes or main push.

Plan03 P1 inventory progress implemented on compression-pipeline-and-cli-20261017:
compresser0.28.0/MangaDL1.54.0. Logical galleries/chapters, completed counts,
file/overall bars, approximate ETA and render-lock safety. P2 bounded inventory
pipeline is next; no production images changed, main not pushed.

Implementation authorized2026-10-17: prior branch fast-forwarded into local main
at0672a42 (main not pushed); new branch compression-pipeline-and-cli-20261017.
[Active plan03](plans/20261013-0600_compression-performance-sampling-and-cache/03_inventory-sampling-pipeline-revision.md)
adds final P8 canonical CLI cleanup; P0 phase/counter baseline starts first. Use
Superpowers inline/TDD ledger, tested feature checkpoints; earlier pilot Task6 excluded.

2026-10-17 planning-only review: [inventory/sampling/pipeline revision](plans/20261013-0600_compression-performance-sampling-and-cache/03_inventory-sampling-pipeline-revision.md)
replaces attached threading/optimal-distribution ideas with bounded measured work,
honest progress and metadata-only sampling guidance. User explicitly does not want
the earlier Task6 pilot/confirmation machinery for this feature. No code changes,
implementation, commit/push or production operations in this review.

Inventory UI hotfix compresser0.26.4/MangaDL1.52.4: correct ProgressBar.set_total/
str and LiveBlock.close API usage; interactive-only errors were missed by redirected
tests. Real renderer + MangaDL inventory fixture regressions added. Task6 untouched.

Repair Task5 compresser0.26.3/MangaDL1.52.3: weighted complete projections,
failure-honest recommendations, warm-cache speed exclusion and actual retained
format evidence. Task4 pushed8f729e2. User says finish Task5 then STOP; do not start
Task6. Real terminal/reader acceptance still manual. No production image writes.

Repair Task4 compresser0.26.2/MangaDL1.52.2: bounded diagnostic cache RAM,
durable queried miss history and honest legacy/forgotten causes.185 compression
(1 skip)/308 MangaDL/55 help pass. Task3 pushed7600196. Next Task5 recommendations.

Repair Task3 compresser0.26.1/MangaDL1.52.1: bounded streaming scratch with pre-read
byte reservations, durable ownership/failure cleanup and fail-fast stalled stagers.
Locks ee4696a already synchronized. Next Task4 diagnostic memory bounds in02_review-repairs.
No production operations; same-volume fixture benchmark showed staging overhead,
not a claimed SSD benefit. Original source/cache identities remain unchanged.

Repair Task2: real read/write coordination in cross_platform0.8.0, compresser0.26.0,
MangaDL1.52.0. Shared local user registry serializes acquisition on overlapping trees;
full standalone operation ownership, covering write reentrancy, legacy locks retained.
161 compression pass/1 skip;129 cross_platform pass/4 skips. Follow02_review-repairs
for remaining scratch/cache/recommendation/CLI plan work; no production operations.

2026-10-17 REVIEW REPAIRS supersede prior completion claims. Active plan:
docs/plans/20261013-0600_compression-performance-sampling-and-cache/02_review-repairs.md.
Task1 corrects conditional confirmation totals/FPC and removes unsupported adaptive
interval/CLI advice. Next lock exclusion, bounded scratch/cache, weighted recommendations,
then persisted CLI confirmation plans. Same feature branch, user authorizes per-checkpoint
tests/commits/pushes. No production images changed.

I5c compresser0.25.0/MangaDL1.51.0 completes the I1-I5 compression continuation plan on
branch `compression-inventory-and-analysis-20261016`: comparison output and JSON
`recommendations` separate `maximum_savings`, `best_lossless` (pixel-exact), and
`practical_tradeoff` (speed/fidelity/reader compatibility) with an explicit fidelity
caveat, and MangaDL reader acceptance tests verify page integrity, cover/archive/sidecar
preservation, and `.mangadl-source.json` retention. 145 compression (1 skip)/308 MangaDL/55 help pass.

I4 compresser0.24.0/MangaDL1.50.0 adds pre-admission cache-hit bypass (`pre_admission_cache_hits`)
before `MemoryScheduler` reservation and opt-in analysis-only SSD scratch staging
(`-X/--scratch-dir PATH`) with ownership manifests, SHA-256 copy verification,
source-change checks, `scratch_copy` phase timing, and verified cleanup. 144 compression
(1 skip)/307 MangaDL/55 help pass.

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
