# agent_benchmark — 1.20.0

Trial output shows code correctness, scope compliance, budget compliance, and confirmed termination separately, followed by specific violations, verifier/provider errors, uncertainty reasons, and an evidence path. Final output also counts functional code passes with an explicit measured denominator and unavailable count. Strict scoring remains the combined contract; correct code with a scope violation is reported as a functional pass and a strict failure. The same diagnostics are written to `benchmark.log`; trial JSON retains bounded verifier diagnostics.

Worker instructions recommend `python -B` for optional Python checks and keeping all temporary tests/caches in `.agent-bench-scratch`. Simple tasks can use read/edit tools and leave testing to the hidden verifier. Arbitrary shell execution may leave scope uncertain; these instructions are cooperative and do not enforce a shell sandbox or change shared OpenCode settings.

A thin evaluator around the existing OpenCode/MCP runtime. Phase 1d project/session checks passed authorized non-inference acceptance. Trial-local scratch policy is implemented and tested offline; no worker has exercised it live. Historical trial outcomes remain unchanged.

```powershell
agent-bench plan
agent-bench run -m MODEL_ID -x
agent-bench status -r reports/RUN_ID
agent-bench cleanup -r reports/RUN_ID       # preview
agent-bench cleanup -r reports/RUN_ID -x    # fresh reconciliation, then owned cleanup
```

`run` requires `-x/--execute`; plan, status and cleanup preview do not call models. Services must already be running. No command starts or reconfigures shared OpenCode/LM Studio services. LM Studio models resolve by exact downloaded `modelKey`; when OpenCode lacks that exact ID, a registration is generated only in the isolated trial project config. Model display names and similar quantizations are never used as aliases. Planning reports provider readiness and distinguishes unknown, unavailable, runnable, and registration-required models. No cloud fallback.

Multi-model experiments default to a shared 16,384-token LM Studio context cap (`-c/--context-length`) and strict `canonical-120s` worker budget (`-b/--budget-profile`). Before a benchmark-initiated load, the scheduler runs LM Studio's read-only allocation estimate and compares it to measured free GPU and host capacity without fixed reserve margins. It loads at the requested context and verifies the reported loaded context. A preloaded model is reused only when its reported context matches. Use `canonical-60s` to reproduce older runs; timeout outcomes remain strict and receive no completion grace. Example:

```powershell
agent-bench experiment plan -m lms/openai/gpt-oss-20b -m lms/meta/muse-glimmer -c 16384 -b canonical-120s
agent-bench experiment run -x -m lms/openai/gpt-oss-20b -m lms/meta/muse-glimmer -c 16384 -b canonical-120s
```

The default persistent state is `~/.local/share/agent-benchmark`, shared across output locations. Use the same `-s/--state-dir` across invocations; an unresolved job blocks later runs even if they use another report directory. An OS-held command lock serializes run/cleanup, while the unresolved receipt survives process exit. Never delete the receipt to bypass uncertain execution. `cleanup -x` requests supported cancellation when needed, then requires fresh matching session/turn/tool evidence. It preserves resources and blocking if termination cannot be confirmed. Cleanup failures never rescore trials.

The single-model `run` command evaluates one explicit model; multi-model `experiment plan/run` accepts repeated `-m` model IDs and repetitions. `benchmark_core` supplies RunInfo, TrialResult, MetricValue, persistence, statistics and JSON/CSV/Markdown reporting. Single-run outputs are `reports/<run_id>/{run.json,trials.jsonl,summary.json,summary.csv,report.md,evidence/}`. Exactly one trial is persisted per attempted repetition, including ordinary infrastructure failures and caller cancellation when storage is writable. Filesystem failures cannot guarantee persistence; uncertain execution still blocks dispatch.

Every run creates a fresh independent Git repository and unique root commit without a remote or host Git configuration changes. Header-routed OpenCode preflight requires exact directory/worktree and a Git project ID equal to that root commit. An empty session is created and its persisted directory/project binding validated before its ID is passed to the single MCP inference submission. Git bookkeeping is excluded from task-content snapshots; worker .git mutations remain scope-audited. See [Phase 1d guarantees and pending probe](docs/plans/20261019-implementation/phase1d.md).

