# Plan Handoff — Multi-Model Benchmarking

**Plan Directory:** `docs/plans/20261019-1130_multi-model-benchmark-suite/`  
**Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Worktree:** `C:\Users\mcarls\src\scripts-multi-model-benchmark`  
**Parent / Baseline:** `main` at `91d04f5d`  
**Stage 1 Commit:** `8ec27f46`  
**Active Plan Stage:** Stage 2 Complete (Awaiting user review before Stage 3)

---

## Architecture Summary
- **Generic Core (`modules/benchmark_core`)**: Owns `Experiment`, `ExperimentConfig`, `ExperimentRunRef`, production comparison eligibility filtering (enforcing `comparison_eligible=True`), denominator preservation (`passed + failed + timed_out`), Wilson score confidence intervals (95% CI), and atomic experiment persistence (`save_experiment`, `load_experiment`).
- **Agent Lifecycle & Scheduler (`modules/agent_benchmark`)**: Owns `list_downloaded_models`, `get_loaded_model`, safe `transition_model` (with explicit authorization checks, VRAM release verification, and zero blind retries), `expand_experiment_plan` (batched model grouping to eliminate GPU thrashing), and `ExperimentScheduler` (enforcing strictly 1 active GPU trial, per-trial reservation, and incremental persistence).
- **Interactive Reports (`modules/interactive_reports`)**: Standalone reusable reporting package providing portable offline HTML visualization, task divergence matrix, and execution efficiency scatterplots across benchmarking domains.
- **Terminal UI (`modules/termdash`)**: Provides reusable bounded in-place rendering (`LiveBlock`) and ANSI table formatting with quiet mode (`-Q`/`--quiet`).
- **Offline & Safe**: No live cloud calls or inference during offline test suite runs; historical evidence immutable.

---

## Verification Evidence
- `pytest modules/agent_benchmark/tests`: 255 passed, 3 skipped in 47.68s
- `pytest modules/benchmark_core/tests`: 92 passed, 1 skipped in 0.39s
- `pytest modules/termdash/tests`: 76 passed, 1 skipped in 10.59s
- `ruff check modules/agent_benchmark`: All checks passed (0 errors)
- `ruff check modules/benchmark_core`: All checks passed (0 errors)

---

## Staged & Unstaged State
- Modified in `modules/agent_benchmark/`:
  - `modules/agent_benchmark/agent_benchmark/lifecycle.py`
  - `modules/agent_benchmark/pyproject.toml`
  - `modules/agent_benchmark/tests/conftest.py`
- Added in `modules/agent_benchmark/`:
  - `modules/agent_benchmark/agent_benchmark/models_lifecycle.py`
  - `modules/agent_benchmark/agent_benchmark/scheduler.py`
  - `modules/agent_benchmark/tests/models_lifecycle_test.py`
  - `modules/agent_benchmark/tests/scheduler_test.py`
- Plan updates in `docs/plans/20261019-1130_multi-model-benchmark-suite/`
