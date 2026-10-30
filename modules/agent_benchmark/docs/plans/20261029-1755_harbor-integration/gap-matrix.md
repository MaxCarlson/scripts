# Gap Matrix: Existing Agent Benchmark vs. Harbor Integration

**Baseline Version:** Agent Benchmark 1.20.0, Benchmark Core 0.2.0  
**Target Harbor Version:** `harbor==0.25.0` (pinned via isolated runner / `uv tool run`)  
**Date:** 2026-10-29  

---

## 1. Architectural Roles & Boundaries

| Functionality | Existing Agent Benchmark Implementation | Harbor External Integration (Required) | Gap / Action Required |
|---|---|---|---|
| **CLI Dispatcher** | `agent-bench plan`, `run`, `status`, `cleanup`, `smoke`, `models`, `experiment` | New subcommand group: `agent-bench external [list \| plan \| run \| import \| report]` | Add `external` parser group; reuse shared argument validators (`positive`, etc.). |
| **Execution Engine** | Internal `attempt.py` with `OpenCodeBridge` / HTTP MCP transport | External Harbor CLI invocation (`harbor run`) in isolated sandbox | Dedicated `harbor_runner.py` executing subprocess argument arrays (no shell interpolation). |
| **Container & Isolation** | Host file-system isolation via `git_workspace.py` and strict path audits | Container sandbox (Docker Linux engine) managed by Harbor | Check Docker engine availability fail-closed; if Docker daemon is unreachable, refuse live execution. |
| **Result Storage** | `benchmark_core.storage` (`RunInfo`, `TrialResult`, `MetricValue`) | Same `benchmark_core` storage contracts | Map Harbor's `JobResult`, `TrialResult`, `lock.json` into canonical `RunInfo` and `TrialResult`. |
| **Scoring Basis** | `worker_first_attempt_full_success` (strict scope + hidden verifier) | `external_verifier_pass_v1` (authoritative external reward) | Separate scoring basis; never conflate external score with internal strict-scope pass. |
| **Durable Receipts** | `state.py` (`pending.json` + `command.lock`) | Reused `state.py` receipt guards | Guard Harbor execution under `reserved_trial` / command lock so concurrent commands cannot collide. |
| **Comparison & Reports** | `benchmark_core.compare` and `reporting.py` | Leaderboard by dataset and protocol | Leverage existing `benchmark_core` summary and leaderboard rendering. |

---

## 2. Data & Schema Mapping

| Concept | Harbor Schema (`harbor==0.25.0`) | Benchmark Core Schema (`0.2.0`) | Mapping / Translation Rule |
|---|---|---|---|
| **Job Summary** | `JobResult` (`result.json` at job root): `id`, `started_at`, `finished_at`, `n_total_trials`, `stats`, `trial_results` | `RunInfo` (`run.json`): `run_id`, `created_at`, `suite_id`, `suite_version`, `task_ids`, `variants`, `repetitions`, `scoring_basis` | Map Harbor job UUID -> `run_id`, dataset name/version -> `suite_id`/`suite_version`, agent/model -> `variants`. |
| **Trial Outcome** | `TrialResult` (`<trial>/result.json`): `task_name`, `trial_name`, `task_id`, `verifier_result.rewards`, `exception_info` | `TrialResult` (`trials.jsonl`): `run_id`, `trial_id`, `task_id`, `variant_id`, `repetition`, `status`, `metrics`, `details` | Status mapping: reward 1.0 -> `passed`, reward 0.0 -> `failed`, budget/timeout -> `timed_out`, sandbox/auth/verifier crash -> `infrastructure_error`. |
| **Verifier Output** | `VerifierResult.rewards`: `dict[str, float \| int]` | `metrics["verifier.reward"]`: `MetricValue(value, "score", "harbor_verifier", "measured")` | Strict extraction: points earned = 1 (pass), 0 (fail), or unavailable (error). |
| **Token & Cost Usage** | `TrialResult.compute_token_cost_totals()`: `(n_input, n_cache, n_output, cost_usd)` | `metrics["tokens.input"]`, `metrics["cost.usd"]`, etc. | If present, convert to `MetricValue` with quality `measured` or `derived`; if missing, mark `unavailable`. |
| **Timing & Duration** | `environment_setup`, `agent_execution`, `verifier` `TimingInfo` | `metrics["duration.wall_ms"]`, `agent_ms`, `verifier_ms` | Extract millisecond durations from `started_at` and `finished_at` where available. |
| **Provenance & Locks** | `lock.json`: `JobLock`, `TaskLock`, `TrialLock` containing digests (`sha256:...`) | `TrialResult.details["harbor_provenance"]` | Store task digests, environment configurations, and Harbor commit/version in trial details. |

---

## 3. Dataset & Agent Matrix

| Benchmark | Upstream / Harbor Dataset Identifier | Languages / Scope | Selection Mechanism |
|---|---|---|---|
| **Aider Polyglot** | `aider/aider-polyglot` | 225 exercises across Python, C++, Go, Java, JavaScript, Rust | Explicit task ID (`-t`), language filter, deterministic seed (`-s`), or full suite. |
| **Terminal-Bench** | `terminal-bench/terminal-bench@4.0.0` (or `terminal-bench-cpu-only`) | Pinned subset of 3–5 deterministic, CPU-compatible tasks | Frozen task IDs with documented reference/oracle solution validation. |

| Agent Adapter | Harbor Supported Agent Identifier | Local / Cloud Support | Prerequisites & Authentication |
|---|---|---|---|
| **Codex CLI** | `codex` | Cloud (OpenAI) | Pinned CLI adapter; requires valid session/API key; no credential copying into container. |
| **Google Antigravity CLI** | `antigravity-cli` | Cloud (Google) | Requires headless authorization or API key environment variable; verify connectivity before trial. |
| **Google Antigravity SDK** | `antigravity-sdk` | Cloud (Google) | Headless SDK configuration. |
| **OpenCode** | `opencode` | Local / Host bridge | Connects to local server via host network route. |
| **Qwen Code** | `qwen-coder` | Local (LM Studio) | OpenAI-compatible endpoint route (`host.docker.internal` or container bridge IP). |
| **Oracle / Nop** | `oracle`, `nop` | Baseline reference | Deterministic oracle baseline for grader validation; no model required. |

---

## 4. Safety & Isolation Verification

1. **Host Safety:** Untrusted benchmark tasks must never run directly on the Windows host.
2. **Docker Preflight:** Harbor requires Docker. If `docker info` fails (e.g. desktop daemon is not running), `agent-bench external run` must fail closed with a clear diagnostic and exit code != 0, while `plan` and `import` remain fully functional without Docker.
3. **No Unbounded Retries:** Harbor retries must default to 0 (`--max-retries 0`) for deterministic evaluation.
4. **Offline Import Safety:** Importer parses filesystem JSON only; never initiates network requests, starts containers, or modifies existing benchmark records.
