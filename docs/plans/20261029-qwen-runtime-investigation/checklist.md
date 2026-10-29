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
- [ ] Run bounded serial Stage A on T1/T2; preserve every trial and independent verifier result. T1 has two one-off passes (unconfigured, `none`); T2 remains untested.
- [ ] Expand to moderate/complex tasks only if Stage A supports it; repeat only informative settings.
- [ ] Analyze per-inference/session telemetry, categorize failures, recommend an operating profile.
- [ ] Review diff/status and commit/push isolated work only; do not merge.
