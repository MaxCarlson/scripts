# Checkpoints

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
- [ ] P5 automatic MangaDL cache and interactive/noninteractive policy, commit/push.
- [ ] P6 MangaDL gallery integrity and terminal/reader acceptance, commit/push.

Publish each usable checkpoint before starting the next feature.
