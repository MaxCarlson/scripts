# LLM Monitor Phase 2 Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with `superpowers:executing-plans`. No local worker delegation is authorized.

**Goal:** Add evidence-backed session diagnostics and reporting while preserving the read-only Phase 1 CLI and deferring persistent telemetry.

**Architecture:** Keep HTTP/provider adapters separate from normalized in-memory events, pure diagnostic rules, and CLI formatting. Prefer documented cursor pagination when advertised; otherwise use bounded overlap polling and report incomplete coverage. Optional LM Studio, hardware, and MCP inputs must not block OpenCode analysis.

**Tech Stack:** Python 3.11+, argparse, standard-library HTTP/JSON, pytest; optional existing `lmstui` and `resource_metrics` APIs.

**Spec:** `docs/plans/llm-monitor.md` and the Phase 2 handoff supplied in the task.

## Global Constraints

- Read-only collection; never initiate inference, modify sessions/configuration, stop jobs, or write telemetry.
- Do not modify `modules/local_agent_bridge/`, other worktrees, OpenCode databases, or original forensic evidence.
- Preserve Phase 1 commands and existing JSON field meanings; add a schema version for enriched records.
- Never emit prompts, source content, tool output, credentials, or inferred file ownership.
- Distinguish per-inference tokens from cumulative session totals and actual capacity from model-card capacity.
- Use only synthetic or sanitized fixtures in automated tests.
- Keep monitoring history bounded in memory and expose completeness/gap metadata.

## Review Focus

- Legacy and cursor API response envelopes differ; test route negotiation and malformed responses.
- Reconnects and reordered/duplicate messages must not clear observed state or double-count events.
- In-progress assistant messages must not be presented as completed inferences.
- Missing context limits, timestamps, tool targets, and job receipts must stay unknown.
- A successful tool report, idle session, MCP unknown status, or high device GPU utilization must not be overstated as task failure/success or session attribution.

---

### Task 1: Normalized event model and resilient OpenCode collection

**Files:** `llm_monitor/events.py`, `llm_monitor/opencode.py`, `tests/events_test.py`, `tests/opencode_test.py`.

- [ ] Add frozen/typed normalized events with provider IDs, timestamps, category, provenance, and nullable fields.
- [ ] Add tests for malformed/reordered/duplicate inputs, stable IDs, and unknown fields; run them red.
- [ ] Implement event projection without retaining message text or tool payloads.
- [ ] Probe `/doc` once for cursor route support; use v2 cursor pages when available and legacy limit-window overlap otherwise.
- [ ] Bound page fetch, event cache, retries, and exponential backoff; preserve prior state on request failure and expose stale/gap/coverage data.
- [ ] Test cursor traversal, overlap dedupe, failed retries, restarts, session removal, and cap-induced partial history.
- [ ] Run module tests and existing CLI contract checks.

### Task 2: Context, compaction, tool, and lifecycle analysis

**Files:** `llm_monitor/analysis.py`, `llm_monitor/diagnostics.py`, `tests/analysis_test.py`, `tests/diagnostics_test.py`.

- [ ] Add failing tests for usage categories, missing values, compaction identity/duration, reads, edits, and lifecycle distinctions.
- [ ] Normalize assistant inference, tool, compaction, permission/question, session status, and model-switch events.
- [ ] Analyze OpenCode model limits and token usage; optional read-only LM Studio loaded-model inspection must label max/model context separately from effective loaded context.
- [ ] Estimate utilization only when numerator and denominator semantics are supported; leave cache accounting and effective capacity unknown otherwise.
- [ ] Detect length finishes, overflow, frequent compaction, repeated reads after compaction, failed edits, and ambiguous completion with evidence and confidence.
- [ ] Keep path normalization conservative and never include source text.
- [ ] Test against sanitized Phase 2A/2B fixtures only for fields those fixtures actually contain.

### Task 3: Optional MCP correlation and performance metrics

**Files:** `llm_monitor/mcp.py`, `llm_monitor/metrics.py`, `tests/mcp_test.py`, `tests/metrics_test.py`.

- [ ] Inspect the supported MCP receipt/store interface and add fixtures with prompt/output fields omitted.
- [ ] Test exact ID correlation, unknown job reconciliation by remembered session ID, uncertain directory/time matches, and unavailable MCP.
- [ ] Parse read-only job metadata from an explicit store location only; do not inspect private databases or assume an internal path.
- [ ] Calculate per-inference elapsed time and output throughput only when corresponding time/token evidence exists; distinguish end-to-end from decode rate.
- [ ] Add optional timestamped resource snapshots as device/process scope only; no live inference, no attribution from utilization alone.

### Task 4: Diagnose/report CLI and watch integration

**Files:** `llm_monitor/cli.py`, `llm_monitor/__init__.py`, `README.md`, `tests/cli_test.py`, scripts-help registry.

- [ ] Add tests for `diagnose` and `report` text/JSON contracts, JSON schema version, partial-history messaging, and Ctrl+C exit.
- [ ] Implement reusable diagnostic findings with stable code, severity, classification, evidence, coverage, and rule parameters.
- [ ] Add `diagnose -s/--session` and `report -s/--session`; maintain the distinction between inference, session/job, work-product, and task acceptance.
- [ ] Enhance `watch` with normalized state, latest tool, context, blockers, warnings, and data freshness without changing existing fields.
- [ ] Update docs, packaging metadata if needed, and help registry.
- [ ] Run full module pytest, CLI help, package build/entry-point check, compile checks, and repository diff/status review.

## Deferred

Persistent telemetry, long-term retention, raw evidence export, historical comparisons, alerts, web/TUI work, active recovery/supervision, and all protected integrations remain out of scope.
