# CLI lifecycle and recovery status

- Branch checkpoint: `c5e0dbaa86e1b001296ca6b3acf5a51248eaff58`.
- Transport now uses per-operation protected artifacts, request integrity and completion evidence; read-only operations no longer alter managed-root ACLs.
- Recovery CLI commands implemented: status, diagnose, restore, resume, reconcile.
- Incident reconcile preview/apply and offline status have deterministic tests.
- Restore/resume remain fail-closed when identity, task snapshot, or prior miner-state safety cannot be proven.
- Focused installation/CLI/architecture validation: 238 passed.
- Actual helper invocation reached Windows Task Scheduler but read access was denied in this agent context. Successful elevated helper execution and UAC acceptance remain unverified.
- Automatic rollback, full fault matrix and disposable elevated-task integration remain in progress.
