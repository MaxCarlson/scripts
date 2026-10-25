# Local Coding-Agent Efficiency — Implementation Plan

**Status:** Proposed — ready for implementation
**Created:** 2026-10-25
**Primary module:** `modules/local_agent_bridge/`
**Repository:** `MaxCarlson/scripts`
**Related modules:** `agent_benchmark`, `benchmark_core`, `resource_metrics`, `agent_memory`, `development_ledger`, `agent_sync`
**Plan owner:** Implementation agent, subject to user review
**Primary objective:** Improve verified coding-task completion per unit of wall-clock time and inference cost.

---

## 1. Objective

Implement an incremental optimization architecture for the locally hosted Qwen coding-agent workflow:

- Qwen 27B Q4_K_M, served by LM Studio.
- OpenCode 1.19.3 as the execution harness.
- `opencode-mcp` 3.0.0 as the coordinator-to-worker bridge.
- Codex or Gemini as a coordinating agent.
- Windows 11, RTX 5090 32 GB VRAM, 64 GB system RAM, WSL2, with sensible portability to macOS and Termux.
- A nominal 65,536-token context and 8,192-token output configuration, subject to verification against the effective runtime.

The goal is not to maximize context length or add as many tools as possible. The goal is to reduce unnecessary source exploration, repeated reads, context loss, and failed agent execution while preserving correctness, permissions, project isolation, and compatibility.

Implement the work in independently testable increments. Prefer changes with high expected benefit relative to engineering effort.

## 2. Existing architecture and constraints

The repository already has relevant infrastructure:

- `local_agent_bridge`: local runtime configuration, installer, worker/reviewer profiles, handoff instructions, and MCP configuration.
- `agent_benchmark`: isolated task fixtures, OpenCode execution, model/session validation, scope auditing, verification, telemetry, and trial management.
- `benchmark_core`: experiment data and comparison/reporting functionality.
- `resource_metrics`: hardware and process measurements.
- `agent_memory`: persistent notes and indexing; potential later integration.
- `development_ledger`: plan progress, validation evidence, and implementation handoffs.
- `agent_sync`: coordination capabilities; potential later integration.

Reuse existing implementations wherever practical.

The connected repository inspection previously identified these relevant files:

- `modules/local_agent_bridge/local_agent_bridge/commands.py`
- `modules/local_agent_bridge/local_agent_bridge/setup/planner.py`
- `modules/local_agent_bridge/local_agent_bridge/setup/installer.py`
- `modules/local_agent_bridge/local_agent_bridge/resources/skills/local-agent-handoff/resources/local-worker.md`
- `modules/local_agent_bridge/local_agent_bridge/resources/skills/local-agent-handoff/references/task-envelope.md`
- `modules/local_agent_bridge/local_agent_bridge/resources/integrations/opencode-agent.example.json`
- `modules/agent_benchmark/agent_benchmark/bridge.py`
- `modules/agent_benchmark/agent_benchmark/tool_profile.py`
- `modules/agent_benchmark/agent_benchmark/comparison_conditions.py`
- `modules/agent_benchmark/agent_benchmark/evidence.py`
- `modules/agent_benchmark/agent_benchmark/runner.py`

These are starting points, not guarantees that current branch contents remain unchanged. Reinspect the actual checkout before editing.

### Existing baseline

User-provided exploratory D5 results:

| Metric | 32K context | 64K context |
|---|---:|---:|
| Wall time | 1,128.58 s | 671.78 s |
| Compactions | 10 | 3 |
| Source reads | 34 | 23 |
| Reasoning tokens | 88,974 | 44,374 |
| Cumulative input tokens | 867,876 | 2,146,292 |
| Steps | 41 | 52 |

These are exploratory single-run observations, not a controlled performance conclusion.

