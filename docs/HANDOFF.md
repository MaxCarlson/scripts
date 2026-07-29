# Scripts Repository Documentation Handoff

## Scope

This handoff covers repository-wide infrastructure and conventions that are not owned by one module.

## Active Repository-Wide Plan

```text
docs/plans/20260729-0900_validation-evidence-context-history/
```

This plan tracks the shared validation evidence system built around:

```text
Invoke-Tests.ps1
validation-targets.json
docs/test-results/<target>/
```

## Current State

The first implementation provides:

- one repository-root validation dispatcher,
- manifest-selected validation targets,
- one authoritative `LATEST.txt` report per target,
- bounded report history,
- generated `LATEST_CONTEXT.md` snapshots from existing project status/checklist files,
- generated `LATEST_PROGRESS.diff` files showing context changes since the prior run.

The current implementation is intentionally lightweight. Future expansion is documented in the active repository-wide plan and should not delay module-specific work unless the validation infrastructure itself is blocking.

## Module-Specific Work

RRBackup consolidation remains tracked separately under:

```text
modules/rrbackup/docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```
