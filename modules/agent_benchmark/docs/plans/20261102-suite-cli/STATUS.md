# Status: Agent Benchmark Suite CLI

**Stage:** Suite CLI committed; frozen revision preflight correction validated and ready for local integration
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
