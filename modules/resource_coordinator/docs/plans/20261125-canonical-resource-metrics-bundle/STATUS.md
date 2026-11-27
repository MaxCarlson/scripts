# Canonical Resource Metrics Bundle Integration

## Scope

Replace H4's staged `modules/resource_metrics` source copy with the qualified
`mxc-resource-metrics` wheel while preserving Resource Coordinator's
`resource_metrics` imports and the bundle's offline reproducibility. Work is
isolated from the Phase-D worktree and based on committed H4 checkpoint
`ea6ad23fe705bc828f06a99ccf1ab3477e621d49`.

## Status

- Successor branch: `retire/resource-metrics-successor-20261127`.
- Starting Scripts main: `4a6425aefc21d5175cbd7f64372b870d1f65738e`; source-retirement test commit `6bb1a30c513079c8a6d5e3b3d36464798fc0ee88`.
- Target wheel: `mxc-resource-metrics==0.3.0`, SHA-256
  `a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71` (published PyPI artifact).
- No live services, persistent data, inference, or Phase-D files are in scope.
- Implemented deterministic in-bundle staging of the verified published wheel, metadata and SHA-256 pin; current and historical H4 snapshots no longer export `modules/resource_metrics`.
- Offline acceptance harness imports the canonical wheel under the existing `resource_metrics` namespace and fails closed if the wheel is missing.
- Resource Metrics source retirement and the exact source-ownership exception are implemented; Resource Coordinator metadata now requires `mxc-resource-metrics>=0.3.0,<0.4`.
- Focused offline regressions pass: 24 retirement/ownership tests and 38 H4 bundle/harness tests. The H4 wheel import test verifies provenance from the wheel and source absence in both snapshots.
- No inference, Windows guest lifecycle, or live service mutation was performed.

## Next

Reconcile the successor with current main, finish source-ownership enforcement,
and publish the isolated feature branch. Real disposable guest acceptance
remains outside this change; H4 owner review is still required before live use.
