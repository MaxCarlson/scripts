# Handoff: Agent Benchmark Harbor Integration & Live Local Qwen Evaluation

**Date:** 2026-10-29  
**Repository:** `MaxCarlson/scripts`  
**Dedicated Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755`  
**Branch:** `harbor-integration-20261029-1755`  
**Baseline (`main`):** `33040f00`  
**Current Branch HEAD:** `8ba37c87` (2 commits ahead of `origin/main`)  
**Versions:** `agent-benchmark==1.20.0`, `benchmark-core==0.2.0`, `harbor==0.25.0`

---

## 1. Objective & Architectural Summary

We are extending `agent-bench` (`modules/agent_benchmark/`) and `benchmark_core` (`modules/benchmark_core/`) to evaluate local and cloud coding agents against standardized, deterministically graded external coding benchmarks via **Harbor (`harbor==0.25.0`)**:

1. **Aider Polyglot (`aider/aider-polyglot` / Harbor `aider-polyglot`)**: 225 Exercism coding exercises across Python, C++, Go, Java, JavaScript, and Rust.
2. **Terminal-Bench (`terminal-bench/terminal-bench@4.0.0` / Harbor `terminal-bench`)**: 89 system/CLI tasks, with a pinned 5-task CPU-only subset for local evaluation.

Key architectural invariants:
- **No LLM-as-judge or subjective grading**: All scores come strictly from Harbor's authoritative container test verifiers (`1.0` = pass, `0.0` = fail/timeout, `unavailable` = infrastructure error).
- **Layered separation**: `agent_benchmark` handles planning, CLI safety gates (`-x/--execute`), lock management, subprocess execution, and artifact ingestion; `harbor==0.25.0` (invoked via `uv tool run --from harbor==0.25.0 harbor`) manages task containers, agent runners, and verifiers; `benchmark_core` stores normalized `RunInfo`, `TrialResult`, and comparative reports.
- **Preservation of existing functionality**: Existing B0/B2/B3 experiments, historical artifacts, and OpenCode/local-agent workflows remain untouched.

---

## 2. What Has Been Implemented & Committed

All implementation work is isolated in the dedicated worktree `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755` on branch `harbor-integration-20261029-1755`:

### Commit History on Branch
1. `a9198d1a` — `feat(agent_benchmark): implement and harden Harbor external benchmark integration`
2. `8ba37c87` — `fix(agent_benchmark): align Harbor execution contracts and verify live evaluation`

### Implemented Modules (`modules/agent_benchmark/agent_benchmark/harbor/`)
- **`models.py`**:
  - Pydantic v2 models matching Harbor 0.25.0 native schemas (`JobResult`, `TrialResult`, `JobLock`, `VerifierResult`, `AgentContext`, `ErrorPolicy`).
  - `evaluate_trial_status()`: Enforces terminal exception precedence over partial verifier output, rejects `NaN`/`Inf` rewards, supports scalar and dict rewards (`reward` / `score` / `pass`), and classifies trials into `passed` (1.0), `failed` (0.0), `timed_out` (0.0), or `infrastructure_error` (unscored).
- **`datasets.py`**:
  - Registered the exact 225 task identifiers from Harbor's `aider-polyglot` dataset (`polyglot_<lang>_<task>`, e.g., `polyglot_python_proverb`) and the pinned 5-task CPU subset from Harbor's 89-task `terminal-bench` dataset (`build-cython-ext`, `regex-log`, `sqlite-db-truncate`, `nginx-request-logging`, `log-summary-date-ranges`).
  - Preserved canonical suite IDs (`aider/aider-polyglot` v`1.0.0`, `terminal-bench/terminal-bench@4.0.0` v`4.0.0`) alongside short aliases (`aider-polyglot`, `terminal-bench`).
  - Deterministic task filtering by language, exact/suffix task ID matching, and seeded random sampling (`select_tasks`).
- **`planner.py`**:
  - Non-executing `plan_benchmark()` with preflight checks (`check_harbor_readiness`, `check_docker_readiness`, `check_agent_readiness`).
  - Defaults tuned for local evaluation: `dataset="aider-polyglot"`, `agent="qwen-coder"`, `model="qwen38_23GB"`, `base_url="http://host.docker.internal:1234/v1"`.
- **`runner.py`**:
  - `build_harbor_command()`: Constructs argument arrays (never shell interpolation) for `harbor run`. Maps canonical dataset IDs to Harbor registry names (`aider-polyglot`, `terminal-bench`), passes `--include-task-name` for dataset task selection (fixing Harbor's rejection of `--task` for dataset tasks), passes `--base-url` for model agents while omitting it for `oracle`, and injects `OPENAI_API_KEY=lm-studio` when unset.
  - `execute_harbor_run()`: Enforces `-x/--execute` and live Docker readiness, acquires `command_lock`, verifies process exit status without falling back to stale job directories, and automatically imports completed runs.
- **`importer.py`**:
  - `HarborImporter`: Idempotently converts Harbor job directories (`result.json`, `lock.json`, `<trial>/result.json`) into `benchmark_core` artifacts (`run.json`, `trials.jsonl`, `summary.json`, `summary.csv`, `report.md`, `harbor_summary.json`).
  - Captures distinct provenance fields: `suite_id`, `suite_version`, `harbor_package_version`, and per-task SHA256 content fingerprints.
- **`reporting.py`**:
  - `collect_run_summaries()` and `render_leaderboard_table()`: Recursively discovers `run.json` files (`rglob`), deduplicates by `run_id`, and generates dataset-separated leaderboards (table, JSON, Markdown).
- **`cli.py`**:
  - Added `agent-bench external {list,plan,run,import,report}` with `-u/--base-url`, deduplicated `external list` output, and `__main__` entrypoint hook.

---

## 3. What Has Been Verified Live (Phases A, B, D, E)

### Phase A — Environment & Connectivity Preflight (Completed)
- **Docker Desktop**: Active Linux engine verified (`Docker version 29.9.2`, WSL2 backend).
- **LM Studio**: Active on host port `1234` with model `qwen38_23GB` (`qwen35` arch, `Q4_K_M`, `98,304` context length, tool use enabled).
- **Container-to-Host Networking**: Verified Docker containers reach LM Studio at `http://host.docker.internal:1234/v1/models`.
- **Harbor 0.25.0 Dry Run**: Verified `qwen-coder` auth/endpoint resolution (`Dry run OK — 1 trial(s)`).

