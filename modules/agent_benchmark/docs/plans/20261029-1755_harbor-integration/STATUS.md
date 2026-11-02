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
- The Oracle trial scored 0 because `test_pyknotid_repository_tests` failed on inner test `test_reconstructed_space_curve` (17 passed, 1 failed; task verifier 10 passed, 1 failed). This failure signature is consistent with the known upstream `pyknotid`/`planarity` compatibility problem (where `planarity` 1.0.0 caused pyknotid `KeyError: 'pos'`), but the preserved local trial artifacts did not retain the installed package version. Do not claim an unobserved exact package version; exclude this Oracle score from agent-capability comparisons.

## Next Action
- Obtain explicit authorization before any Codex or Antigravity inference that may use cloud or paid service. Then run a one-task compatibility pilot from the frozen ten-task set and, if valid, continue with the remaining tasks under the documented protocol; do not alter the task set or verifier.

## Aider Polyglot Coverage and Runtime Audit (2026-10-29)
- Audited the exact pinned dataset source `laude-institute/harbor-datasets` at `f30b14415dd733c83627204bad0af69a89ceb46f`, path `datasets/aider_polyglot`. All 225 catalog IDs match source task directories exactly: C++ 26, Go 39, Java 47, JavaScript 49, Python 34, Rust 30.
- All 225 pinned tasks contain `task.toml`, `instruction.md`, a Dockerfile, and an executable `tests/test.sh` that writes the verifier reward. Each declares 1 CPU, 4 GB RAM, 10 GB storage, and 1,800-second build, agent, and verifier limits. This verifies task/verifier availability, not that all images build or every verifier passes in this environment; dependencies include moving package/toolchain sources.
- Detailed audit output is retained outside version control under `reports/harbor/aider-polyglot-inventory-f30b14415dd7/` (`inventory.csv`, `inventory.json`, `README.md`). The 30-task multilingual proposal is under `reports/harbor/aider-polyglot-expansion-plan-f30b14415dd7/`; it is marked proposed-not-executed, has five tasks per language, and excludes the frozen ten-task cohort.
- Fixed a language-filter defect: substring matching included JavaScript tasks in Java and unrelated Java/JavaScript exercises in Go. Filtering now matches canonical language prefixes; regression test verifies every language selection against that prefix. This matters for language-stratified plans and does not change the frozen Qwen cohort.
- Runtime identity: the completed baseline used Harbor's `qwen-coder` adapter (Harbor adapter version 0.26.4) with the `qwen38_23GB` LM Studio model (Q4_K_M, configured 98,304-token context). This is Qwen Code through Harbor, not the full local-agent workflow. The repository's local workflow is an OpenCode `local-worker` profile reached through the coordinator's `opencode_worker` integration. The same model alias/checkpoint is configured locally, but OpenCode's API was not reachable during this audit, so its effective runtime settings were not verified. The custom workflow has not been benchmarked.
- Harbor exposes an `opencode` adapter, making it a candidate for a bounded local-worker compatibility evaluation once execution is authorized and the runtime configuration can be frozen. This would benchmark that OpenCode worker configuration; it would not by itself represent the entire coordinator-to-MCP workflow.
- Read-only adapter inspection found Harbor contracts for `codex`, `antigravity-cli`, and `opencode`. Installed CLI versions reported by local tools were Codex 0.165.0 and `agy` 1.4.10. Authentication credentials were not inspected and no cloud inference was run. The existing ten-task Qwen baseline remains 7/10 and was not rerun.
- Host OS records are inconsistent in naming: the registry reports `Windows 10 Pro`, `DisplayVersion 26H2`, build `26300.9711`, while prior handoff text says Windows 11. The historical baseline manifest is preserved; this audit does not rewrite it or claim that the naming discrepancy is resolved.
- Full-suite planning: a 30-task proposal (five per language) is estimated at 3–6 hours including multilingual image setup; the 225-task mechanical extrapolation is about 19.7 hours at the pilot's mean time, with substantial environment uncertainty. Proposed execution is sequential in persistent ten-task batches, reconciling native and imported trial IDs before resuming and retrying only classified infrastructure failures. Each batch keeps native Harbor and canonical imports. Existing report discovery deduplicates run IDs but does not create a cross-batch experiment rollup; a manifest-scoped rollup is needed before claiming an overall 225-task score. No expanded run was authorized or started.
- Protocol note: this internal `single-attempt-v1` baseline differs from Aider's published two-attempt feedback methodology; it must not be presented as directly equivalent to published Aider leaderboard scores.
- Validation after the filter fix: dataset tests **5 passed**; full `modules/agent_benchmark/tests`: **449 passed, 3 skipped** (Windows symlink privilege); Ruff on the changed implementation and test: **passed**; `git diff --check`: **passed**. `benchmark_core` was unchanged and its prior validation remains 116 passed, 1 skipped.
- Files changed for this audit: `agent_benchmark/harbor/datasets.py`, `tests/harbor_datasets_test.py`, and this status ledger. Generated inventory/cohort artifacts remain untracked under `reports/` with benchmark evidence and are not source changes.

