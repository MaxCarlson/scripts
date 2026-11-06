# P03 preregistration and paired analysis

## Objective

Complete the offline P03 methodology layer with a fingerprinted, freeze-ready preregistration contract, task-cluster-aware paired analysis, explicit evidence/eligibility layers, and an additive portable report view.

## Source findings

- The authoritative P03 handoff is `local_llm_optimization_handoffs/phases/P03_pre-registered_experimental_protocol_and_statistical_methodology.md`; the master archive and dependency matrix require protocol freeze before confirmatory feature comparisons.
- `lio-experiment-v1`, `lio-variant-v1`, `lio-trial-v1`, and `lio-evidence-v1` in `experiments/local_inference_optimization/contracts.py` remain authoritative. Add a versioned preregistration schema without modifying those validators.
- `comparison-conditions-v1` and the B0/B2/B3 and SV0/SV1 validators remain authoritative. New analysis reports comparability requirements explicitly and does not alter their behavior.
- Existing `compare_runs()`/`aggregate_experiment()` and legacy report rendering stay compatible.
- P02 is not sealed; this work can provide a freeze-ready template, but actual experiment freeze remains gated on real baseline/task/model/runtime identities.
- The P04 branch is read-only context only; its execution-scoped provenance evidence can later be attached as trial metadata. Harbor propagation remains an external acceptance gate.

## Design decisions

1. Add `lio-preregistration-v1` with canonical fingerprinting, strict validation, explicit study class and intervention, and a separate distinction between design readiness and actual freeze eligibility.
2. Add `benchmark_core.experimental` as an additive API: strict scored denominator, pair/block diagnostics, exact McNemar for one pair per task, task-cluster bootstrap for repeated pairs, Holm only for declared confirmatory families, censored-time handling, and layered eligibility reason codes.
3. Keep result records immutable and require caller-supplied compatibility facts; missing identity/effective evidence prevents causal comparison rather than being inferred.
4. Add optional experimental analysis data to portable HTML reports; old serialized reports remain readable and all dynamic text remains escaped.
5. Use synthetic fixtures only. No inference, Harbor, service, GPU, or Resource Coordinator interaction.

## Validation

Run focused benchmark_core, interactive_reports, and LIO test suites; static syntax/format checks on changed Python; review diff and clean scoped Git status. Commit only task-owned paths in this worktree.
