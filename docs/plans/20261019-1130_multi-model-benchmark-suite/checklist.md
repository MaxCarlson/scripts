# Checklist — Multi-Model Benchmarking

**Plan:** `docs/plans/20261019-1130_multi-model-benchmark-suite/`  
**Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Baseline:** `91d04f5d`

---

## Stage 1: `benchmark_core` Generic Experiment Contracts & Eligibility Filtering
- [x] 1.1: Define `ExperimentConfig`, `ExperimentRunRef`, and `Experiment` data models in `benchmark_core/models.py`.
- [x] 1.2: Implement Wilson score 95% confidence interval utility in `benchmark_core/stats.py`.
- [x] 1.3: Implement `filter_eligible_runs` and `aggregate_experiment_runs` in `benchmark_core/compare.py` enforcing `comparison_eligible=True`, matching suite_version and scoring_basis.
- [x] 1.4: Implement denominator preservation: ensure failed and timed-out eligible trials remain in rate denominators, while infrastructure/unscored errors are isolated.
- [x] 1.5: Implement atomic experiment serialization (`save_experiment`, `load_experiment`) in `benchmark_core/storage.py`.
- [x] 1.6: Write offline tests in `benchmark_core/tests/experiment_test.py` and verify all existing tests pass.

## Stage 2: `agent_benchmark` Multi-Model Discovery, Planning, and Safe Model Lifecycle
- [x] 2.1: Implement LM Studio model discovery and loaded model detection in `agent_benchmark/models_lifecycle.py` and re-export in `lifecycle.py`.
- [x] 2.2: Implement safe model transition logic with explicit error handling and VRAM stabilization checks.
- [x] 2.3: Implement `expand_experiment_plan` and `ExperimentScheduler` enforcing sequential local execution (1 active GPU trial) in `agent_benchmark/scheduler.py`.
- [x] 2.4: Validate existing dispatch-receipt guards and preserve durable recovery.
- [x] 2.5: Write offline unit tests with mock LM Studio API responses in `agent_benchmark/tests/models_lifecycle_test.py` and `agent_benchmark/tests/scheduler_test.py`.

## Stage 3: `termdash` Bounded Live Terminal Dashboard & Quiet Mode
- [x] 3.1: Implement `ExperimentDashboard` consuming `termdash.LiveBlock` and `termdash.Table` in `agent_benchmark/dashboard.py`.
- [x] 3.2: Bounded terminal display (strictly <= 10-12 rows) showing progress, per-model rollup, and active trial details.
- [x] 3.3: Implement graceful non-interactive/pipe plain-text fallback.
- [x] 3.4: Implement `-Q`/`--quiet` mode suppressing live block updates while retaining milestone summaries.
- [x] 3.5: Write terminal dashboard unit tests in `agent_benchmark/tests/dashboard_test.py`.

## Stage 4: `interactive_reports` Standalone Reusable Package & Cross-Model Analytics
- [x] 4.1: Implement standalone `modules/interactive_reports` package with reusable HTML builder components.
- [x] 4.2: Build interactive filter bar (metric focus, category, budget profile) and sortable columns.
- [x] 4.3: Build Task Divergence Matrix with clickable trial drill-down drawer.
- [x] 4.4: Build execution efficiency analytics view (time vs tokens vs correctness).
- [x] 4.5: Ensure strict HTML escaping, offline compatibility, and reproducible regeneration from experiment artifacts.
- [x] 4.6: Write unit tests in `modules/interactive_reports/tests/` and benchmark adapter tests.

## Stage 5: CLI Integration, End-to-End Regressions & Acceptance
- [x] 5.1: Wire CLI subcommands (`models list`, `experiment plan`, `experiment run`, `experiment status`, `experiment report`) in `agent_benchmark/cli.py`.
- [x] 5.2: Write end-to-end multi-model experiment integration test.
- [x] 5.3: Run complete offline regression suites across `benchmark_core`, `agent_benchmark`, and `termdash`.
- [x] 5.4: Run Ruff formatting/lint and Mypy static type checking.
- [x] 5.5: Update documentation and prepare Sol Medium handoff.