`experiment plan/run --inference-profile FILE` optionally applies an allowlisted, versioned OpenCode profile to each fresh LM Studio trial project. It records the requested context/output limits, reasoning mode/effort provenance and profile SHA-256; `-c/--context-length` must match the profile context. Explicit reasoning profiles set `reasoningEffort` in the exact model's project-local options. This is evidence of requested/configured settings, not proof of outbound delivery or model acceptance. Compare request-level observations separately. Existing commands without a profile retain their documented defaults.

`experiment plan/run --instruction-append-file FILE` appends a UTF-8 instruction variant to the task prompt without copying its seed or verifier. The experiment metadata records the resolved file path, byte length and SHA-256 so controlled prompt changes can be reproduced. The addition applies to every selected task in that run; use one task per experiment when measuring a task-specific prompt intervention.

New runs use scope policy `trial-local-scratch-v1`: `.agent-bench-scratch/` is permitted for temporary test scripts and caches. Scratch bytes remain in bounded S0/S1 evidence, with separate task/scratch change lists; hidden verification excludes scratch. New checkpoints allow 4,096 entries, 2 MiB/file and 16 MiB total; patch previews are capped at 256 KiB and summarize scratch. A capture-limit failure preserves workspace/diagnostics and cannot produce a passing partial snapshot. Shared `Temp/opencode` writes remain outside benchmark scope, and opaque shell operations remain uncertain. OpenCode inherits its server environment, so the prompt instructs the worker to set `TMPDIR`, `TEMP` and `TMP` inside every temp-using command. This is cooperative routing, not automatic environment injection or an OS sandbox. Policy/version and requested scratch settings are recorded explicitly. Historical evidence without the policy retains strict task-only audit semantics; compare policy versions explicitly. See [scratch policy design and validation](docs/plans/20261019-implementation/scratch-policy.md).

`agent-bench smoke -x -m qwen38_23GB` is a separate integration diagnostic with fixed 60/10-second budgets, the same durable dispatch guards, protected temp probe and post-dispatch user-prompt attribution. It writes only `integration-acceptance/` evidence, with no canonical benchmark records or comparisons. Provider-bound system/tool payload is explicitly unverified and optional. [Exact command, artifacts and limits](docs/plans/20261019-implementation/integration-smoke-proposal.md). Live smoke execution requires separate authorization; it has not been run.

The worker sees a fresh public fixture. S0 and S1 are byte-exact archives outside it; a hidden verifier runs on a disposable S1 copy. Canonical scoring is `worker_first_attempt_full_success`. Expired task budgets, execution errors, unresolved termination and disqualifying scope changes cannot become passes from verifier output. Coordinator repair never changes the frozen worker score. Token/tool counters that are not collected remain unavailable. Retries, coordinator comparisons and multi-model repetition support remain later packages.

OpenCode 1.19.3 can leave `finish="tool-calls"` on a final StructuredOutput message. The adapter accepts that special case only with a matching requested JSON schema, a completed StructuredOutput tool, completed assistant timestamp, idle session and no incomplete tools. Arbitrary non-null structured data is insufficient. Normal abort/error confirmation and malformed-data handling preserve the corrective pass's fixes. See [source notes](docs/TERMINATION.md).

The original smoke task is bundled at `agent_benchmark/tasks/py-grep-smoke` and works from installed wheels. This is trusted-fixture process isolation, not a hostile-code sandbox. Snapshot and transcript scope audits retain known violations and uncertain operations separately. A verifier-passing task with uncertain scope is unscored, with unavailable scope compliance; known failures and expired task budgets retain their statuses. More complete worker-report auditing belongs to Phase 2.

Verifier exit zero alone is insufficient. The runner supplies `AGENT_BENCH_COMPLETION_PATH` and `AGENT_BENCH_VERIFICATION_NONCE`; after every assertion passes, the trusted verifier writes a JSON completion receipt with matching `nonce`, `status="passed"` and positive integer `checks_completed`. A missing/invalid receipt with exit zero is an infrastructure error. Submitted `SystemExit` at import/call boundaries fails the smoke task. Suite version 0.1.1 records this corrected verifier contract; old artifacts are not rescored.

