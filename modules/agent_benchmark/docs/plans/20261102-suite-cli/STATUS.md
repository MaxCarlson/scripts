# Status: Agent Benchmark Suite CLI

**Stage:** OpenCode EPIPE resolved; smoke trial qualified with clean exit 0 and valid score; sequential ten-task cohort executing under LLM Monitor content recording
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
- Resolved OpenCode EPIPE root cause: Harbor 0.25.0 unconditionally passed `OPENCODE_FAKE_VCS="git"` to `opencode run`. In non-git benchmark containers, OpenCode's internal git commands exited 128, abruptly terminating Node/Bun stream pipes on stdout write and scheduling process exit code 1. Patched Harbor adapter to set `OPENCODE_FAKE_VCS` conditionally; implemented `ensure_harbor_opencode_compatibility()` in `agent_benchmark.harbor.runner` to auto-detect and patch uv caches/site-packages prior to execution.
- Valid scored smoke `suite-20261102T111227-18a25987ae` passed qualification on `polyglot_python_beer-song`: OpenCode terminated cleanly with exit 0 (`exception_info=null`); native verifier evaluated test results (raw reward 0.0); classified as valid scored `failed` (0.0 points, 0 infrastructure invalid); 13 inference requests and 893 content segments recorded in SQLite with 0 recorder drops. Smoke requirement met.
- Executed authorized sequential ten-task cohort `aider-python-10` (`suite-20261102T112509-9bb0785010`) under `llm-monitor/qwen38_23GB` and content-mode recording:
  - 10 planned, 10 scored, 5 passed (`pig-latin`, `react`, `robot-name`, `transpose`, `variable-length-quantity`), 5 failed (`beer-song`, `bottle-song`, `bowling`, `dot-dsl`, `zipper`), 0 timed out, 0 infrastructure invalid.
  - Pass rate: 50.0%, 100.0% coverage. Total duration: 3197.7s (~53.3 minutes).
- Implemented and integrated reusable evidence archiver:
  - Added `agent_benchmark.suite_archive` and CLI command `agent-bench suite archive` (`create` dry-run/execute, `verify` offline).
  - Maintained script entry point at `modules/agent_benchmark/scripts/preserve_suite_evidence.py`.
  - Added 6 unit tests in `modules/agent_benchmark/tests/suite_archive_test.py`.
  - Updated documentation in `modules/agent_benchmark/docs/suite-cli.md`.
- Comprehensive evidence preservation and verification:
  - Live consistent backup and final comprehensive archive created at `reports/agent-bench-suite/suite-20261102T112509-9bb0785010/evidence/20261102T122809Z-b213eb74` with `-N` (harbor-jobs, trial logs, verifier results, and API snapshots).
  - Offline cryptographic hash and SQLite integrity verification passed cleanly (`integrity_ok=True`, 0 problems).
- Investigated transcript truncation root cause:
  - Tracing confirmed `LiveInferenceStore`'s 2,000,000-byte in-memory ring buffer clipped segments to 0 bytes after cumulative text exceeded 2 MB during long runs.
  - Tasks 1 through 8 had 0 truncated segments (100% full content recorded).
  - Tasks 9 and 10 had 222 content segments clipped to empty text in SQLite.
  - Confirmed full transcripts remain 100% recoverable from Harbor's native artifacts (`harbor-jobs/.../agent/opencode/xdg-data/opencode/opencode.db` and `trajectory.json`), meaning zero agent trajectory data was lost.
  - Documented root cause and decoupled gateway in-flight accumulator architecture in `modules/llm_monitor/docs/DEFECT_RECORDER_LIVE_STORE_COUPLING.md`.
- Full test suite: 528 passed, 3 skipped, 0 failures in 85.92s. Ruff checks pass with 0 errors.
