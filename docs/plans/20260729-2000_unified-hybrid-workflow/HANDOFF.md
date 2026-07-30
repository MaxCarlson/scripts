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

Stage S2 replaces helper-command orchestration with native modular dispatcher phases.

Implemented:

- all public `Invoke-Tests.ps1` parameters remain available;
- the root script delegates to `validation/ValidationDispatcher.psm1`;
- target selection, temp-root resolution, artifact retention, context generation, command execution, and ledger sequencing are separated into focused modules;
- `file_targets` resolves `path`, `max_depth`, and extension rules inside the dispatcher process;
- target-specific `temp_root` supports `{system_temp}`, `{target_name}`, and `{timestamp}` tokens;
- ledger metadata executes after commands and PowerShell test groups without an explicit manifest command;
- required ledger failures fail the target, while earlier command failures remain authoritative;
- `repository-workflow` validates native file discovery and final-ledger ordering;
- `development-ledger` is migrated to the native ledger phase;
- RRBackup remains behaviorally unchanged and keeps its existing declarative file-target rules.

## Local Validation

Pull and run the default repository workflow target:

```powershell
 gl && .\Invoke-Tests.ps1
```

The target should:

1. create its temporary root below the current user's system temp directory;
2. install the editable development-ledger package;
3. validate plan revision 2;
4. discover and list top-level `.py` files from the configured package and test folders;
5. compile those files through the native `file_targets` command;
6. pass five repository workflow contract checks;
7. run a `DEVELOPMENT LEDGER` phase after ordinary commands;
8. append one revision-2 validation event;
9. generate `LATEST.json`, `PROGRESS.md`, `TRACEABILITY.md`, and `MANUAL_CHECKS.md`;
10. preserve the root dispatcher's actual target result and live console output.

Commit and push generated validation and ledger evidence on the same feature branch. The remote agent must read the generated raw report, context, progress diff, and ledger projections before the next source modification.

## Failure Checks

A failed ordinary command must still produce a nonzero root exit even if ledger recording succeeds. Missing required ledger evidence must also produce a nonzero exit and an actionable `Development ledger` failure in `LATEST.txt`.

## Known Boundary

This stage does not yet:

- migrate RRBackup to a structured development-ledger plan;
- remove the transitional `validation/Invoke-FileTargetCommand.ps1` compatibility helper;
- retire `LATEST_CONTEXT.md` or `LATEST_PROGRESS.diff`;
- add compact report post-processing;
- merge the feature branch into `agent/unified`.
