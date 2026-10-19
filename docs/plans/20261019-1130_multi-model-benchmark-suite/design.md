# Multi-Model Benchmarking & Visualization Suite &mdash; Architecture & Design Specification

**Status:** Approved design baseline with Phase E visual prototype review revisions  
**Date:** 2026-10-19  
**Branch:** `agent/multi-model-benchmark-20261019-1130`  
**Worktree:** `C:\Users\mcarls\src\scripts-multi-model-benchmark`  
**Primary Modules:** `modules/benchmark_core`, `modules/agent_benchmark`, `modules/termdash`

---

## 1. Intent & Architectural Overview

The objective of this project is to extend the repository's benchmarking system to support:
1. Multi-model batch experimentation (comparing multiple downloaded models against coding evaluation tasks with repetitions).
2. Live, bounded terminal visualization and milestone reporting (with `-Q`/`--quiet` suppression).
3. Cross-model comparison reports (standalone, offline-capable interactive HTML reports and console tables).
4. Safe, sequential local GPU scheduling with explicitly authorized model transitions.
5. Reusable experiment aggregation in `benchmark_core` that applies to non-LLM benchmarks (compression, GPU kernels, subprocesses).

### Core Architectural Principle: Boundary Separation

```
+---------------------------------------------------------------------------------+
|                               modules/termdash                                  |
|   Generic Terminal Primitives: LiveBlock (bounded cursor), Tables, Bars         |
|   (Zero knowledge of benchmarks, tasks, models, or LLM providers)               |
+----------------------------------------^----------------------------------------+
                                         |
+----------------------------------------|----------------------------------------+
|                           modules/agent_benchmark                              |
|   Agent & Model Adapter:                                                        |
|   - LM Studio downloaded model inventory & lifecycle (http://127.0.0.1:1234)    |
|   - OpenCode gateway & session dispatch (http://127.0.0.1:4096)                |
|   - Experiment planning (models x tasks x repetitions)                          |
|   - Sequential local trial scheduling (1 active trial on GPU)                   |
|   - Explicitly authorized model transitions (eject -> wait VRAM -> load -> test)|
|   - Task verification, scope auditing, token telemetry, strict scoring         |
|   - Dashboard presentation adapter (feeds LiveBlock)                            |
+----------------------------------------v----------------------------------------+
                                         |
+----------------------------------------v----------------------------------------+
|                           modules/benchmark_core                                |
|   Generic Experiment Framework:                                                 |
|   - Experiment models: Experiment, ExperimentConfig, ExperimentRunRef           |
|   - Production comparison eligibility enforcement (filters ineligible budgets)  |
|   - Denominator preservation: failed/timed-out trials stay in denominator       |
|   - Statistical aggregation (Wilson 95% score intervals, macro/micro deltas)   |
|   - Immutable run referencing & atomic persistence                              |
|   - Offline interactive HTML report generator & JSON/CSV exporters              |
+---------------------------------------------------------------------------------+
```

---

## 2. Package Responsibility Boundaries

### A. `modules/benchmark_core` (Generic Experiment Framework)

`benchmark_core` must remain entirely domain-agnostic. It knows nothing about LLMs, OpenCode, LM Studio, or coding fixtures.

**Responsibilities:**
1. **Experiment Models (`models.py`)**:
   - `Experiment`: Top-level container representing an experiment execution.
   - `ExperimentConfig`: Suite ID, suite version, planned variants, planned tasks, repetitions, scoring basis, budget profile, randomization seed.
   - `ExperimentRunRef`: Immutable reference to a constituent single run (`run_id`, `run_dir`, `variant_id`, `created_at`, `comparison_eligible`, `exclusion_reason`).
   - Reuses existing frozen `RunInfo`, `TrialResult`, and `MetricValue` contracts.
2. **Production Comparison Eligibility (`compare.py` / `aggregation.py`)**:
   - Production enforcement of `comparison_eligible=True`.
   - Separate eligible runs from experimental/ineligible runs.
   - Rejection/exclusion warnings when suite versions, scoring bases, or measurement definitions do not match.
   - Strict denominator preservation: trials with `status IN (failed, timed_out)` remain in denominators of eligible rates.
   - Isolation of `infrastructure_error` and `unscored` trials into separate diagnostic counters.
   - Wilson score confidence interval calculation (95% CI) for binary trial outcomes.
