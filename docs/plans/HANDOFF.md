# Repository-Wide Plans Handoff

## Active Plan

```text
20260729-2000_unified-hybrid-workflow/
```

## Scope Boundary

Use this plan tree for repository-wide infrastructure, standards, branch integration, validation orchestration, and development-ledger behavior shared across modules.

Use `modules/<module>/docs/plans/` for work owned by a single module.

## Current Priority

Validate Stage S2 on `agent/unified-workflow-ledger`:

```powershell
gl && .\Invoke-Tests.ps1
```

Stage S2 replaces the monolithic dispatcher internals with focused modules, resolves `file_targets` natively, supports target-specific temp roots, and records ledger metadata as the final native target phase.

After evidence is pushed, review:

```text
docs/test-results/repository-workflow/LATEST.txt
docs/test-results/repository-workflow/LATEST_CONTEXT.md
docs/test-results/repository-workflow/LATEST_PROGRESS.diff
docs/plans/20260729-2000_unified-hybrid-workflow/ledger/PROGRESS.md
docs/plans/20260729-2000_unified-hybrid-workflow/ledger/TRACEABILITY.md
```

Do not begin RRBackup ledger migration or retire transitional context artifacts until this native dispatcher cycle passes.

## Historical Plan

```text
20260729-0900_validation-evidence-context-history/
```

The earlier context/diff plan remains historical migration evidence. Do not expand it as a parallel progress system.
