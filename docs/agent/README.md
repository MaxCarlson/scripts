# Agent Standards Index

This directory contains standards that support the repository `AGENTS.md` without making `AGENTS.md` long.

## Files

- `PYTHON_REPO_STANDARDS.md`: reusable Python standards suitable for copying into other Python repositories.
- `SCRIPTS_REPO_STANDARDS.md`: standards specific to the `scripts/` repository.
- `HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md`: reusable browser/app implementation plus repository-root local-validation workflow.
- `BRANCH_INTEGRATION_WORKFLOW.md`: canonical roles for `main`, `agent/unified`, and coherent `agent/<work>` branches.
- `LEGACY_PLANNING_MIGRATION.md`: how to treat the old `plans/modules/<module>/...` taxonomy.

## Development-Ledger Documentation

The reusable development-ledger protocol lives under:

```text
modules/development_ledger/docs/
```

Read these documents when creating or updating a substantial plan:

- `PLAN_FORMAT.md`: machine-readable plan-state block syntax and stable item IDs.
- `INTEGRATION.md`: repository-root validation-dispatcher integration and evidence flow.
- `INSTRUCTION_PLACEMENT.md`: instruction precedence and placement guidance.
- `SCRIPTS_INSTRUCTION_CHANGES.md`: migration requirements specific to this repository.

## Rule

Keep `AGENTS.md` short. Put detailed reusable standards here and repository-specific facts in `REPO_LLM_INSTRUCTIONS.md`.