Install both local packages into the intended environment:

```powershell
python -m pip install -e modules/benchmark_core -e modules/agent_benchmark
```

`agent-bench` was introduced at 1.0.0; install/refresh wrappers when first adopting that entry point. Existing editable installs load the 1.3.0 source changes without entry-point wrapper changes; reinstall to refresh package metadata. The bridge must already be cached/installed as `opencode-mcp@3.0.0`; npx is offline and auto-serve is disabled. Existing OpenCode auth environment variables are reused without logging secrets.

Validation from repository root, using the actual repo virtualenv:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy modules/benchmark_core/benchmark_core
```

[Plan/model allocation](docs/plans/20261019-implementation/plan.md) · [Current handoff](docs/HANDOFF.md)


### Runtime memory safety

Local experiment workers record host RAM, top resident processes, and GPU memory during dispatch
and observation. No automatic host RAM percentage or fixed available-RAM threshold is enabled.
Users may opt in with `agent-bench experiment run -M/--max-ram-percent 90`; that limit is applied both
while a worker runs and before a benchmark-initiated model load. `--max-ram-percent 100` retains its
legacy meaning of disabling the percentage check. A configured limit that cannot be measured stops
before dispatch with `ResourceLimitExceeded`; without a configured limit, missing RAM telemetry is
reported as unavailable and does not become a model-quality failure.

Model loads require LM Studio's context-specific estimate to fit measured free dedicated GPU memory
and combined available host/GPU capacity. A missing estimate or missing capacity measurement blocks
the load; an actual runtime allocation failure is reported without blind retry. The former fixed 2
GiB GPU reserve, 4 GiB combined reserve, 4 GiB available-RAM floor, and 1.25x model-file-size rule
were removed because they were not supported as universal capacity boundaries. After unload, the
harness verifies the model inventory is empty and records resource measurements; it does not wait for
a utilization percentage. Unconfirmed worker termination still blocks future dispatch. These checks
cannot prevent a sudden native allocation failure or guarantee shared GPU memory headroom.

Before `run`, `experiment run`, or `smoke` dispatches, it reconciles any pending receipt. It confirms
the exact prior job, or aborts the bound OpenCode session and waits for fresh terminal evidence. A
receipt is cleared only after that confirmation; the old evidence and workspace are preserved. If
OpenCode cannot confirm termination, the new run stops before model transitions or dispatch.

`benchmark.log` records RAM and the largest resident processes every five seconds during local
inference (names, PIDs and RSS only). Shared services are never force-killed. Resource percentages
are observations; capacity decisions use the LM Studio estimate and current measured memory.


### Auditable smoke-task tools

`py-grep-smoke` now declares `opencode_tool_profile: "file-tools-v1"` (task suite 0.2.0).
For LM Studio/OpenCode runs the harness registers a trial-local `benchmark-files` role with
file inspection/editing tools and no shell, delegation, skills or web tools. The worker implements
the deliverable and finishes; the harness runs the hidden verifier. This avoids turning optional
worker-run shell checks into unprovable strict scope compliance or spending the budget debugging
Windows test-script output. It does not guarantee a model's implementation will pass.

Effective tool permissions are checked before submission and retained with trial evidence.
Other trusted task manifests default to `shell-v1`; unknown profiles fail validation. Codex/agy
CLI workers retain their separate existing behavior. Historical scores, scope uncertainty, timeouts,
and the runtime memory policy is described above. Compare runs with matching task/tool profile provenance.

The opt-in `retrieval-files-v1` profile is a separate experimental condition. Before using it,
install the optional local-agent OpenCode tools by reviewing
`local-agent setup plan --code-retrieval -o retrieval-plan.json` and applying it with
`local-agent setup apply -i retrieval-plan.json`. A retrieval task receives the common `benchmark-files` role,
which keeps default deny and allows only the existing file tools plus `code_locate` and
`code_context`; shell, MCP, skills and web tools remain denied. The task manifest's exact profile,
identical role prompt hash and effective permissions are retained for comparison. No live
retrieval-profile evaluation is implied by this implementation.

The distinct `retrieval-structural-v1` condition is for Python structural
retrieval experiments. Set that exact value in a task's `opencode_tool_profile`
manifest field and install the optional tools with
`local-agent setup plan --structural-retrieval` followed by reviewing and
applying the saved plan. Its common `benchmark-files` role allows the usual safe
file tools plus `code_locate`, `code_context`, `code_symbols`, and `code_map`;
default deny remains in force and shell, MCP, skills and web remain denied.
The exact profile, shared prompt identity and effective permissions remain part of
the trial evidence. This is an auditable B3 variant, not evidence of a quality
or efficiency improvement; controlled comparison with matching context and
runtime conditions is still required.

### Explicit judgments and comparison conditions (1.13.0)

Trial details expose functional correctness, final-artifact compliance, execution compliance, budget
compliance and confirmed termination as passed/failed/unknown judgments. `agent.scope_compliance`
remains their compatible combined scope metric. A correct CLI artifact without trusted execution
history remains functionally successful and canonically unscored. Missing or inconsistent evidence
cannot produce a strict pass. First/last edit and completion timings are available only from correlated
runtime timestamps; first edit is not first correct edit.

Numerical rankings omit zero-scored variants. Reports retain their functional observations, durations,
trial counts and uncertainty reasons as unranked diagnostics. Explicit comparison conditions cover
trusted task/verifier digests, tool profile, scope/isolation policy, effective context, actual budgets,
host/runtime identity and effective role/permissions. Different known conditions get separate groups;
missing historical conditions remain diagnostic and do not establish equivalence. Historical artifacts
are not migrated or rewritten. Model identity remains separate from agent-runtime identity.

File-role preflight validates ordered effective permissions, exact role/prompt identity and only the
installed runtime's verified tool-output exception. Trust currently supports OpenCode 1.19.3 with an
inspectable local listener process; unsupported versions/layouts fail closed with a diagnostic. Shared
OpenCode configuration is untouched. This is not an OS sandbox. `sandboxed-shell-v1` is explicitly
unavailable pending the real worker/verifier boundary described in
[the shell-boundary decision](docs/plans/20261020-final-hardening/shell-boundary.md).
See [pending live acceptance](docs/plans/20261020-final-hardening/live-acceptance.md).

### Forensic fixes (1.14.0)

Prompt instructions now keep completion reports in the final response or StructuredOutput and clarify
that edit-tool replacement text is literal source. OpenCode 1.19.3's exact edit `File ... not found`
error is recorded as a proven pre-mutation failure; other failed mutations remain uncertain. Runtime
comparison identity fingerprints only the ordered permissions after the benchmark role's default-deny
reset, so overridden inherited grants do not split equivalent runs.

## Local Agent Efficiency fixtures and comparison

Four fixed offline fixtures cover repository investigation, a focused bug fix,
a coordinated two-file change, and test development. Their manifests use the
same `file-tools-v1` profile and are not rewritten per condition. Select a
condition with `experiment run --tool-profile file-tools-v1`,
`retrieval-files-v1`, or `retrieval-structural-v1`; the role name and worker
prompt remain byte-identical while the default-deny tool surface changes.

Validate the fixtures and schedule offline with:

```powershell
python -m pytest tests/efficiency_fixtures_test.py tests/efficiency_experiment_test.py -q
```

From `modules/agent_benchmark`, inspect the deterministic schedule without
dispatching a worker:

```powershell
python -B experiments/local_agent_efficiency.py --model-key <exact-verified-modelKey>
```

The optional `--execute` flag launches 36 individual runs and is reserved for a
separately approved Gate B. The plan uses four tasks, three repetitions,
counterbalanced B0/B2/B3 orders (each of the six orders twice), seed `20261029`,
the canonical 120-second task budget, a 15-second grace, 32,768 context, a 95%
RAM ceiling, no model transitions, and a two-hour deadline. It stops on the
first failed/invalid attempt and never retries. The script does not verify the
model identity or effective runtime limits; preflight is required before use.

`benchmark_core.compare_runs` still requires exact condition equality by
default. The opt-in `declared-tool-intervention-v1` contract permits only the
versioned B0/B2/B3 tool profile, allowed-tool list, and permission digest to
differ. It still requires identical task/verifier and suite fingerprints,
worker role and prompt, exact model identity/quantization, and effective
context, output, temperature, top-p, reasoning and provider-options fingerprint.
The current runtime evidence producer does not capture all effective inference
settings, so real OpenCode runs remain incomparable until those values can be
verified and recorded. This is a readiness blocker, not a reason to weaken the
comparison contract.


## External Benchmark Evaluation — Harbor Integration

Agent Benchmark provides integration with external coding benchmarks using the Harbor evaluation framework (`harbor==0.25.0`):
1. **Aider Polyglot** (`aider/aider-polyglot`): 225 coding exercises across Python, C++, Go, Java, JavaScript, and Rust.
2. **Terminal-Bench 2.0** (`terminal-bench/terminal-bench-2`, 89 tasks) and **Terminal-Bench 4.0.0** (`terminal-bench/terminal-bench@4.0.0`, 66 tasks) are separate datasets with distinct task sets and source revisions. The short `terminal-bench` and `terminal-bench-cpu-only` aliases refer to the 2.0 catalog; the default selection is the pinned five-task CPU subset. The subset is `build-cython-ext`, `regex-log`, `sqlite-db-truncate`, `nginx-request-logging`, and `log-summary-date-ranges`.

The architecture separates responsibilities cleanly:
- **`agent_benchmark`**: CLI, planning, task filtering, deterministic seeds, lifecycle guards, results normalization, and comparison.
- **Harbor**: external task isolation, containerized sandbox management, agent invocation, and authoritative verification.
- **`benchmark_core`**: persistent storage (`RunInfo`, `TrialResult`, `MetricValue`), statistics, and leaderboard reporting.

### Requirements & Setup
- **Harbor**: Install or pin `harbor==0.25.0` via `uv tool install harbor` or run on-demand via `uv tool run --from harbor==0.25.0 harbor`.
- **Docker**: Harbor requires an active Docker daemon (e.g., Docker Desktop for Windows with WSL2 engine) for containerized agent isolation and verification. If Docker is offline, planning and import remain available, but execution fails closed before dispatch.
- **Windows 11 / WSL2 Deployment**: Run Docker Desktop with the WSL2 backend enabled. For local model servers (e.g., LM Studio), ensure the host model server is accessible from container networks via `host.docker.internal`.

### CLI Commands (`agent-bench external`)

```powershell
# List available datasets, task counts, and environment readiness:
agent-bench external list
agent-bench external list --format json

