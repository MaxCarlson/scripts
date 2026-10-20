# Status - Minimal LM Studio Activity Automation

- Stage: offline implementation and Sol Medium safety review complete; read-only environmental validation may proceed.
- Branch/worktree: `resource-coordinator-phase-d` / `C:/Users/mcarls/src/scripts/.worktrees/resource-coordinator-phase-d`.
- Baseline: `44ce5d6ec9b56ecb75c2cfb4ff848b85964c2764`, preserving Phase D and preflight commits.
- Reusable: inference route classification, pending/active leases, stop-before-forward blocking hooks, coordinator stop ownership, stream completion detection, uncertain-operation inhibition, cancellable per-resource cooldown, manual override, and generic `ProcessSupervisor` policies.
- Implemented: explicit model-load classification and matching YAML policy validation; model loads use exclusive `gpu.inference` leases; unmanaged unload/unknown routes stay rejected; generic optional process startup/shutdown and CLI flags; monotonic-clock injection; FIFO protection for pending exclusive reservations; idle restart callback is serialized with new reservations.
- Safety review corrections: standalone model loads now require a managed service and matching stop policy (`717316713cb8a86a8a4d3f5465f31b146414766c`); automatic restart now requires coordinator-owned stop permission in config parsing and service preflight (`8d21630f1c5d953b1ec424fd7bb74434c5a10485`).
- Validation after review: 230 tests passed in a writable Windows test context; Ruff lint and format pass; Mypy passes with `--ignore-missing-imports`, while plain Mypy reports only missing `types-psutil` stubs. See the module handoff for exact commands and accounting.
- Implementation commit: `eff159c40f0929ce85f9ca9584e35753e60170c3`.
- Next: read-only environmental validation only. Supervised live test remains NO-GO until all independent acceptance gates and separate user authorization are satisfied; unattended operation remains NO-GO.

## Windows HTTP integration follow-up — 2026-10-19

- Scope: bridge the offline workflow to a real loopback coordinator HTTP listener using only a coordinator-owned disposable Windows helper and mocked upstream; prepare, but do not run, one separately gated LM Studio inference.
- Implemented: disposable process regression finalized; new opt-in HTTP harness covers mock success, a second request during cooldown, and uncertain upstream failure. It records process identities and verifies stop-before-forward and cleanup. A separate live test requires `RESOURCE_COORDINATOR_RUN_LIVE_LMSTUDIO_TEST=1`, verifies the exact model is already loaded before starting the helper and before forwarding, and uses an ephemeral coordinator port.
- Environment snapshot: LM Studio port 1234 accepted read-only unauthenticated model-list GETs. `qwen38-27b-q4km` was visible/not-loaded; `openai/gpt-oss-20b` was loaded. No inference or model operation was performed. See [HTTP integration procedure](../../WINDOWS_LMSTUDIO_HTTP_INTEGRATION.md).
- Validation: full suite **245 passed, 1 skipped**; focused HTTP harness **11 passed, 1 live test skipped**. Success log recorded two mock forwards, cooldown restarted after the second completion (1.51 seconds), process restart and shutdown cleanup. Mock upstream error returned 500 and retained inhibition. Ruff lint passed; Ruff format passed for 39 files; Mypy with `--ignore-missing-imports` passed on 16 source files. Plain Mypy has three existing missing `types-psutil` stub errors. A sandboxed test attempt hit pytest temp-root `WinError 5`; writable-context rerun passed.
- Boundary: no Krig, GPU process control, model load/unload, real inference, or shared configuration changes. Live Qwen execution remains gated on the documented exact request and separate authorization.
