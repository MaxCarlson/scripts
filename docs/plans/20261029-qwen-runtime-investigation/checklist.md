# Checklist

- [x] Create and verify the isolated branch/worktree.
- [x] Verify model/runtime identity and service ownership without changing global settings.
- [x] Inspect merged LLM Monitor capabilities; document polling/SSE coverage limits.
- [x] Capture sanitized mock-provider requests for alias, explicit variants, model-level reasoning option, `none`, and output limits.
- [x] Integrate six reusable coding tasks and independent verifiers into Agent Benchmark; retain a supplemental existing-code task.
- [x] Resolve verifier/Git test setup issues and verify timeout, reference, seed-failure and profile regressions.
- [x] Add explicit per-experiment context/output/reasoning profile support and provenance to Agent Benchmark.
- [x] Directly probe LM Studio's handling of reasoning settings for the exact loaded Q4_K_M model; preserve sanitized request/response evidence in `experiments/qwen_runtime_investigation/evidence/direct-model-findings.md`.
- [x] Start isolated OpenCode on verified port 4196, with separate config/data and no changes to the active 4096 server.
- [x] Start independent LLM Monitor recording for OpenCode trials; complete history and comparison captured in the experimental database. The bounded `live` observer connected but hung past its observation deadline; coordinate one SSE observation after that issue is resolved and the observer is ready.
- [x] Run bounded serial T1/T2 screening with omitted/default and explicit `none`; T2 baseline and `none` passed. Preserve the no-dispatch `INFRASTRUCTURE_ERROR` from the initial paused invocation separately.
- [x] Run a matched T4 state-machine screen after both T2 trials passed; both profiles passed. Full results and limitations are in `evidence/t2-t4-comparison.md`.
- [ ] Run T3 or a bounded T5 async comparison only if needed to distinguish Qwen settings from task-workflow causes; do not create a full Cartesian matrix.
- [ ] Repeat informative conditions before claiming reliability. Current paired comparisons are one trial per task/profile.
- [x] Analyze per-inference/session telemetry and record current recommendation: `reasoning_effort=none` is promising but not yet a reliable operating profile; no correctness benefit over default is established.
- [ ] Correlate live OpenCode provider request fields and validate incremental SSE delivery when safe instrumentation/observer support is ready.
- [x] Review and push checkpoint `9bb19500` on the isolated branch; do not merge. Review and checkpoint new evidence separately after verification.
