# RRBackup Consolidation Handoff

## Current State

The active branch is:

```text
agent/merge-restic-backup-modules
```

The active plan is:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/
```

Historical and static analysis established:

- `B:\ResticRepos\PC-Local` contains two known snapshots: `a1609113` and `022aad5b`.
- The snapshots predate the committed `backup_module` implementation.
- `backup_module` is the behavioral successor to the direct Restic workflow.
- The existing `rrbackup` development config targets an unrelated Google Drive repository.
- No current local backup schedule is installed.
- Production retention/prune operations are prohibited during consolidation.

## Collaboration Loop

1. The browser/app agent performs as much planning, implementation, documentation, test authoring, and static review as connected tools permit.
2. The browser/app agent updates the active plan before each implementation stage.
3. The browser/app agent implements source and tests on the feature branch and pushes a coherent stage.
4. The user pulls the branch and runs the repository-root `Invoke-Tests.ps1` dispatcher.
5. The dispatcher reads `validation-targets.json`, bootstraps dependencies, runs the selected language-native and PowerShell tests, and writes one tracked report per target.
6. The user stages, commits, and pushes the generated files under `docs/test-results/<target>/`.
7. The browser/app agent reads the reports, updates `STATUS.md`, `checklist.md`, and stage handoff documents, and implements the next pass.
8. Repeat until temporary-repository integration, Windows adapter, production read-only, controlled backup, restore, scheduler, viewer, audit, and alert acceptance are verified.

The generalized responsibility split and reusable repository-root dispatcher pattern are documented in:

```text
../../../docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md
```

Do not have multiple agents edit this branch concurrently. A local agent should primarily execute tests and report environment-specific evidence unless explicitly assigned a separate patch branch.

## Validation Safety

Default validation must not access or mutate the production repository.

From the repository root, run:

```powershell
./Invoke-Tests.ps1
```

Production read-only checks require:

```powershell
./Invoke-Tests.ps1 -IncludeProductionReadOnly
```

No automated validation may run production backup, restore, init, unlock, forget, prune, cache cleanup, stale-lock removal, or retention application.

## Validation Evidence

### First committed baseline

- 130 tests collected
- 112 passed
- 4 skipped
- 10 failed
- 4 errored
- package-only branch coverage: 32%

That run proved the original module-local report handoff could capture full output and be consumed remotely.

### Second local run

The module-local runner failed before test collection because pytest imported another module's `tests.conftest` from the shared repository environment. A manual `pytest` invocation used a different interpreter that lacked `pytest-mock` and `tomli-w`, causing missing-fixture and missing-dependency failures. The stale console entry points also required an editable reinstall after removal of the duplicate outer initializer.

The response is now structural rather than command-specific:

- repository-root `Invoke-Tests.ps1`,
- manifest-driven target selection,
- dependency bootstrap enabled by default,
- repository virtual-environment Python resolution,
- target working-directory isolation,
- pytest `--import-mode=importlib`,
- timestamped tracked reports under `docs/test-results/rrbackup/`,
- removal of module-local runner and result file.

## Canonical CLI Contract

The merged module will add the canonical `backup` command with six major areas:

```text
backup run
backup view
backup config
backup schedule
backup restore
backup repository
```

`backup edit` aliases `backup config`. `rrb` and `rrbackup` expose the same hierarchy. `backup_module` and `python -m backup_module` preserve their historical interface through a compatibility adapter.

The full CLI and shell-audit replacement contract is:

```text
docs/CLI_ARCHITECTURE_AND_AUDIT_COVERAGE.md
```

The comprehensive read-only replacement for the consolidation PowerShell scripts is:

```text
backup view audit
```

It will aggregate executable resolution, effective configuration, environment provenance, config discovery, input files, repository metadata, keys, snapshots, local runs, logs, locks, schedules, scheduler history, other launchers, health, and provenance without exposing secrets.

## Current Implementation Stage

Stage 1 remains active:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/01_safety-foundation__in-progress.md
```

Stage 2 CLI implementation is planned in:

```text
docs/plans/20260729-0700_rrbackup-consolidation-viewer-alerting/02_compatibility-merge-and-cli__planned.md
```
