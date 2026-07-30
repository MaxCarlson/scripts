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

The active implementation branch provides:

- explicit branch and integration roles;
- repository instruction routing to branch and ledger standards;
- one structured repository-wide plan state;
- a manifest-driven development-ledger bridge;
- a self-hosting `repository-workflow` validation target;
- generic script-result evidence and permanent generated projections;
- continued raw `LATEST.txt` evidence during migration.

Read the active plan's `HANDOFF.md` and generated `ledger/PROGRESS.md` when present.

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
