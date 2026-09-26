# Scripts Repository Documentation Handoff

## Scope

This handoff covers repository-wide infrastructure and conventions that are not owned by one module.

## Active Repository-Wide Plan

```text
docs/plans/20260926-0107_missing-only-bootstrap/
```

This plan tracks missing-only bootstrap entry points and their shared installer. The earlier validation-evidence plan remains separate and open; it built:

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

The missing-only bootstrap implementation is complete and awaiting user validation. See its plan `STATUS.md` for exact checks and limitations. The validation-evidence system remains intentionally lightweight and is tracked separately in `docs/plans/20260729-0900_validation-evidence-context-history/`.

## Module-Specific Work

RRBackup consolidation remains tracked separately under:

```text
modules/rrbackup/docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```
