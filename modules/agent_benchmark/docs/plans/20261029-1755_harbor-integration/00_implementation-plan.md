# Implementation Plan: Harbor Integration and Deterministic Coding-Agent Evaluation

**Plan Identifier:** `20261029-1755_harbor-integration`  
**Target Module:** `modules/agent_benchmark/`  
**Supporting Module:** `modules/benchmark_core/`  
**Date:** 2026-10-29  

---

## 1. Objectives & Architectural Boundaries

Integrate the **Harbor** agent evaluation framework (`harbor==0.25.0`) with `agent_benchmark` and `benchmark_core` to evaluate local and cloud coding agents on standardized benchmarks:
1. **Aider Polyglot** (225 multi-language coding tasks).
2. **Terminal-Bench** (pinned CPU-only deterministic task subset).

### Architecture
- **Coordinator:** `agent_benchmark` (CLI, planning, agent/model metadata, subset selection, receipt lifecycle, import/export, reporting).
- **Execution Engine:** External Harbor framework (runs in isolated container sandbox, invokes agent, executes authoritative verifier, records rewards and traces).
- **Storage & Reporting:** `benchmark_core` (`RunInfo`, `TrialResult`, `MetricValue`, storage, comparison, and reporting).

Harbor is accessed strictly as an external execution provider via subprocess argument arrays and filesystem artifacts. It is not an in-tree dependency of the main package.

---

## 2. Implementation Stages

### Stage A: Harbor Result Importer and Normalizer
- **Harbor Schema Models & Normalizer:**
  - Create `modules/agent_benchmark/agent_benchmark/harbor/models.py`:
    - Strict parser for Harbor `JobResult` (from `result.json` at job root).
    - Strict parser for Harbor `TrialResult` (from `<trial>/result.json`).
    - Parser for `JobLock` / `TrialLock` (from `lock.json`).
    - Status mapper translating Harbor rewards (`1.0` -> `passed`, `0.0` -> `failed`), timeouts -> `timed_out`, and exceptions (`ErrorPolicy` cause) -> `infrastructure_error` / `unscored`.
  - Create `modules/agent_benchmark/agent_benchmark/harbor/importer.py`:
    - Validates job structure.
    - Translates Harbor job and trials into canonical `benchmark_core` `RunInfo` and `TrialResult` instances with `scoring_basis="external_verifier_pass_v1"`.
    - Preserves evidence links, timings, token metrics, cost metrics, and lock digests.
    - Persists results to `benchmark_core` format (`run.json`, `trials.jsonl`, `summary.json`, `summary.csv`, `report.md`).
    - Idempotent re-import: reimporting an existing job updates/reproduces identical records without duplication.
- **CLI Subcommand:**
  - `agent-bench external import -j <job-dir> -o <output-dir> [--format json]`
- **Testing:**
  - Sanitized authentic Harbor 0.25.0 job fixtures (passed, failed, timed_out, exception, duplicate prevention).
  - Validation that strict internal scoring is untouched.

### Stage B: Dataset Catalog & Non-Executing Planner
- **Dataset Resolvers:**
  - Create `modules/agent_benchmark/agent_benchmark/harbor/datasets.py`:
    - Metadata and task catalogs for `aider/aider-polyglot` and `terminal-bench/terminal-bench@4.0.0`.
    - Support language filtering for Aider (python, cpp, go, java, javascript, rust).
    - Deterministic pseudo-random subset selection with recorded seed.
    - Exact task selection by ID.
- **Planner & Readiness Checks:**
  - Create `modules/agent_benchmark/agent_benchmark/harbor/planner.py`:
    - Preflight checks: check Harbor executable availability, Docker daemon status.
    - Agent compatibility validation (`codex`, `antigravity-cli`, `antigravity-sdk`, `opencode`, `qwen-coder`, `oracle`, `nop`).
    - Calculate projected trial count, timeouts, and resource requirements.
    - Plan output with complete reproducible provenance (dataset ID, version, tasks, agent, model, seed).
- **CLI Subcommands:**
  - `agent-bench external list [--format json]`
  - `agent-bench external plan -d <dataset> -a <agent> -m <model> [-t <task>] [-k <reps>] [-s <seed>] [--format json]`
- **Testing:**
  - Deterministic planning tests, task selection verification, and readiness error paths.

### Stage C: Authorized Harbor Execution Adapter
- **Execution Controller:**
  - Create `modules/agent_benchmark/agent_benchmark/harbor/runner.py`:
    - Subprocess invocation of Harbor CLI using argument arrays (never shell strings).
    - Hard gate: requires `-x/--execute` flag.
    - Pre-flight verification: fail closed if Docker daemon is unreachable or Harbor is missing.
    - Integration with `state.py` command lock and pending receipt to serialize execution safely.
    - Post-execution automatic invocation of `HarborImporter` into specified output directory.
- **CLI Subcommand:**
  - `agent-bench external run -x -d <dataset> -a <agent> -m <model> ...`
- **Testing:**
  - Dry-run validation, failure-closed Docker checks, subprocess error handling, timeout handling.

### Stage D: Multi-Agent Evaluation & Comparative Leaderboard
- **Agent Identity & Leaderboard:**
  - Create `modules/agent_benchmark/agent_benchmark/harbor/reporting.py`:
    - Build comparison tables grouped by benchmark dataset and protocol.
    - Metrics: Points earned, Pass rate (%), Coverage (scored/scheduled), Median wall time, Infrastructure errors, Cost.
    - Strict head-to-head validation: require matching task subsets.
- **CLI Subcommand:**
  - `agent-bench external report -o <output-dir> [--format json]`
- **Testing:**
  - Comparison of distinct agent configurations on identical task subsets.

### Stage E: Terminal-Bench Integration, Documentation & Final Hardening
- **Terminal-Bench Curation:**
  - Define CPU-compatible subset of 3–5 tasks with oracle solution verification.
- **Documentation:**
  - Update `modules/agent_benchmark/README.md`.
  - Add installation, Docker preflight, and usage instructions for Windows 11 / WSL2.
- **Final Validation:**
  - Run full test suite, lint, and type checks.
