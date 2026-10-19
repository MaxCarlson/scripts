# agent_benchmark — 1.0.1

A thin evaluator around the existing OpenCode/MCP runtime. Phase 1c's integrated pipeline and P1 corrections are validated offline. The retained first live run was timed out under its 60-second budget; no new live run has been authorized for these corrections.

```powershell
agent-bench plan
agent-bench run -m MODEL_ID -x
agent-bench status -r reports/RUN_ID
agent-bench cleanup -r reports/RUN_ID       # preview
agent-bench cleanup -r reports/RUN_ID -x    # fresh reconciliation, then owned cleanup
```

`run` requires `-x/--execute`; plan, status and cleanup preview do not write or call models. Services must already be running. No command starts or reconfigures shared OpenCode/LM Studio services. Explicit configured LM Studio models only; no cloud fallback.

The default persistent state is `~/.local/share/agent-benchmark`, shared across output locations. Use the same `-s/--state-dir` across invocations; an unresolved job blocks later runs even if they use another report directory. An OS-held command lock serializes run/cleanup, while the unresolved receipt survives process exit. Never delete the receipt to bypass uncertain execution. `cleanup -x` requests supported cancellation when needed, then requires fresh matching session/turn/tool evidence. It preserves resources and blocking if termination cannot be confirmed. Cleanup failures never rescore trials.

Each invocation currently runs one smoke task, one explicit model and one repetition. `benchmark_core` alone supplies RunInfo, TrialResult, MetricValue, persistence, statistics and JSON/CSV/Markdown reporting. Outputs are `reports/<run_id>/{run.json,trials.jsonl,summary.json,summary.csv,report.md,evidence/}`. Exactly one trial is persisted per attempted repetition, including ordinary infrastructure failures and caller cancellation when storage is writable. Filesystem failures cannot guarantee persistence; uncertain execution still blocks dispatch.

The worker sees a fresh public fixture. S0 and S1 are byte-exact archives outside it; a hidden verifier runs on a disposable S1 copy. Canonical scoring is `worker_first_attempt_full_success`. Expired task budgets, execution errors, unresolved termination and disqualifying scope changes cannot become passes from verifier output. Coordinator repair never changes the frozen worker score. Token/tool counters that are not collected remain unavailable. Retries, coordinator comparisons and multi-model repetition support remain later packages.

OpenCode 1.19.3 can leave `finish="tool-calls"` on a final StructuredOutput message. The adapter accepts that special case only with a matching requested JSON schema, a completed StructuredOutput tool, completed assistant timestamp, idle session and no incomplete tools. Arbitrary non-null structured data is insufficient. Normal abort/error confirmation and malformed-data handling preserve the corrective pass's fixes. See [source notes](docs/TERMINATION.md).

The original smoke task is bundled at `agent_benchmark/tasks/py-grep-smoke` and works from installed wheels. This is trusted-fixture process isolation, not a hostile-code sandbox. Snapshot and transcript scope audits retain known violations and uncertain operations separately. A verifier-passing task with uncertain scope is unscored, with unavailable scope compliance; known failures and expired task budgets retain their statuses. More complete worker-report auditing belongs to Phase 2.

Verifier exit zero alone is insufficient. The runner supplies `AGENT_BENCH_COMPLETION_PATH` and `AGENT_BENCH_VERIFICATION_NONCE`; after every assertion passes, the trusted verifier writes a JSON completion receipt with matching `nonce`, `status="passed"` and positive integer `checks_completed`. A missing/invalid receipt with exit zero is an infrastructure error. Submitted `SystemExit` at import/call boundaries fails the smoke task. Suite version 0.1.1 records this corrected verifier contract; old artifacts are not rescored.

Install both local packages into the intended environment:

```powershell
python -m pip install -e modules/benchmark_core -e modules/agent_benchmark
```

`agent-bench` was introduced at 1.0.0; install/refresh wrappers when first adopting that entry point. Existing editable installs pick up the 1.0.1 patch without wrapper changes. The bridge must already be cached/installed as `opencode-mcp@3.0.0`; npx is offline and auto-serve is disabled. Existing OpenCode auth environment variables are reused without logging secrets.

Validation from repository root, using the actual repo virtualenv:

```powershell
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/agent_benchmark/tests -q -rs --basetemp=modules/agent_benchmark/.pytest_tmp_root/final
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m pytest modules/benchmark_core/tests -q -rs
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m ruff check modules/agent_benchmark/agent_benchmark modules/agent_benchmark/tests modules/benchmark_core
& C:/Users/mcarls/src/scripts/.venv/Scripts/python.exe -m mypy modules/benchmark_core/benchmark_core
```

[Plan/model allocation](docs/plans/20261019-implementation/plan.md) · [Current handoff](docs/HANDOFF.md)
