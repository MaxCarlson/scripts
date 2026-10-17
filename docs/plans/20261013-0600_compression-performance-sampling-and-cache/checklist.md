# Checkpoints

## Approved continuation (2026-10-16)

- [x] Reconcile baseline/completed work and record approved I1-I5 plan including SSD scratch.
- [x] I1a durable inventory, validated refresh, inventory-only CLI, focused validation (90 compression/17 integration/55 help).
- [x] I1b single-pass discovery, fast/richer inventory and explicit trusted snapshots.
  - [x] I1b1 filesystem-only -l -D files, separate durable unverified snapshots, totals/error handling and MangaDL exclusions.
  - [x] Trusted completed header snapshots and selected-file validation without whole-target enumeration (-U trust).
  - [x] Readable inventory-only summary requested2026-10-16; preserve clean explicit JSON.
  - [x] Reusable per-folder read/write locks (`cross_platform 0.7.0`), `mangadl lock -s|-u -d TARGET [-j]` (`mangadl 1.47.0`), and live in-place `InventoryProgress` (`compresser 0.21.0`).
- [ ] I2 bounded persistent cache improvements and reusable encoder candidates.
  - [x] I2a reusable serialized SQLite connection, memory promotion of disk hits, periodic bounded eviction; immediate commits retained. 92 compression/17 integration/55 help pass.
  - [x] I2b effective candidate identity and AUTO analysis reuse;95 compression/17 integration pass.
  - [x] I2c automatic per-library use/refresh/off trial-cache policies and path/policy reporting;96 compression/17 integration/55 help pass.
  - [x] I2d1 persistent cache dates (legacy creation unknown) and scoped run lookup diagnostics;113 compression/302 MangaDL/55 help pass.
  - [ ] Detailed per-source/settings/eviction miss explanations need additional indexing; generic misses are not overinterpreted.
- [ ] I3 stable growing samples and pilot-informed advisor with justified uncertainty.
  - [x] I3a stable seeded priorities, monotone quotas, persistent selection/population provenance;98 compression/full MangaDL/55 help pass.
  - [ ] Pilot advisor, defensible outcome-adaptive allocation/confirmation and interval simulations.
- [ ] I4 measured concurrency improvements and opt-in analysis-only SSD scratch.
- [ ] I5 multi-quality recommendations and remaining MangaDL/reader acceptance.
  - [x] I5a full-resolution external preview originals/lossless/multiple-quality variants, manifest, cancellation and source preservation tests.
  - [x] I5b multi-quality comparison on one sample with shared lossless baseline/cache and per-quality stages/projections.

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
- [ ] P4 inventory, proportional percentage sampling and coverage-aware projections, commit/push.
  - [x] Gallery-stratified seeded random sampling, count/byte-weighted quotas, percent selection, and explicit coverage limits.
  - [x] Seven-strategy combined lossless/lossy comparison on one shared sample; text/JSON projections and uncertainty.
  - [x] Explicit persistent cache writes/reuse verified during an active analysis; automatic cache policy remains P5.
- [ ] P5 automatic MangaDL cache and interactive/noninteractive policy, commit/push.
- [ ] P6 MangaDL gallery integrity and terminal/reader acceptance, commit/push.

Publish each usable checkpoint before starting the next feature.
