# Status: Agent Benchmark Suite CLI

**Stage:** Suite CLI, monitored inference routing, and broken-pipe classification merged; smoke trial reconciled as infrastructure-invalid; ten-task cohort blocked pending valid scored smoke
**Branch:** `feature/agent-benchmark-suite-cli-llm-friendly-20261102`
**Worktree:** `C:\Users\mcarls\src\scripts\.worktrees\agent-benchmark-suite-cli-20261102`
**Base:** `d13372389ef6b5f344e26ee150e67722a50a92ac`

## Decisions

- Use existing Harbor planner/runner/importer; schedule one selected task per Harbor job so accepted task results can be checkpointed.
- Freeze the Python cohort task order directly from the preserved, untracked baseline manifest in the primary checkout; preserve source revision and raw result artifacts.
- Monitor status is read from its authenticated/local inference API, using an optional configured authorization header; no credential is copied to provenance.
- Background execution uses a detached module worker with per-run lock and file-backed logs.
- OpenCode monitored routing pins `openai_chat_completions`; the requested recording state must already be active and healthy.
- Before measured execution, Harbor 0.25.0 resolves the selected Aider registry tasks; the run saves and passes the same registry snapshot with `--registry-path`.
- Each Harbor task is checked against the pinned source revision on import; mismatches are infrastructure-invalid and never scored.
- Live request IDs and safe token metadata are captured from LLM Monitor; exact request-to-task linkage is not claimed without a trustworthy correlation key.

## Progress

- Verified baseline and created isolated worktree/branch.
- Read repository Python/CLI guidance and existing Harbor/LLM Monitor interfaces.
- Plan recorded in `plan.md`.
- Added frozen cohort manifests, per-task Harbor orchestration, checkpoint/report storage, monitor preflight, output capture, detached worker and CLI wiring.
- Added 40 focused suite, monitor and CLI tests covering manifests, flags, classification, authorization, resume/retry, output capture, monitoring preflight, background operation and workload fidelity under `-F`.
- The Windows detached worker lifecycle passed a real subprocess fixture with all tasks already completed; it produced the report and exited without inference.
- Benchmark Core tests passed. LLM Monitor recording tests passed. Relevant Agent Benchmark CLI/planner tests passed.
- Full module suites were attempted but not completed: existing Harbor runner checks rely on Docker Desktop access, and LLM Monitor's TestClient loopback test stalls under this Windows sandbox. These limits do not affect the mocked gateway suite checks.
- No ten-task benchmark or live model inference was run. No LLM Monitor runtime state was changed.
- Commit: `ce9250154f7519eb637c2c59451cd420f8e5f7c3` (`feat(agent-benchmark): add persistent suite CLI`).
- Focused correction validation: 57 relevant Agent Benchmark tests passed; Ruff passed. The Agent Benchmark wheel built with `pip wheel --no-build-isolation --no-deps`; CLI run help was inspected. One unrelated Docker readiness test was excluded after Docker Desktop pipe access was denied in this sandbox.
- Registry behavior was inspected in Harbor 0.25.0 `DatasetConfig`: registry resolution yields each task's Git URL and commit, and `registry_path` selects the local snapshot. The same snapshot is supplied to Harbor execution; post-run lock verification remains enabled.
- Correction commit `399e62db` is validated and ready to merge into current local `main`; the primary checkout's untracked Harbor evidence remains untouched. No push is authorized or planned.
- Remaining operational validation: run the documented one-task monitored smoke after Docker and LLM Monitor are available; verify gateway request evidence and recording health. The full ten-task cohort remains deliberately unrun.

## Monitor integration repair — 2026-11-02

- Worktree: `.worktrees/agent-benchmark-monitor-integration-20261102`, branch `fix/agent-benchmark-monitor-integration-20261102`, based on `5480ea69`.
- Host and Docker container reached the loopback monitor. The gateway deliberately has no `/v1/models` endpoint; the authenticated monitor API requires a same-origin header and publishes inventory at `/api/inference/v1/models`.
- Host preflight and per-task snapshots use the loopback API, while Harbor retains the container-facing gateway URL. Monitor and source failures stop further dispatch.
- Focused validation: 62 tests passed, one Docker-dependent test deselected; Ruff and local wheel build passed. Live one-task smoke and cohort replay remain pending.
- First smoke `suite-20261102T091234-9884b456ca` reached Harbor but OpenCode exited before inference because the built-in `openai` provider selected an incompatible Responses adapter. It is infrastructure-invalid, with no gateway request; preserve its evidence.
- A bounded OpenCode probe using `llm-monitor/qwen38_23GB` reached the gateway. The first monitor exposed a recorder lifecycle defect: its writer was not started despite healthy status. Its process and queued evidence remain preserved on port 8788.
- A second loopback monitor on port 8789 uses the repaired recorder and dedicated `reports/agent-bench-suite/monitor-integration-20261102-v2.sqlite3`. The provider probe completed with persisted request and assistant streaming records. Per-task checks now require recorded request IDs and content coverage before accepting a score.
- Next: validate the corrected provider and recorder through the one-task Harbor smoke; proceed to the ten-task replay only if that smoke passes.
- Smoke `suite-20261102T092755-fd3a322efd` used the pinned source revision and generated six completed recorded gateway requests with streamed assistant and tool traffic. Harbor failed to persist a complete trial because its Windows subprocess used a legacy encoding for Unicode exception text; the attempt remains infrastructure-invalid. The runner now forces UTF-8 for Harbor's Windows subprocess before a further smoke.
- Smoke `suite-20261102T093411-e48f660ced` executed the live monitored task `polyglot_python_beer-song`. Harbor container worker routed inference cleanly through `http://host.docker.internal:8789/v1` (`openai_chat_completions`). LLM Monitor captured and recorded 19 inference requests during the coding task window (09:35:29Z to 09:37:07Z) with 390 content segments persisted into `reports/agent-bench-suite/monitor-integration-20261102-v2.sqlite3` (`recording_mode='content'`) and zero recorder drops. However, OpenCode exited nonzero with an uncaught `EPIPE: broken pipe` thrown during stdout piping (`NonZeroAgentExitCodeError`), causing the verifier to execute on incomplete output and return raw reward 0.0. While the historical raw checkpoint originally labeled the trial `failed` (0.0 points), re-evaluation under the repository's authoritative broken-pipe classifier classifies the trial as `infrastructure_error` (`failure_cause=harbor_failed`, unscored, `points_awarded=None`). See `MONITOR_SMOKE_VALIDATION.md` for full evidence and upstream issue tracking. Full live qualification remains blocked pending a valid scored smoke trial free of infrastructure crashes before the ten-task cohort can be authorized.
