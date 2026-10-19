# STATUS — Multi-Model Benchmarking

**Plan:** `20261019-1130_multi-model-benchmark-suite`  
**Current Stage:** Stage 1 Complete & Verified (Ready for Stage 2)  
**Active Worktree:** `C:\Users\mcarls\src\scripts-multi-model-benchmark`  
**Active Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Baseline Commit:** `91d04f5d`  
**Last Updated:** 2026-10-19T11:46:00-07:00

---

## Current Status
- Stage 1 (`benchmark_core` generic experiment models, comparison eligibility enforcement, denominator preservation, and Wilson confidence intervals) implemented and thoroughly verified:
  - Added `ExperimentConfig`, `ExperimentRunRef`, `Experiment` models in `modules/benchmark_core/benchmark_core/models.py`.
  - Added `ScoreConfidenceInterval` and `compute_wilson_score_interval` (95% CI) in `modules/benchmark_core/benchmark_core/stats.py`.
  - Implemented production comparison eligibility filtering and aggregation in `modules/benchmark_core/benchmark_core/compare.py`:
    - Strict scored denominator: `passed + failed + timed_out`. `failed` and `timed_out` trials remain in denominator.
    - Infrastructure errors and unscored trials are isolated and do not pollute the scored denominator.
    - Ineligible runs (`comparison_eligible=False` or mismatched budget profiles) are segregated to `reference_variants` and excluded from `canonical_rankings`.
    - Variant demotion: if any constituent run for a variant is ineligible, the variant is demoted to `reference_variants`.
    - Hard compatibility checks on `suite_id`, `suite_version`, `scoring_basis`, and overlapping `task_ids`.
  - Implemented atomic experiment persistence (`save_experiment`, `load_experiment`) in `modules/benchmark_core/benchmark_core/storage.py`.
  - Added comprehensive test suite in `modules/benchmark_core/tests/experiment_test.py`.
  - All 92 `benchmark_core` tests passed (1 skipped).
  - All 244 `agent_benchmark` tests passed (3 skipped).
  - All 76 `termdash` tests passed (1 skipped).
  - Code hygiene: `ruff check modules/benchmark_core` passed (0 errors); `mypy --explicit-package-bases modules/benchmark_core/benchmark_core` passed (0 errors).

---

## Next Action
1. Stop for user manual validation / confirmation of Stage 1 completion.
2. Upon user approval, commit Stage 1 and proceed to Stage 2 (`agent_benchmark` multi-model discovery, planning, and safe model lifecycle).
