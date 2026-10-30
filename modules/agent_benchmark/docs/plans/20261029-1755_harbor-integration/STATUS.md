# Status: Harbor Integration and Deterministic Coding-Agent Evaluation

**Current Stage:** Qwen Aider Baseline Verified; Cross-Agent Comparisons Pending
**Branch:** `harbor-integration-20261029-1755`  
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\harbor-integration-20261029-1755`  
**Commits:** `a9198d1a` (initial implementation & hardening), `8ba37c87` (live contract alignment & verification), `79ddd70c` (initial live-results handoff), `7b850978` (Terminal-Bench dataset provenance corrections)
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
   - Catalogs `aider/aider-polyglot` (225 tasks), Terminal-Bench 2.0 (`terminal-bench/terminal-bench-2`, 89 tasks), and Terminal-Bench 4.0.0 (`terminal-bench/terminal-bench@4.0.0`, 66 tasks) as distinct identities. The pinned five-task default subset belongs to Terminal-Bench 2.0.
   - Language filtering, explicit task ID filtering, and reproducible seed-based sampling (`random.Random(seed)`).
4. **Non-Executing Planner (`agent_benchmark.harbor.planner`)**:
   - Preflight environment verification: Docker daemon responsiveness and Harbor CLI availability.
   - Supports `base_url` endpoint routing (default `http://host.docker.internal:1234/v1` for containerized local agent access to host LM Studio).
   - Fail-closed safety: planning reports readiness blockers and exits cleanly without running models or starting containers.
5. **Authorized Execution Runner (`agent_benchmark.harbor.runner`)**:
   - Subprocess argument array execution of `harbor run` (never shell string interpolation).
   - Uses `--include-task-name` for dataset task filtering and maps each descriptor to its Harbor registry dataset name.
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
  - Harbor-focused tests in `tests/harbor_*_test.py`: **37 passed** on `7b850978`.
  - Full `modules/agent_benchmark/tests` regression: **448 passed, 3 skipped** on `7b850978`.
  - Full `modules/benchmark_core/tests` regression: **116 passed, 1 skipped**.
  - `ruff check` on Harbor implementation and focused tests: **All checks passed**.

## Phase C: Ten-Task Aider Polyglot Baseline
- Result: **7/10 points (70%)**, 10/10 scored coverage, 0 canonical infrastructure errors, one attempt per task, sequential jobs, zero retries.
- Independently reconciled all ten imported trials against native Harbor locks and `result.json`: task IDs and source revision `f30b14415dd733c83627204bad0af69a89ceb46f` match; task digests and verifier rewards match; all run and trial IDs are unique.
- Regenerated the leaderboard from the canonical directory: 10 rows, 10 unique run IDs, 7 points, 100% scored coverage, 0 infrastructure errors.
- Frozen manifest: `reports/harbor/qwen-baseline-10/baseline-manifest.json`; summary: `reports/harbor/qwen-baseline-10/baseline-summary.md`.
- The manifest's detailed capture timestamp is during task 1, after the aggregate job started. Native Harbor config/lock files preserve resolved settings before each corresponding task execution; the retrospective addendum explicitly records this timing limitation.
- Measured totals in the saved summary: 3,478,686 cumulative prompt tokens, 178,762 completion tokens, 97 model calls, 52.4 minutes summed runtime, 179.8 seconds median runtime; peak single-request prompt was 78,897 tokens. These are cumulative/request metrics, not a single context size.
- Native jobs: `.harbor-jobs/`; canonical imported bundles: `reports/harbor/qwen-baseline-10/canonical/`.
- Initial aggregate attempt failed after one UTF-8 decoding infrastructure error and remains preserved separately; it is excluded from the score.
- Codex and Antigravity have not run. Local CLI versions observed: Codex `0.165.0`; `agy` `1.4.10`. No authentication state was inspected and no cloud inference was started. Their equivalent task/protocol plan is `reports/harbor/qwen-baseline-10/comparison-protocol.md`.

## Terminal-Bench Identity Audit
- `terminal-bench/terminal-bench-2` is Terminal-Bench 2.0 (89 tasks); source repository `https://github.com/laude-institute/terminal-bench-2.git`, pilot lock revision `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`.
- `terminal-bench/terminal-bench@4.0.0` is a separate 66-task release at source tag `v4.0.0` (commit prefix `452bf30`).
- The five-task default CPU subset belongs to Terminal-Bench 2.0. Published task metadata confirms 1 CPU, 2 GB RAM, and about 10 GB storage for `build-cython-ext`, `regex-log`, `sqlite-db-truncate`, and `nginx-request-logging`. The `log-summary-date-ranges` task page omits resource values; its exact pinned task TOML must be checked before a Terminal-Bench execution. Numeric agent/verifier timeouts are not in the retained native lock.
- Original Oracle artifacts and original imported report were preserved. Corrected derived report: `reports/harbor/tb-pilot-corrected/`.
- The Oracle trial scored 0 because `test_pyknotid_repository_tests` failed on inner test `test_reconstructed_space_curve` (17 passed, 1 failed; task verifier 10 passed, 1 failed). This matches the upstream report of `planarity` 1.0.0 breaking pyknotid's `data['pos']` expectation, but this local job did not retain the installed planarity version. Exclude this Oracle score from agent-capability comparisons.

## Next Action
- Obtain explicit authorization before any Codex or Antigravity inference that may use cloud or paid service. Then run a one-task compatibility pilot from the frozen ten-task set and, if valid, continue with the remaining tasks under the documented protocol; do not alter the task set or verifier.
