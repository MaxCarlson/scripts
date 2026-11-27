# Windows Listener and CLI Presentation Corrections

## Goal

Identify Windows TCP listeners with verifiable process identity when psutil cannot enumerate them, and make default Resource Coordinator output schema-aware without changing JSON or live operations.

## Implementation sequence

1. Test a separate Windows listener-discovery abstraction, including native table parsing, process identity failures, and a disposable local socket.
2. Integrate discovery into upgrade preflight and lifecycle verification, retaining fail-closed ownership requirements and useful blocker diagnostics.
3. Add focused renderers for coordinator/miner/gaming/upgrade/health/startup results; keep arbitrary nested objects structured or summarized, never flattened into semicolon strings.
4. Validate offline suites, document the read-only preview, then commit and integrate only after the remote base is rechecked.

## Safety boundaries

- No live coordinator, miner, GPU, LM Studio, or Scheduled Task changes.
- HTTP success alone is not process identity.
- Missing identity evidence remains a blocker; no inferred ownership.
- JSON and raw log output remain machine compatible.
