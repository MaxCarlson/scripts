# agent_benchmark handoff — first model-switch checkpoint

## Goal and location

Implement the thin independent coding-worker evaluator in the user-supplied consolidated plan plus final amendment. Model switching concerns the agent implementing the software; no local-agent delegation is allowed.

- Workspace: C:/Users/mcarls/src/scripts-agent-benchmark
- Branch: agent/agent-benchmark
- Tested implementation commit: da8dda2bbe69b41a40c6938753b96ed259de62b8
- Base: 46768a8d
- Ownership: modules/agent_benchmark only. Do not edit benchmark_core, local_agent_bridge, other worktrees or unrelated paths.
- Full staged plan/model table: plans/20261019-implementation/plan.md
- Current status/checklist: plans/20261019-implementation/{STATUS.md,checklist.md}

## Completed slice

agent_benchmark/lifecycle.py provides:
- WorkerHandle: durable job/session/message IDs and workspace.
- Observation: fresh session/turn/tool evidence; cached cancelled/completed job status cannot establish termination.
- LifecycleBridge async protocol: cancel(handle), observe(handle). No concrete transport adapter yet.
- confirm_termination: one finite cancellation+confirmation budget (default 10 seconds), uncertainty diagnostics, no unbounded await of cancelled I/O.
- DispatchGuard: allocate fresh owned workspace; record unresolved decision latches batch stop and emits warning.
- cleanup_workspace: exact ownership/path/termination checks, bounded Windows-lock retries; returns CleanupOutcome separately from evaluation, never kills processes.

pyproject.toml and __init__.py version 0.1.0; no CLI entry point, no benchmark_core dependency until integration. Tests have module-local temporary setup.

## Validation and review

From modules/agent_benchmark:

```powershell
python -m pytest tests -q --basetemp=.pytest_tmp_root/lifecycle --tb=short
python -m ruff check agent_benchmark tests
```

26 passed, 1 skipped (Windows symlink privilege unavailable); Ruff passed. Native read-only review found one adapter-exception handling gap; two custom-transport tests failed before fix and pass afterward. External CancelledError propagation tested. git diff --cached --check passed before implementation commit. Initial path/temp setup errors were corrected; no outstanding failures.

This is an offline foundation, not M1 completion. No task executed against a real model. S0/S1 capture, S1-fail/S3-pass canonical regression, actual scoring, adapters and reports are not implemented. Cleanup/evaluation independence is structural here; full canonical-result regression belongs to 1c.

## Verified runtime constraints

Installed opencode-mcp 3.0.0 sets cached cancelled immediately after successful abort; job_get/check may return terminal cache. observe adapter must use fresh underlying session/message/tool state and correlate exact turn. Never map a failed status request or missing assistant to finished. Incomplete/unknown tools mean possibly active. Use one new session per trial, never reuse unresolved workspace, never terminate shared services. Cancellable async transport only; persist handle before waiting, preserve handle/workspace on external cancellation.

OpenCode 1.19.3 installed; MCP setup returned server UNREACHABLE during reconnaissance. No services started/configured. Core agent branch still at base when checked; no tested Gate 1 SHA supplied. Do not create provisional canonical data models or serializers. Incorporate tested Gate 1 commit only once identified with passing evidence; integration belongs to Sol.

## Next package: 1b only

Recommended implementing model: Gemini Flash; 6-Luna-High is also appropriate. This is deterministic fixture/verifier work with the interface fully specified in plan task 1b. Stop after its tested commit and hand off back to Codex 6.1 Sol Medium for 1c.

Create tasks/py-grep-smoke/{task.json,instruction.md,seed/grep.py,verifier/check.py} and tests/fixture_test.py. Original smoke fixture, no upstream content yet. Implement substring grep(pattern: str, lines: list[str], ignore_case: bool=False) -> list[str], retaining input order/duplicates. Seed deliberately raises NotImplementedError; worker can edit only grep.py. Coordinator-only stdlib verifier runs against frozen workspace, outside worker tree: exit 0 pass, 1 incorrect implementation, 2 verifier infrastructure failure. Use a bounded subprocess timeout in tests. Exact manifest fields, budget, test cases and protected files are specified in task 1b.

Do not change lifecycle architecture, introduce result contracts, call models/MCP, add a CLI, install runtime services, or implement a loader/router/scheduler. Do not import copyrighted upstream content without pinned revision and attribution/license review. Return to Sol if verifier isolation or lifecycle interfaces need architectural changes.

## Copyable next-agent instruction

Work sequentially in C:/Users/mcarls/src/scripts-agent-benchmark on agent/agent-benchmark. Confirm cwd, branch and Git status before edits. Read modules/agent_benchmark/docs/HANDOFF.md and task 1b of modules/agent_benchmark/docs/plans/20261019-implementation/plan.md. Implement task 1b ONLY with test-first validation. Preserve tested lifecycle interfaces at da8dda2bbe69b41a40c6938753b96ed259de62b8. No local-agent delegation, MCP/model calls, core substitutes, CLI, or edits outside modules/agent_benchmark. Run the documented module pytest and Ruff commands, commit only intended tested paths, update status/checklist/handoff with SHA and results, then stop for Sol Medium integration. benchmark_core Gate 1 is not needed for this independent fixture package.
