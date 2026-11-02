# Monitored smoke validation — 2026-11-02

The original blocked run `suite-20261102T085714-17363aee01` remains preserved with ten pending tasks. Its manifest has the earlier incompatible OpenCode provider selector and must not be resumed.

The first smoke `suite-20261102T091234-9884b456ca` failed before model inference with OpenCode `t.responses is not a function`. The generated `openai` provider combined OpenCode's built-in Responses selection with the OpenAI-compatible SDK. The requested model ID is now retained under the separate `llm-monitor` provider selector. The next smoke `suite-20261102T092755-fd3a322efd` reached the gateway, but Harbor could not write a complete native trial because its Windows Python subprocess used a legacy encoding. Both attempts remain infrastructure-invalid.

The recorder initially reported healthy while its writer had never started. The original monitor on loopback port 8788 remains running with its unpersisted probe events in memory. A separately started monitor on `127.0.0.1:8789` uses the corrected recorder and `reports/agent-bench-suite/monitor-integration-20261102-v2.sqlite3`. Docker's `host.docker.internal:8789` reached the same HTTP service. Authentication was kept in the local process and omitted from evidence.

The third smoke `suite-20261102T093411-e48f660ced` used `llm-monitor/qwen38_23GB`, `openai_chat_completions`, the container URL `http://host.docker.internal:8789/v1`, and frozen revision `f30b14415dd733c83627204bad0af69a89ceb46f`. The native lock contains that revision. The checkpoint contains 19 temporally observed request IDs; all 19 were found completed in content-mode SQLite history, with user, assistant streaming, and tool-call categories present. The recorder reported zero dropped events. Recorded provider usage summed to 313783 input and 7530 generated tokens across those IDs; request-window correlation does not prove exhaustive or exclusive attribution when other clients share the gateway.

The native verifier reward was 0, but OpenCode also exited nonzero with an uncaught `EPIPE: broken pipe` after tool calls. Its last structured `step_finish` reason was `stop`. The original suite checkpoint and report labeled the trial `failed`; those files are preserved as raw historical evidence. Re-evaluation with the corrected classifier yields `infrastructure_error`, no score. The [upstream Harbor issue](https://github.com/harbor-framework/harbor/issues/4019) describes the same pattern and leaves its cause unresolved. Disabling tools, formatters, or changing the agent workload has not been used as a workaround. A valid scored smoke remains required before the ten-task replay.

After the upstream OpenCode broken-pipe cause is resolved without changing benchmark methodology, start an authenticated content-recording monitor and run the one-task smoke from `docs/suite-cli.md`; use `-U http://host.docker.internal:8789/v1 -H http://127.0.0.1:8789` if retaining this port. Confirm the native agent exit, lock, verifier result, checkpoint, request IDs, recorder health and persisted content categories before launching the sequential cohort.

## OpenCode EPIPE Root Cause Resolution & Valid Smoke Qualification — 2026-11-02

The root cause of the broken pipe failure (`EPIPE: broken pipe, write`) was isolated down to Harbor's OpenCode agent adapter (`harbor.agents.installed.opencode.OpenCode.run` line 888), which unconditionally injected `env["OPENCODE_FAKE_VCS"] = "git"`. In non-git benchmark workspaces such as `/app` in Aider Polyglot tasks, OpenCode 1.19.5's internal `git` subcommands (`git symbolic-ref`, `git remote`, etc.) terminate immediately with exit code 128 (`fatal: not a git repository`). The abrupt closure of git's input/output streams triggers an unhandled `EPIPE: broken pipe, write` in Node/Bun stream lifecycle on stream write (`internal:streams/destroy` -> `emitErrorCloseNT`). Bun catches the unhandled exception, prints the stack trace, and schedules process exit code to 1 (`EXIT=1`). Harbor executes under `set -o pipefail`, converting the nonzero exit code into `harbor.agents.installed.base.NonZeroAgentExitCodeError`.

When `OPENCODE_FAKE_VCS` is not injected in non-git directories, OpenCode runs cleanly without git snapshot tracking and exits with status 0 and no EPIPE.

### Compatibility Fix

1. In Harbor's OpenCode adapter `harbor/agents/installed/opencode.py`, `OPENCODE_FAKE_VCS` is made conditional (`if os.environ.get("OPENCODE_FAKE_VCS"): env["OPENCODE_FAKE_VCS"] = os.environ["OPENCODE_FAKE_VCS"]`), preventing unsolicited git snapshot tracking in non-git benchmark directories.
2. An automated compatibility guard `ensure_harbor_opencode_compatibility()` was integrated into `agent_benchmark.harbor.runner`. It scans uv tool caches and Python site-packages environments prior to executing OpenCode Harbor runs, idempotently verifying and patching the adapter if unpatched.
3. Unit test coverage was added in `modules/agent_benchmark/tests/harbor_runner_test.py` (`test_ensure_harbor_opencode_compatibility_patches_target_and_is_idempotent`, `test_find_harbor_opencode_adapters_smoke`) and regression coverage in `modules/agent_benchmark/tests/harbor_status_test.py` (`test_synthetic_subprocess_deterministic_pipe_failure_handling`).

### Fourth Smoke Validation (`suite-20261102T111227-18a25987ae`)

The fourth smoke test was executed against `polyglot_python_beer-song` on dataset `aider/aider-polyglot` at frozen revision `f30b14415dd733c83627204bad0af69a89ceb46f`:

- **Model Requested:** `openai/qwen38_23GB`
- **Effective Monitored Provider:** `llm-monitor/qwen38_23GB`
- **Protocol:** `openai_chat_completions`
- **Harbor Gateway:** `http://host.docker.internal:8789/v1`
- **Monitor Origin:** `http://127.0.0.1:8789`
- **Process Lifecycle:** OpenCode executed all steps and tool calls (`glob`, `read`, `bash`, `write`), completed trajectory recording, and terminated cleanly with exit status 0. `result.json` records `exception_info: null`.
- **Authoritative Verifier:** Harbor's native verifier ran `pytest` in the container against the model's implementation, confirming raw reward `0.0` (5 tests passed, 3 failed due to missing blank-line verse separator).
- **Classification:** The trial was evaluated and accepted as a valid scored failure (`canonical_status="failed"`, `points_awarded=0.0`, `infrastructure_invalid=0`).
- **Telemetry & Recording:** LLM Monitor recorded 13 temporally correlated requests during the trial window with 893 content segments in `reports/agent-bench-suite/monitor-integration-20261102-v2.sqlite3` (`mode='content'`). Recorder reported 0 dropped observations and remained completely healthy.

The smoke qualification requirement was successfully satisfied, unblocking authorization for the sequential ten-task cohort `aider-python-10`.
