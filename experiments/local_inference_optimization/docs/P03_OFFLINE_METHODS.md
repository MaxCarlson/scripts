# P03 offline methods and freeze gates

`lio-preregistration-v1` is an additive preregistration schema in `preregistration.py`. It validates structured design fields, round-trips bounded canonical JSON (rejecting duplicate keys), and fingerprints the design. `randomized_execution_order()` produces a seed-reproducible shuffled block and arm order. Freeze requires a sealed baseline and identified model content, quantization, environment, instrumentation, and fixed conditions. A structurally complete design with those identities absent is reported as `template_ready_blocked`; no baseline digest or runtime value is synthesized. The existing `lio-experiment-v1`, `lio-variant-v1`, `lio-trial-v1`, and `lio-evidence-v1` contracts are unchanged.

Study classes are explicit: `between_models` permits declared model identity/quantization differences, while `within_model_settings` holds model content identity fixed and requires the exact allowed settings to be listed. The result checker validates frozen fingerprint, task list, repetition count, and randomization seed. This helper complements, but does not replace, `comparison-conditions-v1` and its B0/B2/B3 and SV0/SV1 validation.

`benchmark_core.experimental.compare_paired_trials()` uses the benchmark status set. Its primary denominator remains pass + fail + timed out; infrastructure errors and unscored attempts remain visible and excluded. Matching key is `(task_id, repetition)`; task-level paired effects are returned individually. An exact two-sided binomial/McNemar test is returned only for one pair per task with discordant outcomes. For repeated measurements, each task contributes one mean paired binary difference and a seeded bootstrap resamples whole tasks. Percentile intervals assume independent sampled tasks; repeated runs are not independent units. Degenerate task effects and fewer than two distinct paired tasks yield no interval. The condition compatibility helper checks full task/verifier and non-target contracts, allows only declared model identity or setting paths to vary, requires observed-stage model identity evidence, and effective-stage evidence references for model settings.

Timeout duration observations are treated as right-censored and excluded from completed-time means. The module retains distinct successful-only and all-scored-completed summaries with per-trial provenance. Secondary metric deltas are emitted only when unit, source, and quality match across both arms; estimated metrics stay labeled estimated. Holm adjustment requires both a confirmatory declaration and family identifier. Eligibility returns reason codes and never auto-creates a decision; decision records require evidence references, thresholds, compatibility, reviewer, provenance, and rationale.

## Synthetic examples (fabricated)

For a between-model example, four matched task outcomes are baseline `pass, pass, fail, fail` and candidate `pass, pass, pass, fail`. Marginal acceptance is 50% and 75% (+25 percentage points); paired outcomes have one win, zero losses, and three ties. The exact paired p-value is 1.0. The example is exploratory and supports no superiority claim.

For a within-model settings example, use those same outcomes for baseline temperature and candidate temperature while requiring identical model-content digest and declaring temperature as the sole permitted difference. The arithmetic is the same, but the result remains blocked from causal interpretation unless effective temperature and every non-target condition are independently evidenced. The fixture is not evidence that any model or setting was run.

## Remaining real-freeze prerequisites

- Seal and fingerprint the P02 untouched baseline and preserve its task/verifier manifest.
- Supply exact content digest and quantization for each model condition, task/verifier digests, and actual environment/instrumentation identities.
- Resolve P04 trace propagation acceptance before claiming trial-to-inference ownership; the P04 offline implementation does not prove live Harbor propagation.
- Complete the existing P07 integration/evidence gate and obtain any required runtime authorization before collecting experiment outcomes.
- Predeclare sample size, stopping/exclusion rules, multiple-comparison family, and quality/adoption thresholds for the specific study.
