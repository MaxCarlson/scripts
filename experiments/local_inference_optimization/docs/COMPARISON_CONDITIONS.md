# Comparison conditions

Require exact task and verifier digests, frozen baseline and source identities, model content identity and quantization, prompt/tool policy, context/output, resource regime and non-target settings. A declared intervention must identify every permitted difference before data collection. Reuse `benchmark_core.conditions` as the authority for its existing comparison-conditions-v1 and B0/B2/B3 contracts; this package does not replace it.

Unknown or weak model identity, unverified settings, missing source identity, missing or changed verifier, differing workload or unexplained instrumentation drift make a comparison unsupported or separate rather than equivalent. Request evidence establishes a request, not effective backend behavior. Preserve metric quality and missingness; never infer success from missing evidence.
