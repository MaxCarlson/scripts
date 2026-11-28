# Checklist

- [x] Reproduce schema 3 to schema 4 with historical 2.1.2 and 2.5.0 dispatcher implementations plus a harmless guarded provider subprocess.
- [x] Pin interrupted exit bookkeeping and pending-association state at the old wrapper failure.
- [x] Add failing tests for read-only schema/install diagnostics and update preflight.
- [x] Add failing tests for preview/apply recovery through exact pending launch.
- [x] Cover concurrent recovery, interrupted terminal-launch publication, unknown process enumeration, stale reservation, selected-session conflict, running session, and cwd/workflow metadata preservation.
- [x] Implement runtime transition guards for normal writes and rebuild, version-aware preflight, install resolution diagnostics, and exact stopped-session recovery. Native allocation remains disabled.
- [x] Run focused tests, applicable full module/help tests, Ruff, and diff checks.
- [x] Commit/push qualified task branch and report 2.5.2 readiness without merge/deployment.