3. **Storage & Immutability (`storage.py`)**:
   - Reads immutable constituent run directories (`run.json`, `trials.jsonl`, `summary.json`).
   - Writes experiment layout under `reports/experiments/<EXP_ID>/`:
     - `experiment.json`: Manifest and execution configuration.
     - `run-references.json`: Pointers to constituent run directories.
     - `comparison.json`: Aggregated comparison metrics and rankings.
     - `comparison.csv`: Tabular export.
     - `report.md`: Portable Markdown comparison.
     - `index.html`: Standalone offline interactive report.
4. **Offline Interactive HTML Report Generation (`reporting.py`)**:
   - Generates self-contained HTML (inlined CSS and lightweight vanilla JS / SVG).
   - Zero external CDN dependencies (works completely offline and under `file://` protocols).
   - Safe HTML escaping for model-generated content.
   - Reproducible regeneration from immutable experiment artifacts.

### B. `modules/agent_benchmark` (Agent & LLM Adapter)

`agent_benchmark` owns all LLM, model provider, and coding evaluation concerns.

**Responsibilities:**
1. **Model Discovery & Provenance (`lifecycle.py`)**:
   - Inspects LM Studio models via LM Studio REST API (`http://127.0.0.1:1234/v1/models` or native CLI).
   - Inspects OpenCode provider models via OpenCode API (`http://127.0.0.1:4096/provider`).
   - Records accurate model provenance: model ID, architecture, parameter count, quantization format (e.g. `Q5_K_M`), context window, GPU offload percentage.
2. **Experiment Planning (`scheduler.py`)**:
   - Expands `models x tasks x repetitions` into a deterministic trial schedule with recorded seed.
   - Checks existing persistent dispatch receipts (`state.py`) to prevent duplicate or conflicting execution.
   - Produces dry-run execution plan by default.
3. **Sequential Local GPU Scheduling**:
   - Enforces strictly 1 active trial on local GPU.
   - Requires explicit `-x/--execute` flag.
   - Explicitly authorized model transitions:
     1. Unload finished model from LM Studio.
     2. Poll/wait for VRAM release and stabilization.
     3. Load next model into VRAM.
     4. Warmup query to verify responsiveness.
     5. If unexpected service error or timeout occurs: halt safely without blind retries to preserve shared-service stability.
4. **Evaluation & Scored Evidence**:
   - Task fixtures, instruction prompts, hidden verifiers.
   - Filesystem scope audits (allowed vs modified vs forbidden paths).
   - Token telemetry: prompt tokens, completion tokens, reasoning tokens.
   - Neutral token accounting: "Reasoning Token Share" = `reasoning_tokens / total_output_tokens` (volume metric, not qualitative claim).
   - Canonical strict acceptance = `Functional PASS AND Scope PASS AND Budget PASS AND No Uncertain Operations`.

### C. `modules/termdash` (Terminal Rendering Utilities)

`termdash` remains a reusable terminal utility library with zero benchmark domain logic.

**Responsibilities:**
1. **Bounded Relative Live Display (`termdash.LiveBlock`)**:
   - In-place relative-cursor updating beneath existing console output.
   - Bounded row count (pinned header + current summary table + pinned active task row + footer) so large experiment batches (72+ trials) never flood the terminal or scroll off-screen.
2. **Terminal Tables (`termdash.table`)**:
   - ANSI-aware column formatting, auto-padding, visual width calculation, and truncation with ellipses.
3. **Graceful Fallbacks & Quiet Mode**:
   - Plain-text periodic one-line logging when stdout/stderr is redirected to a pipe or file.
   - Clean terminal restoration on Ctrl+C (SIGINT) or unhandled exceptions.
   - `-Q` / `--quiet` flag completely suppresses live redraws, emitting only milestone stage messages.

---

## 3. UI Revisions from Prototype Review (11 Feedback Points)

All 11 points requested during visual mockup review are integrated into the architecture:

