# Checklist

- [x] Inspect scheduler service, executor, models, storage, CLI/TUI, docs, and active plan status.
- [x] Define recommended conditional-rule and managed-process architecture.
- [x] Specify miner start/stop semantics, ownership rules, telemetry limits, and failure behavior.
- [x] Record staged implementation and acceptance criteria.
- [x] User authorizes copying the plan to disk and beginning implementation.
- [x] Implement definition validation, persistence, evaluator, and focused tests.
- [x] Implement monitor command execution, preview, and GPU monitor example.
- [x] Implement owned-process supervision and daemon integration.
- [x] Add CLI/TUI management flows and documentation.
- [x] Run focused verification and update handoffs/status.
- [x] Verify GPU counter access and scheduler monitor test under the non-admin host user's interactive token; 1,318 counter instances were returned.
- [x] Enable the saved PearlMiner rule.
- [x] Add per-monitor logs and durable start/stop/failure statistics with CLI/TUI access.
- [x] Run full scheduler verification after monitor history changes (118 tests, Ruff, compileall).
- [ ] Start the registered daemon and verify its first polling cycle; startup can run due or catch-up scheduled tasks.
