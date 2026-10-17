# Compression review repairs implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with test-first checkpoints and one fresh whole-branch review at completion.

**Goal:** Correct every confirmed review finding and deliver honest, bounded, usable compression analysis.
**Architecture:** Keep fixed-budget sampling intact; make conditional confirmation inference explicit. Use a common external reader/writer coordination gate, bounded streaming scratch, and bounded cache diagnostic memory. Wire validated persisted plans into the CLI rather than suggesting commands that discard the advised allocation.
**Tech stack:** Python3.12, SQLite, Pillow, cross_platform OS locks, termdash, pytest.
**Spec:** User-approved I1-I5 continuation plus the 2026-10-17 review and direct request to plan and implement all fixes. This document records the corrective design, not a new feature roadmap.

## Global constraints

- Stay on `compression-inventory-and-analysis-20261016`; preserve unrelated changes.
- User's continuous authority permits focused tests, scoped commits and feature-branch pushes after each usable checkpoint; no main merge or production image writes.
- No broad live benchmark or production repair/compression. Generated fixtures only.
- Keep short/long CLI forms, module versions/dependencies/help registry synchronized.
- Fail closed on stale sources/populations, missing observations, incompatible settings and partial state.
- Do not claim normal intervals validate outcome-driven pooling, inventory proves integrity, or SSIM proves visual quality.

## Review focus

Pilot-censused singleton galleries; zero/failing/missing pilot results; files larger than scratch budget or growing while copied; write/read acquisition races across parent/gallery paths; different inclusion probabilities and partially unestimated strategies.

## Task 1: correct conditional confirmation estimates and uncertainty claims

Files: compresser/sampling.py, sampling_test.py, module/repo docs and versions.
Interfaces: confirmation_sample adds optional `pilot_results`; returned plan records original pilot images/outcomes. Ordinary primary plans retain existing estimate semantics.

- [ ] RED: N4, pilot savings900+900, remainder100+100 => full total2000 and census interval[2000,2000], not400. Pilot-censused singleton remains known. Missing/failed pilot outcomes must not yield a complete estimate.
- [ ] RED: unsampled remaining strata cannot yield a whole-population confidence interval. No unsupported two-stage adjusted interval or pooling recommendation.
- [ ] Implement conditional totals `sum(pilot) + remaining_N * mean(confirmation)` and remaining-population finite correction; include pilot-known contributions even when remaining outcomes unknown. Validate pilot-result provenance/duplicates and confirmation disjointness.
- [ ] Keep deprecated adjusted-interval field null with explicit explanation for compatibility; ordinary fixed-design interval remains approximate. Add repeated-sampling conditional fixture validation, not merely interval-width assertions.
- [ ] Full compression/MangaDL/help tests, format/lint, docs/version updates, commit/push.

## Task 2: real reader/writer exclusion

Files: cross_platform/locks.py + lock tests, compresser/transactions.py + CLI, mangadl/library_guard.py.
Interfaces: one canonical external coordination gate shared by readers and writers; multiple readers permitted, writes exclusive. Root ownership applies to nested galleries. Keep legacy write-lock inode compatibility and thread reentrancy.

- [ ] RED subprocess tests: reader-first blocks writer, writer-first blocks reader, many readers coexist; parent/gallery combinations and process death release locks.
- [ ] Serialize acquisition/check/publication through common gate to avoid check-then-act races; no deletion of an active inode, no target mutation for read-only acquisition. Hold standalone read ownership through all encoder trials, not just discovery.
- [ ] Test cancellation/error release, PID metadata/stale inspection and legacy lock compatibility. Full lock/compression/MangaDL/help suites; docs/version/install, commit/push.

## Task 3: bounded scratch staging and failure cleanup

Files: compresser/scratch.py, engine.py, scratch_and_admission_test.py.
Interfaces: retain ScratchWorkspace API/original cache identities; reserve encoded bytes before reading, stream fixed-size chunks with cancellation and source-change checks.

