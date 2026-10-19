# agent_benchmark

Thin evaluator for local coding workers. Version 0.3.0 provides the independent Phase 1c components:

- Supported pinned MCP dispatch/cancel adapter, with fresh OpenCode session/message/tool reconciliation.
- Bounded first-attempt observation and termination confirmation, durable recovery evidence, sticky dispatch stop for unresolved execution.
- Fresh owned workspaces, byte-exact S0/S1 checkpoints, actual-path scope auditing and separate verifier processes against disposable S1 copies.
- Original `py-grep-smoke` task and deterministic hidden verifier.

**Canonical result emission and CLI are pending the user's final corrected, tested benchmark_core SHA.** No competing result models exist. No actual model run has been validated; a read-only readiness check timed out. This is not Milestone 1 completion.

[Implementation plan](docs/plans/20261019-implementation/plan.md) contains model allocation, architecture and gates. [Handoff](docs/HANDOFF.md) records exact resume instructions.

From this module directory:

```powershell
& "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m pytest tests -q --basetemp=.pytest_tmp_root/phase1c-final --tb=short
& "C:\Users\mcarls\src\scripts\.venv\Scripts\python.exe" -m ruff check agent_benchmark tests tasks
```

Install module dependencies using the repository environment (`python -m pip install -e .`). The existing `opencode-mcp@3.0.0` must be installed/cached separately. The adapter uses offline npx, never starts shared services, and accepts auth through existing OPENCODE_SERVER_USERNAME/PASSWORD environment variables without logging them.

Programmatic boundaries: `evidence.load_task`, `bridge.connected_bridge`, and `attempt.run_attempt`. Actual execution requires an explicit caller action; there is no enabled benchmark CLI yet. Keep one DispatchGuard for the batch. S1 is captured only after fresh termination evidence; unresolved jobs have no scoreable S1 and halt further dispatch. `AttemptEvidence` carries internal evidence references, not a serialized benchmark result. Canonical integration must preserve expired-task and infrastructure-error facts even if the verifier passes after cancellation.

A cached job status or abort acknowledgement cannot prove termination. Shared services/processes are never terminated. Filesystem cleanup is separate from task scoring. Fixture isolation is not a hostile-code sandbox; use trusted offline tasks and unprivileged execution.

Primary API references: [MCP SDK v1 client](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/docs/client.md), [OpenCode server](https://opencode.ai/docs/server/). Installed SDK 1.30.0 signatures and bridge 3.0.0 source were inspected during implementation.
