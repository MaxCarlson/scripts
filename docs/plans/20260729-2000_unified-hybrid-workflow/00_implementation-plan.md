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
    "plan_revision": 2,
    "stage": {
        "id": "S2",
        "title": "Native dispatcher phases",
        "status": "awaiting_validation"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "request": {
            "status": "no_new_request",
            "summary": "Continue the accepted plan after the first repository-workflow baseline passed.",
            "resolution": "none",
            "affected_ids": [
                "AC-S2-001",
                "AC-S2-002",
                "AC-S2-003"
            ],
            "supersedes": [],
            "conflicts": []
        },
        "objective": "Replace helper-command orchestration with modular native file-target and final-ledger phases while preserving the root interface and evidence contract.",
        "hypothesis": "A thin root wrapper plus focused validation modules can preserve existing behavior while eliminating manifest inventory churn and explicit ledger commands.",
        "target_ids": [
            "AC-S2-001",
            "AC-S2-002",
            "AC-S2-003"
        ],
        "selection_rationale": "The first baseline validated the bridge; modular dispatcher ownership, native discovery, and native ledger ordering are the next dependency-cohesive batch.",
        "stop_conditions": [
            "Invoke-Tests.ps1 retains every public parameter and streams live output while returning the final dispatcher exit code.",
            "A file_targets command resolves path, max_depth, and extension rules without launching the legacy helper.",
            "Ledger metadata runs as the final target phase without an explicit recording command.",
            "Earlier command failures remain authoritative even when the ledger records successfully.",
            "The repository-workflow target is ready for one Windows validation cycle."
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
            "summary": "Decompose the 853-line dispatcher without changing its public command surface, preserve transitional raw/context evidence, and make declarative target metadata drive native phases.",
            "findings": [
                "The old dispatcher mixed target selection, file discovery, command execution, artifact retention, and ledger sequencing in one script.",
                "PowerShell pipeline output must be streamed separately from the final result object and exit code.",
                "The accepted bridge can remain reusable while the dispatcher invokes it natively.",
                "The first S1 manual check was redundant because the Windows dispatcher run produced automated evidence and an immutable validation event."
            ],
            "actions": [
                "Keep Invoke-Tests.ps1 as a thin interface-preserving wrapper.",
                "Move common, artifact, context, execution, target, and dispatcher responsibilities into focused modules.",
                "Resolve file_targets inside the dispatcher process.",
                "Run ledger metadata after all ordinary commands and PowerShell groups.",
                "Remove the redundant S1 manual-check requirement."
            ]
        },
        "relevant_files": [
            "Invoke-Tests.ps1",
            "validation/ValidationCommon.psm1",
            "validation/ValidationArtifacts.psm1",
            "validation/ValidationContext.psm1",
            "validation/ValidationExecution.psm1",
            "validation/ValidationTarget.psm1",
            "validation/ValidationDispatcher.psm1",
            "validation-targets.json",
            "validation/tests/repository_workflow_test.ps1"
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
            "title": "The root dispatcher exposes a repository-workflow target that records generic evidence and a permanent event.",
            "implementation": "implemented",
            "tests": [
                "suite:repository-workflow"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-002"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation-targets.json",
                "validation/tests/repository_workflow_test.ps1"
            ],
            "priority": 10,
            "architecture_role": "integration",
            "notes": "The successful Windows baseline and immutable run event superseded the redundant manual-only acceptance check."
        },
        {
            "id": "AC-S2-001",
            "kind": "criterion",
            "title": "Invoke-Tests.ps1 preserves its public interface while delegating repository validation to focused modules.",
            "implementation": "implemented",
            "tests": [
                "powershell:repository-workflow::native-dispatcher",
                "powershell:repository-workflow::plan"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S1-003"
            ],
            "blocked_by": [],
            "relevant_files": [
                "Invoke-Tests.ps1",
                "validation/ValidationDispatcher.psm1",
                "validation/ValidationTarget.psm1"
            ],
            "priority": 10,
            "architecture_role": "migration"
        },
        {
            "id": "AC-S2-002",
            "kind": "criterion",
            "title": "file_targets rules resolve path, maximum depth, and extensions inside the root dispatcher process.",
            "implementation": "implemented",
            "tests": [
                "powershell:repository-workflow::native-dispatcher",
                "command:compile-development-ledger-files-through-native-file-targets"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S2-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation/ValidationCommon.psm1",
                "validation-targets.json"
            ],
            "priority": 10,
            "architecture_role": "integration"
        },
        {
            "id": "AC-S2-003",
            "kind": "criterion",
            "title": "Ledger metadata executes as the final native target phase without masking prior validation failures.",
            "implementation": "implemented",
            "tests": [
                "powershell:repository-workflow::native-dispatcher",
                "powershell:repository-workflow::bridge",
                "powershell:repository-workflow::missing-evidence",
                "suite:repository-workflow"
            ],
            "manual_checks": [],
            "depends_on": [
                "AC-S2-002"
            ],
            "blocked_by": [],
            "relevant_files": [
                "validation/ValidationExecution.psm1",
                "validation/ValidationTarget.psm1",
                "validation-targets.json"
            ],
            "priority": 10,
            "architecture_role": "integration"
        }
    ],
    "manual_checks": [],
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

Stage S2 makes file discovery and ledger recording native dispatcher phases. It does not yet migrate RRBackup to a structured ledger plan, retire transitional `LATEST_CONTEXT.md` or `LATEST_PROGRESS.diff`, or merge the feature branch into `agent/unified`.
