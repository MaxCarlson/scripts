# Legacy task attribution

- Base: `d290a87ed78ec784bd9684d3b53e951fd343b4d0`.
- The running legacy task uses a PowerShell engine, a virtual-environment Python
  launcher, and a global Python listener. The two Python executables differ.
- Preflight requires one task instance, an unmodified launcher, matching engine
  action, stable PID/creation-time ancestry, and matching service configuration
  and miner shutdown arguments. Inaccessible evidence remains a blocker.
- Offline regression validation: 311 passed, 1 skipped. The skipped disposable
  socket test cannot observe its socket through this runner's Windows TCP table.
- An elevated read-only collector check against the observed live task reported
  `verified: true` and `shutdown_verified: true`. No live upgrade was performed.
- A full preview from this runner remained blocked because neither TCP listener
  backend could see port 1235 in that execution context. The user's normal shell
  must run a fresh read-only preview to establish whether the full preflight passes.
- The task query does not initiate UAC. If Windows denies read-only process or
  task access, preview reports the privilege requirement and stays blocked.
- Next: integrate the validated source and run a separate read-only upgrade preview.
