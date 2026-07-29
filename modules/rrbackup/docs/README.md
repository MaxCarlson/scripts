# RRBackup Project Documentation

This directory is the canonical documentation root for the consolidation of `modules/rrbackup` and `modules/backup_module`.

## Required Reading

Before modifying the merged backup implementation, read:

1. `../../../AGENTS.md`
2. `../../../REPO_LLM_INSTRUCTIONS.md`
3. `../../../MODULE_STANDARDS.md`
4. `../../../docs/agent/PYTHON_REPO_STANDARDS.md`
5. `../../../docs/agent/SCRIPTS_REPO_STANDARDS.md`
6. `HANDOFF.md`
7. `plans/HANDOFF.md`
8. The active plan's `STATUS.md`, `checklist.md`, and current stage document

## Active Plan

The active consolidation plan is:

```text
plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```

The plan covers:

- one shared Restic engine,
- backward-compatible `rrb`, `rrbackup`, and `backup_module` commands,
- safe configuration and setup management,
- scheduler management,
- backup history viewer and timeline,
- missed-backup detection,
- alerting,
- scoped retention,
- automated unit and temporary-repository integration tests,
- Windows-specific PowerShell validation scripts,
- controlled production acceptance.

## Validation Entry Point

From the repository root, run:

```powershell
./Invoke-RRBackupValidation.ps1 -Bootstrap
```

The script writes a paste-ready validation transcript under:

```text
modules/rrbackup/test-results/
```

Generated validation output and temporary test data are not source artifacts and must not be committed.
