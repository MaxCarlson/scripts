# RRBackup Project Documentation

This directory is the canonical documentation root for the consolidation of `modules/rrbackup` and `modules/backup_module`.

## Required Reading

Before modifying the merged backup implementation, read:

1. `../../../AGENTS.md`
2. `../../../REPO_LLM_INSTRUCTIONS.md`
3. `../../../MODULE_STANDARDS.md`
4. `../../../docs/agent/PYTHON_REPO_STANDARDS.md`
5. `../../../docs/agent/SCRIPTS_REPO_STANDARDS.md`
6. `HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md`
7. `CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md`
8. `HANDOFF.md`
9. `plans/HANDOFF.md`
10. The active plan's `STATUS.md`, `checklist.md`, and current stage document

## Active Plan

The active consolidation plan is:

```text
plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```

The plan covers:

- one shared Restic engine,
- canonical `backup` plus compatible `rrb`, `rrbackup`, and `backup_module` commands,
- six hierarchical command areas with nested help,
- safe configuration and setup management,
- scheduler management,
- backup history viewer and timeline,
- one-command replacement for ad hoc shell-based backup audits,
- missed-backup detection,
- alerting,
- scoped retention,
- automated unit and temporary-repository integration tests,
- Windows-specific PowerShell validation scripts,
- controlled production acceptance.

## Canonical CLI Areas

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`.

The planned comprehensive read-only diagnostic command is:

```text
backup view audit
```

## Validation Entry Point

From the module root, run:

```powershell
./Invoke-Tests.ps1 -Bootstrap
```

The script runs the complete pytest suite plus every `*_test.ps1` script under `tests/`. It captures full stdout and stderr, including the complete pytest failure and coverage report, into the tracked file:

```text
TEST_RESULTS.txt
```

After a local run, stage, commit, and push `TEST_RESULTS.txt` so the remote implementation agent can inspect the exact results without manual copy/paste.

Temporary pytest data and coverage databases are written under `.pytest_tmp_root/` and remain ignored.

Production read-only checks are disabled by default and require:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```
