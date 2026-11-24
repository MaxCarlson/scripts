# Canonical Resource Metrics Bundle Integration

## Scope

Replace H4's staged `modules/resource_metrics` source copy with the qualified
`mxc-resource-metrics` wheel while preserving Resource Coordinator's
`resource_metrics` imports and the bundle's offline reproducibility. Work is
isolated from the Phase-D worktree and based on committed H4 checkpoint
`ea6ad23fe705bc828f06a99ccf1ab3477e621d49`.

## Status

- Implementation branch: `feat/resource-metrics-canonical-bundle-20261125`.
- Starting HEAD: `ea6ad23fe705bc828f06a99ccf1ab3477e621d49`.
- Target wheel: `mxc-resource-metrics==0.3.0`, SHA-256
  `1512d9e9ab1a1d603c2dc244d1459baff1abcc738d82c4ee2a5fac835a04189a`.
- No live services, persistent data, inference, or Phase-D files are in scope.
- Implemented deterministic in-bundle staging of the exact wheel, metadata and SHA-256 pin; H4 snapshots no longer export `modules/resource_metrics`.
- Offline acceptance harness imports the canonical wheel under the existing `resource_metrics` namespace and fails closed if the wheel is missing.
- Focused tests pass: 3 targeted bundle/harness regressions. Combined H4 suites: 70 passed, 1 skipped, 4 failed on unavailable host services, ACL validation, and live Windows inventory. Ruff, compileall, and `git diff --check` pass.
- No inference, Windows guest lifecycle, or live service mutation was performed.

## Next

Review the task-only diff, commit and push the isolated branch for H4 owner
integration. Real disposable guest acceptance remains outside this change.