# Plan a benchmark run deterministically without execution (zero inference):
agent-bench external plan -d aider/aider-polyglot --language python -n 5 -s 42
  agent-bench external plan -d terminal-bench-cpu-only -a oracle
  agent-bench external plan -d terminal-bench/terminal-bench@4.0.0 -a oracle -t layout-config-recreation2

# Execute an authorized external benchmark (requires -x/--execute):
agent-bench external run -x -d aider/aider-polyglot -a oracle -t python/bank-account
  agent-bench external run -x -d terminal-bench-cpu-only -a oracle

# Import completed native Harbor jobs into canonical benchmark_core records:
agent-bench external import -j <harbor-job-dir> -o reports/harbor/<job_id>
agent-bench external import -j <harbor-job-dir> --format json

# Rebuild comparative leaderboards across imported runs:
agent-bench external report -o reports/harbor
agent-bench external report -o reports/harbor --format markdown
```

### Scoring and Provenance Contracts
- **Scoring Basis**: `external_verifier_pass_v1`. Solved tasks earn 1.0 point, valid failing tasks earn 0.0 points.
- **Failures & Timeouts**: Budget expirations (`AgentTimeoutError`) are classified as `timed_out` (0.0 points). Container or model-provider crashes are classified as `infrastructure_error` (points `unavailable`).
- **Isolation Scope**: External verification does not assert internal strict-scope compliance; `scope_compliance` is explicitly recorded as `unavailable`.
- **Idempotent Import**: Reimporting the same Harbor job updates records cleanly without generating duplicate trial IDs.
