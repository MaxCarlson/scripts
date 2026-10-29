# Local Agent Efficiency — Validation and Benchmark Readiness Handoff

## 1. Objective

Continue the existing implementation rather than restarting the project.

The previous implementation agent reported completing P0–P6, including bounded lexical retrieval, OpenCode integration, checkpoints, structural retrieval (`code_symbols` and `code_map`), and compaction support.

The reported implementation also includes optional `--structural-retrieval` setup and the `retrieval-structural-v1` benchmark profile.

These are previous-agent claims, not independently verified results.

Your assignment is to:

1. Verify the implementation.
2. Review correctness, security, and compatibility.
3. Reproduce offline validation.
4. Diagnose OpenCode/MCP integration failures.
5. Fix demonstrated defects where feasible.
6. Prepare controlled B0/B2/B3 benchmarks.
7. Produce authorization-ready proposals for live validation.

Do not reimplement completed features without evidence of a defect or missing functionality.

## 2. Repository context

Repository: `MaxCarlson/scripts`

Worktree: `C:\Users\mcarls\.codex\worktrees\d253\scripts`

Branch: `codex/local-agent-efficiency-20261025`

Previously reported implementation commit: `0f1f3f1bcd7a6b6fcb0845dd8257263bca0a8403`

Previously reported HEAD: `ba58ad0d91d7344e72e24a63d277eba7a270d52f`

Project documents:

- `plan.md` — canonical implementation plan.
- `HANDOFF.md` — original implementation handoff, retained for history.
- `STATUS.md` — progress and evidence.
- `HANDOFF-VALIDATION.md` — this validation-phase handoff.

All four documents belong in `modules/local_agent_bridge/docs/plans/20261025-agent-efficiency/`.

Read applicable `AGENTS.md` files and repository instructions before editing.

## 3. Phase A — Verify actual repository state

Inspect the active branch, HEAD, working tree, commit history, and implementation diff.

Read `plan.md`, `HANDOFF.md`, and `STATUS.md`.

Confirm which P0–P6 features are actually implemented, and identify discrepancies between the source code and previous progress reports.

Preserve unrelated work. Do not reset, clean, merge, rebase, or switch branches.

## 4. Phase B — Implementation review

Prefer an independent reviewer agent if available. If the implementation author performs the review, label it a self-audit rather than an independent review.

Review:

- Retrieval workspace containment, path traversal, symlinks/junctions, ignored files, binary files, output limits, and provenance.
- Lexical and structural retrieval tools, including `code_symbols` and `code_map`.
- JavaScript/Python boundary consistency and pinned OpenCode API compatibility.
- Default-deny tool permissions and read-only guarantees.
- Optional setup installation, resource ownership, receipts, and rollback.
- Checkpoint atomicity, project isolation, stale evidence, and recovery behavior.
- Compaction integration and prevention of duplicate worker dispatch.
- Benchmark scope auditing, tool profiles, hidden verification, and comparison contracts.

Record findings with severity, affected file and line, supporting evidence, impact, and proposed fix.

Do not proceed to live benchmarking with unresolved Critical or High findings.

## 5. Phase C — Reproduce offline validation

The previous agent reported:

- 149 passing `local_agent_bridge` tests.
- 117 passing benchmark integration/profile tests.
- 327 passing additional benchmark unit tests.
- 593 passing selected offline tests in total, with six skips and one deselection across those groups.

These results must be reproduced rather than assumed.

Use the exact test commands documented in `STATUS.md` where applicable.

Run relevant Ruff checks and `git diff --check`.

Record exact commands, environment, passed/failed/skipped/deselected counts, and any differences from the previous report.

Do not describe a selected test subset as a passing full suite.

## 6. Phase D — Diagnose OpenCode/MCP failures

The previous agent reported failures in runtime-facing `diagnostic_test.py` and `runner_test.py`, with OpenCode/MCP refusal occurring before model transition or worker dispatch.

Investigate this boundary using offline inspection, focused tests, mocks, and available logs.

Determine whether the problem is caused by:

