# Implementation Handoff — Local Coding-Agent Efficiency

**Project:** `local_agent_bridge` efficiency and context architecture
**Repository:** `MaxCarlson/scripts`
**Canonical plan:** `./plan.md`
**Progress tracker:** `./STATUS.md`
**Execution status:** Release A and offline P3 implementation complete on `codex/local-agent-efficiency-20261025`; P4 persistence/recovery audit is next

## 1. Your assignment

You are the implementation agent responsible for executing the Local Coding-Agent Efficiency Implementation Plan.

Your job is to **implement working improvements**, not merely research, summarize, or produce additional planning documents.

Begin with the highest-value changes and proceed through the implementation milestones while preserving existing functionality.

Your first major deliverable is **Release A: a functioning, tested bounded source-retrieval system integrated with `local_agent_bridge`, accompanied by improved worker instructions**.

After Release A passes its acceptance criteria, continue into Release B's OpenCode integration where practical. Do not stop after creating documentation or modifying prompts.

The complete project includes retrieval, OpenCode integration, checkpoints, structural code intelligence, and compaction support. Use the canonical plan to guide later work.

## 2. Immediate startup procedure

### Step 1 — Inspect the actual repository

Read the repository's current instructions and relevant module documentation.

Inspect at least:

- `modules/local_agent_bridge/README.md`
- `modules/local_agent_bridge/pyproject.toml`
- `modules/local_agent_bridge/local_agent_bridge/commands.py`
- `modules/local_agent_bridge/local_agent_bridge/cli.py`
- `modules/local_agent_bridge/local_agent_bridge/setup/`
- `modules/local_agent_bridge/local_agent_bridge/resources/`
- `modules/local_agent_bridge/tests/`
- `modules/agent_benchmark/README.md`
- `modules/agent_benchmark/agent_benchmark/bridge.py`
- `modules/agent_benchmark/agent_benchmark/tool_profile.py`
- `modules/agent_benchmark/agent_benchmark/comparison_conditions.py`
- `modules/agent_benchmark/agent_benchmark/evidence.py`

Read any applicable `AGENTS.md` and repository contribution instructions.

Check Git status and active worktrees before making changes.

Do not overwrite unrelated or pre-existing work.

### Step 2 — Reconcile the plan with reality

Confirm that the plan's assumptions match the checked-out code.

Pay particular attention to:

- Current CLI architecture.
- Setup planner/installer ownership rules.
- Worker and reviewer permission contracts.
- Existing test conventions.
- Python version and dependencies.
- Benchmark profile and scope-auditing rules.
- Current OpenCode and MCP integration contracts.

Record corrections in `STATUS.md`.

If the current repository already implements a planned feature, inspect and reuse it instead of duplicating it.

Do not spend excessive time rewriting the plan. Correct only material discrepancies.

### Step 3 — Run baseline offline validation

Identify and run the relevant existing offline tests.

Record:

- Exact commands.
- Pass/fail status.
- Existing failures.
- Runtime and dependency issues.
- Any tests requiring unavailable hardware or services.

Do not run LM Studio inference, load a model, or initiate live benchmark trials without explicit authorization.

### Step 4 — Implement P1

Update the canonical worker instructions and task-envelope guidance.

Make the worker prefer:

1. Known file and symbol hints.
2. Path discovery.
3. Targeted lexical search.
4. Small source excerpts.
5. Focused edits and verification.
6. Concise evidence-based results.

Avoid verbose instructions that increase prompt overhead unnecessarily.

Preserve existing result schemas, permission restrictions, and coordinator compatibility.

Add or update focused tests.

### Step 5 — Implement P2

Create the bounded retrieval core inside `local_agent_bridge`.

This is the first substantial engineering deliverable and must not be deferred merely because additional architecture decisions are possible.

Implement:

- Workspace-root validation.
- Git-aware path discovery.
- Bounded lexical search.
- Exact line-range source excerpts.
- Output-size enforcement.
- Truncation metadata.
- Structured JSON results.
- Additive CLI access.
- Unit and integration tests.

Use `ripgrep` where appropriate. Prefer deterministic, local, read-only operations.

Do not introduce embeddings, a vector database, an agent framework, or a background indexing service at this stage.

### Execution handoff — 2026-10-25

Release A is implemented. P0 baseline reconciliation and P1 acceptance reconciliation are recorded in `STATUS.md`; P1 reuses the existing v3.3.0 worker/task-envelope guidance. P2 adds reusable APIs in `local_agent_bridge.retrieval` (`locate`, `search`, `context`), JSON schema `local-agent-retrieval-v1`, and the additive `local-agent code locate|search|context` CLI. The package is now 3.4.0. No new mandatory dependencies, permission changes, setup resources, or prompt variants were added.

Validation: focused retrieval suite **22 passed**; full bridge suite **115 passed, 1 skipped, 1 deselected**. The deselected Git Bash test cannot launch Python through the Windows app-execution alias in this sandbox. Ruff passed on the retrieval core, CLI, and focused tests. Manual CLI checks verified Git discovery, a match at `commands.py:37`, and exact context lines 37–38. See `STATUS.md` for commands and the ambient editable-install/pytest-temp workarounds.

