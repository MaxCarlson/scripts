# Runtime resource policy correction

The benchmark previously applied default RAM and memory reserves without a measured universal basis. The implementation removes those default thresholds while retaining explicit opt-in limits and fail-closed admission checks against LM Studio's estimate and current measured host/GPU capacity.

## Current policy

- RAM percentage and available-byte limits are disabled unless a caller explicitly configures them.
- When a limit is configured but its measurement is unavailable, the run blocks rather than inventing a value.
- Model loading requires a successful context-specific LM Studio allocation estimate and measured capacity. Estimate or capacity gaps block the load; actual allocation failures are recorded without blind retry.
- Model identity, active/busy state, requested context, successful lifecycle commands and confirmed worker termination remain checked.
- Resource measurements before and after model operations are diagnostic; the benchmark does not force-kill processes or wait for an arbitrary utilization threshold.

## Implementation and follow-up

The runtime resource change was implemented in Agent Benchmark 1.19.0 and is part of the Qwen integration. Explicit inference profiles and instruction overlays are now available for reproducible project-local trials. Final Qwen findings and limits, including the B1 outcomes and Monitor reconciliation, are summarized in [`experiments/qwen_runtime_investigation/README.md`](../../../../../experiments/qwen_runtime_investigation/README.md).

No new model inference was part of the integration review. Integration test results are recorded in the repository-level Qwen integration status document.
