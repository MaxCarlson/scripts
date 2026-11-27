# Managed selective validation

## Objective

Reduce unnecessary test overhead by allowing agents to run explicitly selected pytest node IDs, files, modules, or named affected-consumer targets through the existing Scripts validation dispatcher. Reuse a valid existing interpreter/environment without implicit package installs, uninstalls, environment rebuilds, or unrelated validation stages.

## Existing system and design

`Invoke-Tests.ps1` and `validation-targets.json` remain authoritative for named/full validation. That path archives shared `LATEST.*` reports, applies retention, and may execute bootstrap commands before tests. Selective mode will branch before those operations and use only target-specific pytest/provenance metadata.

The PowerShell interface will delegate to a stdlib-only Python runner in `scripts_setup`. It will accept an existing named target as the affected consumer context plus repeatable pytest node IDs, files, and dotted test modules. The runner validates selectors remain inside that target, uses the already selected interpreter, checks configured imports against expected source roots or installed distributions, and never reads or executes the target bootstrap list.

Each run gets a UUID execution identifier, a unique target-local pytest temp root, and an atomic immutable JSON report under `docs/test-results/selective/runs/`. No shared latest report, history mutation, or centralized scheduler is added. Optional reuse is allowed only when a successful report has an identical input fingerprint including exact selection/command, selected source and test files, dependency inputs, interpreter/runtime identities, and import provenance. Changed relevant inputs invalidate reuse.

Toolkit `toolkit_cli/verify_imports.py` provides the model for `find_spec` origin checks against an expected root and distribution. Shared-package release validation remains separate; selective tests do not build or qualify artifacts. Development-ledger's JUnit/event interfaces were reviewed; selective JSON evidence stays independent to avoid mutating plan ledgers or invoking an extra recorder per focused test.

## Scope

- Extend `Invoke-Tests.ps1` with explicit selective options and a direct branch that bypasses the named/full report/bootstrap pipeline.
- Add per-target selective test roots, pytest options, import provenance, and dependency inputs to `validation-targets.json` for pytest-capable consumer targets.
- Implement selector resolution, provenance checking, evidence fingerprint/reuse, pytest execution, concise failure capture, and collision-safe atomic reports in `scripts_setup/selective_validation.py`.
- Add focused unit/integration tests and document a stable consumer-facing command for Agent-Environment's `test-verify` skill.
- Do not modify Toolkit code, shared-package source, named/full validation semantics, Coordinator retirement candidates, or test policy/skill instructions.

## Acceptance

1. Node ID, file, module, and affected-target selections execute only the requested pytest selectors under an existing interpreter.
2. Selective execution never invokes bootstrap commands or changes installed packages/environments.
3. Wrong-checkout imports and configured retired-source roots fail closed with provenance details.
4. Reports record exact selection, command, interpreter, worktree/revision, relevant dependency/import identities, duration, status, and concise failure evidence.
5. Prior passing evidence is reused only when all relevant fingerprints match; changed source, tests, dependencies, imports, or selection invalidate it.
6. Concurrent executions create distinct temp roots and complete independent reports without shared-report races.
7. Existing `-Target`, `-ListTargets`, `-SkipBootstrap`, default-target, and `-Target all` workflows remain intact.

## Implementation steps

1. Add failing tests for selection validation, no-bootstrap behavior, import provenance, evidence invalidation, and concurrent reports.
2. Implement the Python selective runner and target manifest metadata.
3. Add the opt-in PowerShell selector branch before existing named/full report initialization.
4. Document Agent-Environment usage and report contract; update plan handoff/status.
5. Run focused selective-validation tests, PowerShell parser/CLI smoke checks, inspect task-only diff, commit, and push the feature branch.
