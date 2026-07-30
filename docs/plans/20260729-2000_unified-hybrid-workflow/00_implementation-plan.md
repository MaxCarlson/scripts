# Unified Hybrid Workflow and Validation Ledger

## Objective

Implement the merged repository's hybrid-development design as an executable control plane rather than a collection of advisory documents.

The finished system will:

- use `main` as the accepted baseline, `agent/unified` as the integration branch, and `agent/<work>` branches for coherent implementation;
- keep one repository-root validation command;
- express validation scope declaratively;
- preserve complete raw transcripts and exact validation status;
- append normalized immutable development-ledger events;
- generate compact progress, traceability, manual-check, routing, and local-handoff projections;
- retire duplicated progress artifacts only after parallel operation is proven.

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
        "status": "in_progress"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "request": {
            "status": "incorporated",
            "summary": "Implement the connected hybrid-workflow design after the three feature branches were merged into main and agent/unified was established.",
            "resolution": "compatible",
            "affected_ids": [
                "AC-S1-001",
                "AC-S1-002",
                "AC-S1-003"
            ],
            "supersedes": [],
            "conflicts": []
        },
        "objective": "Establish the integration-branch contract and make a repository-wide validation target record its own normalized ledger event.",
        "hypothesis": "A thin manifest-driven PowerShell bridge can reuse the accepted development-ledger module and self-host the repository workflow before the larger dispatcher is refactored.",
        "target_ids": [
            "AC-S1-001",
            "AC-S1-002",
            "AC-S1-003"
        ],
        "selection_rationale": "Branch policy, ledger routing, and one self-hosting target are the minimum dependency-cohesive batch that turns the merged design into working repository infrastructure.",
        "stop_conditions": [
            "Repository instructions describe main, agent/unified, and agent/<work> roles without relying on conversation memory.",
            "A reusable validation bridge resolves ledger metadata from validation-targets.json and records an event without masking prior validation failures.",
            "The repository-workflow target writes a generic script-result artifact and generates ledger projections through the root dispatcher.",
            "The branch is ready for one local run of ./Invoke-Tests.ps1 -Target repository-workflow."
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
            "the repository Python virtual environment"
        ],
        "diagnostic_complexity": "normal",
        "architecture_impact": "shared",
        "architecture_review": {
            "requested": true,
            "performed": true,
            "summary": "Reuse the existing development-ledger module, preserve LATEST.txt during migration, and introduce one self-hosting repository target before changing every module target.",
            "findings": [
                "The development-ledger implementation and dispatcher-safe record adapter already exist and should not be duplicated.",
                "The root dispatcher currently has no generic ledger phase, while the development-ledger target hard-codes its own record command.",
                "File-target discovery is declarative but still runs through a second PowerShell process and manifest parse.",
                "A self-hosting repository target provides a safe acceptance boundary before RRBackup and Manga targets are migrated."
            ],
            "actions": [
                "Add a reusable manifest-driven ledger bridge.",
                "Add a repository-workflow validation target and generic script-result producer.",
                "Keep native file-target expansion and global dispatcher ledger phases as the next bounded stage.",
                "Retain existing raw/context/progress artifacts during two-cycle migration validation."
            ]
        },
        "relevant_files": [
            "AGENTS.md",
            "REPO_LLM_INSTRUCTIONS.md",
            "docs/agent/BRANCH_INTEGRATION_WORKFLOW.md",
            "docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md",
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
                "suite:repository-workflow"
            ],
            "manual_checks": [],
            "depends_on": [],
            "blocked_by": [],
            "relevant_files": [
                "AGENTS.md",
                "REPO_LLM_INSTRUCTIONS.md",
                "docs/agent/BRANCH_INTEGRATION_WORKFLOW.md",
                "docs/agent/HYBRID_REMOTE_LOCAL_DEVELOPMENT_WORKFLOW.md"
            ],
            "priority": 10,
            "architecture_role": "foundation"
        },
        {
            "id": "AC-S1-002",
            "kind": "criterion",
            "title": "A reusable bridge resolves target ledger metadata and invokes the dispatcher-safe record command with exact evidence paths.",
            "implementation": "implemented",
            "tests": [
                "suite:repository-workflow"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation/Invoke-DevelopmentLedger.ps1",
                "validation/tests/repository_workflow_test.ps1"
            ],
            "priority": 10,
            "architecture_role": "integration"
        },
        {
            "id": "AC-S1-003",
            "kind": "criterion",
            "title": "The root dispatcher exposes a repository-workflow target that validates the control plane and records a plan event last.",
            "implementation": "implemented",
            "tests": [
                "command:repository-workflow-contract-tests",
                "command:record-repository-workflow-ledger-event"
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
        },
        {
            "id": "AC-S2-001",
            "kind": "criterion",
            "title": "The root dispatcher expands file-target path, depth, extension, and exclusion rules in-process.",
            "implementation": "planned",
            "tests": [],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-003"
            ],
            "blocked_by": [],
            "relevant_files": [
                "Invoke-Tests.ps1",
                "validation/Invoke-FileTargetCommand.ps1"
            ],
            "priority": 8,
            "architecture_role": "integration"
        },
        {
            "id": "AC-S3-001",
            "kind": "criterion",
            "title": "Ledger recording becomes a native final dispatcher phase for every enabled target while preserving the original validation result.",
            "implementation": "planned",
            "tests": [],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-003",
                "AC-S2-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "Invoke-Tests.ps1",
                "validation-targets.json"
            ],
            "priority": 8,
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
                "Switch to agent/unified-workflow-ledger and pull the remote branch.",
                "Run ./Invoke-Tests.ps1 -Target repository-workflow.",
                "Confirm the target reports PASS and the plan ledger directory contains RUNS.jsonl, LATEST.json, PROGRESS.md, TRACEABILITY.md, MANUAL_CHECKS.md, and LOCAL_HANDOFF.md when routing requires it.",
                "Commit and push generated validation and ledger evidence."
            ],
            "expected": "The target passes, records one immutable validation event, preserves the complete raw transcript, and prints the generated progress and manual-check paths.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": "This is the first repository-wide self-hosting acceptance cycle."
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
        "modules/development_ledger/docs/INTEGRATION.md",
        "modules/development_ledger/docs/PLAN_FORMAT.md"
    ]
}
```
<!-- development-ledger:state:end -->

## Stage Boundary

This first implementation stage intentionally self-hosts one repository-wide target. It does not yet migrate RRBackup, Manga, or every existing validation target to the generic ledger phase.

The next stage will move file-target expansion into `Invoke-Tests.ps1`, then make ledger recording a native final target phase rather than an explicit final command.
