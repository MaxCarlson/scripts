# Multi-Model Benchmarking — Implementation Plan

**Plan Identifier:** `20261019-1130_multi-model-benchmark-suite`  
**Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Worktree:** `C:\Users\mcarls\src\scripts-multi-model-benchmark`  
**Baseline Commit:** `91d04f5d` (Merge branch 'agent/agent-benchmark' into main)  
**Primary Modules:** `modules/benchmark_core`, `modules/agent_benchmark`, `modules/termdash`

---

## 1. Intended Result

A fully tested, offline-validated multi-model benchmark suite that:
1. Discovers and lists downloaded local models from LM Studio and OpenCode.
2. Generates deterministic multi-model experiment plans (`models x tasks x repetitions`).
3. Executes trials sequentially on local GPU with explicitly authorized model unloading and loading.
4. Renders a bounded, in-place live terminal dashboard using `termdash.LiveBlock`, with quiet mode (`-Q`/`--quiet`).
5. Enforces comparison eligibility in the production aggregation layer of `benchmark_core` (excluding experimental budgets from canonical leaderboards, preserving timeouts in denominators, and calculating Wilson 95% score intervals).
6. Generates standalone, offline interactive HTML reports with task divergence drill-downs and execution efficiency analytics.
7. Preserves immutable run artifacts and historical evidence without modification.

---

## 2. Implementation Stages

### Stage 1: `benchmark_core` Generic Experiment Contracts & Eligibility Filtering
- **Goal:** Establish generic experiment data models, production comparison eligibility enforcement, and cross-run statistical aggregation in `modules/benchmark_core`.
- **Key Changes:**
  - `modules/benchmark_core/benchmark_core/models.py`: Add `ExperimentConfig`, `ExperimentRunRef`, `Experiment`.
  - `modules/benchmark_core/benchmark_core/stats.py`: Add Wilson score 95% confidence interval calculations for trial success rates.
  - `modules/benchmark_core/benchmark_core/compare.py`: Add `aggregate_experiment_runs`, `filter_eligible_runs`. Reject or cleanly segregate runs with mismatched suite versions, scoring bases, or `comparison_eligible=False`. Preserve failed and timed-out trials in canonical denominators.
  - `modules/benchmark_core/benchmark_core/storage.py`: Add `save_experiment`, `load_experiment`, atomic manifest writing.
- **Verification:** Unit and contract tests in `modules/benchmark_core/tests/experiment_test.py` and `compare_eligibility_test.py`.

### Stage 2: `agent_benchmark` Multi-Model Discovery, Planning, and Safe Model Lifecycle
- **Goal:** Implement model inventory discovery, experiment planning, and safe model transitions in `modules/agent_benchmark`.
- **Key Changes:**
  - `modules/agent_benchmark/agent_benchmark/lifecycle.py`: Add `list_downloaded_models`, `get_loaded_model`, `transition_model` (unload current, wait for VRAM release, load target, verify warmup). Halt safely on unexpected service errors without blind retries.
  - `modules/agent_benchmark/agent_benchmark/scheduler.py`: Add `expand_experiment_plan`, `ExperimentScheduler` enforcing sequential local execution (strictly 1 active trial on GPU).
  - Integration with existing persistent dispatch receipts (`state.py`).
- **Verification:** Offline fixture and mock tests in `modules/agent_benchmark/tests/scheduler_test.py` and `lifecycle_test.py`.

### Stage 3: `termdash` Bounded Live Terminal Dashboard & Quiet Mode
- **Goal:** Connect generic `termdash` primitives to the experiment runner for bounded live console visualization and `-Q`/`--quiet` suppression.
- **Key Changes:**
  - `modules/agent_benchmark/agent_benchmark/dashboard.py`: Terminal presentation adapter consuming `termdash.LiveBlock` and `termdash.table`.
  - Bounded display: fixed window (max 10-12 rows) showing overall progress bar, model summary table, active trial counter, and status badges.
  - Safe terminal restoration on SIGINT/exception.
  - Non-interactive / pipe fallback (periodic one-line progress).
  - `-Q`/`--quiet` mode: suppresses live blocks and outputs concise milestone logs only.
- **Verification:** Terminal rendering and quiet mode tests in `modules/agent_benchmark/tests/dashboard_test.py`.

### Stage 4: `benchmark_core` Standalone Offline Interactive HTML Report & Divergence Matrix
- **Goal:** Implement the standalone, offline-capable interactive HTML report generator in `benchmark_core`.
- **Key Changes:**
  - `modules/benchmark_core/benchmark_core/reporting.py`: Add `generate_experiment_html_report`, `generate_divergence_matrix`, `generate_efficiency_charts`.
  - Inlined CSS/JS with zero external CDN dependencies (works locally via `file://`).
  - Interactive features: metric selector, task/model filters, column sorting, clickable trial drill-down drawer (showing patch diff, verifier stdout, scope receipt).
  - Explicit metric breakdown (strict acceptance, functional pass, budget compliance, scope compliance, uncertain ops, infrastructure errors).
  - Markdown summary report generator (`report.md`) and CSV export (`comparison.csv`).
- **Verification:** HTML generation, escaping safety, and content tests in `modules/benchmark_core/tests/html_report_test.py`.

### Stage 5: CLI Integration, End-to-End Regressions & Acceptance
- **Goal:** Expose `agent-bench models` and `agent-bench experiment` commands, run end-to-end regression suites, and document handoff.
- **Key Changes:**
  - `modules/agent_benchmark/agent_benchmark/cli.py`: Add subcommands `models list`, `experiment plan`, `experiment run`, `experiment status`, `experiment report`.
  - Argument validation: `-m/--model` (repeatable), `-r/--repetitions`, `-x/--execute`, `-Q/--quiet`, `-e/--experiment-dir`.
  - End-to-end integration test running a multi-model simulated experiment through the full lifecycle.
  - Full test suite execution across `modules/benchmark_core`, `modules/agent_benchmark`, and `modules/termdash`.
- **Verification:** Complete offline pytest suites, Ruff lint clean, Mypy type-check clean.

---

## 3. Constraints & Commitments

- All development is conducted in isolated worktree `C:\Users\mcarls\src\scripts-multi-model-benchmark` on branch `agent/multi-model-benchmark-20261019-1130`.
- Staged/unstaged files in main working tree (`modules/cli_tui`) remain untouched.
- Historical benchmark evidence and reports remain immutable.
- No live inference or unapproved model switching is performed during offline test runs.
- Strict denominator semantics (failed + timed-out trials included) are preserved.
