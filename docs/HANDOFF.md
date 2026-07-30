# Scripts Repository Documentation Handoff

## Scope

This handoff covers repository-wide infrastructure and conventions that are not owned by one module.

## Active Repository-Wide Plan

```text
docs/plans/20260729-2000_unified-hybrid-workflow/
```

This plan implements the merged hybrid-development design around:

```text
main
agent/unified
agent/<work>
Invoke-Tests.ps1
validation-targets.json
modules/development_ledger/
docs/test-results/<target>/
```

## Current State

Stage S1 passed its first Windows self-hosting cycle and produced raw plus immutable ledger evidence.

Stage S2 is implemented and awaiting validation. It provides:

- explicit branch and integration roles;
- repository instruction routing to branch and ledger standards;
- a structured repository-wide plan at revision 2;
- a thin interface-preserving `Invoke-Tests.ps1` entry point;
- focused validation modules for common resolution, artifacts, context, execution, target orchestration, and repository dispatch;
- native `file_targets` expansion from path, depth, and extension rules;
- optional per-target `temp_root` resolution;
- a native final development-ledger phase driven by target metadata;
- required-ledger and prior-command failure preservation tests;
- continued raw `LATEST.txt`, context, and progress-diff evidence during migration.

Read the active plan's `HANDOFF.md` and generated `ledger/PROGRESS.md` before another source pass.

## Historical Repository-Wide Plan

The earlier validation evidence/context-diff foundation remains under:

```text
docs/plans/20260729-0900_validation-evidence-context-history/
```

Its `LATEST_CONTEXT.md` and `LATEST_PROGRESS.diff` design remains transitional evidence until the ledger workflow has passed multiple real cycles.

## Module-Specific Work

Module-owned plans remain under:

```text
modules/<module>/docs/plans/
```

Do not continue work on already merged historical feature branches. Create new coherent branches from current `agent/unified`.
