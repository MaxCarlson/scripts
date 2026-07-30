# Traceability: Unified Hybrid Workflow and Validation Ledger

> Generated. Plan items declare expected evidence; normalized results report actual evidence.

## Item to Evidence

### `AC-S1-001` — Repository instructions define the main, agent/unified, and agent/<work> lifecycle and merge gates.

- Kind: `criterion`
- Architecture role: `foundation`
- Priority: `10`
- Depends on: (none)
- Implementation: `implemented`
- Verification: `verified`
- Expected test patterns: `powershell:repository-workflow::policy`, `powershell:repository-workflow::plan`
- Matched tests: `powershell:repository-workflow::policy`, `powershell:repository-workflow::plan`
- Manual checks: (none)
- Relevant files: `AGENTS.md`, `REPO_LLM_INSTRUCTIONS.md`, `docs/agent/BRANCH_INTEGRATION_WORKFLOW.md`

### `AC-S1-002` — A reusable bridge resolves target ledger metadata and invokes dispatcher-safe recording with exact evidence paths.

- Kind: `criterion`
- Architecture role: `integration`
- Priority: `10`
- Depends on: `AC-S1-001`
- Implementation: `implemented`
- Verification: `verified`
- Expected test patterns: `powershell:repository-workflow::bridge`, `powershell:repository-workflow::missing-evidence`
- Matched tests: `powershell:repository-workflow::bridge`, `powershell:repository-workflow::missing-evidence`
- Manual checks: (none)
- Relevant files: `validation/DevelopmentLedgerBridge.psm1`, `validation/Invoke-DevelopmentLedger.ps1`

### `AC-S1-003` — The root dispatcher exposes a repository-workflow target that records generic evidence and a permanent event last.

- Kind: `criterion`
- Architecture role: `integration`
- Priority: `10`
- Depends on: `AC-S1-002`
- Implementation: `implemented`
- Verification: `manual_pending`
- Expected test patterns: `suite:repository-workflow`
- Matched tests: `powershell:repository-workflow::policy`, `powershell:repository-workflow::plan`, `powershell:repository-workflow::bridge`, `powershell:repository-workflow::missing-evidence`
- Manual checks: `MC-S1-001`
- Relevant files: `validation-targets.json`, `validation/tests/repository_workflow_test.ps1`

## Test to Item

- `powershell:repository-workflow::policy` → `AC-S1-001`, `AC-S1-003` — **passed**
- `powershell:repository-workflow::plan` → `AC-S1-001`, `AC-S1-003` — **passed**
- `powershell:repository-workflow::bridge` → `AC-S1-002`, `AC-S1-003` — **passed**
- `powershell:repository-workflow::missing-evidence` → `AC-S1-002`, `AC-S1-003` — **passed**
- `command:clean-stale-development-ledger-editable-metadata` → (regression-only) — **passed**
- `command:install-development-ledger-for-repository-workflow-validation` → (regression-only) — **passed**
- `command:validate-unified-hybrid-workflow-active-plan` → (regression-only) — **passed**
- `command:repository-workflow-contract-tests` → (regression-only) — **passed**
