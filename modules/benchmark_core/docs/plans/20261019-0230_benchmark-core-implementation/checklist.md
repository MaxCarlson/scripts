# Implementation Checklist: `benchmark_core`

## Stage 1: Gate 1 Shared Contracts
- [x] Package structure and `pyproject.toml`
- [x] Shared data models (`RunInfo`, `TrialResult`, `MetricValue`) in `benchmark_core/models.py`
- [x] Strict validation (reject NaN/inf, validate allowed status and quality, safe relative paths)
- [x] UTC timestamp handling and normalization
- [x] Canonical fixtures (`canonical_run.json`, `canonical_trials.jsonl`)
- [x] Contract tests in `tests/contract_test.py` (41 passing tests)
- [x] Separate commit for Gate 1 deliverable

## Stage 2: Storage and Statistics
- [x] Implement `benchmark_core/storage.py` (filesystem layout, duplicate prevention, corrupted JSONL handling)
- [x] Implement `benchmark_core/stats.py` (descriptive statistics, all-scored vs successful duration, macro/micro rates)
- [x] Edge cases: 3 failures (0.0%), 3 infra errors (null/insufficient), mixed valid and infra errors
- [x] Tests in `tests/storage_test.py` and `tests/stats_test.py` (54 total passing tests)
- [x] Commit Stage 2

## Stage 3: Reporting, Comparison, and CLI
- [x] Output generators (`summary.json`, wide-form deterministic `summary.csv`, `report.md`) in `benchmark_core/reporting.py`
- [x] Comparison utilities in `benchmark_core/compare.py`
- [x] CLI commands (`report`, `compare`, `import`) with short/long flags and `-w`/`--write` protection in `benchmark_core/cli.py`
- [x] Tests in `tests/reporting_test.py`, `tests/compare_test.py`, `tests/cli_test.py` (65 total passing tests)
- [x] Commit Stage 3

## Stage 4: Hyperfine Importer & Final Verification
- [ ] Hyperfine JSON importer in `benchmark_core/importers/hyperfine.py`
- [ ] Tests in `tests/hyperfine_importer_test.py`
- [ ] End-to-end synthetic agent benchmark integration test
- [ ] Final docs and verification summary
- [ ] Commit Stage 4