- [ ] RED oversized input rejected before full allocation; simultaneous stages cannot exceed byte reservation; growth during copy rejected.
- [ ] RED injected partial-write/full-disk/hash/manifest failures leave no untracked source copies, preserve recoverable ownership manifest if cleanup fails, and never remove bystander files.
- [ ] Register ownership before exclusive creation/copy, verify streamed checksum/length, release reservation on every path; retain manifest until actual cleanup succeeds. Reject linked ancestors/junctions and unsafe root relationships.
- [ ] Full suites, isolated with/without-scratch equality and bounded benchmark; report actual overhead, not presumed SSD improvement. Docs/version/install, commit/push.

## Task 4: bound diagnostic cache memory

Files: compresser/cache.py, cache_connection_test.py/cache tests.
Interfaces: persistent trial_index preserves miss history; bounded in-memory diagnostic LRU does not grow with every file/setting ever observed.

- [ ] RED max_entries1 after1000 identities has bounded diagnostic memory; evicted history remains queryable in SQLite and miss causes remain correct.
- [ ] Bound promotions/updates; query only relevant path history on miss; retain transaction and concurrency guarantees. Validate memory-only history limits and legacy DB behavior.
- [ ] Full suites, docs/version/install, commit/push.

## Task 5: design-weighted, failure-honest recommendations

Files: compresser/ui.py, recommendation tests, reader acceptance docs.
Interfaces: maximum/best-lossless use complete projected savings for sampled targets; practical ranking uses the same scope and excludes unsupported/failed/unestimated rows rather than falling back to calling them winners.

- [ ] RED measured1800/projected9000 versus measured1000/projected100000 selects latter. Missing projection, all failures, low SSIM and zero-savings cases explicitly unavailable or caveated.
- [ ] Do not treat warm-cache throughput as measured encoder speed or null SSIM as proven fidelity. AUTO reader compatibility is conditional on actual output formats, not merely label.
- [ ] Full suites, docs/version/install, commit/push. Reopen manual Windows terminal/reader acceptance: fixture integrity tests are not real-reader acceptance.

## Task 6: usable pilot/confirmation CLI and budget semantics

Files: sampling planner/persistence module, shared CLI arguments, standalone/MangaDL adapters, integration tests/docs.
Interfaces: versioned external pilot/confirmation plan contains population identity, seed, selected identities/observations, settings/runtime fingerprints and per-gallery quotas. Explicit short/long export/apply options; no silent outcome-driven stopping.

- [ ] RED exported advice round-trips actual quotas (steady3/volatile37 must not become20/20); remaining/census populations, stale source/runtime/settings, invalid/duplicate paths fail closed.
- [ ] Export measured pilot provenance and an explicit confirmation plan; applying it selects disjoint remaining images with original pilot contributions and Task1 inference. If comparisons need common confirmation, use a documented shared envelope of stage quotas and preserve per-strategy pilot observations.
- [ ] Honor zero/runtime budgets before enforcing coverage minimum; report infeasible minimum honestly. Cost/variance fallbacks marked heuristic; zero observed variance is not proof of sufficient sample size. Validate finite positive precision and finite nonnegative runtime inputs.
- [ ] Remove misleading `-s N` advice until exact plan consumption exists; expose actionable validated commands once integrated. Add adaptive-allocation conditional simulations, source-change and JSON/UI tests.
- [ ] Full suites, docs/version/install, commit/push. One fresh whole-branch review, address important findings, leave manual acceptance gates explicit.

## Current status

Tasks1-4 committed/pushed7dea9b3/ee4696a/7600196/8f729e2. Task5 weighted recommendations
implemented/tested:197 compression (1 platform skip),308 MangaDL/55 help pass. User explicitly requests
STOP after Task5. Task6 has NOT started. Manual real reader/terminal acceptance and
final whole-plan review remain open. No production images changed.