### Phase B — First Real Single-Task Local Qwen Evaluation (Completed)
- **Command Executed**:
  ```powershell
  $env:PYTHONPATH = "C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\agent_benchmark;C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\benchmark_core"
  C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m agent_benchmark.cli external run -x -d aider-polyglot -a qwen-coder -m qwen38_23GB -t polyglot_python_proverb -o reports/harbor/pilot-qwen
  ```
- **Artifacts Produced**:
  - Native Harbor job: `C:\Users\mcarls\src\scripts\.harbor-jobs\harbor_20261030_022708_121c73c0` (Job UUID: `442fe010-32d4-41eb-b00b-0d69c2e1f5ea`)
  - Imported `benchmark_core` bundle: `C:\Users\mcarls\src\scripts\reports\harbor\pilot-qwen\harbor_20261030_022708_121c73c0`
- **Results**:
  - End-to-end execution succeeded with **0 infrastructure errors** in **267.4s (4m 27s)**.
  - Local Qwen (`qwen-coder` v0.26.4 / `qwen38_23GB`) processed **185,195 input tokens** and emitted **16,218 output tokens**, editing the workspace inside the container.
  - Authoritative pytest verifier ran 8 unit tests inside the Linux container: **5 passed, 3 failed** (missed optional `qualifier` keyword formatting and single-element list edge case).
  - Normalized score: `0/1` (`0.0` points, status `failed`, 100% coverage).

### Phase D — Codex & Antigravity Compatibility Audit (Completed)
- Audited `harbor agent schema codex` and `harbor agent schema antigravity-cli`:
  - **`codex`**: Supports `base_url`, `reasoning_effort` (`none|minimal|low|medium|high|xhigh|max`), `reasoning_summary`, `web_search`, `disable_web_search`, `config`, `version`. Requires `OPENAI_API_KEY`.
  - **`antigravity-cli`**: Supports `base_url`, `reasoning_effort` (`minimal|low|medium|high`), `disable_web_search`, `sandbox`, `binary_path` (allows uploading a local `agy` binary into the container), `config`, `version`.
- No paid cloud inference was triggered.

### Phase E — Terminal-Bench Verification (Completed)
- **Command Executed**:
  ```powershell
  $env:PYTHONPATH = "C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\agent_benchmark;C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\benchmark_core"
  C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m agent_benchmark.cli external run -x -d terminal-bench -a oracle -t build-cython-ext -o reports/harbor/tb-pilot
  ```
