# Unified Hybrid Workflow Handoff

## Active Branch

```text
agent/unified-workflow-ledger
```

Base and integration target:

```text
agent/unified
```

## Current Stage

Stage S1 implements the repository control-plane self-hosting boundary.

Implemented:

- canonical `main` / `agent/unified` / `agent/<work>` branch roles and merge gates;
- repository instruction routing to branch and development-ledger standards;
- a structured repository-wide active plan;
- `validation/Invoke-DevelopmentLedger.ps1`, a reusable manifest-driven ledger bridge;
- `validation/tests/repository_workflow_test.ps1`, which emits generic script-result JSON;
- the `repository-workflow` root validation target;
- explicit preview/write safety and required-evidence enforcement;
- projection verification after an immutable write.

## Local Validation

Run:

```powershell
./Invoke-Tests.ps1 -Target repository-workflow
```

The target should:

1. install the editable development-ledger package;
2. validate the active plan state;
3. pass repository workflow contract tests;
4. write `docs/test-results/repository-workflow/LATEST.txt`;
5. append one event under `docs/plans/20260729-2000_unified-hybrid-workflow/ledger/`;
6. generate `LATEST.json`, `PROGRESS.md`, `TRACEABILITY.md`, and `MANUAL_CHECKS.md`;
7. preserve the root dispatcher's actual target result.

Commit and push generated validation and ledger evidence on the same feature branch. The remote agent must read the generated progress, traceability, manual checks, and raw transcript before the next source modification.

## Known Boundary

This stage does not yet:

- move file-target discovery into the `Invoke-Tests.ps1` process;
- add a native generic ledger phase to the root dispatcher;
- migrate RRBackup, Manga, or every existing target to ledger metadata;
- retire `LATEST_CONTEXT.md` or `LATEST_PROGRESS.diff`;
- merge the feature branch into `agent/unified`.

Those changes are intentionally ordered after the first repository-wide self-hosting validation cycle.
