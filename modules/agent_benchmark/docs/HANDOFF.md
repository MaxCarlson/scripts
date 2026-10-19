# agent_benchmark handoff — second model-switch checkpoint (Task 1b complete)

## Goal and location

Implement the thin independent coding-worker evaluator in the user-supplied consolidated plan plus final amendment. Model switching concerns the agent implementing the software; no local-agent delegation is allowed.

- Workspace: C:/Users/mcarls/src/scripts-agent-benchmark
- Branch: agent/agent-benchmark
- Tested implementation commit (1b): 85dca55522a867e4fafbb4299ca493d869fc2d5f
- Preceding foundation commit (1a): da8dda2bbe69b41a40c6938753b96ed259de62b8
- Base: 46768a8d
- Ownership: modules/agent_benchmark only. Do not edit benchmark_core, local_agent_bridge, other worktrees or unrelated paths.
- Full staged plan/model table: plans/20261019-implementation/plan.md
- Current status/checklist: plans/20261019-implementation/{STATUS.md,checklist.md}

## Completed slice (Task 1a + Task 1b)

### 1a: Bounded lifecycle safety foundation (`agent_benchmark/lifecycle.py`)
- `WorkerHandle`: durable job/session/message IDs and workspace.
- `Observation`: fresh session/turn/tool evidence; cached cancelled/completed job status cannot establish termination.
- `LifecycleBridge` async protocol: `cancel(handle)`, `observe(handle)`.
- `confirm_termination`: finite cancellation+confirmation budget (default 10s), uncertainty diagnostics, no unbounded await of cancelled I/O.
- `DispatchGuard`: allocate fresh owned workspace; latch unresolved decision to halt batch and emit warning.
- `cleanup_workspace`: exact path ownership and termination checks, bounded Windows-lock retries; returns `CleanupOutcome` separately from evaluation, never kills processes.

### 1b: Deterministic task fixture and verifier (`tasks/py-grep-smoke/`, `tests/fixture_test.py`)
- Original smoke fixture (`tasks/py-grep-smoke`):
  - `task.json`: Manifest with `task_id` ("py-grep-smoke"), `suite_version` ("0.1.0"), `category` ("smoke"), `time_budget_seconds` (60), `allowed_paths` (["grep.py"]), `forbidden_paths` (["instruction.md", "task.json"]), and relative `verifier` path ("verifier/check.py"). All paths relative, no `..`.
  - `instruction.md`: Worker instructions specifying substring `grep(pattern, lines, ignore_case=False) -> list[str]`, stable ordering, duplicate preservation, case handling, empty strings, Unicode, and editing constraints.
  - `seed/grep.py`: Deliberately raises `NotImplementedError`. Worker can edit only `grep.py`.
  - `verifier/check.py`: Coordinator-only stdlib verifier running against frozen workspace, outside worker tree. Exit 0 for pass, 1 for incorrect implementation, 2 for verifier infrastructure failure. Verifies basic match, no match, default and explicit case sensitivity, order preservation, duplicates, empty pattern/lines, literal substring handling (no regex interpretations), Unicode, and non-mutation of input.
- `tests/fixture_test.py`: Comprehensive test suite verifying manifest validity, seed failure (exit 1), known-good success (exit 0), infrastructure errors (exit 2), bad implementations (exit 1), missing files (exit 1), and timeout distinction (`subprocess.TimeoutExpired`).

## Validation and review

From `modules/agent_benchmark`:

```powershell
python -m pytest tests -q --basetemp=.pytest_tmp_root/lifecycle --tb=short
python -m ruff check agent_benchmark tests tasks
```

Results:
- Tests: 37 passed, 1 skipped (Windows symlink privilege unavailable in 1a); 0 failures.
- Ruff: All checks passed clean across `agent_benchmark`, `tests`, and `tasks`.

## Verified runtime constraints

- OpenCode 1.19.3 installed; opencode-mcp 3.0.0.
- Verifier runs strictly outside the worker workspace as a separate unprivileged process against a frozen snapshot.
- No upstream copyrighted content imported; fixture is an original smoke implementation (`suite_version: 0.1.0`).

## Next package: 1c integration (Return to Codex 6.1 Sol Medium)

Resume Phase 1c integration:
1. Obtain tested `benchmark_core` Gate 1 commit SHA and evidence; cherry-pick into this branch and import canonical types (`RunInfo`, `TrialResult`, `MetricValue`, etc.).
2. Add minimal supported MCP client adapter for OpenCode / opencode-mcp 3.0.0; bypass terminal cache via fresh session/message reconciliation.
3. Wire lifecycle (1a) and task fixture (1b) with byte-exact S0/S1 snapshots outside the worker workspace.
4. Establish the critical canonical regression: verify S1 incorrect, then prove repair S3 leaves worker first-pass false and status failed.
5. Provide guarded CLI with paired arguments.

## Copyable next-agent instruction

Work sequentially in C:/Users/mcarls/src/scripts-agent-benchmark on agent/agent-benchmark. Confirm cwd, branch and Git status before edits. Read modules/agent_benchmark/docs/HANDOFF.md and task 1c of modules/agent_benchmark/docs/plans/20261019-implementation/plan.md. Incorporate tested benchmark_core Gate 1 commit once available. Integrate lifecycle foundation (commit da8dda2b) with py-grep-smoke fixture (commit 85dca555). Maintain verifier isolation outside worker workspace and enforce S0/S1 immutability. No local-agent delegation, and no edits outside modules/agent_benchmark without authorization.