| # | Requested Revision | Architectural Implementation |
|---|-------------------|------------------------------|
| 1 | Leaderboard & Task Divergence Matrix as core views | Both views are primary tabs in the web report and summary exports. |
| 2 | Metric selection, filters, sorting, clickable trial drill-down | Web report includes dropdown filter bar (metric, task category, budget profile), column sorting, and interactive trial inspector drawer displaying patch diffs, verifier output, and scope receipts. |
| 3 | Metric decomposition | Explicit columns and cards distinguishing: Strict Acceptance, Functional Pass, Budget Compliance, Scope Compliance, Uncertain Operations, and Infrastructure Errors. |
| 4 | Eligibility, denominators, budget profile, Wilson CI | Prominent eligibility badge (`COMPARISON ELIGIBLE` vs `INELIGIBLE: EXCLUDED`). Explicit denominators (timeouts remain in denominator!). Wilson 95% confidence intervals on all success rates. Incompatible runs blocked from silent comparison. |
| 5 | Reasoning Token Share | Renamed from "Reasoning Depth" to "Reasoning Token Share". Documented as neutral volume metric (`reasoning_tokens / total_output_tokens`). |
| 6 | Execution efficiency analytics | Tradeoff view comparing Throughput (tok/s) vs Strict Acceptance (%) vs Tokens per Successful Task. |
| 7 | Bounded `termdash` display | `termdash.LiveBlock` bounds display to a fixed window (max 10-12 rows) regardless of batch size. |
| 8 | Safe model lifecycle | Removed claims of guaranteed OOM prevention. Requires explicit authorization for model transitions; halts on unexpected service failure. |
| 9 | Port & service grounding | OpenCode Gateway clearly identified at `127.0.0.1:4096`; LM Studio backend clearly identified at `127.0.0.1:1234`. Model quantization provenance recorded. |
| 10 | Synthetic data labeling | All mockup/prototype assets prominently marked `[SYNTHETIC PROTOTYPE DATA - FOR UI REVIEW ONLY]`. |
| 11 | Offline & reproducible | Self-contained static HTML report; fully regenerable from immutable experiment directories. |

---

## 4. CLI Interface Design

The CLI uses the `experiment` subcommand structure under `agent-bench`, alongside a `models` inventory command:

```powershell
# 1. Inspect available and loaded local models
agent-bench models list -p lmstudio

# 2. Plan a multi-model experiment (dry-run, prints JSON manifest)
agent-bench experiment plan -m qwen38_23GB -m qwen/qwen3-coder-30b -r 3 --budget-profile canonical-60s

# 3. Execute experiment (requires explicit -x/--execute)
agent-bench experiment run -x -m qwen38_23GB -m qwen/qwen3-coder-30b -r 3 --budget-profile canonical-60s

# 4. Quiet mode execution (suppresses in-place live dashboard)
agent-bench experiment run -x -Q -m qwen38_23GB -m qwen/qwen3-coder-30b -r 3

# 5. Check experiment status and progress
agent-bench experiment status -e .\reports\experiments\EXP_20261019_01 --format json

# 6. Regenerate HTML comparison report from immutable experiment artifacts
agent-bench experiment report -e .\reports\experiments\EXP_20261019_01 --html
```

### Conflict-Free Flags Check:
- `-m, --model`: Repeatable string (or nargs="+").
- `-r, --repetitions`: Integer >= 1 (default: 1).
- `-x, --execute`: Execution safety gate.
- `-Q, --quiet`: Suppresses live terminal table redraws. (`-q` remains `--request-timeout` for backwards compatibility).
- `-e, --experiment-dir`: Path to experiment root directory.
- `--html`: Generates standalone interactive HTML report.

---

## 5. Persisted Artifacts Layout

```text
reports/
  experiments/
    EXP_20261019_113000_a1b2/
      experiment.json          # Experiment metadata, configuration, seed, suite version
      execution-state.json     # Execution progress ledger, active trial, completed trials
      run-references.json      # List of referenced constituent single-run directories
      comparison.json          # Aggregated leaderboard, metrics, Wilson CIs, divergence matrix
      comparison.csv           # Tabular export of model comparison
      report.md                # Human-readable Markdown comparison
      index.html               # Standalone, offline interactive report viewer
```

Each constituent run retains its immutable single-run artifacts (`run.json`, `trials.jsonl`, `summary.json`, `evidence/`) in its original directory, referenced cleanly by relative path or directory reference.
