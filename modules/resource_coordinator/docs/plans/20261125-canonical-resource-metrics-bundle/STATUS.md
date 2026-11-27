# Canonical Resource Metrics Bundle Integration

## Scope

Replace H4's staged `modules/resource_metrics` source copy with the qualified
`mxc-resource-metrics` wheel while preserving Resource Coordinator's
`resource_metrics` imports and the bundle's offline reproducibility. Work is
isolated from the Phase-D worktree and based on committed H4 checkpoint
`ea6ad23fe705bc828f06a99ccf1ab3477e621d49`.

## Status

- Successor branch: `retire/resource-metrics-successor-20261127`.
- Reconciled on Scripts `origin/main` checkpoint `61722b3c04bc36d32e0eaa51b2a478ab155a6dea`; implementation commit `8abbc6aea9660017316e71a92295dea0881be8eb`.
- Target wheel: `mxc-resource-metrics==0.3.0`, SHA-256
  `a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71` (published PyPI artifact).
- No live services, persistent data, inference, or Phase-D files are in scope.
- Implemented deterministic in-bundle staging of the verified published wheel, metadata and SHA-256 pin; current and historical H4 snapshots no longer export `modules/resource_metrics`.
- Offline acceptance harness imports the canonical wheel under the existing `resource_metrics` namespace and fails closed if the wheel is missing.
- Resource Metrics source retirement and the exact source-ownership exception are implemented; Resource Coordinator metadata now requires `mxc-resource-metrics>=0.3.0,<0.4`.
- Focused offline regressions pass: 24 retirement/ownership tests and 38 H4 bundle/harness tests. The H4 wheel import test verifies provenance from the wheel and source absence in both snapshots.
- No inference, Windows guest lifecycle, or live service mutation was performed.

## Integration gate

The successor branch is pushed at `dd076e98d26fb93185ab6c4c3a6d1d36a5ff5bf3`;
source-ownership enforcement passed against the reconciled current-main ref.
Real disposable guest acceptance remains outside this change, and H4 owner
review is required before live use or integration.
