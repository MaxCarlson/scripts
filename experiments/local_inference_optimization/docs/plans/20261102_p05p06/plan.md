# P05/P06 Implementation Plan

Base commit: `9273e0c2d85ea9c4ef83319e30c579920ea90974`
Branch: `agent/local-inference-p05p06-20261102`
Scope: P05 versioned feature registry, P06 deterministic configuration compiler with backend mapping, and safe offline apply/rollback engine in `experiments/local_inference_optimization/`.

1. Reconcile P03/P04 base contracts and review downstream requirements.
2. Implement `lio-feature-def-v1` schema, validation, catalog, and `FeatureRegistry` (`registry.py`).
3. Implement `lio-plan-v1` schema, capability gating, backend mappings, and `compile_plan()` (`compiler.py`).
4. Implement `lio-receipt-v1` schema, drift-guarded atomic apply and rollback engine (`apply.py`).
5. Write comprehensive unit and regression tests for registry, compiler, and apply engine.
6. Verify 0 regressions on existing 46 P03/P04 contract tests (75 total tests passing).
7. Run Ruff linting, formatting, and Git whitespace validation.
8. Review and commit validated changes on isolated feature branch.
