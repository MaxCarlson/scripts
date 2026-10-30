# Harbor Integration Checklist

**Plan:** `20261029-1755_harbor-integration`  
**Branch:** `harbor-integration-20261029-1755`  
**Authoritative Baseline:** Agent Benchmark 1.20.0, Benchmark Core 0.2.0  

---

## Stage A: Harbor Research and Offline Importer
- [x] Create `harbor/` subpackage under `agent_benchmark/`
- [x] Implement `harbor/models.py` (Pydantic models for Harbor 0.25.0 `JobResult`, `TrialResult`, `JobLock`, `ErrorPolicy` mapping)
- [x] Implement `harbor/importer.py` (idempotent normalization into `benchmark_core` `RunInfo` / `TrialResult`)
- [x] Implement `external import` CLI subcommand in `agent_benchmark/cli.py`
- [x] Create sanitized Harbor job fixture and test suite in `tests/harbor_importer_test.py`
- [x] Verify test suite passes without inference or Docker requirements
- [x] Stage A validation and review

## Stage B: Dataset Catalog and Non-Executing Planning
- [x] Implement `harbor/datasets.py` (catalogs for `aider/aider-polyglot` and `terminal-bench`)
- [x] Implement language filtering for Aider and deterministic seed subset selection
- [x] Implement `harbor/planner.py` (preflight readiness checks, resource and trial projections)
- [x] Implement `external list` and `external plan` CLI subcommands
- [x] Create unit tests in `tests/harbor_planner_test.py` and `tests/harbor_datasets_test.py`
- [x] Stage B validation and review

## Stage C: Controlled Execution
- [x] Implement `harbor/runner.py` (subprocess invocation with argument array, `-x/--execute` gate)
- [x] Implement Docker daemon connectivity verification (fail closed if unavailable)
- [x] Integrate with `state.py` command lock and pending receipt recovery
- [x] Implement `external run` CLI subcommand
- [x] Create unit tests for runner execution, authorization gates, and failure modes in `tests/harbor_runner_test.py`
- [x] Stage C validation and review

## Stage D: Multi-Agent Evaluation & Comparative Leaderboard
- [x] Implement `harbor/reporting.py` (dataset-separated leaderboard with points, pass rate, coverage, errors, duration)
- [x] Implement `external report` CLI subcommand
- [x] Create tests for multi-agent leaderboard comparisons in `tests/harbor_importer_test.py` and `tests/harbor_cli_test.py`
- [x] Stage D validation and review

## Stage E: Terminal-Bench Extension, Documentation & Final Hardening
- [x] Curate and freeze 5 CPU-compatible Terminal-Bench tasks with oracle baseline
- [x] Update `modules/agent_benchmark/README.md` with instructions for Harbor setup, Windows 11 / WSL2, Docker, and `agent-bench external` CLI
- [x] Run full repository regression test suite (`agent_benchmark` and `benchmark_core`): 436 passed, 3 skipped
- [x] Run lint (`ruff`) and static checks: All checks passed
- [x] Update `STATUS.md` and `HANDOFF.md`
