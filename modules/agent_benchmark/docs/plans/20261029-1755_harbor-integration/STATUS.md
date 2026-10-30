# Status: Harbor Integration and Deterministic Coding-Agent Evaluation

**Current Stage:** Live Evaluation Verified (Phases A, B, D, E Complete; Phase C 10-Task Baseline Ready to Run)  
**Branch:** `harbor-integration-20261029-1755`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755`  
**Commits:** `a9198d1a` (initial implementation & hardening), `8ba37c87` (live contract alignment & verification)  
**Package Version Baseline:** 1.20.0 (Agent Benchmark), 0.2.0 (Benchmark Core)  
**Pinned External Version:** `harbor==0.25.0`  

---

## Completed Capabilities
1. **Schema Models & Status Normalization (`agent_benchmark.harbor.models`)**:
   - Pydantic v2 schemas for Harbor 0.25.0 `JobResult`, `TrialResult`, `JobLock`, `VerifierResult`, `AgentContext`, and `ErrorPolicy`.
   - Objective status mapping: 1.0 -> `passed` (1 pt), 0.0 -> `failed` (0 pt), `AgentTimeoutError` -> `timed_out` (0 pt), sandbox/provider/verifier failure -> `infrastructure_error` (unavailable).
2. **Offline Importer (`agent_benchmark.harbor.importer`)**:
   - `HarborImporter` loads Harbor job directories, extracts task digests from `lock.json`, computes timing/token/cost totals, and translates records into canonical `benchmark_core` `RunInfo` and `TrialResult`.
   - Generates standard `run.json`, `trials.jsonl`, `summary.json`, `summary.csv`, `report.md`, and extended `harbor_summary.json`.
   - Idempotent re-import: re-running against the same directory overwrites cleanly without generating duplicate trial IDs.
3. **Dataset Catalog & Task Selection (`agent_benchmark.harbor.datasets`)**:
   - Authoritative Harbor 0.25.0 catalog for `aider/aider-polyglot` (all 225 `polyglot_<lang>_<task>` exercises across python, cpp, go, java, javascript, rust) and `terminal-bench/terminal-bench@4.0.0` (pinned 5 CPU-only tasks from the 89-task suite: `build-cython-ext`, `regex-log`, `sqlite-db-truncate`, `nginx-request-logging`, `log-summary-date-ranges`).
   - Language filtering, explicit task ID filtering, and reproducible seed-based sampling (`random.Random(seed)`).
4. **Non-Executing Planner (`agent_benchmark.harbor.planner`)**:
   - Preflight environment verification: Docker daemon responsiveness and Harbor CLI availability.
   - Supports `base_url` endpoint routing (default `http://host.docker.internal:1234/v1` for containerized local agent access to host LM Studio).
   - Fail-closed safety: planning reports readiness blockers and exits cleanly without running models or starting containers.
5. **Authorized Execution Runner (`agent_benchmark.harbor.runner`)**:
   - Subprocess argument array execution of `harbor run` (never shell string interpolation).
   - Uses `--include-task-name` for dataset task filtering and maps canonical suite IDs to Harbor registry dataset names (`aider-polyglot`, `terminal-bench`).
   - Passes `--base-url` for model agents while omitting it for `oracle`; injects fallback `OPENAI_API_KEY=lm-studio`.
   - Mandatory authorization gate (`-x/--execute`), live Docker readiness check, `command_lock` protection, and fail-closed exit verification.
6. **Comparative Reporting (`agent_benchmark.harbor.reporting`)**:
   - Recursive `rglob("run.json")` discovery with `run_id` deduplication.
   - Groups results by benchmark suite and protocol; renders table, JSON, and GitHub-flavored Markdown leaderboards.
7. **CLI Integration (`agent_benchmark.cli`)**:
   - Subcommand group `agent-bench external [list | plan | run | import | report]` with `-u/--base-url`.

## Verification Evidence
- **Live Phase A (Preflight)**: Verified Docker Linux engine (`29.9.2`), `harbor==0.25.0`, LM Studio (`qwen38_23GB`, Q4_K_M, 98k context), and container-to-host networking (`http://host.docker.internal:1234/v1`).
- **Live Phase B (Single-Task Local Qwen Pilot)**: Executed `polyglot_python_proverb` with `qwen-coder` / `qwen38_23GB` (Job `442fe010-32d4-41eb-b00b-0d69c2e1f5ea`, 267.4s, 185,195 input tokens, 16,218 output tokens, 0 exceptions; 5/8 pytest checks passed in container -> binary reward `0.0`, imported to `reports/harbor/pilot-qwen`).
- **Live Phase D (Cloud Adapter Audit)**: Verified `codex` and `antigravity-cli` option schemas via `harbor agent schema` without invoking paid cloud endpoints.
- **Live Phase E (Terminal-Bench Pilot)**: Executed `build-cython-ext` on `terminal-bench` with `oracle` (Job `76bdf6c9-0ec9-4336-82e7-2f3431cdfea7`, 87.9s, 0 exceptions; 10/11 pytest checks passed in container, imported to `reports/harbor/tb-pilot`).
- **Offline Test Suites**:
  - 34 focused unit and CLI tests in `tests/harbor_*_test.py`: **34 passed**.
  - Full `modules/agent_benchmark/tests` regression: **445 passed, 3 skipped**.
  - Full `modules/benchmark_core/tests` regression: **116 passed, 1 skipped**.
  - Static analysis with `ruff check`: **All checks passed**.

## Next Action
- Execute Phase C 10-task deterministic Python baseline (`--language python -n 10 -s 42`) with `qwen-coder` / `qwen38_23GB` into `reports/harbor/qwen-baseline-10` (~35–45m runtime). See [`HANDOFF.md`](HANDOFF.md) for exact commands.
