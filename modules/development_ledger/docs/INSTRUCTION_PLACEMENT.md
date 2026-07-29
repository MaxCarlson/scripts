# Instruction Placement Strategy

## Core rule

The local LLM cannot see ChatGPT’s general Custom Instructions. Therefore, every repository behavior required for correct local work must exist in the repository instruction hierarchy.

General Custom Instructions should contain only cross-repository preferences and the high-level hybrid routing principle. They must not be the sole source of coding standards, safety rules, plan syntax, validation commands, or local-agent handoff behavior.

## General ChatGPT Custom Instructions

Keep these concepts globally:

- Prefer the browser/app agent for planning, implementation, tests, documentation, review, commits, pushes, and evidence diagnosis when repository tools permit.
- Use deterministic local validation rather than local-agent execution for routine checks.
- Escalate detailed environment-dependent debugging to local Codex.
- After returned validation evidence, begin with a compact stage review and decide whether to continue remotely, replan, or hand off locally.
- Do not repeat a remote fix without a new evidence-backed hypothesis.
- Generate a self-contained local handoff when escalation is warranted.
- Preserve the user’s general code-delivery, research, safety, and completion preferences.

Do not put repository-specific paths, commands, schemas, or model-routing tables only in this field.

## Root `AGENTS.md`

Keep generic rules shared by repositories:

- instruction-reading order,
- project-root discovery,
- canonical stage terminology,
- requirement to read project handoffs and plans,
- advisory hybrid-workflow reminder for substantial local tasks,
- branch-ownership rule,
- no concurrent local/remote edits to one branch,
- test and commit safety requirements.

The root file should route agents to repository-specific workflow documents rather than contain the complete ledger specification.

## `REPO_LLM_INSTRUCTIONS.md`

Store scripts-repository requirements:

- canonical root validation dispatcher,
- target manifest,
- development-ledger module and generated artifact locations,
- requirement to read `PROGRESS.md` before resuming an active plan,
- requirement to update the active plan state block before publishing changes,
- evidence-gated stage review,
- local escalation thresholds,
- generated files that must not be edited manually,
- exact local validation and evidence-publication loop.

## `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md`

Store the complete workflow protocol:

- responsibility split,
- stage lifecycle,
- required plan-state updates,
- validation event lifecycle,
- progress/stall/loop classifications,
- remote/local routing rules,
- local model/reasoning selection,
- local patch-branch procedure,
- manual-check lifecycle,
- return path after a local patch.

This document must be readable by both remote and local agents.

## Python and scripts standards files

Keep non-hybrid engineering rules in repository files:

- semantic versioning,
- CLI short/long flags,
- testing requirements,
- temp-root conventions,
- cross-platform support,
- entry-point installation behavior,
- help-registry updates,
- dependency ordering,
- formatting and linting.

These rules must never depend on global ChatGPT instructions.

## Project-level plan documents

Store project-specific facts:

- objective and architecture,
- stable item IDs and acceptance criteria,
- current stage,
- source/test mappings,
- manual checks,
- relevant files and documents,
- project safety invariants.

The generated ledger should derive history from this state; it should not replace the technical plan.

## Generated files

Agents read but do not manually edit:

- `RUNS.jsonl`
- `LATEST.json`
- `PROGRESS.md`
- `TRACEABILITY.md`
- `MANUAL_CHECKS.md`
- `LOCAL_HANDOFF.md`

Changes to generated files must come from the CLI or dispatcher.
