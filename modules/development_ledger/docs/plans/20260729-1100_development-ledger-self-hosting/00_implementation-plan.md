# Development Ledger Self-Hosting

## Objective

Execute and verify the first complete module validation and immutable-ledger cycle through the merged repository-root dispatcher.

## Development Ledger State

<!-- development-ledger:state:start -->
```json
{
    "schema_version": 1,
    "plan_id": "development-ledger-self-hosting",
    "title": "Development Ledger Self-Hosting",
    "project_root": "modules/development_ledger",
    "plan_revision": 2,
    "stage": {
        "id": "S1",
        "title": "Repository dispatcher self-hosting corrections",
        "status": "awaiting_validation"
    },
    "session": {
        "actor": "remote_llm",
        "mode": "hybrid",
        "request": {
            "status": "incorporated",
            "summary": "Review the pushed first-cycle evidence and correct the attributable schema-test, JUnit-ID, and routing-state defects.",
            "resolution": "compatible",
            "affected_ids": [
                "AC-S1-001",
                "AC-S1-002"
            ],
            "supersedes": [],
            "conflicts": []
        },
        "objective": "Correct the first-cycle schema assertion and canonicalize pytest JUnit IDs so the same root target can verify implementation and traceability.",
        "hypothesis": "The failing run-event schema is valid through top-level oneOf, while pytest 9 omits file attributes and requires dotted classnames to be normalized to documented test-file IDs.",
        "target_ids": [
            "AC-S1-001",
            "AC-S1-002"
        ],
        "selection_rationale": "Both corrections are directly attributable to the first self-host run and form one bounded evidence-quality pass.",
        "stop_conditions": [
            "The run-event schema test accepts a valid top-level oneOf schema without KeyError.",
            "Pytest classname-only JUnit cases normalize to tests/<module>.py IDs and match the active plan.",
            "The active plan no longer treats routine local validation prerequisites as unresolved diagnostic dependencies.",
            "The branch is ready for one rerun of ./Invoke-Tests.ps1 -Target development-ledger."
        ],
        "batch": {
            "profile": "standard",
            "target_minutes": 15,
            "max_minutes": 20,
            "max_items": 4
        },
        "environment_dependencies": [],
        "diagnostic_complexity": "mechanical",
        "architecture_impact": "local",
        "architecture_review": {
            "requested": false,
            "performed": true,
            "summary": "Keep the existing adapter and dispatcher contract; patch only the invalid schema assertion, JUnit ID normalization, and plan metadata exposed by the first run.",
            "findings": [
                "run-event.schema.json correctly uses top-level oneOf and therefore has no top-level type key.",
                "Pytest 9 emitted dotted classname values without file attributes, so documented file-path mappings did not match.",
                "Routine Windows validation requirements were incorrectly declared as unresolved environment dependencies, causing a false local handoff."
            ],
            "actions": [
                "Use payload.get when accepting object-or-oneOf schemas.",
                "Canonicalize pytest classname-only JUnit cases to forward-slash Python file paths.",
                "Clear environment_dependencies for this remotely diagnosable correction pass."
            ]
        },
        "relevant_files": [
            "development_ledger/results.py",
            "tests/results_test.py",
            "tests/schema_test.py",
            "docs/plans/20260729-1100_development-ledger-self-hosting/00_implementation-plan.md"
        ]
    },
    "items": [
        {
            "id": "AC-S1-001",
            "kind": "criterion",
            "title": "The dispatcher adapter treats a successfully written failed-test event as recording success while preserving actual recording failures.",
            "implementation": "implemented",
            "tests": [
                "glob:pytest:tests/dispatcher_record_test.py::test_dispatcher_record_preserves_recording_failures*"
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
                "tests/scripts_repository_integration_test.py",
                "development_ledger/results.py"
            ],
            "priority": 10,
            "architecture_role": "integration"
        }
    ],
    "manual_checks": [
        {
            "id": "MC-S1-001",
            "title": "Run and inspect the Windows self-host validation",
            "item_ids": [
                "AC-S1-002"
            ],
            "platform": "windows",
            "instructions": [
                "Run ./Invoke-Tests.ps1 -Target development-ledger from the repository root.",
                "Confirm the dispatcher preserves its exact overall result.",
                "Confirm one new run event and all generated projections are written."
            ],
            "expected": "The target records complete evidence and the dispatcher result still reflects the validation sections.",
            "status": "pending",
            "safety": "non_destructive",
            "notes": "The first failed run proved the evidence path; record this check after the corrected passing rerun is inspected."
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

## First-cycle evidence

The first Windows run proved that the dispatcher continued after a pytest failure, recorded the JUnit and transcript evidence, preserved the target failure, and generated all ledger projections.

The correction pass addresses only:

1. an unsafe test assertion against the valid top-level `oneOf` run-event schema,
2. pytest 9 classname-only JUnit IDs that did not match documented file-path mappings,
3. plan metadata that incorrectly treated routine local validation as an unresolved diagnostic dependency.

## Design decision

Keep the dedicated `development_ledger.dispatcher_record` adapter for this cycle. Do not broaden the public CLI or root dispatcher until the corrected evidence is reviewed.

## Validation boundary

Remote review covers the attributable source, tests, plan state, and generated evidence. Windows PowerShell execution, editable installation, Ruff, pytest, coverage, ledger append behavior, and tracked artifact rotation remain authoritative local validation.