P3 is implemented and offline-verified. The pinned v1.19.3 source supports file-based custom tools with JSON-schema args and `execute(args, context)`; default-export tool names use the file basename and the execution context supplies the active project directory. The optional managed resource installs `code_locate` and `code_context` without changing OpenCode config. It launches the existing CLI via argv, never a shell. Setup owns each tool/helper file separately and can retire them with `--no-code-retrieval`.

`agent_benchmark` recognizes `retrieval-files-v1` as a distinct condition and prepares a `benchmark-retrieval` role. Its default deny remains, with explicit allows only for its standard file tools and the two read-only retrieval tools. Offline validation is in `STATUS.md`: bridge 118 passed/1 skipped/1 known Windows launcher deselected; benchmark profile/comparison/evidence/attempt/mock preflight 82 passed/1 skipped; targeted Ruff and diff checks passed. The two tool definitions serialize to 852 compact UTF-8 bytes in the measured name/description/JSON-schema shape; tokenizer tokens and complete OpenCode request overhead are not yet measured. There has been no live worker evaluation, OpenCode session, or model request.

Next: audit v3.3.0 job/session reconciliation and the existing `agent_memory`/`development_ledger` stores before P4. Add a task checkpoint only if it preserves authoritative information those components do not. Recovery must not resubmit uncertain work. Controlled B0/B2 evaluation and exact model-context overhead remain pending separate live-evaluation authorization.

### Step 6 — Verify Release A

Run all relevant offline tests.

Manually inspect representative retrieval outputs from an isolated fixture or safe repository path.

Confirm:

- Exact source provenance.
- Bounded output.
- Stable ordering.
- Safe path handling.
- No filesystem mutation.
- No public CLI regression.
- No permission changes.
- No unnecessary runtime dependencies.

Update documentation with real usage examples matching the implemented CLI.

Record actual evidence in `STATUS.md`.

### Step 7 — Begin Release B

Once Release A is working, investigate and implement the smallest OpenCode-compatible adapter for the retrieval core.

Verify APIs against the pinned OpenCode 1.19.3 implementation.

Prefer a small tool surface:

- `code_locate`
- `code_context`

Keep the adapter thin. Do not duplicate retrieval logic.

Use the existing setup planner/installer for optional production resources.

Integrate with `agent_benchmark` through a distinct, auditable retrieval-enabled profile. Do not weaken its existing default-deny policy or allow unrestricted shell access as a workaround.

Implement offline adapter tests first.

If the exact pinned runtime API cannot be verified, document the blocker and leave the adapter optional. Continue with other independent work rather than guessing at API compatibility.

## 3. Expected implementation structure

A suggested retrieval package:

- `retrieval/models.py`
- `retrieval/workspace.py`
- `retrieval/discover.py`
- `retrieval/search.py`
- `retrieval/excerpt.py`
- `retrieval/budget.py`

Use the existing package conventions for imports, CLI registration, packaging, tests, and typing.

Do not create new modules simply to match a proposed tree if a smaller design is clearer.

The implementation must be reusable by both the CLI and future OpenCode tools.

## 4. Technical requirements

### Retrieval

- Read-only by construction.
- No shell interpolation of untrusted search patterns.
- Canonical workspace containment.
- Safe handling of symlinks and Windows junctions.
- Bounded bytes, lines, and result counts.
- Exact file/line provenance.
- Explicit truncation and error states.
- Deterministic output ordering where practical.
- Support for literal search and explicit regex mode.
- Appropriate handling of Git ignored and untracked files.
- Clear behavior when `rg` is missing.
- No unnecessary network access.

### Compatibility

- Preserve existing commands and their behavior.
- Preserve model aliases and inference configuration.
- Preserve worker/reviewer permissions.
- Preserve existing installation receipts and rollback semantics.
- Avoid global configuration writes.
- Avoid mandatory new services.
- Keep new dependencies minimal and justified.

### Testing

Use the repository's established test framework and conventions.

At minimum, cover:

- Successful search and excerpt retrieval.
- Empty results.
- Large result truncation.
- Invalid ranges.
- Binary/Unicode handling.
- Path traversal.
- Symlink escapes.
- Ignored/untracked files.
- Missing `ripgrep`.
- JSON output stability.
- CLI backward compatibility.

Do not claim a test passed unless it actually ran.

## 5. Work sequencing and autonomy

You are authorized to perform repository-local source edits, create tests, update documentation, and run non-destructive offline validation required by this plan.

You may complete multiple coherent milestones in one working session.

Do not stop after each individual file to request approval.

Do not stop after P1 if P2 is feasible.

Do not stop after P2 if Release A passes and Release B can be safely started.

Use these rules:

- Complete the current milestone to a testable state.
- Run focused validation.
- Update `STATUS.md`.
- Continue to the next ready milestone.
- Stop only for an actual authorization boundary, unsafe operation, unresolved architectural conflict, or significant external dependency.

If blocked by an unrelated runtime issue, record it and continue with independent offline implementation.

Do not interpret this as permission to run live inference, install packages globally, change model settings, commit, push, merge, or modify unrelated repositories.

