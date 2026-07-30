# Validation Context: repository-workflow

Generated: 2026-07-29T21:10:45.2058340-07:00
Branch: agent/unified-workflow-ledger
Commit: 41e3ac6ba21156acdc9733a76b751730731d1d95
Validation report: docs\test-results\repository-workflow\LATEST.txt

## Validation Highlights

- RESULT: PASS - Clean stale development-ledger editable metadata
- RESULT: PASS - Install development-ledger for repository workflow validation
- RESULT: PASS - Validate unified hybrid workflow active plan
- RESULT: PASS - Repository workflow contract tests
- RESULT: PASS - Record repository workflow ledger event
- TARGET RESULT: PASS

## Working Tree

```text
?? docs/plans/20260729-2000_unified-hybrid-workflow/ledger/
?? docs/test-results/repository-workflow/
```

## Project Status Sources

### `../docs/plans/20260729-2000_unified-hybrid-workflow/00_implementation-plan.md`

# Unified Hybrid Workflow and Validation Ledger

## Objective

Implement the merged repository's hybrid-development design as executable repository infrastructure: coherent agent branches feed `agent/unified`, the root dispatcher remains the local entry point, and development-ledger events replace duplicated progress reconstruction.

## Development Ledger State

<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1,
    "plan_id": "unified-hybrid-workflow",
    "title": "Unified Hybrid Workflow and Validation Ledger",
    "project_root": ".",
    "plan_revision": 1,
    "stage": {
        "id": "S1",
        "title": "Repository control-plane self-hosting",
        "status": "awaiting_validation"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "request": {
            "status": "incorporated",
            "summary": "Implement the connected hybrid-workflow design after the feature branches were merged and agent/unified was established.",
            "resolution": "compatible",
            "affected_ids": [
                "AC-S1-001",
                "AC-S1-002",
                "AC-S1-003"
            ],
            "supersedes": [],
            "conflicts": []
        },
        "objective": "Establish branch integration policy and self-host one repository-wide validation-ledger cycle.",
        "hypothesis": "A thin manifest-driven bridge can reuse the accepted development-ledger module before ledger recording becomes a native dispatcher phase.",
        "target_ids": [
            "AC-S1-001",
            "AC-S1-002",
            "AC-S1-003"
        ],
        "selection_rationale": "Branch policy, ledger routing, and one self-hosting target form the minimum independently verifiable control-plane batch.",
        "stop_conditions": [
            "Branch roles are discoverable without conversation memory.",
            "The ledger bridge previews safely and records required projections when write is explicit.",
            "The repository-workflow target emits generic evidence and records its event last.",
            "The branch is ready for ./Invoke-Tests.ps1 -Target repository-workflow."
        ],
        "batch": {
            "profile": "standard",
            "target_minutes": 20,
            "max_minutes": 30,
            "max_items": 4
        },
        "environment_dependencies": [
            "PowerShell 7+",
            "Git",
            "repository Python virtual environment"
        ],
        "diagnostic_complexity": "normal",
        "architecture_impact": "cross_cutting",
        "architecture_review": {
            "requested": true,
            "performed": true,
            "summary": "Reuse the existing ledger module, preserve raw LATEST.txt evidence during migration, and validate one repository-wide target before changing every module target.",
            "findings": [
                "Development-ledger recording already has a dispatcher-safe Python adapter.",
                "The root manifest lacked a repository-wide self-hosting target.",
                "File-target discovery remains declarative but still uses a subprocess helper."
            ],
            "actions": [
                "Add branch and evidence-routing instructions.",
                "Add a reusable manifest-driven ledger bridge and contract test.",
                "Defer native file-target and native ledger phases until this cycle validates."
            ]
        },
        "relevant_files": [
            "AGENTS.md",
            "REPO_LLM_INSTRUCTIONS.md",
            "docs/agent/BRANCH_INTEGRATION_WORKFLOW.md",
            "validation/DevelopmentLedgerBridge.psm1",
            "validation/Invoke-DevelopmentLedger.ps1",
            "validation/tests/repository_workflow_test.ps1",
            "validation-targets.json"
        ]
    },
    "items": [
        {
            "id": "AC-S1-001",
            "kind": "criterion",
            "title": "Repository instructions define the main, agent/unified, and agent/<work> lifecycle and merge gates.",
            "implementation": "implemented",
            "tests": [
                "powershell:repository-workflow::policy",
                "powershell:repository-workflow::plan"
            ],
            "manual_checks": [],
            "depends_on": [],
            "blocked_by": [],
            "relevant_files": [
                "AGENTS.md",
                "REPO_LLM_INSTRUCTIONS.md",
                "docs/agent/BRANCH_INTEGRATION_WORKFLOW.md"
            ],
            "priority": 10,
            "architecture_role": "foundation"
        },
        {
            "id": "AC-S1-002",
            "kind": "criterion",
            "title": "A reusable bridge resolves target ledger metadata and invokes dispatcher-safe recording with exact evidence paths.",
            "implementation": "implemented",
            "tests": [
                "powershell:repository-workflow::bridge",
                "powershell:repository-workflow::missing-evidence"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation/DevelopmentLedgerBridge.psm1",
                "validation/Invoke-DevelopmentLedger.ps1"
            ],
            "priority": 10,
            "architecture_role": "integration"
        },
        {
            "id": "AC-S1-003",
            "kind": "criterion",
            "title": "The root dispatcher exposes a repository-workflow target that records generic evidence and a permanent event last.",
            "implementation": "implemented",
            "tests": [
                "suite:repository-workflow"
            ],
            "manual_checks": [
                "MC-S1-001"
            ],
            "depends_on": [
                "AC-S1-002"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation-targets.json",
                "validation/tests/repository_workflow_test.ps1"
            ],
            "priority": 10,
            "architecture_role": "integration"
        }
    ],
    "manual_checks": [
        {
            "id": "MC-S1-001",
            "title": "Run the repository-workflow target through the Windows root dispatcher",
            "item_ids": [
                "AC-S1-003"
            ],
            "platform": "windows",
            "instructions": [
                "Switch to agent/unified-workflow-ledger and pull.",
                "Run ./Invoke-Tests.ps1 -Target repository-workflow.",
                "Confirm the target passes and generates raw validation plus ledger projections.",
                "Commit and push generated evidence."
            ],
            "expected": "One immutable validation event is recorded without hiding the root target result.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": "This is the first repository-wide self-hosting cycle."
        }
    ],
    "policy": {
        "session": {
            "target_minutes": 20,
            "max_minutes": 30,
            "max_items": 4
        },
        "architecture_review": {
            "max_validation_runs": 5,
            "max_plan_revisions": 3
        }
    },
    "relevant_docs": [
        "docs/agent/BRANCH_INTEGRATION_WORKFLOW.md",
        "docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md",
        "modules/development_ledger/docs/INTEGRATION.md"
    ]
}
```
<!-- development-ledger:state:end -->

## Next Stage

After this cycle passes, move file-target expansion into `Invoke-Tests.ps1`, then make ledger recording a native final target phase and migrate module targets incrementally.

### `../docs/plans/20260729-2000_unified-hybrid-workflow/HANDOFF.md`

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