The local forensic data may be available under `C:\Users\mcarls\local-agent-forensics\analysis\`. Do not claim to have inspected it unless it is actually accessible.

A previous repository validation reported successful bounded worker execution through MCP, but production Codex CLI dispatch was blocked by missing `opencode_worker` exposure in the active client session. Investigate this independently; do not assume the problem remains unchanged.

## 3. Architectural principles

1. **Preserve the existing execution harness.** OpenCode and `opencode-mcp` remain the default execution path.
2. **Separate retrieval from execution.** Read-only source intelligence must not implicitly grant shell or edit permissions.
3. **Prefer bounded evidence.** Return relevant paths, symbols, and excerpts rather than large source dumps.
4. **Use progressive disclosure.** Start with path discovery, then targeted search, then excerpts, then deeper structural context.
5. **Preserve durable task state.** Conversation history is not a reliable long-term task database.
6. **Use independent verification.** Benchmark correctness and scope compliance must be assessed outside the worker's self-report.
7. **Avoid duplicate frameworks.** Do not rebuild benchmark, coordination, memory, or process supervision infrastructure already present in the repository.
8. **Make integrations optional.** Missing optional parsers, plugins, or MCP tools must not break existing local-agent functionality.
9. **Keep the implementation reversible.** Preserve current commands, configurations, profiles, and installer ownership semantics.
10. **Measure before expanding complexity.** Add advanced indexing or alternate harnesses only when experiments justify them.

## 4. Target architecture

The intended workflow is:

1. The coordinator creates a bounded task envelope.
2. The repository retrieval layer identifies relevant files, symbols, and tests.
3. A compact context packet supplies the worker with high-value evidence.
4. The worker executes through the existing OpenCode/MCP route.
5. The worker reads additional source only as needed.
6. A checkpoint records task state and validated discoveries.
7. The worker implements and verifies the change.
8. The coordinator receives a structured result and independently checks the outcome.
9. The benchmark system measures correctness, latency, retrieval behavior, and context costs.

### Ownership

**`local_agent_bridge` owns:**

- Worker instructions and task-envelope conventions.
- Read-only repository retrieval.
- Context-packet construction.
- Task checkpoints and recovery.
- Optional OpenCode retrieval and compaction adapters.
- Installation and configuration integration for those adapters.

**`agent_benchmark` owns:**

- Trial orchestration.
- Isolated workspaces.
- Worker execution evidence.
- Strict scope auditing.
- Correctness verification.
- Experimental variant tracking.
- Trial-level performance metrics.

**`benchmark_core` owns:**

- Canonical experiment results.
- Aggregation.
- Statistical comparison.
- Reports.

Other modules remain optional integrations unless a demonstrated requirement justifies tighter coupling.

## 5. Implementation priorities

| ID | Priority | Workstream | Estimated effort | Dependencies |
|---|---|---|---|---|
| P0 | Critical | Baseline, repository reconnaissance, readiness | 0.5–2 days | None |
| P1 | Critical | Worker instructions and task envelopes | 0.5–1 day | P0 |
| P2 | Critical | Bounded lexical retrieval core | 2–4 days | P0 |
| P3 | High | OpenCode retrieval-tool integration | 2–4 days | P2 |
| P4 | High | Durable task checkpoints and recovery | 2–4 days | P1 |
| P5 | High | Structural outlines and repository maps | 3–6 days | P2 |
| P6 | Medium–high | OpenCode-aware compaction integration | 3–6 days | P4 |
| P7 | Experimental | Advanced retrieval and alternative harness evaluation | 4–10+ days | P2–P6 |

Effort estimates are planning estimates, not performance measurements.

The implementation agent should progress through P0–P3 without requiring a new high-level planning assignment. P4–P6 may proceed once prerequisites and relevant safety checks pass. P7 requires evidence-based justification.

---

## 6. P0 — Baseline and repository reconnaissance

### Tasks

- Inspect repository guidance, module documentation, public CLI interfaces, tests, and active worktree state.
- Identify current package versions and installation ownership rules.
- Verify the current OpenCode and `opencode-mcp` integration contracts.
- Inspect the existing benchmark's comparison conditions, execution profiles, and scope auditing.
- Identify available offline tests and supported local commands.
- Investigate the reported production Codex MCP-discovery issue.
- Record any uncertainty about model identity, context configuration, token counters, or forensic data.
- Create or update the plan's `STATUS.md` and `HANDOFF.md`.

### Implementation rules

Do not block the entire project on production MCP-discovery troubleshooting. Time-box initial investigation, record the blocker, and proceed with offline retrieval development if the runtime problem is independent.

Do not alter model configuration or reload a model merely to establish a baseline.

### Deliverables

- Reconciled repository inventory.
- Documented existing interfaces and safety invariants.
- Initial baseline/measurement specification.
- Reproducible offline test commands.
- Updated status and handoff documents.

### Acceptance

- The actual code paths to be extended are identified.
- Existing relevant tests pass, or pre-existing failures are documented.
- The current runtime blocker is either resolved or precisely characterized.
- No production settings have been changed without authorization.

---

## 7. P1 — Efficient worker instructions and task envelopes

### Objective

Improve source exploration efficiency with minimal additional prompt overhead.

### Tasks

Update the canonical worker prompt and relevant handoff resources to encourage:

- Using supplied file and symbol hints first.
- Path discovery before broad source reads.
- Lexical search before reading large files.
- Small, line-bounded excerpts.
- Expansion only when additional context is necessary.
- Avoidance of repeated identical searches.
- Explicit stopping criteria for exploration.
- Focused verification after changes.
- Concise evidence-based results.

Do not force every task through an implementation workflow; investigation and review tasks may legitimately finish without edits.

Extend task-envelope guidance with optional fields for:

- Candidate files and symbols.
- Known relevant tests.
- Base commit or source revision.
- Allowed and forbidden paths.
- Acceptance criteria.
- Suggested verification commands.
- Context budget or retrieval hints.

Maintain backward compatibility with existing handoff instructions and result schemas.

### Acceptance

- Worker/reviewer permissions are unchanged.
- Prompt resources remain compact.
- Existing handoff workflows remain valid.
- Resource and schema tests pass.
- Instruction changes can be identified as a distinct benchmark variant.

---

## 8. P2 — Bounded lexical retrieval core

### Objective

Implement the first substantial optimization: fast, deterministic, read-only source retrieval.

### Proposed package

`modules/local_agent_bridge/local_agent_bridge/retrieval/`

Suggested files:

- `models.py`
- `workspace.py`
- `discover.py`
- `search.py`
- `excerpt.py`
- `budget.py`

The implementation may use a different internal organization if justified.

### Required operations

**Path discovery**

- Enumerate candidate source files.
- Respect Git tracking and ignore rules where appropriate.
- Permit explicit, authorized access to untracked source files.
- Exclude common generated, binary, cache, and dependency directories.
- Support bounded result counts.

**Lexical search**

- Use `ripgrep` when available.
- Pass arguments safely without shell interpolation.
- Support literal search by default and explicit regex mode.
- Return file path, line number, and bounded match context.
- Report truncation and subprocess failures explicitly.
- Provide a reasonable fallback or clear dependency error when `rg` is unavailable.

**Source excerpts**

- Read an exact file and line range.
- Return stable file/line provenance.
- Enforce byte and line limits.
- Support continuation requests.
- Reject unsafe paths.
- Detect binary or unsuitable files.
- Preserve source text accurately.

**Budget enforcement**

- Enforce hard byte limits independently of estimated token counts.
- Make output limits configurable.
- Return truncation metadata rather than silently omitting content.
- Avoid loading unnecessarily large files into memory.

### Initial proposed defaults

| Operation | Limit |
|---|---|
| Path discovery | 200 paths / 8 KiB |
| Lexical search | 80 matches / 12 KiB |
| Source excerpt | 200 lines / 16 KiB |
| Prepared source context | Approximately 8–12K estimated tokens |

Treat these as tunable starting points.

### Security and portability

- Canonicalize and validate workspace roots.
- Reject path traversal and symlink/junction escapes.
- Keep all operations read-only.
- Handle Windows and WSL path differences.
- Use UTF-8 carefully and report decoding problems.
- Avoid hidden network access.
- Avoid global package installation.
- Avoid modifying the target repository during retrieval.

### CLI integration

Expose the functionality through additive `local-agent` subcommands, using existing CLI conventions.

Suggested conceptual commands:

- `local-agent code locate`
- `local-agent code excerpt`

The agent should inspect the current CLI architecture before deciding the final command and argument syntax.

Prefer machine-readable JSON output with an optional human-readable presentation.

### Tests

Cover:

- Literal and regex searches.
- Spaces and Unicode in paths.
- Empty matches.
- Output truncation.
- Large files.
- Binary files.
- Ignored files.
- Explicit untracked files.
- Nested repositories.
- Symlink/junction escapes.
- Path traversal.
- Windows path behavior.
- Stable ordering.
- Missing dependencies.
- Invalid line ranges.
- No filesystem mutation.

### Acceptance

- Retrieval is usable independently of LM Studio and OpenCode.
- Relevant file locations and excerpts are returned with exact provenance.
- Every operation has a bounded response.
- No unsafe path access is possible.
- Existing CLI behavior remains unchanged.
- New and existing offline tests pass.

---

## 9. P3 — OpenCode retrieval integration

### Objective

Make the retrieval core directly usable by the local worker without broadening its execution permissions.

### Tasks

- Verify the custom-tool/plugin APIs available in OpenCode 1.19.3.
- Select the smallest stable integration mechanism.
- Prefer a project-local adapter when supported.
- Otherwise evaluate an optional local MCP retrieval server.
- Expose a minimal tool surface, initially:
  - `code_locate`
  - `code_context`
- Reuse the P2 retrieval implementation rather than duplicating logic.
- Add installation resources through the existing setup planner/installer.
- Preserve existing worker/reviewer roles and permission boundaries.
- Keep retrieval optional and disabled by default until validated.

### Benchmark integration

The current `agent_benchmark` file-tools profile is deliberately restrictive. Do not bypass it.

Create a separately identifiable, auditable retrieval-enabled execution profile or equivalent explicit capability declaration.

Update transcript auditing only for known, read-only operations with verified arguments and project-root containment.

### Acceptance

- Retrieval tools can be resolved in an isolated OpenCode test environment.
- Tool calls remain read-only and project-scoped.
- No unrestricted shell allowance is introduced.
- Existing strict benchmark profiles remain valid.
- The adapter can be removed without disrupting the original workflow.
- The selected API is confirmed compatible with the pinned OpenCode version.

---

## 10. P4 — Durable task checkpoints

### Objective

Preserve important task state independently of conversation history.

### Proposed package

`local_agent_bridge/context/`

Suggested components:

- Task-envelope normalization.
- Versioned checkpoint model.
- Atomic checkpoint storage.
- Checkpoint validation.
- Compact recovery-packet generation.

### Checkpoint contents

- Task ID and objective.
- Authorized scope.
- Project/workspace identity.
- Base commit or source revision.
- Session and job identifiers, if known.
- Confirmed source references.
- Decisions and assumptions.
- Modified paths.
- Completed verification.
- Pending checks.
- Blockers.
- Next action.

### Requirements

- Store state outside the working tree by default.
- Partition state by canonical project identity.
- Avoid storing secrets or unnecessary source dumps.
- Use atomic writes and schema validation.
- Detect stale file references and changed revisions.
- Never automatically resubmit a job on recovery.
- Keep `agent_memory` integration optional.

### Acceptance

- Interrupted tasks can recover their objective and next action.
- Changed source invalidates stale evidence.
- No unauthorized job is launched during recovery.
- Checkpoint storage does not modify project source files.

---

## 11. P5 — Structural retrieval and repository maps

### Objective

Improve source selection for cross-file tasks without imposing a heavy indexing system.

### Tasks

- Implement Python AST-based symbol extraction first.
- Return compact definitions, classes, methods, imports, and line ranges.
- Add task-specific ranking of relevant symbols.
- Build token-budgeted repository maps.
- Support cache invalidation using file content or revision identity.
- Evaluate optional Tree-sitter or ast-grep adapters for additional languages.
- Measure index construction cost and memory overhead.

### Acceptance

- Repository maps are bounded and source-linked.
- Stale indexes are detected.
- Relevant-symbol retrieval improves over lexical-only search on representative tasks, or the feature remains optional.
- No parser is required for languages that can be handled adequately through lexical retrieval.

---

## 12. P6 — Compaction-aware context recovery

### Objective

Reduce loss of critical task information across long-running sessions.

### Tasks

- Inspect the exact OpenCode 1.19.3 compaction lifecycle and available hooks.
- Determine whether the `experimental.session.compacting` hook is supported in the pinned runtime.
- Add a version-gated adapter only if the API is stable enough.
- Supply verified checkpoint information to compaction.
- Preserve objective, constraints, decisions, modified files, checks, and next action.
- Avoid retaining repeated searches and obsolete tool outputs.
- Provide a standalone checkpoint-recovery fallback when plugin integration is unavailable.

### Acceptance

- Compaction does not remove critical task constraints.
- Recovery does not duplicate edits or dispatch.
- Unsupported OpenCode versions fail safely.
- Controlled trials demonstrate a measurable benefit or the adapter remains disabled.

---

## 13. P7 — Advanced retrieval and framework experiments

Evaluate only after the lightweight architecture has a measured baseline.

Potential candidates:

- Serena for symbol-aware code navigation.
- Aider repository-map techniques.
- Tree-sitter for multi-language structural parsing.
- ast-grep for structural matching.
- SCIP for larger cross-reference indexes.
- Hybrid lexical/semantic retrieval.
- OpenHands SDK or SWE-agent as alternative execution/ACI references.

Evaluate each candidate for:

- Retrieval quality.
- Added prompt/tool overhead.
- Runtime and indexing cost.
- Installation complexity.
- License and maintenance.
- Windows, WSL2, macOS, and Termux compatibility.
- Correctness impact.
- Measured wall-clock benefit.

Do not adopt a heavyweight framework merely because it has more capabilities.

---

## 14. Benchmark and evaluation plan

### Variants

- B0: Current baseline.
- B1: Revised instructions only.
- B2: B1 plus bounded lexical retrieval.
- B3: B2 plus structural repository map.
- B4: B2 plus checkpoints/compaction support.
- B5: Best-performing combination.
- B6: Optional alternative retrieval framework.

### Task categories

- Focused bug fix.
- Multi-file change.
- Test creation.
- Investigation-only task.
- Cross-file dependency reasoning.
- Long-horizon implementation and recovery.

### Metrics

**Primary**

- Independently verified success.
- Strict scope compliance.
- Wall-clock completion time.
- Coordinator repair required.

**Secondary**

- Source reads and repeated reads.
- Search count.
- Source bytes returned.
- Tool calls and failures.
- Input/output/reasoning tokens when available.
- Compaction count.
- Recovery success and time.
- Peak RAM/VRAM and GPU utilization when available.

Do not interpret missing telemetry as zero.

### Experimental controls

- Pin model identity and quantization.
- Record effective context and output settings.
- Keep task fixtures and verifier versions fixed.
- Use fresh, isolated workspaces.
- Record warm/cold runtime state.
- Counterbalance task and variant order.
- Preserve explicit comparison contracts.
- Avoid mixing 32K and 64K runs in a controlled comparison.
- Use multiple repetitions rather than drawing conclusions from single runs.

### Suggested gates

- No correctness or scope regression.
- Target at least 15% lower median wall-clock time for promotion.
- Target at least 25% fewer repeated source reads for retrieval improvements.
- No material increase in tool failures or coordinator repair.
- Demonstrate benefit across multiple task categories.

These are proposed engineering gates, not guaranteed outcomes.

### Benchmark architecture

Extend `agent_benchmark` and `benchmark_core` instead of introducing a separate benchmarking subsystem.

When a tool profile intentionally changes, record the intervention as a distinct versioned experimental condition. Do not silently disable existing comparison safeguards.

For long-running tasks, introduce an explicit extended budget rather than changing canonical short-task benchmark defaults.

---

## 15. Release strategy

### Release A — Foundation

Includes P0, P1, and P2.

Deliver:

- Repository reconciliation.
- Updated worker guidance.
- Bounded retrieval core.
- CLI access.
- Offline tests.
- Baseline measurement specification.

This is the **minimum useful implementation release**.

### Release B — Worker integration

Includes P3.

Deliver:

- OpenCode retrieval adapter.
- Auditable tool permissions.
- Installer integration.
- Retrieval-enabled benchmark profile.
- Initial B0/B1/B2 comparison when inference is authorized.

### Release C — Context persistence

Includes P4.

Deliver:

- Checkpoint schema and storage.
- Recovery packets.
- Stale-evidence detection.
- Restart and interruption tests.

### Release D — Structural intelligence

Includes P5.

Deliver:

- Symbol extraction.
- Task-aware repository maps.
- Retrieval-quality measurements.

### Release E — Compaction

Includes P6.

Deliver:

- Validated OpenCode compaction integration or documented fallback.
- Long-running recovery evaluation.

### Release F — Advanced experiments

Includes P7 only when prior measurements justify further complexity.

---

## 16. Repository layout

Proposed additions:

`modules/local_agent_bridge/local_agent_bridge/retrieval/`

`modules/local_agent_bridge/local_agent_bridge/context/`

`modules/local_agent_bridge/local_agent_bridge/resources/integrations/opencode-tools/`

`modules/local_agent_bridge/tests/` — extend existing test organization.

`modules/agent_benchmark/agent_benchmark/variants.py` — if justified by the current architecture.

`modules/agent_benchmark/agent_benchmark/tasks/agent-efficiency/` — new benchmark fixtures when ready.

Do not create empty placeholder modules unnecessarily.

---

## 17. Safety and compatibility

The implementation must:

- Preserve public CLI behavior.
- Preserve existing model aliases and runtime settings.
- Preserve worker/reviewer permissions.
- Preserve project isolation.
- Preserve installer ownership and rollback behavior.
- Preserve strict benchmark scope auditing.
- Avoid writing to unrelated projects.
- Avoid installing dependencies globally.
- Avoid loading/reloading models without authorization.
- Avoid live inference without authorization.
- Avoid commits, pushes, or merges unless explicitly authorized.
- Avoid destructive cleanup of user data.
- Respect pre-existing uncommitted changes.

Repository source edits and offline tests are authorized as part of implementing this plan, subject to the operating instructions supplied with the task.

---

## 18. Completion criteria

The overall project is complete when:

1. A local worker can retrieve relevant source through bounded, project-scoped tools.
2. The worker uses a compact, effective exploration policy.
3. The retrieval implementation has comprehensive offline tests.
4. OpenCode integration is version-compatible and permission-safe.
5. Task checkpoints can preserve and recover essential state.
6. Structural retrieval and compaction improvements are adopted only when justified.
7. Benchmark variants are independently verifiable and comparable.
8. At least one optimized configuration demonstrates a meaningful efficiency improvement without reducing correctness.
9. Documentation and installation/rollback procedures are complete.
10. Existing workflows continue to function.

## 19. Project tracking

- `plan.md`: authoritative specification.
- `STATUS.md`: completed work, tests, blockers, decisions, and next actions.
- `HANDOFF.md`: execution instructions and continuation protocol.

Update `STATUS.md` after each meaningful milestone.

When a stage is blocked, document the reason and continue with independent work where safe.

Do not replace this plan with a new high-level plan unless a genuine architectural conflict requires revision. Record changes and rationale instead.

## 20. References

- Repository: https://github.com/MaxCarlson/scripts
- OpenCode: https://opencode.ai
- Serena: https://github.com/oraios/serena
- Aider: https://github.com/Aider-AI/aider
- Tree-sitter: https://github.com/tree-sitter/tree-sitter
- ast-grep: https://github.com/ast-grep/ast-grep
- SCIP: https://github.com/sourcegraph/scip
- SWE-agent: https://github.com/SWE-agent/SWE-agent
- OpenHands SDK: https://github.com/OpenHands/software-agent-sdk

Research findings and benchmark results should be added to the plan as explicit evidence, not represented as validated if they have not been independently checked.