- Configuration loading or setup.
- MCP server initialization or tool discovery.
- Permission registration.
- OpenCode session initialization.
- Runtime/API version incompatibility.
- Test fixture or environmental assumptions.
- A genuine implementation regression.

Compare the existing worker tool, lexical retrieval tools, and structural retrieval tools.

Implement narrowly scoped fixes when a defect is demonstrated, with regression tests.

Classify remaining issues as resolved offline, environment-dependent, requiring authorized live validation, or unresolved.

Do not start a live OpenCode worker session or invoke a model to diagnose the issue without authorization.

## 7. Phase E — Prepare controlled benchmarks

Prepare a reproducible evaluation of:

- **B0:** Existing baseline.
- **B2:** Bounded lexical retrieval.
- **B3:** Structural retrieval and repository maps.

Use the existing benchmark infrastructure rather than creating a replacement harness.

Define:

- Exact model, quantization, context window, inference settings, and tool versions.
- Identical task prompts, fixtures, verification rules, and timeouts.
- Explicit differences between B0, B2, and B3 tool profiles.
- Tasks covering bug fixing, repository investigation, multi-file changes, and tests.
- Repetition counts and randomized or counterbalanced run order.
- Correctness, scope violations, elapsed time, tool calls, source reads, repeated reads, tokens, compactions, and other available telemetry.
- Treatment of missing telemetry and invalid attempts.
- Exact benchmark commands, maximum run count, and runtime limits.

Do not claim an efficiency improvement before controlled measurements exist.

## 8. Authorization boundaries

Authorized:

- Read repository files and inspect Git state.
- Create or modify repository-local documentation, code, and tests.
- Run non-destructive offline tests and static analysis.
- Implement narrowly scoped fixes supported by evidence.
- Prepare benchmark configurations and commands.

Not authorized without separate explicit approval:

- Model inference.
- Live OpenCode worker dispatch.
- Model-backed benchmark execution.
- Model loading/reloading or inference configuration changes.
- Global dependency installation or configuration changes.
- Git commit, push, merge, rebase, reset, or destructive cleanup.
- Weakening default-deny permissions or benchmark safety checks.

## 9. Required deliverables

Update `STATUS.md` with actual evidence and the next continuation point.

Provide:

1. Verified implementation state.
2. Review findings, including severity and file/line references.
3. Exact offline test results.
4. OpenCode/MCP failure diagnosis and any fixes.
5. B0/B2/B3 benchmark protocol and readiness assessment.
6. Remaining risks and blockers.
7. Two separate authorization proposals:

   **Gate A — Live runtime smoke test:** Minimal model-backed integration test, with exact commands, configuration, request count, timeout, and stop conditions.

   **Gate B — Controlled benchmark:** Full B0/B2/B3 execution, with exact run counts, maximum duration, and stop conditions.

Approval for Gate A must not be treated as approval for Gate B.

## 10. Execution instruction

Begin immediately after saving this document.

Verify repository state, review the implementation, reproduce offline tests, and investigate the OpenCode/MCP failures.

Do not stop at documentation creation. Continue through all work that is safely possible offline.

At the end, report verified results and clearly identify anything requiring further authorization.

---

**Now execute this handoff.** Start with repository verification and the existing `STATUS.md`. Preserve the original `HANDOFF.md`. Do not commit or push changes.

## Continuation after benchmark preparation — 2026-10-29

Four matched fixtures, the default-strict intervention comparator, profile override, and a dry-run-first 36-dispatch B0/B2/B3 schedule are implemented and offline-tested. Continue from the benchmark preparation phase at the end of `STATUS.md`; do not repeat P0–P6 or execute either gate.

Current blockers: runtime evidence lacks effective output/context and inference-option provenance needed by the comparator; Gate A also has no hard bound on underlying completion turns in OpenCode 1.19.3. First action: design and test a pinned-source-backed settings collector at preflight. Keep both gates blocked until their specific controls are verifiable. All prior local edits remain uncommitted; no service/model operation, commit, or push occurred.