## 6. Decision policy

Prefer the simplest solution satisfying the requirements.

Before adding a dependency, answer:

- Can the standard library or an existing repository dependency do this?
- Does the dependency materially improve correctness or performance?
- Is it maintained and compatible with target platforms?
- Can the feature remain optional?
- What is its installation and runtime cost?

Do not introduce Serena, SCIP, embeddings, or an alternative execution harness into Release A.

Do not replace `agent_benchmark` with a custom benchmark implementation.

Do not replace OpenCode or `opencode-mcp` during the initial releases.

## 7. Performance and benchmarking

Implement features so they can be measured independently.

Preserve identifiable variants:

- B0: Existing baseline.
- B1: Updated instructions.
- B2: Updated instructions plus bounded retrieval.
- B3: Structural repository map.
- B4: Checkpoint/compaction support.

Record code/configuration identity and tool-profile differences.

Do not present benchmark results from different contexts or permission profiles as directly comparable without a declared experimental contract.

The existing 32K/64K D5 results are exploratory observations, not proof of an optimization.

Live benchmark runs require authorization.

## 8. Follow-on implementation after Release B

Continue in the following order, subject to measured value and prerequisites.

### P4 — Checkpoints

Implement versioned, atomic, project-scoped task checkpoints with stale-evidence detection and recovery packets.

Do not automatically restart or resubmit worker jobs.

### P5 — Structural retrieval

Implement Python AST symbol outlines and bounded task-specific repository maps.

Use Tree-sitter or ast-grep only if justified by language coverage and retrieval failures.

### P6 — Compaction

Verify OpenCode 1.19.3's actual compaction hooks and add an optional adapter using validated checkpoint state.

Do not depend on undocumented latest-version APIs.

### P7 — Advanced experiments

Evaluate Serena, hybrid retrieval, SCIP, or alternate harnesses only if the lightweight implementation has identifiable limitations.

Record the experiment and adoption criteria before installing a new framework.

## 9. Required progress reporting

After each milestone, update `STATUS.md` with:

- Completed changes.
- Exact changed files.
- Tests executed and results.
- Decisions made.
- Known regressions or blockers.
- Next recommended action.

Keep the handoff current enough that another agent can resume without reconstructing the entire conversation.

When a significant design decision differs from `plan.md`, document the reason and update the plan if necessary.

## 10. Definition of success for your first implementation session

The preferred first-session outcome is:

- Current repository state inspected.
- Existing offline tests characterized.
- P1 worker guidance implemented.
- P2 retrieval core implemented.
- CLI exposed.
- Retrieval tests passing.
- Documentation updated.
- `STATUS.md` contains accurate evidence.
- P3 adapter work started if time and API compatibility permit.

A partial session is acceptable when a real constraint prevents completion, but it must leave working code, tests, and a precise continuation point.

**Do not substitute planning output for implementation output.**

## 11. Final response contract

At the end of the session, report:

1. Milestones completed.
2. Files created or modified.
3. Functionality implemented.
4. Tests and exact outcomes.
5. Remaining blockers and risks.
6. Next milestone and concrete first action.
7. Whether any runtime/model operations were performed.

Clearly distinguish verified behavior from untested assumptions.

Do not claim the overall optimization is complete until the relevant implementation and benchmark acceptance criteria have been satisfied.

---

**Start now:** inspect the repository and working tree, run baseline offline checks, implement P1, and build the bounded retrieval core for P2. Continue into P3 if the prerequisites are satisfied.

## P0/P1 reconciliation — 2026-10-25

Verified remote `main` is `92c5f068fe2d0c8c99ca4a14991388b1819a3764`, which merges reliability v3.3.0. Performance work is isolated on `codex/local-agent-efficiency-20261025` at that commit. The local `origin/main` tracking ref was stale; the GitHub connector verified the pushed merge because direct Git Bash/SSH lookup failed with the Windows sandbox `NtCreateDirectoryObject` error.

P0 is reconciled. The `local_agent_bridge` 3.3.0 suite baseline is 92 passed, 1 skipped, with two known Git Bash shell-hook failures under this sandbox; excluding those exact cases in the post-merge worktree yields 92 passed, 1 skipped, 2 deselected. Benchmark profile/comparison/evidence tests yield 55 passed, 1 skipped. See `STATUS.md` for exact commands and limitations.

P1 is satisfied by existing implementation. Reuse the v3.3.0 worker and task-envelope resources; do not create a B1 instruction variant or rewrite canonical prompts without new evidence. Existing search-first, bounded-read, identity, permission, recovery, verification, and result-schema guarantees remain in force.

P2 interface/design is reconciled: additive `local-agent code locate|search|context` commands backed by reusable read-only APIs, Git-aware discovery, optional `rg`, bounded JSON, explicit truncation/errors, and workspace containment. Python `>=3.11`; no new mandatory dependency. Bump package and `__version__` in sync when implementation begins.

No inference, model, service, profile, or live benchmark operation was performed. The miner is running, so do not issue local-model requests. Next action: after the user switches to the lower-cost model, write focused retrieval tests first in the isolated branch, then implement P2.
