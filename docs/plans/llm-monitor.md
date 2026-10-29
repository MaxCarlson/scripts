Proposed Module: "llm_monitor" — Local LLM Observability and Diagnostics

Repository: "MaxCarlson/scripts"

Recommended location: "modules/llm_monitor/"

CLI entry point: "llm-monitor"

Status: Proposed / Not implemented

Objective

Build a reusable, primarily read-only monitoring and diagnostic suite for locally hosted LLMs and coding agents.

The suite should make it easy to answer:

- Which local models are loaded and processing requests?
- Which OpenCode sessions and delegated jobs are running?
- Is an agent making progress, waiting on inference, compacting, or blocked?
- How much context is being consumed per inference?
- How often is compaction occurring, and how long does it take?
- Are large source reads causing context thrashing?
- Has the model attempted or completed file edits?
- Is the GPU saturated, VRAM exhausted, or another process competing for resources?
- Has the worker finished successfully, truncated its generation, or become unresponsive?

The system must distinguish inference completion, session completion, and successful task completion.

Architecture

Implement independently usable collection adapters for:

1. OpenCode: Sessions, messages, message parts, tool activity, compaction, permissions, and finish reasons.
2. LM Studio: Loaded model identity, configured context length, provider usage, and available inference diagnostics.
3. Hardware: Reuse "resource_metrics" for NVIDIA GPU, VRAM, power, temperature, CPU, and process measurements.
4. OpenCode MCP: Job/session/message correlation and discrepancies between MCP-reported status and actual session state.
5. Optional integrations: Runmux process history and Resource Coordinator request timing.

Define a normalized, timestamped event schema so data from different services can be correlated reliably.

Use feature detection and version-aware adapters. Avoid assuming OpenCode API schemas and behavior never change.

Proposed CLI

llm-monitor status
llm-monitor sessions
llm-monitor watch --session SESSION_ID
llm-monitor watch --all
llm-monitor diagnose --session SESSION_ID
llm-monitor report --session SESSION_ID
llm-monitor export --session SESSION_ID --output PATH --write
llm-monitor gpu

Support "--format text|json", "--interval", "--verbose", and source endpoint overrides where applicable.

Monitoring should be read-only by default. Evidence export should require an explicit "--write" flag.

Live monitoring

Provide a periodically refreshed terminal display including:

- Session / job identifiers.
- Model and agent names.
- Running, idle, blocked, finished, or unknown state.
- Elapsed execution time.
- Message, inference, and tool-call counts.
- Most recent completed inference's input/output/reasoning tokens.
- Context utilization relative to effective loaded capacity.
- Compaction events and durations.
- Latest tool operation and outcome.
- Successful and failed edit attempts.
- Permission or question blockers.
- GPU utilization, VRAM, and power.
- Inference throughput and timing when measurable.

Clearly distinguish in-progress counters from completed inference statistics.

Count unique compaction operations, not simply the number of message parts associated with compaction.

Diagnostics

Automatically flag patterns such as:

- Frequent repeated compaction.
- Repeated source reads following compaction.
- Context overflow or "finish="length"".
- Worker completion with no deliverable.
- Missing or inconsistent model-limit configuration.
- OpenCode agent identity changes.
- Orphaned MCP job IDs.
- Failed edit operations.
- Unreliable session-level file-change summaries.
- Stalled inference or stale monitoring records.
- Heavy GPU contention.

Classify findings as observed facts, strong inferences, or hypotheses.

Do not assume that high GPU utilization belongs to the monitored model. Distinguish device-level utilization from process-level memory attribution.

Evidence and historical analysis

Support collecting timestamped telemetry during a session and generating a post-run report.

Preserve sufficient event history to reconstruct:

- Inference and tool timelines.
- Token usage trends.
- Compaction frequency.
- Tool errors.
- File changes.
- Worker and coordinator outcomes.
- Hardware contention.

Offer optional private raw-evidence export, including hashes and a manifest.

Avoid storing full prompts, source code, credentials, or tool output by default. Make sensitive capture opt-in.

Reuse existing repository components

- "resource_metrics": GPU and process telemetry.
- "local_agent_bridge": Model configuration and OpenCode integration.
- "lmstui": Existing LM Studio API utilities where compatible.
- "termdash" / "cli_tui": Optional native terminal interface.
- "runmux": Optional process supervision, not the monitoring engine.
- "resource_coordinator": Optional request-level telemetry for traffic routed through its proxy.

Avoid copying logic or creating hard dependencies on unrelated process-management functionality.

Implementation priorities

MVP: "status", "sessions", "watch", "gpu", JSON output, and a reliable OpenCode session adapter.

Second stage: Context and compaction diagnostics, MCP correlation, repeated-read detection, and inference-speed analysis.

Third stage: Historical telemetry, evidence exports, session comparisons, alerts, and richer TUI/web visualization.

Engineering requirements

- Python 3.11+ with "argparse" and short/long flags.
- Cross-platform where feasible: Windows, WSL2/Linux, macOS, and Termux.
- Poll efficiently; avoid repeatedly downloading entire conversation histories.
- Handle unavailable services and partial data gracefully.
- Do not initiate inference, modify sessions, reload models, or terminate processes.
- Use isolated, synthetic fixtures for automated tests.
- Include pytest tests for parsing, state transitions, API failures, compaction counting, and job correlation.
- Keep the collected telemetry separate from OpenCode's own SQLite database.
- Never modify historical session records.

Initial reference implementation

Use the Argon Phase 2A experimental runner as a functional reference, particularly its periodic OpenCode polling, token accounting, compaction detection, SQLite/session inspection, and LM Studio log correlation.

Relevant local files:

"C:\Users\mcarls\.gemini\antigravity-cli\brain\3f6d383d-0ba5-4344-b130-b35ff15fad6d\scratch\run_phase2a_condition.py"

"C:\Users\mcarls\local-agent-forensics\analysis\phase2a\"

These are reference materials, not permanent package dependencies.

First deliverable: A working read-only live monitor showing equivalent session information to the Phase 2A "polls.json" output, without requiring Argon's experimental runner.
