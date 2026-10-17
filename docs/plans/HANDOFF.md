# Repository-Wide Plans Handoff

2026-10-17 current checkpoint: compresser1.4.1/MangaDL2.4.1, TermDash0.8.0.
Workspace/report plan Tasks1-5 complete and pushed on
`compression-ui-color-and-stats-20261017`. Final gates: 326 compresser/1 skipped,
317 MangaDL, 76 TermDash/1 skipped, 55 help passed; Ruff and Black120 clean.
Workspace boundary review fixes cover hardlink cache aliases, report/previews cache
collisions, report target ownership and early invalid-recovery rejection. No production
images touched. Plan: modules/compresser/docs/plans/20261017-1026_workspace-and-comparison-reports/plan.md.
Manual Windows terminal resize/color and reader quality acceptance remain; paused Plan03 P8 remains excluded.
Historical paragraphs below are not current status.

2026-10-17: Compression-owned workspace/report plan:
`modules/compresser/docs/plans/20261017-1026_workspace-and-comparison-reports/plan.md`.
Written plan awaits review; implementation not started. Native/inline execution
preserves existing workflow. Historical Plan03 P8 remains paused; current source64b33d1
contains later UI/memory changes. Inventory and other detailed reports are explicit deliverables.

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


Plan03 Task4/P3a validated: shared ancestor validation deduplicated, directory IDs
checked at batch boundaries; compresser0.29.2/MangaDL1.55.2. Remaining Task4:
bounded cache lookups/preparation overlap, measured stat concurrency and startup/
cancellation checks. Do not mark Task4 complete or start sampling profile work yet.

Plan03 P2b compresser0.29.1/MangaDL1.55.1 finishes root discovery reuse and reparse
admission check; task3 gate then P3 trusted-source/cache preparation. Main unpushed,
Task6 pilot CLI excluded; manual terminal/reader gates and final branch review open.

Plan03 P2a usable pipeline slice compresser0.29.0/MangaDL1.55.0 validated;
shared run connection, bounded changed-header jobs/SQL, source identity and safe
completed-selection preservation. Task3/P2 remains open for root discovery reuse
and final failure/admission review. Earlier Task6 pilot/confirmation remains excluded.

Plan03 P1 progress checkpoint: compresser0.28.0/MangaDL1.54.0, current logical
gallery files versus completed gallery work, chapter grouping, estimated ETA and
thread-safe rendering. P2 inventory pipeline next. Actual terminal acceptance is
manual; no production scans/writes and no push of main.

## Current branch

Active execution: compression-pipeline-and-cli-20261017, main fast-forwarded locally
to0672a42 and not pushed. [Plan03](20261013-0600_compression-performance-sampling-and-cache/03_inventory-sampling-pipeline-revision.md)
P0-P8 authorized2026-10-17, CLI cleanup last. Earlier pilot/confirmation Task6 excluded.
Supersedes the planning-only state below. First task: phase/counter measurements.

Reviewed proposal only: [03 inventory/sampling/pipeline revision](20261013-0600_compression-performance-sampling-and-cache/03_inventory-sampling-pipeline-revision.md).
User requests plan analysis/edits, not execution. Sampling stays inventory-metadata
based; no pilot/confirmation machinery from the earlier repair Task6. No implementation
or publication authorized by this review. Current baseline876115e on feature branch.

[02 review repairs](20261013-0600_compression-performance-sampling-and-cache/02_review-repairs.md)
Tasks1-5 are implemented/pushed, followed by interactive inventory hotfix876115e.
Earlier repair Task6 remains unstarted; do not treat older continuation notes below
as current instructions to execute it. Real reader/terminal acceptance remains manual.

Readable inventory footer checkpoint0.20.0/1.46.0 follows pushed1689ffb.134
compression/305 MangaDL/55 help pass,1 Windows privilege skip. User requested
one live read-only header index and final stats pasted into chat; see active STATUS.

Latest I1b2: -U refresh|trust whole-selection snapshots,128 compression/303 MangaDL/
55 help pass,1 privilege skip. Next readable inventory stats summary, then remaining
advisor/performance/scratch/reader gates. See active STATUS for publication evidence.

`compression-inventory-and-analysis-20261016`: I1a inventory, I2a/I2b cache reuse,
I2c automatic cache policies and I3a stable expanding samples. Each tested checkpoint
is committed/pushed under explicit user authorization; main is not pushed. Remaining
advisor, fast/trusted inventory, scratch and reader gates stay open in active status.

Active performance/cache continuation:
[plan](20261013-0600_compression-performance-sampling-and-cache/00_plan.md),
[status](20261013-0600_compression-performance-sampling-and-cache/STATUS.md).
Prior compression safety/reader acceptance gates still apply. Publish each usable
feature before the next; user explicitly authorizes scoped commits/pushes.

`compression-module-mangadl-20261013-0151` uses `20261013-0151_compression-module-and-mangadl-integration/`. The plan covers the standalone `modules/compresser` package, `mangadl compress` subcommand, termdash table and horizontal comparison bar enhancements, perceptual SSIM search, smart caching, and safe non-destructive defaults.

## Other plans

The compression plan REVIEW.md and05_reviewed-plan.md supersede predecessor
completion claims; S5–S8 reopened. Audit follow-up is module-owned at
`modules/mangadl/docs/plans/20261013-0300_audit-ux-and-manual-folder-repair/`.

- `20261012-2039_codex-agent-instructions/`
- `20261009-0349_kavita-module-mangadl-collections/`
- `20261009-0941_scheduler-log-explorer-and-shared-logging/`
- `20260926-0107_missing-only-bootstrap/`
- `20260729-0900_validation-evidence-context-history/`

These plans have separate histories and possible remaining acceptance work. Check each plan's current status and repository evidence before continuing it. Use a module's own `docs/plans/` for module-owned work.