- **Artifacts Produced**:
  - Native Harbor job: `C:\Users\mcarls\src\scripts\.harbor-jobs\harbor_20261030_023504_3bab67cd` (Job UUID: `76bdf6c9-0ec9-4336-82e7-2f3431cdfea7`)
  - Imported `benchmark_core` bundle: `C:\Users\mcarls\src\scripts\reports\harbor\tb-pilot\harbor_20261030_023504_3bab67cd`
- **Results**:
  - Executed cleanly in **87.9s (1m 28s)** with **0 infrastructure exceptions**.
  - Container built Cython extensions (`chelpers`, `ccomplexity`, `cinvariants`) and ran 11 pytest checks: **10 passed, 1 failed** (`test_pyknotid_repository_tests` due to upstream `pyknotid` 0.5.3 test incompatibility under Python 3.13 in the container).
  - Confirmed multi-suite leaderboard generation across `reports/harbor` via `agent-bench external report -o reports/harbor --format markdown`.

### Offline Test & Lint Verification (Completed)
- `pytest modules/agent_benchmark/tests/harbor_*_test.py --basetemp="$env:TEMP/pt"` -> **34 passed**
- `pytest modules/agent_benchmark/tests --basetemp="$env:TEMP/pt"` -> **445 passed, 3 skipped**
- `pytest modules/benchmark_core/tests --basetemp="$env:TEMP/pt"` -> **116 passed, 1 skipped**
- `ruff check modules/agent_benchmark` -> **All checks passed**

---

## 4. What Remains To Be Done

1. **Execute Phase C — 10-Task Local Qwen Baseline on Aider Polyglot**:
   - The deterministic 10-task Python subset (`--language python -n 10 -s 42`) is planned and verified ready:
     `polyglot_python_beer-song`, `polyglot_python_bottle-song`, `polyglot_python_bowling`, `polyglot_python_dot-dsl`, `polyglot_python_pig-latin`, `polyglot_python_react`, `polyglot_python_robot-name`, `polyglot_python_transpose`, `polyglot_python_variable-length-quantity`, `polyglot_python_zipper`.
   - Run command (expect ~35–45 minutes wall time at ~3.5–4.5 min/task on local Qwen):
     ```powershell
     $env:PYTHONPATH = "C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\agent_benchmark;C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\benchmark_core"
     $env:PYTHONIOENCODING = "utf-8"
     C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m agent_benchmark.cli external run -x -d aider-polyglot -a qwen-coder -m qwen38_23GB --language python -n 10 -s 42 -o reports/harbor/qwen-baseline-10
     ```
   - After completion, generate the updated leaderboard:
     ```powershell
     C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m agent_benchmark.cli external report -o reports/harbor/qwen-baseline-10 --format markdown
     ```

2. **Optional Local Qwen Evaluation on Terminal-Bench CPU Subset**:
   - Run `qwen-coder` (`qwen38_23GB`) against one or more pinned Terminal-Bench CPU tasks (`regex-log`, `sqlite-db-truncate`, `nginx-request-logging`, `log-summary-date-ranges`):
     ```powershell
     C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe -m agent_benchmark.cli external run -x -d terminal-bench -a qwen-coder -m qwen38_23GB -t regex-log -o reports/harbor/tb-qwen
     ```

3. **Minor Polish / Environment Notes for Next Session**:
   - **`PYTHONPATH` / `.pth` Precedence**: `C:\Users\mcarls\src\scripts\.venv` has a `.pth` entry pointing to `C:\Users\mcarls\src\scripts\modules` (which is on `main`). Until `harbor-integration-20261029-1755` is merged into `main`, always set `$env:PYTHONPATH = "C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\agent_benchmark;C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755\modules\benchmark_core"` when invoking `python -m agent_benchmark.cli`.
   - **Windows `cp1252` Logging in Harbor**: Harbor 0.25.0 logs a non-fatal `UnicodeEncodeError` for `\u2192` (`→`) when Windows stdout/stderr encoding is `cp1252`. Setting `run_env["PYTHONIOENCODING"] = "utf-8"` in `runner.py` (or `$env:PYTHONIOENCODING = "utf-8"` in the shell) suppresses that logging warning cleanly.
   - **Pytest Windows `MAX_PATH`**: Always pass `--basetemp="$env:TEMP/pt"` when running `pytest` inside `.worktrees/harbor-integration-20261029-1755` so Git fixture tests do not exceed Windows' 260-character path limit.
   - **Branch Merge**: Once Phase C baseline results are reviewed and approved by the user, merge `harbor-integration-20261029-1755` into `main`.
