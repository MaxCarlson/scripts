# Experimental protocol

Pre-register task/verifier hashes, baseline and selected model identity, variant hashes, controls and permitted differences, randomization seed, repetition counts, timeouts, quality threshold and exclusion rules before comparisons. Randomize or counterbalance task-by-repetition blocks and record warm/cold state, contention and concurrency. Preserve B0/B2/B3 retrieval interventions as separate designs. Never change task/verifier identity to salvage a run.

Strict accepted-task success across all attempted tasks is primary. Censored timeouts, infrastructure errors, unconfirmed termination and missing evidence remain explicit outcomes; do not convert them to success or hide them from denominators. Duration, prefill/decode, tokens and VRAM are secondary and need attributable quality/provenance. Zero-success, all-failure, zero-baseline, missing-reference and incomplete-telemetry cases do not justify percentage improvement or significance claims.

Use separately identified comparisons: candidate against preserved P02 reference; candidate against the immediately previous accepted profile; and later P18 leave-one-feature-out ablations. Instrumentation changes require a contemporaneous matched instrumented control, not an assumed match. Use paired blocks and uncertainty intervals only where there is sufficient independent data; adjust interpretation for repeated measures and multiple comparisons. A small pilot is exploratory.

Record decisions as adopt, provisional, experimental, unsupported, rejected or superseded with evidence and reviewer. No automatic promotion follows a speed-only result. P18 requires comparable accepted individual interventions and documented invalid combinations. This is a template, not a frozen preregistration or completed experiment.

See [P03_OFFLINE_METHODS.md](P03_OFFLINE_METHODS.md) for the additive preregistration schema, paired-analysis assumptions, synthetic examples, and current P02/P04/P07 freeze gates.