### Next actions
1. Review and commit the language-filter fix and status update locally; do not push or merge.
2. Keep the existing ten-task score as the preliminary Qwen Code baseline. Do not rerun without a methodological reason.
3. Obtain explicit authorization and freeze OpenCode local-worker settings before any expanded local inference. Begin with one bounded compatibility task; review resource use and multilingual task-image behavior before requesting full-suite authorization.
4. Obtain separate authorization before Codex or Antigravity inference. Compare first on the exact frozen ten-task cohort, keeping model identity, billing route, tools, and task outcomes explicit.
5. Do not claim complete 225-task runnability until image builds/verifiers are exercised; do not report a 225-task aggregate until the manifest-scoped cross-batch rollup exists.

## Final Review Hardening and Merge Readiness (2026-11-01)
- **Issue A (Agent Configuration Defaults)**: Addressed default model and base-url routing in `planner.py`, `runner.py`, and `cli.py`. Prevented cloud and reference agents (`codex`, `antigravity-cli`, `oracle`, `nop`) from silently inheriting local Qwen defaults (`qwen38_23GB` and `http://host.docker.internal:1234/v1`). Preflight checks now detect missing API credentials (e.g., `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) as runnable blockers. Non-model agents (`oracle`, `nop`) omit `--model` and `--base-url`.
- **Issue B (Nonzero Harbor Process Exits)**: Updated runner exit handling to validate job outcome before accepting artifacts. Exits with nonzero return codes fail closed if trials are incomplete or if `result.json` is missing or unparseable. Successfully completed runs with nonzero exits log a warning and record `harbor_process_returncode` in environment attributes, run metadata, and summary metrics.
- **Issue C (Dependency Declaration)**: Added explicit direct dependency `pydantic>=2.0,<3` to `modules/agent_benchmark/pyproject.toml`.
- **Issue D (Oracle Limitation Alignment)**: Documented that the Terminal-Bench Oracle failure on `build-cython-ext` is consistent with the upstream `pyknotid`/`planarity` regression without claiming an unobserved installed version.
- **Verification Summary**:
  - Harbor-focused tests: **47 passed, 0 failed**
  - Full `modules/agent_benchmark` regression: **458 passed, 3 skipped**
  - Full `modules/benchmark_core` regression: **116 passed, 1 skipped**
  - Ruff lint: **All checks passed**
  - Wheel packaging: **agent_benchmark-1.20.0-py3-none-any.whl built successfully**
  - CLI smoke tests: `external list`, `external plan` (`codex`, `oracle`, `qwen-coder`), and `external report` verified
- **Merge Readiness Recommendation**: **READY TO MERGE** into `main`. All functional, safety, and documentation requirements are satisfied. Branch is ahead of origin by local hardening commits; awaiting explicit user authorization prior to push or merge.
