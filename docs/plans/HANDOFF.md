# Repository-Wide Plans Handoff

## Active Plan

```text
20260729-2000_unified-hybrid-workflow/
```

## Scope Boundary

Use this plan tree for repository-wide infrastructure, standards, branch integration, validation orchestration, and development-ledger behavior shared across modules.

Use `modules/<module>/docs/plans/` for work owned by a single module.

## Current Priority

Validate the first repository-wide self-hosting cycle on `agent/unified-workflow-ledger`:

```powershell
./Invoke-Tests.ps1 -Target repository-workflow
```

After evidence is pushed, review the generated ledger projections and raw transcript before moving file-target expansion and ledger recording into native root-dispatcher phases.

## Historical Plan

```text
20260729-0900_validation-evidence-context-history/
```

The earlier context/diff plan remains historical migration evidence. Do not expand it as a parallel progress system.
