# Qwen Runtime Investigation Plan

**Goal:** Establish which model and variant options OpenCode 1.19.3 sends through the LM Studio OpenAI-compatible adapter, then evaluate bounded coding tasks using trustworthy per-attempt telemetry.

**Architecture:** Keep all evidence and disposable fixtures on the isolated branch. Reuse Agent Benchmark for isolated tasks, per-attempt telemetry, durable outcomes, scoring, and comparison. Use a local mock endpoint for sanitized OpenCode request tests. For live work, use LLM Monitor's merged read-only `record` poller and an independent database if the newer SSE observer is not yet ready; explicitly report polling gaps and unavailable streaming delivery rather than waiting indefinitely.

**Tech Stack:** OpenCode 1.19.3, local-agent 3.5.1, LM Studio CLI/API, Python standard library, LLM Monitor, synthetic Git fixtures.

**Scope:** Investigation and evidence artifacts across local_agent_bridge, llm_monitor, and agent_benchmark. Any product fix requires direct evidence and focused tests. No global runtime configuration changes, merge, or model/version switch.

## Stages

1. **Isolation and preflight:** create this worktree; verify branch and clean status; identify active services, model alias configuration, OpenCode/LM Studio versions, GPU ownership, and monitor developer readiness.
2. **Request and response contract:** trace OpenCode model and variant resolution, run sanitized mock requests for the configured Qwen alias and explicit controls at 8,192/16,384 output. Preserve negative controls. Reuse Agent Benchmark bridge/parser tests for finish reasons, provider errors, and terminal tool/structured-output handling; add focused coverage only for untested response behavior.
3. **Task fixtures and measurement protocol:** integrate six deterministic coding tasks with independent verifiers into Agent Benchmark; verify references and bad seeds. Use its S0/S1 snapshots, trial runner, task limits, scope audit, correctness scoring, durable records, telemetry and reports.
4. **Live experiments:** confirm exact Qwen model identity/quantization, service ownership, and serial GPU capacity. Start OpenCode under isolated XDG config/data directories on port 4196; preserve LM Studio settings. Use an SSE observer if ready, otherwise the merged Monitor polling recorder with a dedicated evidence database. Coordinate the session/project when possible, use fresh sessions and identical fixtures, keep the baseline context at 98,304, and run one GPU workload at a time.
5. **Analysis and closeout:** analyze inference and session scopes separately; classify failures; document coverage/device-attribution limits; propose only evidence-supported fixes and an operating profile. Commit and push this isolated branch only; do not merge.

## Stop conditions

- Do not issue live inference while another worker is active or the loaded model is not idle; retain device-level VRAM attribution limits.
- Do not use an unvalidated SSE observer. Use only the merged read-only poller until the user confirms the new observer is ready.
- Do not retry an identical unproductive condition after its failure mode is established.
- Do not infer LM Studio support for a reasoning field from model-catalog descriptions; confirm the exact loaded GGUF through API response and request/response behavior.
- Do not alter the user's global runtime configuration or existing telemetry/evidence databases.
