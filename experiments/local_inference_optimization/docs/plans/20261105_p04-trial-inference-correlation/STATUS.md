# P04 verified trial-to-inference correlation status

- Base: `f6aac8b98c2931ae7cc474dd15f0aaf4df20eb56`
- Branch: `agent/local-inference-p04-correlation-20261105`
- Worktree: `.worktrees/agent-local-inference-p04-correlation-20261105`
- State: offline implementation and validation complete; isolated checkpoint is ready. No live inference, Harbor workload, or service operations were performed.
- Strict correlation is enabled for new monitored OpenCode v1 study manifests. Older manifests retain temporal legacy behavior and report readers remain compatible.
- Real Harbor container propagation is not verified: installed Harbor source confirms an explicit `env` mapping into container execution and OpenCode documents inline config/provider headers, but validating their interaction requires launching a Harbor task, which was prohibited.
- Same-user local processes can request the correlation-write scope through Monitor's protected local IPC. A task process that can read its own environment can copy its credential until close; the gateway verifies issuance/scope, not process identity. The credential is never persisted or forwarded upstream.
- Initial sandbox attempts at gateway/local-control tests were blocked by Windows event-loop socketpair and named-pipe permissions. The offline mocked test selection then passed under scoped unsandboxed execution; no inference service or Harbor process was contacted.
- Next after checkpoint: separately authorize live Harbor-to-container acceptance; do not merge or push without separate authorization.

## Validation

- `pytest -o addopts= -q modules/llm_monitor/tests/gateway_test.py modules/llm_monitor/tests/inference_storage_test.py modules/llm_monitor/tests/inference_recording_test.py modules/llm_monitor/tests/inference_web_test.py modules/llm_monitor/tests/local_control_test.py modules/llm_monitor/tests/inference_correlation_test.py modules/llm_monitor/tests/inference_correlation_storage_test.py` — 59 passed (scoped unsandboxed; mocked/in-process only).
- `pytest -o addopts= -q modules/agent_benchmark/tests/suite_test.py modules/agent_benchmark/tests/suite_monitor_test.py modules/agent_benchmark/tests/harbor_runner_test.py modules/agent_benchmark/tests/suite_archive_test.py modules/agent_benchmark/tests/opencode_correlation_test.py` — 57 passed.
- `PYTHONPATH=experiments pytest -o addopts= -q experiments/local_inference_optimization/tests/contracts_test.py experiments/local_inference_optimization/tests/compiler_test.py experiments/local_inference_optimization/tests/registry_test.py` — 77 passed.
- Gateway cross-origin/content-type test — 1 passed in sandbox; local capability scope subset — 3 passed.
- Ruff lint passed on changed Python files. Full format check reports existing formatting drift throughout touched legacy files; newly added files and small OpenCode adapter were formatted.
- `git diff --check` and `compileall` passed after implementation edits.

## Protected scope

- Main checkout untracked artifacts, existing P02/SV/P15a worktrees, Resource Coordinator worktree, and all preserved reports remain outside this work.
