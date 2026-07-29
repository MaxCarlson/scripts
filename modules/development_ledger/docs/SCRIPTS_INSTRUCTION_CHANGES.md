# Proposed Scripts-Repository Instruction Changes

No repository-level file was changed in the initial module branch. This document specifies the later edits required after the module is accepted.

## `AGENTS.md`

Add only a compact routing rule:

- For an active substantial plan, read its generated `ledger/PROGRESS.md` after the normal handoff files.
- Do not edit generated ledger files manually.
- Before publishing a source pass, update the structured state block in the active plan.
- A local agent assigned a generated `LOCAL_HANDOFF.md` must keep the assignment narrow and use a separate patch branch for source edits.

Do not copy the complete ledger protocol into `AGENTS.md`.

## `REPO_LLM_INSTRUCTIONS.md`

Add a `Development Ledger` section containing:

1. Module location: `modules/development_ledger/`.
2. Generated per-plan output location: `<active-plan>/ledger/`.
3. The root dispatcher runs the ledger phase after all test/script phases.
4. `PROGRESS.md` is the first generated project-state view to read.
5. `RUNS.jsonl` is append-only and must not be manually edited.
6. The plan’s structured state block is the only recurring LLM-maintained progress input.
7. Source-editing agents must update objective, hypothesis, target IDs, implementation states, mappings, and manual checks before publishing.
8. Validation evidence must be pushed before the next remote modification pass.
9. The remote agent must review generated progress and routing before editing again.
10. Local source changes require a separate patch branch.

## `docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md`

Replace the snapshot-diff-centered diagnosis step with:

```text
Implement remotely
→ publish implementation commit
→ validate locally
→ normalize results
→ append immutable plan event
→ regenerate LLM projections
→ publish evidence commit
→ remote stage review
→ continue, replan, manual-check, or local handoff
```

Add explicit definitions for:

- material progress,
- partial progress,
- stalled,
- looping,
- regressing,
- ready,
- immediate local-escalation triggers,
- model/reasoning recommendation policy.

## `docs/agent/README.md`

Add `modules/development_ledger/docs/` to the instruction/documentation map and identify:

- `PLAN_FORMAT.md` as the plan-state syntax,
- `INTEGRATION.md` as dispatcher integration,
- `INSTRUCTION_PLACEMENT.md` as precedence guidance.

## Planning templates

Update the canonical plan template to include one development-ledger state block.

Do not require the LLM to maintain separate status and checklist files containing the same state indefinitely. During migration, existing `STATUS.md` and `checklist.md` may remain as project prose, but the machine-readable block should become the source used for generated state and validation correlation.

## `validation-targets.json`

Add target fields for:

- active plan path,
- ledger output path,
- JUnit result paths,
- generic script-result paths,
- raw transcript path,
- whether ledger recording is required,
- optional manual-check platform metadata.

## `Invoke-Tests.ps1`

Later integration should:

- request JUnit XML from pytest,
- pass generic result paths to the module,
- invoke `development-ledger record -w` last,
- preserve original validation exit codes,
- fail when required evidence cannot be recorded,
- display the generated progress/routing summary,
- show pending manual-check instructions,
- stop generating `LATEST_PROGRESS.diff` once migration is complete.

## `modules/scripts_help/.../registry.py`

After the CLI is accepted and installed, register:

- name: `development-ledger (module)`
- path: `modules/development_ledger`
- command: `development-ledger --help`
- version: module major/minor version

This update is intentionally outside the initial module-only branch.
