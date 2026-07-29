# Development Ledger Self-Hosting

## Objective

Execute the first complete module validation and immutable-ledger cycle through the merged repository-root dispatcher.

## Development Ledger State

<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1,
    "plan_id": "development-ledger-self-hosting",
    "title": "Development Ledger Self-Hosting",
    "project_root": "modules/development_ledger",
    "plan_revision": 1,
    "stage": {
        "id": "S1",
        "title": "Repository dispatcher self-hosting",
        "status": "awaiting_validation"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "request": {
            "status": "incorporated",
            "summary": "Use the merged repository validation dispatcher to execute and record the first development-ledger validation cycle.",
            "resolution": "compatible",
            "affected_ids": [
                "AC-S1-001",
                "AC-S1-002"
            ],
            "supersedes": [],
            "conflicts": []
        },
        "objective": "Make development_ledger the first self-hosted validation target without masking the root dispatcher result.",
        "hypothesis": "A narrow adapter around the existing record command is sufficient for the first evidence cycle; public CLI and generic dispatcher changes should wait for real validation evidence.",
        "target_ids": [
            "AC-S1-001",
            "AC-S1-002"
        ],
        "selection_rationale": "The adapter and manifest target form one dependency-cohesive integration stage and avoid broad dispatcher or public-CLI changes before the first real run.",
        "stop_conditions": [
            "The branch contains the adapter, target, tests, plan, and self-host documentation.",
            "Static syntax, manifest, plan-state, and adapter behavior checks pass.",
            "The user can pull and run one repository-root validation command."
        ],
        "batch": {
            "profile": "standard",
            "target_minutes": 15,
            "max_minutes": 20,
            "max_items": 4
        },
        "environment_dependencies": [
            "Windows 11 PowerShell 7 root-dispatcher execution",
            "editable Python package installation"
        ],
        "diagnostic_complexity": "normal",
        "architecture_impact": "local",
        "architecture_review": {
            "requested": false,
            "performed": true,
            "summary": "Use a dedicated adapter and existing ordered target commands for the first self-host cycle; defer public CLI and generic dispatcher changes until the evidence is reviewed.",
            "findings": [
                "The root dispatcher already preserves prior command failures.",
                "The existing record command writes evidence before returning result 1 for failed normalized tests.",
                "A narrow adapter can map only that post-write result without changing current callers."
            ],
            "actions": [
                "Add the adapter and its unit test.",
                "Add one development-ledger validation target."
            ]
        },
        "relevant_files": [
            "development_ledger/dispatcher_record.py",
            "tests/dispatcher_record_test.py",
            "../../validation-targets.json",
            "docs/SELF_HOSTING.md"
        ]
    },
    "items": [
        {
            "id": "AC-S1-001",
            "kind": "criterion",
            "title": "The dispatcher adapter treats a successfully written failed-test event as recording success while preserving actual recording failures.",
            "implementation": "implemented",
            "tests": [
                "pytest:tests/dispatcher_record_test.py::test_dispatcher_record_preserves_recording_failures*"
            ],
            "manual_checks": [],
            "depends_on": [],
            "blocked_by": [],
            "relevant_files": [
                "development_ledger/dispatcher_record.py",
                "tests/dispatcher_record_test.py"
            ],
            "priority": 10,
            "architecture_role": "foundation"
        },
        {
            "id": "AC-S1-002",
            "kind": "criterion",
            "title": "The repository root dispatcher exposes a development-ledger target that validates the module, emits JUnit XML, and records a plan event last.",
            "implementation": "implemented",
            "tests": [
                "pytest:tests/scripts_repository_integration_test.py::test_validation_manifest_self_hosts_development_ledger"
            ],
            "manual_checks": [
                "MC-S1-001"
            ],
            "depends_on": [
                "AC-S1-001"
            ],
            "blocked_by": [],
            "relevant_files": [
                "../../validation-targets.json",
                "tests/scripts_repository_integration_test.py"
            ],
            "priority": 10,
            "architecture_role": "integration"
        }
    ],
    "manual_checks": [
        {
            "id": "MC-S1-001",
            "title": "Run and inspect the first Windows self-host validation",
            "item_ids": [
                "AC-S1-002"
            ],
            "platform": "windows",
            "instructions": [
                "Run ./Invoke-Tests.ps1 -Target development-ledger from the repository root.",
                "Confirm the dispatcher preserves its exact overall result.",
                "Confirm one run event and all generated projections are written."
            ],
            "expected": "The target records complete evidence and the dispatcher result still reflects the validation sections.",
            "status": "pending",
            "safety": "non_destructive"
        }
    ],
    "policy": {
        "session": {
            "target_minutes": 15,
            "max_minutes": 20,
            "max_items": 4
        },
        "architecture_review": {
            "max_validation_runs": 5,
            "max_plan_revisions": 3
        }
    },
    "relevant_docs": [
        "docs/SELF_HOSTING.md",
        "docs/INTEGRATION.md"
    ]
}
```
<!-- development-ledger:state:end -->

## Design decision

Use a dedicated `development_ledger.dispatcher_record` adapter for this first cycle. It changes no existing public CLI semantics and can be removed or promoted after evidence review.

## Validation boundary

Remote checks cover syntax, manifest/plan consistency, and adapter result mapping. Windows PowerShell execution, editable installation, Ruff, pytest, coverage, and generated tracked artifacts remain local authoritative validation.
