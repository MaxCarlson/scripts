# Checkpoints

## Plan03 inventory/sampling/pipeline and CLI continuation

- [x] P0 current-run phase/counter baseline and generated repeatable benchmark (0.27.0/1.53.0).
- [x] P1 accurate gallery/file progress and estimated ETA (real terminal visual acceptance still manual).
- [x] P2 reduced I/O and bounded header concurrency.
  - [x] P2a shared run connection/pool, bounded changed-header work/SQL, short transactions, identity/visited-scope safety.
  - [x] P2b root discovery reuse and failure/admission review; task3 post-commit gate follows.
- [x] P3 trusted-source/cache preparation optimization (serial validation/streaming scalar dispatch rulings recorded).
  - [x] P3a deduplicated operation-local ancestor validation and replacement checks;227 compression/314 MangaDL/55 help pass.
  - [x] P3b bounded cache preparation/dispatch overlap and bulk lookup parity; final gate follows.
- [x] P4 metadata-only persisted sampling profiles; no pilot/confirmation machinery.
- [x] P5 verified AUTO candidate reuse; no unmeasured metric/process-pool changes.
- [x] P6 explicit auto memory policy/pressure-aware admission; default remains512MiB.
- [x] P7 bounded parallel previews and single manifest owner.
- [ ] P8 canonical argument simplification/major migration, compatibility and safety checks.
- [ ] Fresh whole-branch review and explicit manual reader/Windows terminal gates.

## Review repairs (2026-10-17) — earlier completion claims are conditional

- [x] Correct conditional confirmation estimator and remove unsupported adaptive pooling claim (0.25.1/1.51.1).
- [x] Real reader/writer exclusion, including nested targets and standalone full-run ownership (0.26.0/1.52.0/cross_platform0.8.0).
- [x] Bounded streaming scratch/reservations and partial-write/manifest cleanup (0.26.1/1.52.1).
- [x] Bounded diagnostic cache memory with durable history lookup (0.26.2/1.52.2).
- [x] Design-weighted failure-honest recommendations (0.26.3/1.52.3); manual reader acceptance remains open.
- [ ] Actual CLI plan consumption, runtime budget semantics and conditional simulations.
- [ ] Whole-branch review; real terminal/reader acceptance remains manual, not replaced by fixtures.

## Approved continuation (2026-10-16)

- [x] Reconcile baseline/completed work and record approved I1-I5 plan including SSD scratch.
- [x] I1a durable inventory, validated refresh, inventory-only CLI, focused validation (90 compression/17 integration/55 help).
- [x] I1b single-pass discovery, fast/richer inventory and explicit trusted snapshots.
  - [x] I1b1 filesystem-only -l -D files, separate durable unverified snapshots, totals/error handling and MangaDL exclusions.
  - [x] Trusted completed header snapshots and selected-file validation without whole-target enumeration (-U trust).
  - [x] Readable inventory-only summary requested2026-10-16; preserve clean explicit JSON.
  - [x] Reusable per-folder read/write locks (`cross_platform 0.7.0`), `mangadl lock -s|-u -d TARGET [-j]` (`mangadl 1.47.0`), and live in-place `InventoryProgress` (`compresser 0.21.0`).
- [x] I2 bounded persistent cache improvements and reusable encoder candidates.
  - [x] I2a reusable serialized SQLite connection, memory promotion of disk hits, periodic bounded eviction; immediate commits retained. 92 compression/17 integration/55 help pass.
  - [x] I2b effective candidate identity and AUTO analysis reuse;95 compression/17 integration pass.
  - [x] I2c automatic per-library use/refresh/off trial-cache policies and path/policy reporting;96 compression/17 integration/55 help pass.
  - [x] I2d1 persistent cache dates (legacy creation unknown) and scoped run lookup diagnostics;113 compression/302 MangaDL/55 help pass.
  - [x] Detailed per-source/settings/runtime/eviction miss explanations via `trial_index` (`compresser 0.23.0` / `mangadl 1.49.0`).
- [x] I3 stable growing samples and pilot-informed advisor with justified uncertainty.
  - [x] I3a stable seeded priorities, monotone quotas, persistent selection/population provenance;98 compression/full MangaDL/55 help pass.
  - [x] Pilot advisor, defensible outcome-adaptive allocation/confirmation and interval simulations (`compresser 0.22.0` / `mangadl 1.48.0`).
- [x] I4 measured concurrency improvements (pre-admission cache-hit bypass) and opt-in analysis-only SSD scratch (`-X/--scratch-dir`, `compresser 0.24.0` / `mangadl 1.50.0`).
- [x] I5 multi-quality recommendations and remaining MangaDL/reader acceptance (`compresser 0.25.0` / `mangadl 1.51.0`).
  - [x] I5a full-resolution external preview originals/lossless/multiple-quality variants, manifest, cancellation and source preservation tests.
  - [x] I5b multi-quality comparison on one sample with shared lossless baseline/cache and per-quality stages/projections.
  - [x] I5c comparison recommendations separating maximum storage savings, best lossless, and practical speed/fidelity/reader trade-off, plus MangaDL reader/library acceptance tests (`145 passed, 1 skipped` in `compresser`; `308 passed` in `mangadl`; `55 passed` in `scripts_help`).

Historical checkpoints below retain publication status; they do not imply newer work
has been pushed or accepted in a reader/real terminal.

- [x] Evidence-backed plan covering all requested features.
- [x] Plan committed and pushed (c76df28).
- [x] P1 stopping and nonblocking lock feedback implemented/tested; setup refreshed.
- [x] P1 commit/push checkpoint.
- [x] P2 phase diagnosis, effective/active worker UI, readable narrow reports, tested/setup.
  - [x] Worker-visibility slice: actual counts, limiter and active image details, tested/setup.
  - [x] Exclusive phase timings/cache-hit freshness and narrow comparison fallback.
  - [x] Publish P2 phase checkpoint; scheduling-wait metrics remain with P3.
- [x] P3 memory-aware scheduling and bounded resource configuration, tests/setup.
- [x] Publish P3 checkpoint before P4.
- [x] P4 inventory, proportional percentage sampling and coverage-aware projections, commit/push.
  - [x] Gallery-stratified seeded random sampling, count/byte-weighted quotas, percent selection, and explicit coverage limits.
  - [x] Seven-strategy combined lossless/lossy comparison on one shared sample; text/JSON projections and uncertainty.
  - [x] Explicit persistent cache writes/reuse verified during an active analysis; automatic cache policy remains P5.
- [x] P5 automatic MangaDL cache and interactive/noninteractive policy, commit/push.
- [x] P6 MangaDL gallery integrity and terminal/reader acceptance, commit/push.

Publish each usable checkpoint before starting the next feature.
