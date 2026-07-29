<!-- development-ledger:generated-template:v1 -->
# Hybrid Development and Validation Workflow

## Purpose

This repository uses a plan-aware development ledger so remote and local LLMs can exchange implementation intent, validation evidence, and narrow diagnostic assignments without reconstructing history from chat.

## Scope discovery

- The repository root uses `docs/` for repository-wide plans and evidence.
- A subdirectory with its own `AGENTS.md` and adjacent `docs/` is a separate planning scope for that directory and descendants.
- Use the nearest applicable scope unless an active plan explicitly coordinates multiple scopes.
- More-specific native instruction files override conflicting broader instructions for their subtree.

## Required reading order

1. Applicable native instruction files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or Copilot instructions)
2. Nearest `docs/HANDOFF.md`
3. Active plan
4. Active plan's generated `ledger/PROGRESS.md`
5. `ledger/TRACEABILITY.md`, `MANUAL_CHECKS.md`, and `LOCAL_HANDOFF.md` when relevant
6. Raw logs only when normalized evidence is insufficient

## Agent responsibilities

### Remote/browser agent

- Inspect the repository and current plan state.
- Define one bounded stage or corrective pass.
- Implement source, tests, configuration, and documentation together.
- Review the complete diff.
- Update the active plan state block before publishing changes.
- Commit and push coherent feature-branch work when authorized.
- Analyze returned validation evidence before editing again.

### Deterministic local validator

- Pull the implementation commit.
- Run the repository's canonical validation dispatcher.
- Capture exact commands, stdout/stderr, exit codes, platform/runtime metadata, normalized tests, and supporting artifacts.
- Append one immutable development-ledger event and regenerate projections.
- Avoid production mutation by default.

### Local LLM

- Enter only for environment-dependent diagnosis, interactive debugging, or a generated narrow handoff.
- Work on a separate local patch branch when source changes are needed.
- Do not take over unrelated stages.

### User

- Run local validation when required.
- Inspect generated evidence and any manual-check instructions.
- Stage, commit, and push evidence or local patches according to repository authorization.

## Plan-state requirement

Before a source-editing agent stops, it updates the structured state block in the active plan with:

- stage identity and state,
- actor and hybrid/local mode,
- bounded objective,
- diagnostic hypothesis when applicable,
- target feature/requirement/criterion IDs,
- implementation states,
- expected test mappings,
- local-environment dependencies,
- manual checks,
- relevant files and documents.

Agents do not manually write validation outcomes or run-history entries.

## Evidence gate

After validation evidence is published, no further source modification begins until the responsible agent reviews the generated progress summary and classifies the iteration.

Material progress requires at least one of:

- a plan item becomes verified,
- a failure is resolved,
- a broad failure is reduced to a narrower reproducible case,
- a hypothesis is confirmed or falsified in a way that narrows the search space,
- a required environment dependency is demonstrated,
- a regression is removed.

Code volume, formatting changes, repeated validation, or rewritten explanations do not independently count as progress.

## Progress classifications

- `progressing`: material progress with a clear next remote action
- `partial_progress`: progress occurred but blockers remain
- `stalled`: no semantic implementation or diagnostic progress
- `looping`: repeated failures or hypotheses without useful new evidence
- `regressing`: new failures, lost verification, weakened tests, or unsafe scope expansion
- `ready`: all non-deferred items are verified, subject to remaining acceptance/manual checks

## Routing

- Continue remotely while evidence shows progress or supports a distinct bounded hypothesis.
- Permit only one targeted remote pass after a stalled run, and require the new hypothesis to be stated first.
- Replan remotely for architecture, requirements, scope, or source-visible design defects.
- Hand off locally when failures depend on the actual OS, installed tools, services, credentials, hardware, networking, storage, GUI/TUI behavior, local-only state, profiling, or interactive debugging.
- Hand off locally when the same failure survives two targeted remote fixes or consecutive runs make no material progress.

## Branch ownership

- The remote agent owns the main feature branch.
- Deterministic evidence-only commits may be added according to repository policy.
- Local-agent source changes use a separate patch branch.
- Remote and local agents must not edit the same source branch concurrently.
- Merge only after required validation and user acceptance.

## Generated artifacts

The plan's `ledger/` directory contains:

- `RUNS.jsonl`: append-only immutable events
- `LATEST.json`: latest event
- `PROGRESS.md`: primary fresh-agent orientation
- `TRACEABILITY.md`: plan-item/test/manual evidence mapping
- `MANUAL_CHECKS.md`: exact user validation steps
- `LOCAL_HANDOFF.md`: narrow local-agent assignment when escalation is active

Do not edit these files manually.

## Manual checks

Behavior automation cannot establish must be represented by stable manual-check IDs with:

- platform/environment,
- exact steps,
- expected result,
- safety classification,
- linked plan items.

An agent must show pending manual instructions to the user before claiming the stage complete.
